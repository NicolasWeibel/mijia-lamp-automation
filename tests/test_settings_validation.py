import base64
import codecs
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SettingsValidationTests(unittest.TestCase):
    def run_validator(self, payload, utf8="1"):
        result = subprocess.run(
            [sys.executable, "-B", str(ROOT / "tools" / "validate_config.py")],
            input=payload,
            capture_output=True,
            env={**os.environ, "PYTHONUTF8": utf8},
            timeout=15,
        )
        self.assertEqual(result.stderr, b"")
        return result.returncode, json.loads(result.stdout.decode("ascii"))

    def test_accented_city_with_and_without_pipeline_bom(self):
        config = json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))
        config["location_name"] = "San Mart\u00edn \u00b7 Mendoza"
        payload = base64.b64encode(json.dumps(config, ensure_ascii=False).encode("utf-8"))
        for utf8 in ("0", "1"):
            for prefix in (b"", codecs.BOM_UTF8):
                with self.subTest(utf8=utf8, bom=bool(prefix)):
                    code, result = self.run_validator(prefix + payload + b"\r\n", utf8)
                    self.assertEqual(code, 0)
                    self.assertEqual(result, {"ok": True})

    def test_non_base64_bytes_are_rejected(self):
        code, result = self.run_validator(codecs.BOM_UTF8 + b"%%%invalid%%%")
        self.assertEqual(code, 2)
        self.assertFalse(result["ok"])
        self.assertTrue(result["message"])

    def test_invalid_configuration_is_rejected_after_bom_removal(self):
        config = json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))
        config["light_profiles"]["evening"]["brightness"] = 101
        payload = codecs.BOM_UTF8 + base64.b64encode(json.dumps(config).encode("utf-8"))
        code, result = self.run_validator(payload)
        self.assertEqual(code, 2)
        self.assertFalse(result["ok"])
        self.assertTrue(result["message"])
