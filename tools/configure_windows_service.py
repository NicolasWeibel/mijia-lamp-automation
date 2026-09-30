from __future__ import annotations

import sys

SERVICE = "MijiaLampService"


def main() -> int:
    if sys.platform != "win32":
        return 0
    import win32service
    import win32evtlogutil

    try:
        win32evtlogutil.AddSourceToRegistry("MijiaLamp", eventLogType="Application")
    except Exception as exc:
        print(f"WARNING: no se pudo registrar Event Viewer source: {exc}")

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
        print(f"ERROR: no se pudo configurar preshutdown timeout: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
