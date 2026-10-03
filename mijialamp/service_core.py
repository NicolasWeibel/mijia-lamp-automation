from __future__ import annotations

import contextlib
import socket
import threading
import time
from dataclasses import asdict

from . import __version__
from .controller import LampController
from .errors import MijiaLampError
from .secrets_store import token_exists, token_metadata
from .util import utc_now_iso


class ServiceCore:
    """OS-independent service state machine; Windows service/IPC are adapters around it."""

    def __init__(
        self,
        controller: LampController,
        cfg: dict,
        logger,
        *,
        runtime_name: str = "MijiaLampService",
        token_scope: str | None = None,
    ):
        self.controller = controller
        self.cfg = cfg
        self.log = logger
        self.runtime_name = runtime_name
        self.token_scope = token_scope
        self._stop = threading.Event()
        self._periodic_thread: threading.Thread | None = None
        self._network_thread: threading.Thread | None = None

    def start(self) -> None:
        if self._periodic_thread and self._periodic_thread.is_alive():
            return
        self._stop.clear()
        self.controller.invalidate_interactive_state(
            "portable-start" if self.runtime_name == "MijiaLampPortable" else "service-start"
        )
        self._periodic_thread = threading.Thread(
            target=self._periodic_loop, name="MijiaLampPeriodic", daemon=True
        )
        self._network_thread = threading.Thread(
            target=self._network_loop, name="MijiaLampNetworkWatch", daemon=True
        )
        self._periodic_thread.start()
        self._network_thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._periodic_thread:
            self._periodic_thread.join(timeout=2)
        if self._network_thread:
            self._network_thread.join(timeout=2)

    @staticmethod
    def _network_signature() -> tuple[str, ...]:
        try:
            values: set[str] = set()
            for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
                address = item[4][0] if item[4] else None
                if isinstance(address, str) and not address.startswith(("127.", "169.254.")):
                    values.add(address)
            return tuple(sorted(values))
        except OSError:
            return ()

    def _network_loop(self) -> None:
        interval = max(5.0, float(self.cfg.get("network_change_poll_seconds", 10)))
        previous = self._network_signature()
        while not self._stop.wait(interval):
            current = self._network_signature()
            if not current or current == previous:
                if current:
                    previous = current
                continue
            self.log.info("Cambio de red detectado: %s -> %s", previous, current)
            previous = current
            try:
                self.controller.network_changed()
                state = self.controller.state.read()
                if bool(state.get("automation_enabled", False)):
                    self.controller.sync("network-change")
            except Exception as exc:
                self.log.warning("Network-change sync failed: %s", exc)

    def _periodic_loop(self) -> None:
        interval = max(10.0, float(self.cfg.get("sync_interval_seconds", 60)))
        while not self._stop.wait(interval):
            state = self.controller.state.read()
            if not bool(state.get("automation_enabled", False)):
                continue
            try:
                self.controller.sync("periodic-sync")
            except Exception as exc:
                self.log.warning("Periodic sync failed: %s", exc)

    def _critical_off(
        self,
        reason: str,
        *,
        clear_overrides: bool,
        reassert: bool,
        critical_timeout: float | None = None,
    ) -> dict:
        self.controller.system_off(
            reason,
            fast=True,
            clear_overrides=clear_overrides,
            critical_timeout=critical_timeout,
        )
        critical_revision = int(self.controller.state.read().get("critical_off_revision", 0))

        if reassert:

            def reassert_off() -> None:
                time.sleep(0.25)
                self.controller.reassert_critical_off(reason, critical_revision)

            threading.Thread(target=reassert_off, name="MijiaLampOffReassert", daemon=True).start()
        return {"off": True, "reason": reason}

    @staticmethod
    def _sync_payload(result: dict):
        result = dict(result)
        if result.get("desired") is not None and hasattr(result["desired"], "power"):
            result["desired"] = asdict(result["desired"])
        return result

    def dispatch(self, request: dict):
        command = str(request.get("command", ""))
        if command == "_wake":
            return None
        if command == "ping":
            return {
                "service": self.runtime_name,
                "runtime": self.runtime_name,
                "version": 3,
                "app_version": __version__,
                "at": utc_now_iso(),
            }
        if command == "token-status":
            configured = token_exists(expected_scope=self.token_scope) if self.token_scope else token_exists()
            result: dict[str, object] = {"configured": configured}
            if configured:
                with contextlib.suppress(Exception):
                    result["scope"] = token_metadata().get("scope")
            return result
        if command == "status":
            return self.controller.status(query_physical=bool(request.get("physical", True)))
        if command == "doctor":
            return self.controller.doctor()
        if command == "night-status":
            return self.controller.solar_status()
        if command == "sync":
            result = self.controller.sync(
                str(request.get("reason", "ipc-sync")), force=bool(request.get("force", False))
            )
            return self._sync_payload(result)
        if command == "manual-on":
            return asdict(self.controller.manual_on())
        if command == "manual-off":
            self.controller.manual_off()
            return {"off": True}
        if command == "enable":
            self.controller.set_automation_enabled(True)
            return self._sync_payload(self.controller.sync("automation-enabled", force=True))
        if command == "disable":
            self.controller.set_automation_enabled(False)
            return {"enabled": False}
        if command == "pause":
            until = self.controller.pause(float(request.get("seconds", -1)))
            return {"paused_until": until}
        if command == "pause-until-tomorrow":
            until = self.controller.pause(until_tomorrow=True)
            return {"paused_until": until}
        if command == "resume-automation":
            self.controller.resume_automation()
            return self._sync_payload(self.controller.sync("resume-automation", force=True))
        if command == "display":
            on = bool(request.get("on"))
            pending = bool(request.get("pending", False))
            self.controller.set_display(on, pending_off=pending, event=str(request.get("event", "display")))
            if not pending:
                return self._sync_payload(self.controller.sync(str(request.get("event", "display"))))
            return {"pending": True}
        if command == "session":
            locked = bool(request.get("locked"))
            event = str(request.get("event", "session-lock" if locked else "session-unlock"))
            self.controller.set_session_locked(locked, event=event)
            if not locked and not bool(self.cfg.get("on_on_session_unlock", True)):
                return {"recorded": True, "sync": False}
            return self._sync_payload(self.controller.sync(event))
        if command == "presence":
            presence = str(request.get("presence"))
            event = f"presence-{presence}"
            self.controller.set_user_presence(presence, event=event)
            return self._sync_payload(self.controller.sync(event))
        if command in {"agent-start", "agent-heartbeat"}:
            heartbeat_locked = request.get("session_locked")
            heartbeat_display = request.get("display_on")
            heartbeat_presence = request.get("user_presence")
            _state, changed = self.controller.update_interactive_snapshot(
                session_locked=bool(heartbeat_locked) if heartbeat_locked is not None else None,
                display_on=bool(heartbeat_display) if heartbeat_display is not None else None,
                user_presence=str(heartbeat_presence)
                if heartbeat_presence in {"present", "not_present", "inactive"}
                else None,
                event=command,
            )
            if changed:
                return self._sync_payload(self.controller.sync(command))
            return {"changed": False, "recorded": True}
        if command in {"resume-auto", "resume-user"}:
            # Bump the intent revision so work that started before sleep is stale. Do not
            # invent display=ON: a real display/session event decides whether to restore.
            self.controller.record_resume_event(command)
            return {"recorded": True}
        if command == "suspend":
            not_after = request.get("not_after_monotonic")
            if not_after is not None and time.monotonic() > float(not_after):
                self.log.warning("suspend-off-missed: evento vencido; OFF obsoleto descartado")
                self.controller.record_windows_event("suspend-off-missed")
                return {"off": False, "reason": "suspend", "expired": True}
            # Suspend is temporary: preserve manual-day/manual-off/external overrides.
            # No delayed reassert is allowed because it could run after Resume.
            return self._critical_off(
                "suspend",
                clear_overrides=False,
                reassert=False,
                critical_timeout=float(self.cfg.get("suspend_off_timeout_seconds", 0.25)),
            )
        if command in {"shutdown", "preshutdown"}:
            return self._critical_off(
                command,
                clear_overrides=True,
                reassert=True,
                critical_timeout=float(self.cfg.get("miio_fast_timeout_seconds", 0.55)),
            )
        raise MijiaLampError(f"Comando IPC desconocido: {command}")
