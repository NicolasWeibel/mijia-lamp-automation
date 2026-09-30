import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .paths import LOG_DIR


class SecretRedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # We never intentionally log tokens. This catches accidental 32-char hex
        # values passed as ordinary formatted strings.
        try:
            import re

            msg = record.getMessage()
            redacted = re.sub(r"(?i)\b[0-9a-f]{32}\b", "<redacted-token>", msg)
            if redacted != msg:
                record.msg = redacted
                record.args = ()
        except Exception:
            pass
        return True


def configure_logging(name: str, cfg: dict, console: bool = False, event_log: bool = False) -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if logger.handlers:
        return logger

    max_bytes = int(cfg.get("log_max_bytes", 5 * 1024 * 1024))
    backups = int(cfg.get("log_backup_count", 5))
    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(process)d | %(message)s")
    filt = SecretRedactionFilter()

    file_handler = RotatingFileHandler(
        Path(LOG_DIR) / f"{name}.log",
        maxBytes=max_bytes,
        backupCount=backups,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)
    file_handler.addFilter(filt)
    logger.addHandler(file_handler)

    if console:
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(fmt)
        stream.addFilter(filt)
        logger.addHandler(stream)

    if event_log and sys.platform == "win32" and bool(cfg.get("event_log_enabled", True)):
        try:
            from logging.handlers import NTEventLogHandler

            event = NTEventLogHandler("MijiaLamp")
            event.setLevel(logging.WARNING)
            event.setFormatter(logging.Formatter("%(name)s: %(levelname)s: %(message)s"))
            event.addFilter(filt)
            logger.addHandler(event)
        except Exception:
            # File logging remains authoritative if Event Viewer integration is unavailable.
            pass

    return logger
