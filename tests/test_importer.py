import importlib.util
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
