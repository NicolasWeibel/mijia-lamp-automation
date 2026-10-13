"""Shared English/Spanish message catalogs; protocol identifiers stay unchanged."""

from __future__ import annotations

import contextlib
import contextvars
import json
import locale
import os
from functools import lru_cache, wraps
from pathlib import Path

SUPPORTED_LANGUAGES = ("en", "es")
_override: contextvars.ContextVar[str | None] = contextvars.ContextVar("mijialamp_ui_language", default=None)
_CATALOG_DIR = Path(__file__).resolve().parent / "locales"


def get_language() -> str:
    explicit = _override.get()
    if explicit in SUPPORTED_LANGUAGES:
        return explicit
    # Read the preference afresh so the tray can pick up a saved language change.
    try:
        from .paths import CONFIG_PATH

        with CONFIG_PATH.open(encoding="utf-8-sig") as stream:
            saved = json.load(stream).get("ui_language")
        if saved in SUPPORTED_LANGUAGES:
            return saved
    except (OSError, ValueError, AttributeError):
        pass
    requested = os.environ.get("MIJIALAMP_LANGUAGE")
    if requested in SUPPORTED_LANGUAGES:
        return requested
    system_language = locale.getlocale()[0] or "en"
    return "es" if system_language.lower().startswith("es") else "en"


@contextlib.contextmanager
def language(code: str):
    token = _override.set(code if code in SUPPORTED_LANGUAGES else "en")
    try:
        yield
    finally:
        _override.reset(token)


@lru_cache(maxsize=2)
def catalog(code: str) -> dict[str, str]:
    if code not in SUPPORTED_LANGUAGES:
        raise ValueError("Unsupported interface language")
    with (_CATALOG_DIR / f"{code}.json").open(encoding="utf-8") as stream:
        messages = json.load(stream)
    return messages


def tr(key: str, *args, code: str | None = None) -> str:
    text = catalog(code or get_language()).get(key)
    if text is None:
        text = catalog("en")[key]
    return text.format(*args) if args else text


def localize_config(function):
    """Validate using the supplied config's language, even before it is saved."""

    @wraps(function)
    def wrapped(cfg, *args, **kwargs):
        selected = cfg.get("ui_language", get_language()) if isinstance(cfg, dict) else get_language()
        with language(selected):
            return function(cfg, *args, **kwargs)

    return wrapped
