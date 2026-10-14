"""Validate the settings editor's Base64 input independently of console encoding."""

import base64
import codecs
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mijialamp.config import validate_config


def main() -> int:
    try:
        # Windows PowerShell can prepend a UTF-8 BOM to native stdin. Read
        # bytes so Python's text encoding cannot turn it into non-ASCII text.
        encoded = sys.stdin.buffer.read().removeprefix(codecs.BOM_UTF8).strip()
        config = json.loads(base64.b64decode(encoded, validate=True).decode("utf-8"))
        validate_config(config)
    except Exception as exc:
        print(json.dumps({"ok": False, "message": str(exc)}, ensure_ascii=True))
        return 2
    print(json.dumps({"ok": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
