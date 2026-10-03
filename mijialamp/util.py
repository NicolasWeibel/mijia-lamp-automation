import contextlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SECRET_HEX_RE = re.compile(r"(?i)\b[0-9a-f]{32}\b")


def redact_secrets(value) -> str:
    return _SECRET_HEX_RE.sub("<redacted-token>", str(value))


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def epoch_now() -> float:
    return datetime.now(timezone.utc).timestamp()


def atomic_write_json(path: Path, data: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = None
    fd = None
    try:
        fd, tmp_path = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent), text=True
        )
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fd = None
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
        tmp_path = None
    finally:
        if fd is not None:
            with contextlib.suppress(OSError):
                os.close(fd)
        if tmp_path:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)


def cleanup_temp_files(directory: Path, older_than_seconds: float = 3600) -> int:
    directory = Path(directory)
    if not directory.exists():
        return 0
    now = epoch_now()
    removed = 0
    for item in directory.glob(".*.tmp"):
        try:
            if now - item.stat().st_mtime >= older_than_seconds:
                item.unlink()
                removed += 1
        except OSError:
            pass
    return removed
