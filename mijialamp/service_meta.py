from __future__ import annotations

import json
import re

from mijialamp.i18n import tr

from .errors import ConfigError
from .paths import SERVICE_META_PATH

_SID_RE = re.compile(r"^S-1-(?:\d+-)+\d+$", re.IGNORECASE)


def load_authorized_user_sid() -> str:
    """Return the installer-selected interactive user's SID for pipe ACLs.

    The service fails closed if this metadata is absent or malformed. The pipe ACL is
    built separately for SYSTEM, Administrators, the exact Service SID and this user.
    """
    try:
        with open(SERVICE_META_PATH, encoding="utf-8") as fh:
            payload = json.load(fh)
    except FileNotFoundError as exc:
        raise ConfigError(tr("msg_ef1d678ce0fb")) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(tr("msg_a4437afb2d73")) from exc
    sid = str(payload.get("authorized_user_sid", "")).strip()
    if not _SID_RE.fullmatch(sid):
        raise ConfigError(tr("msg_391560ad2d41"))
    return sid
