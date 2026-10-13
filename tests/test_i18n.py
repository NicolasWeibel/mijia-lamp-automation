import json
import re
import tempfile
import unittest
from pathlib import Path
from string import Formatter
from unittest.mock import patch

from mijialamp.config import validate_config
from mijialamp.errors import ConfigError
from mijialamp.i18n import catalog, get_language, language, tr

ROOT = Path(__file__).resolve().parents[1]


class LocalizationTests(unittest.TestCase):
    def test_catalogs_cover_all_references_and_preserve_placeholders(self):
        english, spanish = catalog("en"), catalog("es")
        self.assertEqual(set(english), set(spanish))
        formatter = Formatter()
        for key in english:
            with self.subTest(key=key):
                self.assertIsInstance(english[key], str)
                self.assertTrue(english[key].strip())
                self.assertEqual(
                    sorted(re.findall(r"\{\d+(?:![rsa])?(?::[^}]+)?\}|%[srdf]", english[key])),
                    sorted(re.findall(r"\{\d+(?:![rsa])?(?::[^}]+)?\}|%[srdf]", spanish[key])),
                )
                # Formatting syntax must be valid in either language.
                list(formatter.parse(english[key]))
                list(formatter.parse(spanish[key]))
        paths = [
            *ROOT.glob("*.py"),
            *ROOT.glob("*.ps1"),
            *(ROOT / "mijialamp").glob("*.py"),
            *(ROOT / "tools").glob("*.py"),
        ]
        for path in paths:
            text = path.read_text(encoding="utf-8-sig")
            for key in re.findall(r"(?:tr\(|\bT\s+)['\"]([^'\"]+)", text):
                if key.endswith("."):
                    continue  # Dynamic, bounded tray/profile namespaces are checked below.
                self.assertTrue(key in english, f"{path.name}: missing {key}")

    def test_language_selection_survives_config_validation_without_changing_policy(self):
        original = json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))
        for code in ("en", "es"):
            with self.subTest(code=code):
                cfg = validate_config({**original, "ui_language": code})
                self.assertEqual(cfg["ui_language"], code)
                self.assertEqual(cfg["night_start"], "sunset")
                self.assertEqual(cfg["night_end"], "sunrise")
                self.assertEqual(cfg["timezone"], original["timezone"])
        legacy = {k: v for k, v in original.items() if k != "ui_language"}
        self.assertEqual(validate_config(legacy)["ui_language"], "en")
        for invalid in ("fr", "../es", None, 5):
            with self.subTest(invalid=invalid), self.assertRaises(ConfigError):
                validate_config({**original, "ui_language": invalid})

    def test_saved_preference_overrides_inherited_environment_and_updates_after_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            with (
                patch("mijialamp.paths.CONFIG_PATH", path),
                patch.dict("os.environ", {"MIJIALAMP_LANGUAGE": "en"}),
            ):
                for code in ("es", "en", "es"):
                    path.write_text(json.dumps({"ui_language": code}), encoding="utf-8")
                    self.assertEqual(get_language(), code)
                with language("en"):
                    self.assertEqual(get_language(), "en")
                self.assertEqual(get_language(), "es")

    def test_validation_errors_follow_unsaved_config_language(self):
        original = json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))
        errors = []
        for code in ("en", "es"):
            with self.assertRaises(ConfigError) as context:
                validate_config({**original, "ui_language": code, "lamp_ip": "not-an-ip"})
            errors.append(str(context.exception))
        self.assertNotEqual(*errors)
        self.assertIn("IPv4", errors[0])
        self.assertIn("IPv4", errors[1])

    def test_tray_captions_follow_current_language(self):
        with language("en"):
            self.assertEqual(tr("tray.on"), "ON")
        with language("es"):
            self.assertEqual(tr("tray.on"), "ENCENDIDA")

    def test_formatting_and_english_fallback(self):
        with language("es"):
            self.assertIn("host: example", tr("msg_feb1ebf9ed28", "example"))
        with patch(
            "mijialamp.i18n.catalog", side_effect=lambda code: {"test": "Hello {0}"} if code == "en" else {}
        ):
            self.assertEqual(tr("test", "world", code="es"), "Hello world")
        with self.assertRaises(ValueError):
            catalog("../en")


if __name__ == "__main__":
    unittest.main()
