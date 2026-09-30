"""Check release ZIP contents and hashes before they are published or installed."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path

ARCHIVE_RE = re.compile(r"^MijiaLamp-(Portable|Service)-([0-9]+\.[0-9]+\.[0-9]+)\.zip$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class VerificationError(ValueError):
    pass


def _safe_path(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or value.startswith("/") or ":" in value:
        raise VerificationError(f"Ruta insegura en archivo o manifiesto: {value!r}")
    parts = value.rstrip("/").split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise VerificationError(f"Ruta insegura en archivo o manifiesto: {value!r}")
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
            raise VerificationError(f"Entrada fuera de la carpeta de release: {name}")
        if (item.external_attr >> 16) & 0o170000 == 0o120000:
            raise VerificationError(f"Enlace simbólico dentro del ZIP: {name}")
        if item.is_dir():
            continue
        if name.casefold() in folded:
            raise VerificationError(f"Entrada duplicada en el ZIP: {name}")
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
        raise VerificationError(f"Manifiesto sin entradas para {prefix}")
    expected: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise VerificationError("Entrada de manifiesto inválida")
        relative = _safe_path(entry.get("path", ""))
        name = prefix + relative
        if name in expected:
            raise VerificationError(f"Entrada duplicada en manifiesto: {relative}")
        expected.add(name)
        if name not in names:
            if require_all:
                raise VerificationError(f"Falta archivo manifestado: {name}")
            continue
        size = entry.get("size")
        digest = entry.get("sha256")
        if type(size) is not int or size < 0 or not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
            raise VerificationError(f"Metadatos inválidos en manifiesto: {relative}")
        if archive.getinfo(name).file_size != size or _zip_hash(archive, name) != digest:
            raise VerificationError(f"Hash o tamaño incorrecto: {name}")
    return expected


def verify_archive(path: Path, *, require_runtime: bool = False) -> str:
    path = Path(path)
    match = ARCHIVE_RE.fullmatch(path.name)
    if not match:
        raise VerificationError(f"Nombre de ZIP inesperado: {path.name}")
    flavor, version = match.groups()
    root = path.stem

    sidecar = path.with_name(path.name + ".sha256")
    try:
        digest_line = sidecar.read_text(encoding="ascii").strip()
    except FileNotFoundError as exc:
        raise VerificationError(f"Falta {sidecar.name}") from exc
    actual_digest = _file_hash(path)
    if digest_line != f"{actual_digest}  {path.name}":
        raise VerificationError(f"SHA-256 del ZIP no coincide con {sidecar.name}")

    manifest_name = (
        f"{root}/runtime-manifest.json"
        if flavor == "Portable"
        else f"{root}/prepared-runtime/manifest.json"
    )
    runtime_prefix = f"{root}/runtime/" if flavor == "Portable" else f"{root}/prepared-runtime/python/"
    with zipfile.ZipFile(path) as archive:
        names = _check_entries(archive, root)
        runtime_names = {name for name in names if name.startswith(runtime_prefix)}
        if manifest_name not in names:
            if require_runtime or runtime_names:
                raise VerificationError(f"Falta manifiesto de runtime: {manifest_name}")
            return "bootstrap sin runtime"

        try:
            manifest = json.loads(archive.read(manifest_name))
        except (ValueError, UnicodeError) as exc:
            raise VerificationError("Manifiesto de runtime inválido") from exc
        if not isinstance(manifest, dict) or manifest.get("schema") != 1 or manifest.get("project_version") != version:
            raise VerificationError("Versión o esquema del manifiesto incorrecto")

        expected_runtime = _check_manifest_entries(
            archive, names, manifest.get("runtime_files"), prefix=runtime_prefix, require_all=True
        )
        if runtime_names != expected_runtime:
            raise VerificationError("Runtime contiene archivos no manifestados")

        expected_source = _check_manifest_entries(
            archive,
            names,
            manifest.get("source_files"),
            prefix=f"{root}/",
            require_all=flavor == "Service",
        )
        code_names = {
            name for name in names if name.startswith((f"{root}/mijialamp/", f"{root}/tools/"))
        }
        if not code_names <= expected_source:
            raise VerificationError("Código dentro del ZIP no está manifestado")
    return "runtime y source verificados"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="ZIP o carpeta release/")
    parser.add_argument("--require-runtime", action="store_true")
    args = parser.parse_args()
    paths = sorted(args.path.glob("MijiaLamp-*.zip")) if args.path.is_dir() else [args.path]
    if not paths:
        print("ERROR: no encontré ZIPs de release", file=sys.stderr)
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
