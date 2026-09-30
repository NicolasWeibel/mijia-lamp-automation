from __future__ import annotations

import json
import re

from .errors import ConfigError
from .paths import SERVICE_META_PATH

_SID_RE = re.compile(r"^S-1-(?:\d+-)+\d+$", re.IGNORECASE)


def load_authorized_user_sid() -> str:
    """Return the installer-selected interactive user's SID for pipe ACLs.

    The service fails closed if this metadata is absent or malformed. The pipe ACL is
    built separately for SYSTEM, Administrators, the exact Service SID and this user.
    """
    try:
        with open(SERVICE_META_PATH, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except FileNotFoundError as exc:
        raise ConfigError(
            "Falta data/service_meta.json. Reinstalá MijiaLamp v3 como Administrador."
        ) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError("data/service_meta.json no es válido") from exc
    sid = str(payload.get("authorized_user_sid", "")).strip()
    if not _SID_RE.fullmatch(sid):
        raise ConfigError("authorized_user_sid inválido en service_meta.json")
    return sid
