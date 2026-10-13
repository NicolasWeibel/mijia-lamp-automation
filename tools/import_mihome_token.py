import argparse
import ipaddress
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mijialamp.config import load_config, update_device_cache, update_lamp_ip
from mijialamp.i18n import tr
from mijialamp.paths import ensure_service_dirs
from mijialamp.secrets_store import SCOPE_CURRENT_USER, SCOPE_LOCAL_MACHINE, load_token, store_token

TOKEN_RE = re.compile(r"^[0-9a-fA-F]{32}$")
DID_KEYS = ("did", "device_id", "deviceId", "id")
TOKEN_KEYS = ("token", "miio_token", "miioToken")
IP_KEYS = ("localip", "local_ip", "localIp", "ip")
MODEL_KEYS = ("model", "model_id", "modelId")
MAC_KEYS = ("mac", "mac_address", "macAddress")
MAC_RE = re.compile(r"^(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$")


def candidate_files() -> list[Path]:
    values = []
    env_home = os.environ.get("MIHOME_CTL_HOME")
    if env_home:
        values.append(Path(env_home) / "mi-tokens.json")
    values.extend(
        [
            Path.cwd() / ".secrets" / "mi-tokens.json",
            Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
            / "mihome-ctl"
            / "mihome-ctl"
            / "mi-tokens.json",
            Path.home() / ".local" / "state" / "mihome-ctl" / "mi-tokens.json",
        ]
    )
    local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "mihome-ctl"
    if local.exists():
        values.extend(local.glob("**/mi-tokens.json"))
    seen = set()
    result = []
    for path in values:
        try:
            key = str(path.resolve())
        except OSError:
            key = str(path)
        if key not in seen:
            seen.add(key)
            result.append(path)
    return result


def get_first(obj: dict, keys):
    for key in keys:
        if key in obj and obj[key] not in (None, ""):
            return obj[key]
    return None


def walk(obj, path=(), parent_key=None):
    if isinstance(obj, dict):
        yield obj, path, parent_key
        for key, value in obj.items():
            yield from walk(value, path + (str(key),), str(key))
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            yield from walk(value, path + (str(index),), parent_key)


def find_device(data, expected_did: str):
    matches = []
    for obj, path, parent_key in walk(data):
        did = get_first(obj, DID_KEYS)
        parent_matches = parent_key == expected_did
        if (did is not None and str(did) == expected_did) or parent_matches:
            token = get_first(obj, TOKEN_KEYS)
            if token is not None and TOKEN_RE.fullmatch(str(token).strip()):
                matches.append((obj, path))
    if not matches:
        # Some formats place did and token in sibling/nested objects. Search any
        # dict with the expected DID, then recursively inspect only that subtree.
        for obj, path, _ in walk(data):
            did = get_first(obj, DID_KEYS)
            if did is not None and str(did) == expected_did:
                for sub, subpath, _ in walk(obj, path):
                    token = get_first(sub, TOKEN_KEYS)
                    if token is not None and TOKEN_RE.fullmatch(str(token).strip()):
                        matches.append((sub, subpath))
                        break
    if not matches:
        raise RuntimeError(tr("msg_506731dc1e7d", expected_did))
    return matches[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=tr("msg_8a249fece9d5"))
    parser.add_argument("--source", type=Path)
    parser.add_argument("--encrypted-source", type=Path)
    parser.add_argument("--did")
    parser.add_argument(
        "--scope", choices=(SCOPE_LOCAL_MACHINE, SCOPE_CURRENT_USER), default=SCOPE_LOCAL_MACHINE
    )
    args = parser.parse_args()

    if args.source and args.encrypted_source:
        parser.error("--source y --encrypted-source son excluyentes")

    ensure_service_dirs()
    cfg = load_config()
    expected_did = str(args.did or cfg["device_id"])

    if args.encrypted_source:
        # The GUI creates this LocalMachine/CurrentUser DPAPI blob before setup.
        # Decrypting and re-encrypting occurs in this process; the token is never
        # passed through command-line arguments, logs or a plaintext JSON file.
        token = load_token(args.encrypted_source, expected_scope=args.scope)
        store_token(token, scope=args.scope)
        print(tr("msg_fa0482a5051d"))
        print(tr("msg_c106960738f6") + expected_did)
        print(tr("msg_ac0532150db1", args.scope))
        return 0

    source = args.source
    if source is None:
        source = next((p for p in candidate_files() if p.is_file()), None)
    if source is None or not source.is_file():
        print(tr("msg_bc07d7ba3181"))
        return 2

    with open(source, encoding="utf-8-sig") as fh:
        data = json.load(fh)
    obj, path = find_device(data, expected_did)
    token = str(get_first(obj, TOKEN_KEYS)).strip()

    model = get_first(obj, MODEL_KEYS)
    if model and str(model) != str(cfg["expected_model"]):
        print(tr("msg_8e4b16318233", model, cfg["expected_model"]))
        return 3

    store_token(token, scope=args.scope)

    mac_value = get_first(obj, MAC_KEYS)
    imported_mac = None
    if mac_value and MAC_RE.fullmatch(str(mac_value).strip()):
        imported_mac = str(mac_value).strip().replace("-", ":").upper()
        update_device_cache(observed_mac=imported_mac)

    ip_value = get_first(obj, IP_KEYS)
    imported_ip = None
    if ip_value:
        try:
            imported_ip = str(ipaddress.ip_address(str(ip_value)))
            update_lamp_ip(imported_ip)
        except ValueError:
            imported_ip = None

    print(tr("msg_329375e3e8cb"))
    print(f"  DID: {expected_did}")
    print(tr("msg_b53d10f63284", model or cfg["expected_model"]))
    print(f"  IP: {imported_ip or cfg['lamp_ip']}")
    if imported_mac:
        print(f"  MAC: {imported_mac}")
    print(tr("msg_ac0532150db1", args.scope))
    print(f"  Fuente: {source}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
