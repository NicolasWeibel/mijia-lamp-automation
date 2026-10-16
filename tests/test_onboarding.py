import base64
import codecs
import hashlib
import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

try:
    from Crypto.Cipher import ARC4
except ModuleNotFoundError:
    ARC4 = None

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("xiaomi_onboarding", ROOT / "tools" / "xiaomi_onboarding.py")
ONBOARD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ONBOARD)


class XiaomiOnboardingTests(unittest.TestCase):
    def test_select_stdin_preserves_unicode_with_or_without_powershell_bom(self):
        device = {"did": "42", "model": "yeelink.light.lamp22", "name": "Lámpara", "token": "a" * 32}
        encoded = base64.b64encode(json.dumps(device, ensure_ascii=False).encode("utf-8"))
        selected = {"ip": "192.168.1.2", "did": "42", "model": device["model"], "token_staged": True}
        for prefix in (b"", codecs.BOM_UTF8):
            with self.subTest(prefix=prefix):
                output = io.StringIO()
                stdin = SimpleNamespace(buffer=io.BytesIO(prefix + encoded + b"\r\n"))
                with (
                    patch(
                        "sys.argv",
                        ["xiaomi_onboarding.py", "select", "--config", "test.json", "--mode", "Portable"],
                    ),
                    patch("sys.stdin", stdin),
                    patch.object(ONBOARD, "select_device", return_value=selected) as select,
                    redirect_stdout(output),
                ):
                    self.assertEqual(ONBOARD.main(), 0)
                select.assert_called_once_with(device, Path("test.json"), "Portable")
                self.assertEqual(json.loads(output.getvalue()), {"type": "selected", **selected})
                self.assertNotIn(device["token"], output.getvalue())

    def test_select_rejects_malformed_base64_before_selecting_a_device(self):
        output = io.StringIO()
        with (
            patch(
                "sys.argv", ["xiaomi_onboarding.py", "select", "--config", "test.json", "--mode", "Service"]
            ),
            patch("sys.stdin", SimpleNamespace(buffer=io.BytesIO(codecs.BOM_UTF8 + b"not!base64\n"))),
            patch.object(ONBOARD, "select_device") as select,
            redirect_stdout(output),
        ):
            self.assertEqual(ONBOARD.main(), 1)
        select.assert_not_called()
        self.assertEqual(json.loads(output.getvalue())["type"], "error")

    def test_qr_image_and_poll_may_use_xiaomi_account_frontend(self):
        login = SimpleNamespace(
            url="https://account.xiaomi.com/longPolling/loginUrl",
            status_code=200,
            content=b"{}",
            text=json.dumps(
                {
                    "qr": "https://ak.account.xiaomi.com/longPolling/qr?ticket=test",
                    "lp": "https://sgp.lp.account.xiaomi.com/longPolling/login?ticket=test",
                    "timeout": 120,
                }
            ),
        )
        image = SimpleNamespace(
            url="https://ak.account.xiaomi.com/longPolling/qr?ticket=test",
            status_code=200,
            content=b"jpeg image",
            headers={"Content-Type": "image/jpeg"},
        )
        replies = iter((login, image))
        session = ONBOARD.XiaomiQrSession(SimpleNamespace(get=lambda *_args, **_kwargs: next(replies)))
        self.assertEqual(session.begin(), b"jpeg image")

    def test_only_expected_https_hosts_are_contacted(self):
        self.assertEqual(
            ONBOARD._xiaomi_url("https://account.xiaomi.com/longPolling/loginUrl"),
            "https://account.xiaomi.com/longPolling/loginUrl",
        )
        self.assertEqual(
            ONBOARD._xiaomi_url("https://ak.account.xiaomi.com/longPolling/login?ticket=test"),
            "https://ak.account.xiaomi.com/longPolling/login?ticket=test",
        )
        for url in (
            "http://account.xiaomi.com/longPolling/loginUrl",
            "https://account.xiaomi.com.attacker.example/qr",
            "https://evilak.account.xiaomi.com/qr",
            "https://sgp.lp.account.xiaomi.com.attacker.example/qr",
            "https://account.xiaomi.com:8080/qr",
            "https://example.com/qr",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                ONBOARD._xiaomi_url(url)

    def test_qr_redirect_cannot_leave_xiaomi_hosts(self):
        response = SimpleNamespace(
            url="https://account.xiaomi.com/qr",
            status_code=302,
            headers={"Location": "https://example.com/collect"},
        )
        fake_http = SimpleNamespace(get=lambda *_args, **_kwargs: response)
        session = ONBOARD.XiaomiQrSession(fake_http)
        with self.assertRaises(ValueError):
            session._get("https://account.xiaomi.com/qr")

    def test_cloud_response_decrypts_with_xiaomi_signed_nonce(self):
        if ARC4 is None:
            self.skipTest("pycryptodome no está instalado en el job de calidad")
        secret = base64.b64encode(b"s" * 16).decode()
        session = ONBOARD.XiaomiQrSession(session=SimpleNamespace())
        session.user_id = "42"
        session.security = secret
        session.service_token = "session-token"

        def fake_post(url, **kwargs):
            nonce = kwargs["params"]["_nonce"]
            signed = hashlib.sha256(base64.b64decode(secret) + base64.b64decode(nonce)).digest()
            cipher = ARC4.new(signed)
            cipher.encrypt(bytes(1024))
            encrypted = base64.b64encode(cipher.encrypt(b'{"result":{"homelist":[]}}')).decode()
            return SimpleNamespace(url=url, status_code=200, content=encrypted.encode(), text=encrypted)

        with patch.object(session.http, "post", side_effect=fake_post, create=True):
            result = session._api("cn", "/v2/homeroom/gethome", {"fg": True})
        self.assertEqual(result, {"result": {"homelist": []}})

    def test_cloud_list_keeps_only_devices_with_valid_miio_identity_and_token(self):
        session = ONBOARD.XiaomiQrSession(session=SimpleNamespace())
        session.user_id = "42"

        def response(_region, path, _payload):
            if path.endswith("gethome"):
                return {"result": {"homelist": [{"id": 7}]}}
            if path.endswith("get_device_cnt"):
                return {"result": {"share": {"share_family": []}}}
            return {
                "result": {
                    "device_info": [
                        {
                            "name": "Lámpara",
                            "did": "123456789",
                            "model": "yeelink.light.lamp22",
                            "localip": "192.168.1.8",
                            "token": "a" * 32,
                        },
                        {"name": "Sin token", "did": "9", "model": "test.device", "token": ""},
                    ]
                }
            }

        with patch.object(session, "_api", side_effect=response):
            devices = session.devices(("cn", "de"))
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0]["did"], "123456789")
        self.assertEqual(devices[0]["localip"], "192.168.1.8")

    def test_selected_device_is_verified_and_token_is_staged_separately(self):
        device = {
            "name": "Lámpara",
            "did": "123456789",
            "model": "yeelink.light.lamp22",
            "localip": "192.168.1.8",
            "mac": "AA:BB:CC:DD:EE:FF",
            "token": "b" * 32,
        }
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / "config.json"
            secret = Path(temp) / "onboarding-token.dpapi.json"
            previous = json.loads((ONBOARD.ROOT / "config.example.json").read_text(encoding="utf-8"))
            previous["expected_mac"] = "11:22:33:44:55:66"
            config.write_text(json.dumps(previous), encoding="utf-8")
            with (
                patch.object(ONBOARD, "find_local_ip", return_value="192.168.1.9") as verify,
                patch.object(ONBOARD, "stage_path", return_value=secret),
                patch.object(ONBOARD, "_secure_stage_directory"),
                patch.object(ONBOARD, "store_token") as store,
            ):
                result = ONBOARD.select_device(device, config, "Service")
            verify.assert_called_once_with(device)
            store.assert_called_once_with("b" * 32, secret, scope=ONBOARD.SCOPE_LOCAL_MACHINE)
            saved = json.loads(config.read_text(encoding="utf-8"))
            self.assertEqual(saved["lamp_ip"], "192.168.1.9")
            self.assertEqual(saved["device_id"], "123456789")
            self.assertEqual(saved["expected_mac"], "AA:BB:CC:DD:EE:FF")
            self.assertNotIn("token", saved)
            self.assertEqual(result["ip"], "192.168.1.9")

    def test_selecting_device_without_mac_clears_previous_lamp_mac(self):
        device = {"did": "123456789", "model": "yeelink.light.lamp22", "token": "b" * 32}
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / "config.json"
            secret = Path(temp) / "onboarding-token.dpapi.json"
            previous = json.loads((ONBOARD.ROOT / "config.example.json").read_text(encoding="utf-8"))
            previous["expected_mac"] = "11:22:33:44:55:66"
            config.write_text(json.dumps(previous), encoding="utf-8")
            with (
                patch.object(ONBOARD, "find_local_ip", return_value="192.168.1.9"),
                patch.object(ONBOARD, "stage_path", return_value=secret),
                patch.object(ONBOARD, "_secure_stage_directory"),
                patch.object(ONBOARD, "store_token"),
            ):
                ONBOARD.select_device(device, config, "Portable")
            saved = json.loads(config.read_text(encoding="utf-8"))
            self.assertEqual(saved["expected_mac"], "")

    def test_unreachable_device_does_not_stage_token_or_write_config(self):
        device = {"did": "123456789", "model": "yeelink.light.lamp22", "token": "c" * 32}
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / "config.json"
            with (
                patch.object(ONBOARD, "find_local_ip", side_effect=RuntimeError("Sin LAN")),
                patch.object(ONBOARD, "store_token") as store,
                self.assertRaises(RuntimeError),
            ):
                ONBOARD.select_device(device, config, "Portable")
            store.assert_not_called()
            self.assertFalse(config.exists())


if __name__ == "__main__":
    unittest.main()
