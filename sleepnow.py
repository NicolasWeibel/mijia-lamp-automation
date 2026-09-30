from __future__ import annotations

import argparse
import threading
import time

from mijialamp.config import load_config
from mijialamp.ipc import PORTABLE_PIPE_NAME, PipeClient
from mijialamp.logging_setup import configure_logging
from mijialamp.paths import ensure_agent_dirs
from mijialamp.windows_power import suspend_windows


def _confirmed_off(client: PipeClient, timeout: float = 2.0) -> tuple[bool, str | None]:
    """Run request/reply on a daemon thread so a stuck pipe cannot block Sleep Now forever."""
    done = threading.Event()
    result = {"error": None}

    def worker() -> None:
        try:
            client.request("suspend", timeout=min(1.0, timeout))
        except Exception as exc:  # reported by the caller, never swallowed silently
            result["error"] = str(exc)
        finally:
            done.set()

    threading.Thread(target=worker, name="MijiaLampSleepOff", daemon=True).start()
    if not done.wait(max(0.1, float(timeout))):
        return False, "timeout esperando confirmación del servicio"
    return result["error"] is None, result["error"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Apaga la lámpara y suspende/hiberna Windows")
    parser.add_argument("--hibernate", action="store_true")
    parser.add_argument("--mode", choices=("service", "portable"), default="service")
    parser.add_argument("--delay", type=float, default=0.35)
    parser.add_argument("--require-lamp-off", action="store_true")
    parser.add_argument("--off-timeout", type=float, default=2.0)
    args = parser.parse_args()

    ensure_agent_dirs()
    cfg = load_config()
    log = configure_logging("sleepnow", cfg, console=True, event_log=True)
    client = PipeClient(PORTABLE_PIPE_NAME) if args.mode == "portable" else PipeClient()

    if args.require_lamp_off:
        off_ok, error = _confirmed_off(client, timeout=float(args.off_timeout))
        if not off_ok:
            log.error("No se confirmó OFF crítico: %s", error)
            return 4
    else:
        # One-way IPC prevents a slow miIO response from recreating the original v2 bug
        # where Sleep Now killed/waited on the lamp command instead of suspending Windows.
        try:
            client.notify("suspend", timeout=0.5)
        except Exception as exc:
            log.error("No se pudo encolar OFF crítico al servicio: %s", exc)

    time.sleep(max(0.0, float(args.delay)))
    try:
        suspend_windows(hibernate=args.hibernate)
        return 0
    except Exception as exc:
        log.error("No se pudo suspender Windows: %s", exc, exc_info=True)
        return 5


if __name__ == "__main__":
    raise SystemExit(main())
