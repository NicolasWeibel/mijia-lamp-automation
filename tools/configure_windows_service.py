from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mijialamp.i18n import tr

SERVICE = "MijiaLampService"


def main() -> int:
    if sys.platform != "win32":
        return 0
    import win32evtlogutil
    import win32service

    try:
        win32evtlogutil.AddSourceToRegistry("MijiaLamp", eventLogType="Application")
    except Exception as exc:
        print(tr("msg_760122896e77", exc))

    try:
        scm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_CONNECT)
        try:
            svc = win32service.OpenService(scm, SERVICE, win32service.SERVICE_CHANGE_CONFIG)
            try:
                win32service.ChangeServiceConfig2(
                    svc,
                    win32service.SERVICE_CONFIG_PRESHUTDOWN_INFO,
                    10000,
                )
            finally:
                win32service.CloseServiceHandle(svc)
        finally:
            win32service.CloseServiceHandle(scm)
    except Exception as exc:
        print(tr("msg_3ccf7b39eee5", exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
