import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"
DATA_DIR = ROOT / "data"
LOG_DIR = ROOT / "logs"
SECRETS_DIR = ROOT / "secrets"
STATE_PATH = DATA_DIR / "runtime_state.json"
STATE_LOCK_PATH = DATA_DIR / "runtime_state.lock"
CONTROL_LOCK_PATH = DATA_DIR / "control.lock"
CONFIG_LOCK_PATH = DATA_DIR / "config.lock"
DEVICE_CACHE_PATH = DATA_DIR / "device_cache.json"
DEVICE_CACHE_LOCK_PATH = DATA_DIR / "device_cache.lock"
USER_DATA_DIR = Path(os.environ.get("LOCALAPPDATA", str(DATA_DIR))) / "MijiaLamp"
AGENT_LOCK_PATH = USER_DATA_DIR / "agent.lock"
TOKEN_PATH = SECRETS_DIR / "token.dpapi.json"
SERVICE_META_PATH = DATA_DIR / "service_meta.json"


def ensure_service_dirs() -> None:
    """Directories owned/written by the Windows service or elevated setup tools."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    SECRETS_DIR.mkdir(parents=True, exist_ok=True)


def ensure_agent_dirs() -> None:
    """Directories an interactive, non-elevated Agent is allowed to touch."""
    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    # The installer grants the authorized user Modify on logs, but deliberately no
    # access to secrets and no write access to service data.
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def ensure_dirs() -> None:
    """Compatibility helper for elevated/service contexts only.

    New code should call :func:`ensure_service_dirs` or :func:`ensure_agent_dirs`
    explicitly so privilege boundaries remain visible at call sites.
    """
    ensure_service_dirs()
    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
