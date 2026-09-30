import copy
import json
import unittest
from pathlib import Path

from mijialamp.config import validate_config
from mijialamp.errors import ConfigError

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_CONFIG = ROOT / "config.example.json"


def example_config() -> dict:
    with open(EXAMPLE_CONFIG, "r", encoding="utf-8") as fh:
        return validate_config(json.load(fh))


class ConfigTests(unittest.TestCase):
    def test_example_config_validates(self):
        cfg = example_config()
        self.assertEqual(cfg["expected_model"], "yeelink.light.lamp22")
        self.assertNotIn("token", cfg)

    def test_bad_profile_rejected(self):
        cfg = copy.deepcopy(example_config())
        cfg["light_profiles"]["evening"]["brightness"] = 101
        with self.assertRaises(ConfigError):
            validate_config(cfg)

    def test_scan_is_limited_to_24(self):
        cfg = copy.deepcopy(example_config())
        cfg["discovery_scan_prefix"] = 16
        with self.assertRaises(ConfigError):
            validate_config(cfg)

    def test_string_boolean_rejected(self):
        cfg = copy.deepcopy(example_config())
        cfg["night_mode"] = "false"
        with self.assertRaises(ConfigError):
            validate_config(cfg)

    def test_ipv6_rejected(self):
        cfg = copy.deepcopy(example_config())
        cfg["lamp_ip"] = "::1"
        with self.assertRaises(ConfigError):
            validate_config(cfg)

    def test_unknown_key_rejected(self):
        cfg = copy.deepcopy(example_config())
        cfg["typo_sync_intervall_seconds"] = 60
        with self.assertRaises(ConfigError):
            validate_config(cfg)

    def test_wrong_schema_version_rejected(self):
        cfg = copy.deepcopy(example_config())
        cfg["version"] = 2
        with self.assertRaises(ConfigError):
            validate_config(cfg)

    def test_corrupt_device_cache_is_quarantined(self):
        import tempfile
        from unittest.mock import patch
        import mijialamp.config as config_mod

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cache = root / "device_cache.json"
            lock = root / "device_cache.lock"
            cache.write_text("{not-json", encoding="utf-8")
            with patch.object(config_mod, "DEVICE_CACHE_PATH", cache), patch.object(
                config_mod, "DEVICE_CACHE_LOCK_PATH", lock
            ):
                self.assertEqual(config_mod.read_device_cache(), {})
            self.assertFalse(cache.exists())
            self.assertEqual(len(list(root.glob("device_cache.corrupt-*.json"))), 1)



if __name__ == "__main__":
    unittest.main()
