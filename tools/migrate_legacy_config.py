from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# When this file is executed directly (as setup-portable.ps1/install.ps1 do),
# Python puts tools/ at sys.path[0], not the project root. Add the parent
# explicitly so the local mijialamp package is importable from any working directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import contextlib

from mijialamp.secrets_store import (
    SCOPE_CURRENT_USER,
    SCOPE_LOCAL_MACHINE,
    store_token,
    token_exists,
    validate_token,
)
from mijialamp.util import atomic_write_json


def migrate(path: Path, *, token_scope: str = SCOPE_LOCAL_MACHINE) -> tuple[bool, bool]:
    """Migrate v1/v2 config fields without exposing secret values.

    The v3 runtime rejects unknown keys so typos do not silently change behaviour.
    Known legacy fields are therefore mapped or removed here before config-check.
    """
    with open(path, encoding="utf-8-sig") as fh:
        cfg = json.load(fh)
    if not isinstance(cfg, dict):
        raise ValueError("config.json debe contener un objeto JSON")

    changed = False
    token_migrated = False
    legacy_token = cfg.pop("token", None)
    if legacy_token is not None:
        changed = True
        try:
            token = validate_token(str(legacy_token))
        except Exception:
            token = None
        if token and not token_exists(expected_scope=token_scope):
            store_token(token, scope=token_scope)
            token_migrated = True

    # v2 duplicated this profile. v3 only uses light_profiles.manual_day.
    if "manual_day_profile" in cfg:
        cfg.pop("manual_day_profile", None)
        changed = True

    # Preserve the useful intent of renamed v2 settings.
    mappings = {
        "transition_ms": "power_transition_ms",
        "auto_discover_on_failure": "discovery_enabled",
        "scan_timeout_seconds": "discovery_scan_timeout_seconds",
    }
    for old, new in mappings.items():
        if old in cfg:
            if new not in cfg:
                cfg[new] = cfg[old]
            cfg.pop(old, None)
            changed = True

    if "scan_max_workers" in cfg:
        if "discovery_scan_workers" not in cfg:
            with contextlib.suppress(Exception):
                cfg["discovery_scan_workers"] = max(1, min(32, int(cfg["scan_max_workers"])))
        cfg.pop("scan_max_workers", None)
        changed = True

    # Obsolete v2 implementation details. Their semantics are built into v3.
    obsolete = {
        "scan_max_hosts",
        "apply_light_profile_on_on",
        "respect_display_state_in_sync",
        "last_seen_model",
        "last_discovered_at",
        "resume_user_fallback_seconds",
        "sync_reapply_minutes",
    }
    for key in obsolete:
        if key in cfg:
            cfg.pop(key, None)
            changed = True

    if cfg.get("version") != 3:
        cfg["version"] = 3
        changed = True

    if changed:
        atomic_write_json(path, cfg)
    return changed, token_migrated


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Migra config legacy sin exponer secretos")
    parser.add_argument("path", type=Path)
    parser.add_argument(
        "--scope",
        choices=[SCOPE_CURRENT_USER, SCOPE_LOCAL_MACHINE],
        default=SCOPE_LOCAL_MACHINE,
        help="Scope DPAPI destino si existe un token plaintext legacy",
    )
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    changed, token_migrated = migrate(args.path, token_scope=args.scope)
    if token_migrated:
        print("Token legacy migrado a DPAPI; su valor no se mostró.")
    if changed:
        print("config.json migrado a esquema v3 y saneado.")
    else:
        print("config.json no necesitó migración sensible.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
