"""Validate hashed runtime locks and optionally export plain pins for audit tools."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = (
    ROOT / "requirements.lock.txt",
    ROOT / "requirements.windows.lock.txt",
    ROOT / "requirements.miio.lock.txt",
)
PIN_RE = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s=]+)((?:\s+--hash=sha256:[0-9a-f]{64})+)$")
HASH_RE = re.compile(r"--hash=sha256:([0-9a-f]{64})")


def canonical_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plain-output", type=Path, help="Export pins without hashes for audit/SBOM tools")
    args = parser.parse_args()

    errors: list[str] = []
    seen: set[str] = set()
    plain_pins: list[str] = []
    for path in FILES:
        for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            match = PIN_RE.fullmatch(line)
            if not match:
                errors.append(f"{path.name}:{number}: dependency needs an exact pin and SHA-256 hash: {line}")
                continue
            name, version, hashes_text = match.groups()
            normalized = canonical_name(name)
            if normalized in seen:
                errors.append(f"{path.name}:{number}: duplicate dependency: {name}")
            seen.add(normalized)
            if normalized == "netifaces":
                errors.append(f"{path.name}:{number}: netifaces must not be installed by this project")
            hashes = HASH_RE.findall(hashes_text)
            if len(hashes) != len(set(hashes)):
                errors.append(f"{path.name}:{number}: duplicate hash: {name}")
            plain_pins.append(f"{name}=={version}")
    if errors:
        print("\n".join(errors))
        return 1
    if args.plain_output:
        args.plain_output.write_text("\n".join(plain_pins) + "\n", encoding="ascii")
    print(f"Dependency pins and SHA-256 hashes: OK ({len(plain_pins)} packages)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
