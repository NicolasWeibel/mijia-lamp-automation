"""Interactive, unprivileged Xiaomi QR onboarding for the Windows setup GUI.

The QR/cloud protocol follows the MIT-licensed work in
https://github.com/daviddwlee84/mihome-ctl and
https://github.com/PiotrMachowski/Xiaomi-cloud-tokens-extractor.
No Xiaomi account session is written to disk. The device list containing tokens
travels only over a redirected pipe to the GUI; the selected token is staged
only as a DPAPI blob. No token is printed after device selection.
"""

from __future__ import annotations

import argparse
import base64
import codecs
import contextlib
import hashlib
import ipaddress
import json
import os
import re
import secrets
import socket
import string
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin, urlparse

try:
    import requests
except ModuleNotFoundError:  # quality job does not install runtime dependencies
    requests = None
try:
    from Crypto.Cipher import ARC4
except ModuleNotFoundError:  # quality job does not install runtime dependencies
    ARC4 = None

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mijialamp.config import validate_config
from mijialamp.i18n import tr
from mijialamp.secrets_store import SCOPE_CURRENT_USER, SCOPE_LOCAL_MACHINE, store_token
from mijialamp.util import atomic_write_json

RequestException = requests.RequestException if requests else OSError
RequestsTimeout = requests.Timeout if requests else TimeoutError

ROOT = Path(__file__).resolve().parents[1]
REGIONS = ("cn", "de", "us", "ru", "sg", "i2", "tw")
TOKEN_RE = re.compile(r"^[0-9a-fA-F]{32}$")
MAX_QR_BYTES = 1_000_000


def stage_path() -> Path:
    local = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
    return local / "MijiaLamp" / "onboarding-private" / "token.dpapi.json"


def _secure_stage_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise RuntimeError(tr("msg_2b72681af498"))
    if os.name != "nt":
        return
    import ntsecuritycon
    import win32api
    import win32con
    import win32security

    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
    try:
        user_sid = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
    finally:
        token.Close()
    acl = win32security.ACL()
    inheritance = win32security.OBJECT_INHERIT_ACE | win32security.CONTAINER_INHERIT_ACE
    for sid in (
        user_sid,
        win32security.ConvertStringSidToSid("S-1-5-32-544"),  # Administrators
        win32security.ConvertStringSidToSid("S-1-5-18"),  # SYSTEM
    ):
        acl.AddAccessAllowedAceEx(win32security.ACL_REVISION, inheritance, ntsecuritycon.FILE_ALL_ACCESS, sid)
    sd = win32security.SECURITY_DESCRIPTOR()
    sd.SetSecurityDescriptorDacl(1, acl, 0)
    win32security.SetFileSecurity(
        str(path),
        win32security.DACL_SECURITY_INFORMATION | win32security.PROTECTED_DACL_SECURITY_INFORMATION,
        sd,
    )


def _event(kind: str, **values: object) -> None:
    # Windows PowerShell 5.1 and redirected Python stdout can choose different
    # code pages. ASCII JSON escapes preserve Spanish text and device names.
    print(json.dumps({"type": kind, **values}, ensure_ascii=True, separators=(",", ":")), flush=True)


def _xiaomi_url(url: str, *, allow_api: bool = False) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    # Xiaomi's QR response can use the dedicated account frontend for the
    # image or long-poll URL. Keep an exact host allowlist (no wildcards).
    allowed = {
        "account.xiaomi.com",
        "ak.account.xiaomi.com",
        "sgp.lp.account.xiaomi.com",
        "sts.api.io.mi.com",
    }
    if allow_api:
        allowed.update({"api.io.mi.com", *(f"{region}.api.io.mi.com" for region in REGIONS)})
    if parsed.scheme != "https" or host not in allowed or parsed.port not in (None, 443):
        # Do not include the full URL: QR/poll query strings contain tickets.
        raise ValueError(tr("msg_feb1ebf9ed28", host or "(empty)"))
    return url


def _decode_json(response: requests.Response) -> dict:
    if response.status_code != 200 or len(response.content) > 2_000_000:
        raise RuntimeError(tr("msg_56f26d68f89b"))
    data = json.loads(response.text.removeprefix("&&&START&&&"))
    if not isinstance(data, dict):
        raise RuntimeError(tr("msg_75f57f8bb6e7"))
    return data


