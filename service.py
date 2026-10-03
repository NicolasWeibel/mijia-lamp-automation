from __future__ import annotations

import contextlib
import os
import sys

SERVICE_NAME = "MijiaLampService"

if os.name == "nt":
    import servicemanager
    import win32event
    import win32service
    import win32serviceutil

    from mijialamp.config import load_config
    from mijialamp.controller import LampController
    from mijialamp.ipc import PipeServer
    from mijialamp.logging_setup import configure_logging
    from mijialamp.paths import ensure_service_dirs
    from mijialamp.secrets_store import SCOPE_LOCAL_MACHINE
    from mijialamp.service_core import ServiceCore
    from mijialamp.service_meta import load_authorized_user_sid

    class MijiaLampService(win32serviceutil.ServiceFramework):
        _svc_name_ = SERVICE_NAME
        _svc_display_name_ = "MijiaLamp Automation Service"
        _svc_description_ = (
            "Owns Xiaomi/Mijia LAN control, token access, synchronization and "
            "preshutdown/suspend safety for MijiaLamp."
        )

        def __init__(self, args):
            super().__init__(args)
            self.stop_event = win32event.CreateEvent(None, 0, 0, None)
            self.core = None
            self.pipe = None
            self.log = None

        def GetAcceptedControls(self):
            controls = super().GetAcceptedControls()
            controls |= win32service.SERVICE_ACCEPT_SHUTDOWN
            controls |= win32service.SERVICE_ACCEPT_PRESHUTDOWN
            controls |= win32service.SERVICE_ACCEPT_POWEREVENT
            return controls

        def SvcStop(self):
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            if self.pipe:
                self.pipe.stop()
            if self.core:
                self.core.stop()
            win32event.SetEvent(self.stop_event)

        def SvcShutdown(self):
            try:
                if self.core:
                    self.core.dispatch({"command": "shutdown"})
            except Exception as exc:
                if self.log:
                    self.log.error("Shutdown OFF failed: %s", exc, exc_info=True)

        def SvcOtherEx(self, control, event_type, data):
            try:
                if not self.core:
                    return 0
                if control == win32service.SERVICE_CONTROL_PRESHUTDOWN:
                    self.core.dispatch({"command": "preshutdown"})
                    return 0
                if control == win32service.SERVICE_CONTROL_POWEREVENT:
                    if event_type == 0x0004:  # PBT_APMSUSPEND
                        self.core.dispatch({"command": "suspend"})
                    elif event_type == 0x0012:  # PBT_APMRESUMEAUTOMATIC
                        self.core.dispatch({"command": "resume-auto"})
                    elif event_type == 0x0007:  # PBT_APMRESUMESUSPEND
                        self.core.dispatch({"command": "resume-user"})
                    return 0
            except Exception as exc:
                if self.log:
                    self.log.error("Service control failed: %s", exc, exc_info=True)
            return 0

        def SvcDoRun(self):
            ensure_service_dirs()
            try:
                cfg = load_config()
                self.log = configure_logging("service", cfg, event_log=True)
                controller = LampController(cfg, self.log, token_scope=SCOPE_LOCAL_MACHINE)
                self.core = ServiceCore(
                    controller,
                    cfg,
                    self.log,
                    runtime_name="MijiaLampService",
                    token_scope=SCOPE_LOCAL_MACHINE,
                )
                authorized_sid = load_authorized_user_sid()
                import win32security

                service_sid_obj, _domain, _sid_type = win32security.LookupAccountName(
                    None, f"NT SERVICE\\{SERVICE_NAME}"
                )
                service_sid = win32security.ConvertSidToStringSid(service_sid_obj)
                self.pipe = PipeServer(
                    self.core.dispatch,
                    authorized_user_sid=authorized_sid,
                    server_sid=service_sid,
                    logger=self.log,
                )
                self.core.start()
                self.log.info("MijiaLampService started")
                self.ReportServiceStatus(win32service.SERVICE_RUNNING)
                self.pipe.serve_forever()
            except Exception as exc:
                with contextlib.suppress(Exception):
                    servicemanager.LogErrorMsg(f"MijiaLampService failed: {type(exc).__name__}: {exc}")
                if self.log:
                    self.log.error("Service fatal error: %s", exc, exc_info=True)
            finally:
                if self.core:
                    self.core.stop()
                if self.log:
                    self.log.info("MijiaLampService stopped")


def main() -> int:
    if os.name != "nt":
        print("MijiaLampService sólo puede ejecutarse/instalarse en Windows.", file=sys.stderr)
        return 2
    if len(sys.argv) == 1:
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(MijiaLampService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        win32serviceutil.HandleCommandLine(MijiaLampService)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
