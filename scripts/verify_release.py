"""Check release ZIP contents and hashes before they are published or installed."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path

ARCHIVE_RE = re.compile(r"^MijiaLamp-(Portable|Service|Setup)-([0-9]+\.[0-9]+\.[0-9]+)\.zip$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class VerificationError(ValueError):
    pass


def _safe_path(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or value.startswith("/") or ":" in value:
        raise VerificationError(f"Unsafe path in file or manifest: {value!r}")
    parts = value.rstrip("/").split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise VerificationError(f"Unsafe path in file or manifest: {value!r}")
    return value


def _zip_hash(archive: zipfile.ZipFile, name: str) -> str:
    digest = hashlib.sha256()
    with archive.open(name) as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _check_entries(archive: zipfile.ZipFile, root: str) -> set[str]:
    names: set[str] = set()
    folded: set[str] = set()
    for item in archive.infolist():
        name = _safe_path(item.filename)
        if not name.startswith(root + "/"):
            raise VerificationError(f"Entry is outside the release folder: {name}")
        if (item.external_attr >> 16) & 0o170000 == 0o120000:
            raise VerificationError(f"Symbolic link inside ZIP: {name}")
        if item.is_dir():
            continue
        if name.casefold() in folded:
            raise VerificationError(f"Duplicate entry in ZIP: {name}")
        folded.add(name.casefold())
        names.add(name)
    return names


def _check_manifest_entries(
    archive: zipfile.ZipFile,
    names: set[str],
    entries: object,
    *,
    prefix: str,
    require_all: bool,
) -> set[str]:
    if not isinstance(entries, list) or not entries:
        raise VerificationError(f"Manifest has no entries for {prefix}")
    expected: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise VerificationError("Invalid manifest entry")
        relative = _safe_path(entry.get("path", ""))
        name = prefix + relative
        if name in expected:
            raise VerificationError(f"Duplicate manifest entry: {relative}")
        expected.add(name)
        if name not in names:
            if require_all:
                raise VerificationError(f"Manifested file is missing: {name}")
            continue
        size = entry.get("size")
        digest = entry.get("sha256")
        if (
            type(size) is not int
            or size < 0
            or not isinstance(digest, str)
            or not SHA256_RE.fullmatch(digest)
        ):
            raise VerificationError(f"Invalid manifest metadata: {relative}")
        if archive.getinfo(name).file_size != size or _zip_hash(archive, name) != digest:
            raise VerificationError(f"Incorrect hash or size: {name}")
    return expected


def verify_archive(path: Path, *, require_runtime: bool = False) -> str:
    path = Path(path)
    match = ARCHIVE_RE.fullmatch(path.name)
    if not match:
        raise VerificationError(f"Unexpected ZIP name: {path.name}")
    flavor, version = match.groups()
    root = path.stem

    sidecar = path.with_name(path.name + ".sha256")
    try:
        digest_line = sidecar.read_text(encoding="ascii").strip()
    except FileNotFoundError as exc:
        raise VerificationError(f"Missing {sidecar.name}") from exc
    actual_digest = _file_hash(path)
    if digest_line != f"{actual_digest}  {path.name}":
        raise VerificationError(f"ZIP SHA-256 does not match {sidecar.name}")

    manifest_name = (
        f"{root}/runtime-manifest.json" if flavor == "Portable" else f"{root}/prepared-runtime/manifest.json"
    )
    runtime_prefix = f"{root}/runtime/" if flavor == "Portable" else f"{root}/prepared-runtime/python/"
    with zipfile.ZipFile(path) as archive:
        names = _check_entries(archive, root)
        runtime_names = {name for name in names if name.startswith(runtime_prefix)}
        if manifest_name not in names:
            if require_runtime or runtime_names:
                raise VerificationError(f"Runtime manifest is missing: {manifest_name}")
            return "bootstrap without runtime"

        try:
            manifest = json.loads(archive.read(manifest_name))
        except (ValueError, UnicodeError) as exc:
            raise VerificationError("Invalid runtime manifest") from exc
        if (
            not isinstance(manifest, dict)
            or manifest.get("schema") != 1
            or manifest.get("project_version") != version
        ):
            raise VerificationError("Manifest version or schema is incorrect")

        expected_runtime = _check_manifest_entries(
            archive, names, manifest.get("runtime_files"), prefix=runtime_prefix, require_all=True
        )
        if runtime_names != expected_runtime:
            raise VerificationError("Runtime contains unmanifested files")

        source_entries = manifest.get("source_files")
        if flavor == "Service" and isinstance(source_entries, list):
            portable_only = {
                "setup-portable.ps1",
                "start-portable.cmd",
                "portable-status.cmd",
                "portable-on.cmd",
                "portable-off.cmd",
                "portable-sleep-now.cmd",
                "enable-portable-autostart.ps1",
                "disable-portable-autostart.ps1",
                "enable-portable-automation.ps1",
                "disable-portable-automation.ps1",
            }
            source_entries = [
                entry
                for entry in source_entries
                if isinstance(entry, dict) and entry.get("path") not in portable_only
            ]
        expected_source = _check_manifest_entries(
            archive,
            names,
            source_entries,
            prefix=f"{root}/",
            require_all=flavor in {"Service", "Setup"},
        )
        code_names = {
            name
            for name in names
            if name.startswith((f"{root}/mijialamp/", f"{root}/tools/", f"{root}/mijialamp/locales/"))
        }
        code_names |= {
            name for name in names if name.endswith((".ps1", ".cmd", ".vbs", ".py")) and name.count("/") == 1
        }
        if not code_names <= expected_source:
            raise VerificationError("Code in ZIP is not manifested")
        if flavor == "Setup":
            for required in ("setup-gui.vbs", "setup-portable.ps1", "start-portable.cmd", "install.ps1"):
                if f"{root}/{required}" not in names:
                    raise VerificationError(f"Installer mode or launcher is missing: {required}")
    return "runtime and source verified"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="ZIP o carpeta release/")
    parser.add_argument("--require-runtime", action="store_true")
    args = parser.parse_args()
    paths = sorted(args.path.glob("MijiaLamp-*.zip")) if args.path.is_dir() else [args.path]
    if not paths:
        print("ERROR: no release ZIPs found", file=sys.stderr)
        return 1
    try:
        for path in paths:
            print(f"{path.name}: {verify_archive(path, require_runtime=args.require_runtime)}")
    except (OSError, zipfile.BadZipFile, VerificationError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
