from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys

from .config import load_config
from .errors import ConfigError, SecretError
from .ipc import IPCError, PORTABLE_PIPE_NAME, PipeClient
from .secrets_store import (
    SCOPE_CURRENT_USER,
    SCOPE_LOCAL_MACHINE,
    clear_token,
    store_token,
    token_exists,
    token_metadata,
)

EXIT_OK = 0
EXIT_CONFIG = 2
EXIT_SECRET = 3
EXIT_COMM = 4
EXIT_OTHER = 10


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mijialamp", description="MijiaLamp Windows automation CLI")
    parser.add_argument(
        "--mode",
        choices=("service", "portable"),
        default="service",
        help="runtime destino: servicio instalado o proceso portable",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name in (
        "config-check",
        "service-status",
        "runtime-status",
        "token-status",
        "token-clear",
        "doctor",
        "status",
        "night-status",
        "manual-on",
        "manual-off",
        "enable",
        "disable",
        "resume-auto",
    ):
        sub.add_parser(name)
    token = sub.add_parser("token-set")
    token.add_argument("--stdin", action="store_true", required=True)
    sync = sub.add_parser("sync")
    sync.add_argument("--force", action="store_true")
    status = sub.choices["status"]
    status.add_argument("--no-physical", action="store_true")
    pause = sub.add_parser("pause")
    pause.add_argument("--minutes", type=float, default=60)
    sub.add_parser("pause-until-tomorrow")
    return parser


def dump(data) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str))


def _secret_write_allowed() -> bool:
    if os.name != "nt":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    portable = args.mode == "portable"
    secret_scope = SCOPE_CURRENT_USER if portable else SCOPE_LOCAL_MACHINE
    client = PipeClient(PORTABLE_PIPE_NAME) if portable else PipeClient()
    runtime_label = "PORTABLE" if portable else "SERVICE"

    if args.command == "token-set":
        if not portable and not _secret_write_allowed():
            print(
                "TOKEN ERROR: token-set en modo service requiere PowerShell como Administrador; "
                "preferí import-token.ps1.",
                file=sys.stderr,
            )
            return EXIT_SECRET
        try:
            store_token(sys.stdin.read().strip(), scope=secret_scope)
            scope_label = "CurrentUser" if portable else "LocalMachine"
            print(f"Token almacenado con DPAPI {scope_label}. El valor no se muestra.")
            return EXIT_OK
        except (SecretError, OSError) as exc:
            print(f"TOKEN ERROR: {exc}", file=sys.stderr)
            return EXIT_SECRET
    if args.command == "token-clear":
        if not portable and not _secret_write_allowed():
            print("TOKEN ERROR: token-clear en modo service requiere Administrador.", file=sys.stderr)
            return EXIT_SECRET
        try:
            clear_token()
        except OSError as exc:
            print(f"TOKEN ERROR: {exc}", file=sys.stderr)
            return EXIT_SECRET
        print("Token almacenado eliminado.")
        return EXIT_OK
    if args.command == "token-status":
        try:
            result = client.request("token-status", timeout=3)
            configured = bool(result.get("configured", False)) if isinstance(result, dict) else False
            scope = result.get("scope") if isinstance(result, dict) else None
            suffix = f" ({scope})" if scope else ""
            print(("Token DPAPI: configurado" + suffix) if configured else "Token DPAPI: NO configurado")
            return EXIT_OK if configured else EXIT_SECRET
        except IPCError as exc:
            # Portable token import/status is useful before starting portable.py. In that
            # case inspect only metadata; never decrypt or print the secret.
            if portable and token_exists(expected_scope=secret_scope):
                try:
                    scope = token_metadata().get("scope")
                except SecretError:
                    scope = secret_scope
                print(f"Token DPAPI: configurado ({scope}); runtime portable no iniciado")
                return EXIT_OK
            print(f"{runtime_label} ERROR: {exc}", file=sys.stderr)
            return EXIT_COMM
    if args.command == "config-check":
        try:
            cfg = load_config()
            print(f"config.json: OK (schema v{cfg['version']})")
            return EXIT_OK
        except ConfigError as exc:
            print(f"CONFIG ERROR: {exc}", file=sys.stderr)
            return EXIT_CONFIG

    try:
        if args.command in {"service-status", "runtime-status"}:
            dump(client.request("ping", timeout=3))
        elif args.command == "doctor":
            dump(client.request("doctor", timeout=30))
        elif args.command == "status":
            dump(client.request("status", timeout=10, physical=not args.no_physical))
        elif args.command == "night-status":
            dump(client.request("night-status", timeout=5))
        elif args.command == "manual-on":
            dump(client.request("manual-on", timeout=30))
        elif args.command == "manual-off":
            dump(client.request("manual-off", timeout=15))
        elif args.command == "sync":
            dump(client.request("sync", timeout=30, reason="cli-sync", force=args.force))
        elif args.command == "enable":
            dump(client.request("enable", timeout=30))
        elif args.command == "disable":
            dump(client.request("disable", timeout=5))
        elif args.command == "pause":
            dump(client.request("pause", timeout=5, seconds=max(0, args.minutes) * 60))
        elif args.command == "pause-until-tomorrow":
            dump(client.request("pause-until-tomorrow", timeout=5))
        elif args.command == "resume-auto":
            dump(client.request("resume-automation", timeout=30))
        else:
            return EXIT_OTHER
        return EXIT_OK
    except IPCError as exc:
        print(f"{runtime_label} ERROR: {exc}", file=sys.stderr)
        return EXIT_COMM
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_OTHER