class XiaomiQrSession:
    def __init__(self, session: requests.Session | None = None):
        if session is None and requests is None:
            raise RuntimeError(tr("msg_0d7642e0264f"))
        self.http = session or requests.Session()
        agent_prefix = "".join(secrets.choice(string.ascii_lowercase) for _ in range(18))
        agent_id = "".join(secrets.choice("ABCDE") for _ in range(13))
        self.agent = f"{agent_prefix}-{agent_id} APP/com.xiaomi.mihome APPV/10.5.201"
        self.user_id: str | None = None
        self.security: str | None = None
        self.service_token: str | None = None
        self.qr_image: bytes | None = None
        self.poll_url: str | None = None
        self.expires_at = 0.0

    def _get(self, url: str, *, timeout: float = 12) -> requests.Response:
        for _ in range(4):
            _xiaomi_url(url)
            response = self.http.get(url, timeout=timeout, allow_redirects=False)
            _xiaomi_url(response.url)
            if response.status_code not in (301, 302, 303, 307, 308):
                return response
            target = response.headers.get("Location")
            if not target:
                raise RuntimeError(tr("msg_a559d097324e"))
            url = _xiaomi_url(urljoin(url, target))
        raise RuntimeError("Demasiadas redirecciones de Xiaomi")

    def begin(self) -> bytes:
        response = self.http.get(
            "https://account.xiaomi.com/longPolling/loginUrl",
            params={
                "_qrsize": "480",
                "qs": "%3Fsid%3Dxiaomiio%26_json%3Dtrue",
                "callback": "https://sts.api.io.mi.com/sts",
                "_hasLogo": "false",
                "sid": "xiaomiio",
                "serviceParam": "",
                "_locale": "en_GB",
                "_dc": str(int(time.time() * 1000)),
            },
            timeout=12,
            allow_redirects=False,
        )
        _xiaomi_url(response.url)
        data = _decode_json(response)
        qr_url = _xiaomi_url(str(data["qr"]))
        self.poll_url = _xiaomi_url(str(data["lp"]))
        timeout = max(30, min(int(data.get("timeout", 180)), 300))
        self.expires_at = time.monotonic() + timeout
        qr = self._get(qr_url)
        content_type = qr.headers.get("Content-Type", "").lower()
        if qr.status_code != 200 or "image/" not in content_type or len(qr.content) > MAX_QR_BYTES:
            raise RuntimeError(tr("msg_3b0728ad553f"))
        self.qr_image = qr.content
        return self.qr_image

    def finish(self) -> None:
        if not self.poll_url:
            raise RuntimeError(tr("msg_bdadc86021d4"))
        response = None
        while time.monotonic() < self.expires_at:
            try:
                candidate = self._get(self.poll_url, timeout=10)
            except RequestsTimeout:
                continue
            if candidate.status_code == 200:
                response = candidate
                break
            if candidate.status_code not in (202, 204, 408):
                raise RuntimeError(tr("msg_74fd12d4caa1"))
        if response is None:
            raise RuntimeError(tr("msg_152a9b4ff817"))
        data = _decode_json(response)
        self.user_id = str(data["userId"])
        self.security = str(data["ssecurity"])
        location = _xiaomi_url(str(data["location"]))
        ticket = self._get(location)
        self.service_token = ticket.cookies.get("serviceToken") or self.http.cookies.get("serviceToken")
        if not self.service_token or not self.security:
            raise RuntimeError(tr("msg_543201033120"))

    def _api(self, region: str, path: str, payload: dict) -> dict:
        if not self.security or not self.service_token or not self.user_id:
            raise RuntimeError(tr("msg_ed4104355342"))
        if ARC4 is None:
            raise RuntimeError(tr("msg_b44cb10f20ea"))
        host = "api.io.mi.com" if region == "cn" else f"{region}.api.io.mi.com"
        url = _xiaomi_url(f"https://{host}/app{path}", allow_api=True)
        data = json.dumps(payload, separators=(",", ":"))
        nonce = base64.b64encode(os.urandom(8) + (int(time.time() / 60)).to_bytes(4, "big")).decode()
        signed = base64.b64encode(
            hashlib.sha256(base64.b64decode(self.security) + base64.b64decode(nonce)).digest()
        ).decode()
        uri = urlparse(url).path.removeprefix("/app")

        def signature(fields: dict[str, str]) -> str:
            parts = ["POST", uri, *(f"{key}={value}" for key, value in fields.items()), signed]
            return base64.b64encode(hashlib.sha1("&".join(parts).encode()).digest()).decode()

        fields = {"data": data}
        fields["rc4_hash__"] = signature(fields)

        def encrypt(value: str) -> str:
            cipher = ARC4.new(base64.b64decode(signed))
            cipher.encrypt(bytes(1024))
            return base64.b64encode(cipher.encrypt(value.encode())).decode()

        encrypted = {key: encrypt(value) for key, value in fields.items()}
        encrypted["signature"] = signature(encrypted)
        encrypted["ssecurity"] = self.security
        encrypted["_nonce"] = nonce
        response = self.http.post(
            url,
            params=encrypted,
            headers={
                "Accept-Encoding": "identity",
                "Content-Type": "application/x-www-form-urlencoded",
                "MIOT-ENCRYPT-ALGORITHM": "ENCRYPT-RC4",
                "x-xiaomi-protocal-flag-cli": "PROTOCAL-HTTP2",
                "User-Agent": self.agent,
            },
            cookies={
                "userId": self.user_id,
                "serviceToken": self.service_token,
                "yetAnotherServiceToken": self.service_token,
                "locale": "en_GB",
                "timezone": "GMT+02:00",
                "is_daylight": "1",
                "dst_offset": "3600000",
                "channel": "MI_APP_STORE",
            },
            timeout=12,
            allow_redirects=False,
        )
        _xiaomi_url(response.url, allow_api=True)
        if response.status_code != 200 or len(response.content) > 2_000_000:
            raise RuntimeError(tr("msg_56fac8706830"))
        cipher = ARC4.new(base64.b64decode(signed))
        cipher.encrypt(bytes(1024))
        decoded = cipher.decrypt(base64.b64decode(response.text))
        result = json.loads(decoded)
        if not isinstance(result, dict):
            raise RuntimeError(tr("msg_7dc92c9ed82e"))
        return result

    def devices(self, regions: tuple[str, ...] = REGIONS) -> list[dict]:
        found: dict[str, dict] = {}
        succeeded = False
        for region in regions:
            if region not in REGIONS:
                raise ValueError(tr("msg_e5bf4c5bcfb8"))
            try:
                homes_response = self._api(
                    region,
                    "/v2/homeroom/gethome",
                    {"fg": True, "fetch_share": True, "fetch_share_dev": True, "limit": 300, "app_ver": 7},
                )
                homes = [
                    (home["id"], int(self.user_id))
                    for home in ((homes_response.get("result") or {}).get("homelist") or [])
                ]
                try:
                    count_response = self._api(
                        region, "/v2/user/get_device_cnt", {"fetch_own": True, "fetch_share": True}
                    )
                    shared = ((count_response.get("result") or {}).get("share") or {}).get(
                        "share_family"
                    ) or []
                except (RequestException, ValueError, KeyError, TypeError, RuntimeError):
                    shared = []
                homes.extend((item["home_id"], item["home_owner"]) for item in shared)
                succeeded = True
                for home_id, owner_id in homes:
                    info = self._api(
                        region,
                        "/v2/home/home_device_list",
                        {
                            "home_owner": int(owner_id),
                            "home_id": home_id,
                            "limit": 200,
                            "get_split_device": True,
                            "support_smart_home": True,
                        },
                    )
                    rows = (info.get("result") or {}).get("device_info") or []
                    for row in rows:
                        did = str(row.get("did", ""))
                        token = str(row.get("token", ""))
                        model = str(row.get("model", ""))
                        if not did.isdigit() or not TOKEN_RE.fullmatch(token) or not model:
                            continue
                        found.setdefault(
                            did,
                            {
                                "name": str(row.get("name", ""))[:100],
                                "did": did,
                                "model": model,
                                "localip": str(row.get("localip", "")),
                                "mac": str(row.get("mac", "")),
                                "token": token,
                                "region": region,
                            },
                        )
            except (RequestException, ValueError, KeyError, TypeError, RuntimeError):
                continue
        if not succeeded:
            raise RuntimeError(tr("msg_e115ecb0a76f"))
        return list(found.values())


