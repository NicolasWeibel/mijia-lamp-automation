from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.verify_release import VerificationError, verify_archive


class VerifyReleaseTests(unittest.TestCase):
    def make_release(self, folder: Path, *, extra_runtime: bool = False, bad_source: bool = False) -> Path:
        root = "MijiaLamp-Service-3.1.3"
        path = folder / f"{root}.zip"
        runtime = b"python executable placeholder"
        source = b"print('agent')\n"
        manifest = {
            "schema": 1,
            "project_version": "3.1.3",
            "runtime_files": [
                {
                    "path": "python.exe",
                    "size": len(runtime),
                    "sha256": hashlib.sha256(runtime).hexdigest(),
                }
            ],
            "source_files": [
                {
                    "path": "agent.py",
                    "size": len(source),
                    "sha256": hashlib.sha256(source).hexdigest(),
                }
            ],
        }
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(f"{root}/prepared-runtime/manifest.json", json.dumps(manifest))
            archive.writestr(f"{root}/prepared-runtime/python/python.exe", runtime)
            archive.writestr(f"{root}/agent.py", source if not bad_source else b"modified")
            if extra_runtime:
                archive.writestr(f"{root}/prepared-runtime/python/extra.pth", b"import malware")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        (folder / f"{root}.zip.sha256").write_text(f"{digest}  {path.name}", encoding="ascii")
        return path

    def test_complete_release_matches_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(
                verify_archive(self.make_release(Path(tmp)), require_runtime=True),
                "runtime y source verificados",
            )

    def test_unmanifested_runtime_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.make_release(Path(tmp), extra_runtime=True)
            with self.assertRaisesRegex(VerificationError, "no manifestados"):
                verify_archive(path, require_runtime=True)

    def test_changed_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.make_release(Path(tmp), bad_source=True)
            with self.assertRaisesRegex(VerificationError, "Hash o tamaño incorrecto"):
                verify_archive(path, require_runtime=True)

    def test_changed_archive_is_rejected_by_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.make_release(Path(tmp))
            with path.open("ab") as stream:
                stream.write(b"changed")
            with self.assertRaisesRegex(VerificationError, "SHA-256 del ZIP"):
                verify_archive(path, require_runtime=True)


if __name__ == "__main__":
    unittest.main()
