import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mijialamp.secrets_store import SCOPE_CURRENT_USER, SCOPE_LOCAL_MACHINE
from tools.migrate_legacy_config import migrate


class MigrationTests(unittest.TestCase):
    def test_legacy_plaintext_token_is_removed_and_migrated(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "config.json"
            token = "a" * 32
            path.write_text(json.dumps({"token": token, "manual_day_profile": {"kelvin": 4000}}))
            with patch("tools.migrate_legacy_config.token_exists", return_value=False), patch(
                "tools.migrate_legacy_config.store_token"
            ) as store:
                changed, migrated = migrate(path)
            data = json.loads(path.read_text())
            self.assertTrue(changed)
            self.assertTrue(migrated)
            store.assert_called_once_with(token, scope=SCOPE_LOCAL_MACHINE)
            self.assertNotIn("token", data)
            self.assertNotIn("manual_day_profile", data)
            self.assertEqual(data["version"], 3)

    def test_portable_migration_uses_current_user_scope(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "config.json"
            token = "b" * 32
            path.write_text(json.dumps({"token": token}))
            with patch("tools.migrate_legacy_config.token_exists", return_value=False) as exists, patch(
                "tools.migrate_legacy_config.store_token"
            ) as store:
                changed, migrated = migrate(path, token_scope=SCOPE_CURRENT_USER)
            self.assertTrue(changed)
            self.assertTrue(migrated)
            exists.assert_called_once_with(expected_scope=SCOPE_CURRENT_USER)
            store.assert_called_once_with(token, scope=SCOPE_CURRENT_USER)
            self.assertNotIn("token", json.loads(path.read_text()))

    def test_v2_operational_fields_are_mapped_or_removed(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "version": 2,
                        "transition_ms": 50,
                        "auto_discover_on_failure": True,
                        "scan_timeout_seconds": 0.8,
                        "scan_max_workers": 64,
                        "scan_max_hosts": 512,
                        "apply_light_profile_on_on": True,
                        "respect_display_state_in_sync": True,
                        "last_seen_model": "legacy",
                    }
                )
            )
            changed, migrated = migrate(path)
            data = json.loads(path.read_text())
            self.assertTrue(changed)
            self.assertFalse(migrated)
            self.assertEqual(data["version"], 3)
            self.assertEqual(data["power_transition_ms"], 50)
            self.assertTrue(data["discovery_enabled"])
            self.assertEqual(data["discovery_scan_timeout_seconds"], 0.8)
            self.assertEqual(data["discovery_scan_workers"], 32)
            for key in (
                "transition_ms",
                "auto_discover_on_failure",
                "scan_timeout_seconds",
                "scan_max_workers",
                "scan_max_hosts",
                "apply_light_profile_on_on",
                "respect_display_state_in_sync",
                "last_seen_model",
            ):
                self.assertNotIn(key, data)

    def test_migrator_direct_script_imports_project_from_any_cwd(self):
        root = Path(__file__).resolve().parents[1]
        script = root / "tools" / "migrate_legacy_config.py"
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            config = td_path / "config.json"
            config.write_text(json.dumps({"version": 2, "manual_day_profile": {"kelvin": 4000}}))
            cp = subprocess.run(
                [sys.executable, str(script), "--scope", SCOPE_CURRENT_USER, str(config)],
                cwd=td_path,
                text=True,
                capture_output=True,
                timeout=15,
            )
            self.assertEqual(cp.returncode, 0, cp.stdout + cp.stderr)
            data = json.loads(config.read_text())
            self.assertEqual(data["version"], 3)
            self.assertNotIn("manual_day_profile", data)



if __name__ == "__main__":
    unittest.main()