def _probe(ip: str, token: str, expected_did: str, expected_model: str) -> bool:
    from miio import Device

    try:
        device = Device(ip, token, timeout=1.5, lazy_discover=True)
        info = device.info()
        return str(device.device_id) == expected_did and str(info.model) == expected_model
    except Exception:
        return False


def _scan_networks(cloud_ip: str) -> list[ipaddress.IPv4Network]:
    ips: list[str] = []
    try:
        target = str(ipaddress.IPv4Address(cloud_ip))
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect((target, 54321))
            ips.append(sock.getsockname()[0])
    except (OSError, ValueError):
        pass
    with contextlib.suppress(OSError):
        ips.extend(socket.gethostbyname_ex(socket.gethostname())[2])
    nets = []
    for ip in ips:
        try:
            addr = ipaddress.IPv4Address(ip)
            if not addr.is_private or addr.is_loopback or addr.is_link_local:
                continue
            network = ipaddress.IPv4Network(f"{addr}/24", strict=False)
            if network not in nets:
                nets.append(network)
        except ipaddress.AddressValueError:
            continue
    return nets[:2]


def find_local_ip(device: dict) -> str:
    did = str(device["did"])
    model = str(device["model"])
    token = str(device["token"])
    cloud_ip = str(device.get("localip", ""))
    try:
        cloud_address = ipaddress.IPv4Address(cloud_ip)
        if cloud_address.is_private and not cloud_address.is_loopback and _probe(cloud_ip, token, did, model):
            return cloud_ip
    except ipaddress.AddressValueError:
        pass

    from miio import Device

    def handshake(ip: str) -> str | None:
        try:
            response = Device(ip, token, lazy_discover=True)._protocol.discover(ip, timeout=0.45)
            raw = response.header.value.device_id
            return ip if str(int.from_bytes(raw, byteorder="big")) == did else None
        except Exception:
            return None

    for network in _scan_networks(cloud_ip):
        candidates = (str(ip) for ip in network.hosts() if str(ip) != cloud_ip)
        with ThreadPoolExecutor(max_workers=16) as pool:
            for candidate in pool.map(handshake, candidates):
                if candidate and _probe(candidate, token, did, model):
                    return candidate
    raise RuntimeError(tr("msg_d28d269c80b1"))


