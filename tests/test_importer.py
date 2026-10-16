import importlib.util
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "import_mihome_token", ROOT / "tools" / "import_mihome_token.py"
)
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)

TEST_DID = "123456789"
TEST_IP = "192.168.1.100"


class ImporterTests(unittest.TestCase):
    def test_finds_device_in_nested_region(self):
        data = {
            "cn": {
                "devices": [
                    {"did": "1", "token": "0" * 32},
                    {
                        "did": TEST_DID,
                        "model": "yeelink.light.lamp22",
                        "localip": TEST_IP,
                        "token": "a" * 32,
                    },
                ]
            }
        }
        obj, _ = MOD.find_device(data, TEST_DID)
        self.assertEqual(obj["token"], "a" * 32)

    def test_parent_did_key_supported(self):
        data = {TEST_DID: {"token": "b" * 32, "local_ip": TEST_IP}}
        obj, _ = MOD.find_device(data, TEST_DID)
        self.assertEqual(obj["token"], "b" * 32)

    def test_encrypted_source_is_rewrapped_without_showing_token(self):
        secret = "d" * 32
        with (
            patch.object(
                sys,
                "argv",
                ["import_mihome_token.py", "--encrypted-source", "staged.json", "--scope", "local-machine"],
            ),
            patch.object(MOD, "ensure_service_dirs"),
            patch.object(MOD, "load_config", return_value={"device_id": TEST_DID}),
            patch.object(MOD, "load_token", return_value=secret) as load,
            patch.object(MOD, "store_token") as store,
            redirect_stdout(io.StringIO()) as output,
        ):
            result = MOD.main()
        self.assertEqual(result, 0)
        load.assert_called_once_with(Path("staged.json"), expected_scope="local-machine")
        store.assert_called_once_with(secret, scope="local-machine")
        self.assertNotIn(secret, output.getvalue())


if __name__ == "__main__":
    unittest.main()
