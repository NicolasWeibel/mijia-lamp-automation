from __future__ import annotations

import os
import sys
import threading

from agent import LampAgent
from mijialamp.config import load_config
from mijialamp.controller import LampController
from mijialamp.ipc import PORTABLE_PIPE_NAME, PipeClient, PipeServer
from mijialamp.locking import FileLock
from mijialamp.logging_setup import configure_logging
from mijialamp.paths import AGENT_LOCK_PATH, ensure_service_dirs
from mijialamp.secrets_store import SCOPE_CURRENT_USER
from mijialamp.service_core import ServiceCore


def _current_user_sid() -> str:
    if os.name != "nt":
        raise RuntimeError("MijiaLamp Portable sólo funciona en Windows")
    import win32api
    import win32con
    import win32security

    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
    sid, _attrs = win32security.GetTokenInformation(token, win32security.TokenUser)
    return win32security.ConvertSidToStringSid(sid)


def main() -> int:
    if os.name != "nt":
        print("MijiaLamp Portable sólo puede ejecutarse en Windows.", file=sys.stderr)
        return 2

    # In portable mode these directories live beside the extracted application and are
    # owned by the interactive user. No privileged ACL setup is required.
    ensure_service_dirs()
    cfg = load_config()
    log = configure_logging("portable", cfg, console=False, event_log=False)

    try:
        with FileLock(AGENT_LOCK_PATH, timeout=0.1):
            controller = LampController(
                cfg,
                log,
                token_scope=SCOPE_CURRENT_USER,
            )
            core = ServiceCore(
                controller,
                cfg,
                log,
                runtime_name="MijiaLampPortable",
                token_scope=SCOPE_CURRENT_USER,
            )
            pipe = PipeServer(
                core.dispatch,
                authorized_user_sid=_current_user_sid(),
                pipe_name=PORTABLE_PIPE_NAME,
                logger=log,
                max_clients=8,
            )
            core.start()
            pipe_thread = threading.Thread(
                target=pipe.serve_forever,
                name="MijiaLampPortablePipe",
                daemon=True,
            )
            pipe_thread.start()
            log.info("MijiaLamp Portable runtime iniciado")
            try:
                agent = LampAgent(
                    client=PipeClient(PORTABLE_PIPE_NAME),
                    cfg=cfg,
                    log=log,
                    backend_label="Portable",
                    suspend_handler=lambda: core.dispatch(
                        {"command": "suspend", "source": "portable-direct"}
                    ),
                )
                agent.run()
            finally:
                pipe.stop()
                core.stop()
                pipe_thread.join(timeout=1.5)
                log.info("MijiaLamp Portable runtime detenido")
        return 0
    except Exception as exc:
        log.error("Portable runtime terminó con error: %s", exc, exc_info=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