def select_device(device: dict, config_path: Path, mode: str) -> dict:
    did = str(device.get("did", ""))
    model = str(device.get("model", ""))
    token = str(device.get("token", ""))
    if not did.isdigit() or not model or not TOKEN_RE.fullmatch(token):
        raise ValueError(tr("msg_70311df10079"))
    ip = find_local_ip(device)
    template = json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))
    if config_path.is_file():
        current = json.loads(config_path.read_text(encoding="utf-8-sig"))
        if "token" in current:
            raise ValueError(tr("msg_e5921d919d7c"))
        template.update(current)
    template["lamp_ip"] = ip
    template["expected_model"] = model
    template["device_id"] = did
    # An old MAC belongs to the previously selected lamp, not this device.
    template["expected_mac"] = ""
    mac = str(device.get("mac", ""))
    if re.fullmatch(r"(?:[0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}", mac):
        template["expected_mac"] = mac.replace("-", ":").upper()
    validate_config(template)
    scope = SCOPE_LOCAL_MACHINE if mode == "Service" else SCOPE_CURRENT_USER
    secret = stage_path()
    _secure_stage_directory(secret.parent)
    # A failed second selection must never leave the first lamp's staged token
    # paired with the second lamp's config.
    secret.unlink(missing_ok=True)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(config_path, template)
    store_token(token, secret, scope=scope)
    return {"ip": ip, "did": did, "model": model, "token_staged": True}


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    auth = sub.add_parser("qr")
    auth.add_argument("--regions", default=",".join(REGIONS))
    select = sub.add_parser("select")
    select.add_argument("--config", type=Path, required=True)
    select.add_argument("--mode", choices=("Portable", "Service"), required=True)
    args = parser.parse_args()
    try:
        if args.command == "qr":
            regions = tuple(x.strip().lower() for x in args.regions.split(",") if x.strip())
            if not regions or any(x not in REGIONS for x in regions):
                raise ValueError(tr("msg_3b12dc31cb52"))
            session = XiaomiQrSession()
            qr = session.begin()
            _event("qr", image_b64=base64.b64encode(qr).decode("ascii"))
            session.finish()
            _event("devices", devices=session.devices(regions))
        else:
            # PowerShell's redirected StreamWriter can prepend a UTF-8 BOM.
            # Decode bytes explicitly, independently of Python's console encoding.
            encoded = sys.stdin.buffer.readline().removeprefix(codecs.BOM_UTF8).strip()
            device = json.loads(base64.b64decode(encoded, validate=True).decode("utf-8"))
            _event("selected", **select_device(device, args.config, args.mode))
        return 0
    except Exception as exc:
        # Never include request objects or device rows in errors: both can carry secrets.
        message = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else type(exc).__name__
        _event("error", message=message)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
