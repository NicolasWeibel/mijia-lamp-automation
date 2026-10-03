"""Regenerate runtime requirement hashes from reviewed Windows wheels.

Download wheels for every supported Python version first. The wheel directory is
an input, not a trust anchor: review its source before committing new hashes.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import zipfile
from collections import defaultdict
from email.parser import BytesParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCKS = (
    ROOT / "requirements.lock.txt",
    ROOT / "requirements.windows.lock.txt",
    ROOT / "requirements.miio.lock.txt",
)
PIN_RE = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s=]+)(?:\s+--hash=sha256:[0-9a-f]{64})*$")


def canonical_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def wheel_identity(path: Path) -> tuple[str, str]:
    with zipfile.ZipFile(path) as archive:
        metadata_files = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
        if len(metadata_files) != 1:
            raise ValueError(f"Wheel sin metadata única: {path.name}")
        metadata = BytesParser().parsebytes(archive.read(metadata_files[0]), headersonly=True)
    name, version = metadata.get("Name"), metadata.get("Version")
    if not name or not version:
        raise ValueError(f"Wheel sin nombre o versión: {path.name}")
    return canonical_name(name), version


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel_dir", type=Path, help="Directorio de wheels Windows revisados")
    args = parser.parse_args()
    wheels = sorted(args.wheel_dir.glob("*.whl"))
    if not wheels:
        parser.error("No hay wheels en el directorio")

    hashes: dict[tuple[str, str], list[str]] = defaultdict(list)
    for wheel in wheels:
        identity = wheel_identity(wheel)
        digest_state = hashlib.sha256()
        with wheel.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest_state.update(chunk)
        digest = digest_state.hexdigest()
        hashes[identity].append(digest)

    expected: set[tuple[str, str]] = set()
    updates: dict[Path, str] = {}
    for lock in LOCKS:
        output: list[str] = []
        for raw in lock.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                output.append(raw)
                continue
            match = PIN_RE.fullmatch(line)
            if not match:
                raise ValueError(f"Pin inválido en {lock.name}: {line}")
            name, version = match.groups()
            identity = canonical_name(name), version
            if identity in expected:
                raise ValueError(f"Pin duplicado: {name}=={version}")
            expected.add(identity)
            if identity not in hashes:
                raise ValueError(f"Falta wheel para {name}=={version}")
            suffix = " ".join(f"--hash=sha256:{digest}" for digest in sorted(set(hashes[identity])))
            output.append(f"{name}=={version} {suffix}")
        updates[lock] = "\n".join(output).rstrip() + "\n"

    unexpected = set(hashes) - expected
    if unexpected:
        raise ValueError(f"Wheels ajenos a los locks: {sorted(unexpected)}")
    for lock, content in updates.items():
        lock.write_text(content, encoding="utf-8", newline="\n")
    print(f"Hashes SHA-256 actualizados: {len(expected)} paquetes, {len(wheels)} wheels")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
