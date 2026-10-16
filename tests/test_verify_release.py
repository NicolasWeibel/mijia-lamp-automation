from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from mijialamp import __version__
from scripts.verify_release import VerificationError, verify_archive


class VerifyReleaseTests(unittest.TestCase):
    def make_release(
        self,
        folder: Path,
        *,
        extra_runtime: bool = False,
        bad_source: bool = False,
        flavor: str = "Service",
        missing_setup_file: bool = False,
    ) -> Path:
        root = f"MijiaLamp-{flavor}-{__version__}"
        path = folder / f"{root}.zip"
        runtime = b"python executable placeholder"
        source = b"print('agent')\n"
        files = {"agent.py": source}
        if flavor == "Setup":
            files.update(
                {
                    name: b"launcher placeholder"
                    for name in ("setup-gui.vbs", "setup-portable.ps1", "start-portable.cmd", "install.ps1")
                }
            )
        manifest = {
            "schema": 1,
            "project_version": __version__,
            "runtime_files": [
                {
                    "path": "python.exe",
                    "size": len(runtime),
                    "sha256": hashlib.sha256(runtime).hexdigest(),
                }
            ],
            "source_files": [
                {
                    "path": name,
                    "size": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
                for name, content in files.items()
            ],
        }
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(f"{root}/prepared-runtime/manifest.json", json.dumps(manifest))
            archive.writestr(f"{root}/prepared-runtime/python/python.exe", runtime)
            for name, content in files.items():
                if missing_setup_file and name == "setup-portable.ps1":
                    continue
                archive.writestr(f"{root}/{name}", content if not bad_source else b"modified")
            if extra_runtime:
                archive.writestr(f"{root}/prepared-runtime/python/extra.pth", b"import malware")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        (folder / f"{root}.zip.sha256").write_text(f"{digest}  {path.name}", encoding="ascii")
        return path

    def test_complete_release_matches_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(
                verify_archive(self.make_release(Path(tmp)), require_runtime=True),
                "runtime and source verified",
            )

    def test_combined_setup_includes_both_verified_modes(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(
                verify_archive(self.make_release(Path(tmp), flavor="Setup"), require_runtime=True),
                "runtime and source verified",
            )

    def test_combined_setup_rejects_missing_mode(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            self.assertRaisesRegex(VerificationError, "Manifested file is missing"),
        ):
            verify_archive(
                self.make_release(Path(tmp), flavor="Setup", missing_setup_file=True),
                require_runtime=True,
            )

    def test_unmanifested_runtime_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.make_release(Path(tmp), extra_runtime=True)
            with self.assertRaisesRegex(VerificationError, "unmanifested files"):
                verify_archive(path, require_runtime=True)

    def test_changed_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.make_release(Path(tmp), bad_source=True)
            with self.assertRaisesRegex(VerificationError, "Incorrect hash or size"):
                verify_archive(path, require_runtime=True)

    def test_changed_archive_is_rejected_by_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.make_release(Path(tmp))
            with path.open("ab") as stream:
                stream.write(b"changed")
            with self.assertRaisesRegex(VerificationError, "ZIP SHA-256"):
                verify_archive(path, require_runtime=True)

    def test_unmanifested_translation_catalog_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.make_release(Path(tmp))
            with zipfile.ZipFile(path, "a") as archive:
                archive.writestr(f"{path.stem}/mijialamp/locales/en.json", '{"unexpected": "text"}')
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            path.with_suffix(".zip.sha256").write_text(f"{digest}  {path.name}", encoding="ascii")
            with self.assertRaisesRegex(VerificationError, "is not manifested"):
                verify_archive(path, require_runtime=True)


if __name__ == "__main__":
    unittest.main()
