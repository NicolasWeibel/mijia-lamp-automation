from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = [
    ROOT / "requirements.lock.txt",
    ROOT / "requirements.windows.lock.txt",
    ROOT / "requirements.miio.lock.txt",
]
PIN_RE = re.compile(r"^[A-Za-z0-9_.-]+==[^=\s]+(?:\s*;.*)?$")


def main() -> int:
    errors: list[str] = []
    for path in FILES:
        for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if not PIN_RE.match(line):
                errors.append(f"{path.name}:{number}: dependency is not exactly pinned: {line}")
            if line.lower().startswith("netifaces=="):
                errors.append(f"{path.name}:{number}: netifaces must not be installed by this project")
    if errors:
        print("\n".join(errors))
        return 1
    print("Dependency pins: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
