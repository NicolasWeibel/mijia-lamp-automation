import json
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.check_repository import check_hygiene

ROOT = Path(__file__).resolve().parents[1]


class RepositoryHygieneTests(unittest.TestCase):
    def test_release_tag_must_match_project_version(self):
        with patch.dict("os.environ", {"GITHUB_REF": "refs/tags/v0.0.0"}):
            with self.assertRaises(SystemExit):
                check_hygiene()

    def test_private_config_is_not_tracked(self):
        self.assertFalse((ROOT / "config.json").exists())
        self.assertTrue((ROOT / "config.example.json").is_file())

    def test_example_config_has_no_token(self):
        with open(ROOT / "config.example.json", "r", encoding="utf-8") as fh:
            cfg = json.load(fh)
        self.assertNotIn("token", cfg)

    def test_gitignore_covers_runtime_and_secrets(self):
        text = (ROOT / ".gitignore").read_text(encoding="utf-8")
        for entry in ("config.json", "secrets/", "data/", "logs/", "mi-tokens.json"):
            self.assertIn(entry, text)

    def test_agent_does_not_import_device_or_secret_layers(self):
        text = (ROOT / "agent.py").read_text(encoding="utf-8")
        self.assertNotIn("secrets_store", text)
        self.assertNotIn("miio_client", text)
        self.assertNotIn("from miio", text)
        self.assertIn("ensure_agent_dirs", text)

    def test_cli_does_not_create_service_owned_directories(self):
        text = (ROOT / "mijialamp" / "cli.py").read_text(encoding="utf-8")
        self.assertNotIn("ensure_service_dirs", text)
        self.assertNotIn("ensure_dirs", text)

    def test_service_uses_service_owned_directory_setup(self):
        text = (ROOT / "service.py").read_text(encoding="utf-8")
        self.assertIn("ensure_service_dirs", text)

    def test_automation_management_scripts_require_administrator(self):
        for name in ("enable-automation.ps1", "disable-automation.ps1"):
            text = (ROOT / name).read_text(encoding="utf-8")
            self.assertIn("WindowsBuiltInRole]::Administrator", text)
            self.assertIn("Assert-Administrator", text)


if __name__ == "__main__":
    unittest.main()
