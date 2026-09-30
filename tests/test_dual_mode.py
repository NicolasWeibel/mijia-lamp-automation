from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mijialamp.cli import build_parser
from mijialamp.secrets_store import (
    SCOPE_CURRENT_USER,
    SCOPE_LOCAL_MACHINE,
    load_token,
    store_token,
    token_metadata,
)


class DualModeTests(unittest.TestCase):
    def test_cli_accepts_portable_mode(self):
        args = build_parser().parse_args(["--mode", "portable", "status"])
        self.assertEqual(args.mode, "portable")
        self.assertEqual(args.command, "status")

    def test_current_user_scope_is_persisted_and_enforced(self):
        token = "ab" * 16
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "token.dpapi.json"
            with patch("mijialamp.secrets_store._protect", return_value=b"cipher"):
                store_token(token, path, scope=SCOPE_CURRENT_USER)
            self.assertEqual(token_metadata(path)["scope"], SCOPE_CURRENT_USER)
            with patch("mijialamp.secrets_store._unprotect", return_value=token.encode("ascii")):
                self.assertEqual(load_token(path, expected_scope=SCOPE_CURRENT_USER), token)
                with self.assertRaises(Exception):
                    load_token(path, expected_scope=SCOPE_LOCAL_MACHINE)

    def test_legacy_machine_scope_is_normalized(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "token.dpapi.json"
            path.write_text(
                json.dumps(
                    {
                        "version": 2,
                        "scope": "dpapi-local-machine-service-owned",
                        "ciphertext_b64": "YQ==",
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(token_metadata(path)["scope"], SCOPE_LOCAL_MACHINE)

    def test_elevated_installer_has_no_package_download_or_pip_execution(self):
        root = Path(__file__).resolve().parents[1]
        text = (root / "install.ps1").read_text(encoding="utf-8").lower()
        self.assertNotIn("-m pip install", text)
        self.assertNotIn("-m pip download", text)
        self.assertNotIn("invoke-webrequest", text)
        self.assertNotIn("invoke-restmethod", text)
        self.assertIn("verify-preparedruntime", text)

    def test_service_preparation_is_explicitly_non_elevated(self):
        root = Path(__file__).resolve().parents[1]
        text = (root / "prepare-service-runtime.ps1").read_text(encoding="utf-8")
        self.assertIn("Assert-NotElevated", text)
        self.assertIn("--only-binary=:all:", text)
        self.assertIn("manifest.json", text)

    def test_portable_setup_refuses_elevation(self):
        root = Path(__file__).resolve().parents[1]
        text = (root / "setup-portable.ps1").read_text(encoding="utf-8")
        self.assertIn("Assert-NotElevated", text)
        self.assertIn(".venv", text)

    def test_portable_setup_migrates_legacy_config_to_current_user_scope(self):
        root = Path(__file__).resolve().parents[1]
        text = (root / "setup-portable.ps1").read_text(encoding="utf-8").lower()
        self.assertIn("[string]$configpath", text)
        self.assertIn("migrate_legacy_config.py --scope current-user", text)

    def test_hardened_install_rechecks_staging_and_integrity(self):
        root = Path(__file__).resolve().parents[1]
        install = (root / "install.ps1").read_text(encoding="utf-8").lower()
        security = (root / "security-check.ps1").read_text(encoding="utf-8").lower()
        self.assertIn("verify-stagingagainstpreparedmanifest", install)
        self.assertIn("integrity-manifest.json", install)
        self.assertIn("integrity-manifest.json", security)

    def test_portable_start_is_idempotent_at_wrapper_level(self):
        root = Path(__file__).resolve().parents[1]
        text = (root / "start-portable.cmd").read_text(encoding="utf-8").lower()
        self.assertIn("runtime-status", text)
        self.assertIn("ya esta ejecutandose", text)

    def test_portable_release_prefers_bundled_runtime(self):
        root = Path(__file__).resolve().parents[1]
        setup = (root / "setup-portable.ps1").read_text(encoding="utf-8").lower()
        build = (root / "scripts" / "build-release.ps1").read_text(encoding="utf-8").lower()
        self.assertIn("verify-bundledruntime", setup)
        self.assertIn("runtime-manifest.json", setup)
        self.assertIn("runtime-manifest.json", build)



if __name__ == "__main__":
    unittest.main()
