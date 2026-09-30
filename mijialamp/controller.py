from __future__ import annotations

import threading
import time
from dataclasses import asdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .errors import CommunicationError, LockTimeoutError, StaleIntentError
from .locking import FileLock
from .miio_client import MiioLampClient
from .secrets_store import SCOPE_LOCAL_MACHINE
from .paths import CONTROL_LOCK_PATH
from .policy import calculate_desired, expire_overrides
from .profiles import resolve_profile
from .solar import is_night_now, solar_times
from .state import StateStore
from .transport import LampPhysicalState, LampTransport, ProfileValues
from .util import epoch_now, utc_now_iso


class LampController:
    def __init__(
        self,
        cfg: dict,
        logger,
        transport: LampTransport | None = None,
        *,
        token_scope: str = SCOPE_LOCAL_MACHINE,
    ):
        self.cfg = cfg
        self.log = logger
        self.state = StateStore(logger=logger)
        self.client: LampTransport = transport or MiioLampClient(
            cfg, logger, token_scope=token_scope
        )
        self._send_lock = threading.RLock()

    def _expire_state(self) -> dict:
        changed = False

        def mutate(state: dict) -> None:
            nonlocal changed
            changed = expire_overrides(self.cfg, state)
            if changed:
                state["intent_revision"] = int(state.get("intent_revision", 0)) + 1
                state["last_intent_reason"] = "override-expired"
                state["last_intent_at"] = utc_now_iso()

        state = self.state.mutate(mutate)
        if changed:
            self.log.info("Overrides vencidos limpiados; intent revision=%s", state["intent_revision"])
        return state

    def _record_command(self, command: str, **extra) -> None:
        self.state.update(last_command=command, last_command_at=utc_now_iso(), **extra)

    def _record_physical(self, physical: LampPhysicalState) -> None:
        data = asdict(physical)
        data["at"] = utc_now_iso()
        self.state.update(last_physical=data)

    def _record_success(
        self, desired_power: str, profile: ProfileValues | None, reason: str
    ) -> None:
        self.state.update(
            last_success_at=utc_now_iso(),
            last_desired_state=desired_power,
            last_desired_profile=profile.name if profile else None,
            last_desired_brightness=profile.brightness if profile else None,
            last_desired_kelvin=profile.kelvin if profile else None,
            last_success_reason=reason,
        )
        self.state.record_success()

    def _guard(self, revision: int, critical_revision: int, action: str) -> None:
        current = self.state.read()
        now_rev = int(current.get("intent_revision", 0))
        now_critical = int(current.get("critical_off_revision", 0))
        if now_rev != revision or now_critical != critical_revision:
            raise StaleIntentError(
                f"{action} cancelado: intent cambió {revision}/{critical_revision} -> "
                f"{now_rev}/{now_critical}"
            )

    def _wait_for_ip(self, power: str, fast: bool, wait_override: float | None = None) -> str:
        if fast:
            return str(self.cfg["lamp_ip"])
        wait = float(wait_override) if wait_override is not None else float(
            self.cfg.get("network_wait_seconds_on", 20)
            if power == "on"
            else self.cfg.get("network_wait_seconds_off", 3)
        )
        return self.client.ensure_reachable(wait, allow_discovery=True)

    def _read_with_recovery(self, desired_power: str, wait_override: float | None = None) -> LampPhysicalState:
        ip = str(self.cfg["lamp_ip"])
        try:
            physical = self.client.read_state(ip, timeout=float(self.cfg["miio_timeout_seconds"]))
            self._record_physical(physical)
            return physical
        except CommunicationError as first:
            self.log.warning("Lectura en IP configurada falló: %s", first)
            ip = self._wait_for_ip(desired_power, fast=False, wait_override=wait_override)
            physical = self.client.read_state(ip)
            self._record_physical(physical)
            return physical

    def _profile_matches(self, physical: LampPhysicalState, expected: ProfileValues) -> bool:
        if physical.brightness is None or physical.kelvin is None:
            return False
        return (
            abs(physical.brightness - expected.brightness)
            <= int(self.cfg.get("profile_brightness_tolerance", 1))
            and abs(physical.kelvin - expected.kelvin)
            <= int(self.cfg.get("profile_kelvin_tolerance", 25))
        )

    def _confirm_expected(
        self,
        ip: str,
        power: str,
        profile: ProfileValues | None,
        revision: int,
        critical_revision: int,
    ) -> LampPhysicalState:
        delay = 0.12
        if power == "on" and profile:
            delay += max(0, int(self.cfg.get("profile_transition_ms", 0))) / 1000.0
        time.sleep(min(delay, 1.5))
        self._guard(revision, critical_revision, "confirm")
        physical = self.client.read_state(ip)
        self._record_physical(physical)
        if physical.power != power:
            raise CommunicationError(
                f"La lámpara confirmó power={physical.power!r}; esperaba {power!r}"
            )
        if power == "on" and profile and not self._profile_matches(physical, profile):
            raise CommunicationError(
                "La lámpara quedó encendida pero el perfil físico no coincide "
                f"(bright={physical.brightness}, ct={physical.kelvin}; "
                f"esperado={profile.brightness}/{profile.kelvin})"
            )
        return physical

    def _external_change_detected(
        self, desired, expected: ProfileValues | None, physical: LampPhysicalState, state: dict
    ) -> bool:
        policy = str(self.cfg.get("external_change_policy", "enforce"))
        if policy == "enforce" or state.get("external_override_active"):
            return False
        if not state.get("last_success_at"):
            return False

        # Safety states always win over changes made from Mi Home/physical controls.
        if desired.reason in {
            "manual-off override",
            "display off/unknown",
            "Windows session locked",
            "user not present",
            "user inactive",
        }:
            return False

        last_power = state.get("last_desired_state")
        last_profile = state.get("last_desired_profile")
        last_brightness = state.get("last_desired_brightness")
        last_kelvin = state.get("last_desired_kelvin")

        if desired.power == "on":
            if expected is None:
                return False
            # A scheduled profile transition is not an external change. In continuous mode
            # the segment name can stay stable while the target values drift each minute,
            # so compare the physical state with the last values we actually applied.
            if last_power != "on":
                return False
            if last_profile != expected.name:
                return False
            if physical.power != "on":
                mismatch = True
            elif last_brightness is None or last_kelvin is None:
                return False
            else:
                previous = ProfileValues(
                    name=str(last_profile or "previous"),
                    brightness=int(last_brightness),
                    kelvin=int(last_kelvin),
                )
                mismatch = not self._profile_matches(physical, previous)
        elif desired.power == "off" and desired.reason == "daytime":
            # Only treat ON as external if OFF was already our settled daytime intent.
            mismatch = last_power == "off" and physical.power == "on"
        else:
            mismatch = False
        if not mismatch:
            return False

        now = epoch_now()
        until = 0.0
        if policy == "respect_for_minutes":
            until = now + float(self.cfg.get("external_change_respect_minutes", 60)) * 60
        marker = expected.name if expected is not None else "daytime"
        payload = asdict(physical)
        self.state.bump_intent(
            "external-change",
            external_override_active=True,
            external_override_until=until,
            external_override_profile=marker,
            external_override_physical=payload,
        )
        self.log.info("Cambio externo detectado y respetado (%s): %s", policy, payload)
        return True

    def _sync_locked(self, reason: str, force: bool = False):
        state = self._expire_state()
        revision = int(state.get("intent_revision", 0))
        critical_revision = int(state.get("critical_off_revision", 0))
        desired = calculate_desired(self.cfg, state)
        self.log.info(
            "Sync reason=%s rev=%s/%s desired=%s profile=%s policy=%s",
            reason,
            revision,
            critical_revision,
            desired.power,
            desired.profile,
            desired.reason,
        )

        if desired.power == "hold":
            self.state.update(last_desired_state="hold", last_desired_profile=None, last_success_reason=reason)
            return {"changed": False, "desired": desired, "physical": None, "stale": False}

        wait_override = float(self.cfg.get("network_wait_seconds_periodic", 3)) if reason == "periodic-sync" else None
        try:
            physical = self._read_with_recovery(desired.power, wait_override=wait_override)
        except CommunicationError:
            self._guard(revision, critical_revision, "blind-off/pre-command")
            if desired.power == "off":
                ip = str(self.cfg["lamp_ip"])
                with self._send_lock:
                    self._guard(revision, critical_revision, "blind-off")
                    self.client.set_power("off", ip=ip, fast=False)
                self._record_success("off", None, reason + " (blind off)")
                return {"changed": True, "desired": desired, "physical": None, "stale": False}
            raise

        self._guard(revision, critical_revision, "post-read")
        expected = resolve_profile(self.cfg, manual_day=(desired.profile == "manual_day")) if desired.power == "on" else None
        if desired.power == "on" and desired.profile and desired.profile.startswith("continuous:"):
            expected = resolve_profile(self.cfg)

        if self._external_change_detected(desired, expected, physical, state):
            return {"changed": False, "desired": desired, "physical": physical, "external_override": True}

        changed = False
        ip = physical.ip
        if desired.power == "off":
            if force or physical.power != "off":
                with self._send_lock:
                    self._guard(revision, critical_revision, "set-power-off")
                    self.client.set_power("off", ip=ip, fast=False)
                changed = True
        else:
            assert expected is not None
            if force or physical.power != "on":
                with self._send_lock:
                    self._guard(revision, critical_revision, "set-power-on")
                    self.client.set_power("on", ip=ip, fast=False)
                changed = True
                self._guard(revision, critical_revision, "profile-after-on")
                with self._send_lock:
                    self._guard(revision, critical_revision, "apply-profile-after-on")
                    self.client.apply_profile(expected, ip=ip, fast=False)
            elif force or not self._profile_matches(physical, expected):
                with self._send_lock:
                    self._guard(revision, critical_revision, "apply-profile")
                    self.client.apply_profile(expected, ip=ip, fast=False)
                changed = True

        if changed:
            self._confirm_expected(ip, desired.power, expected, revision, critical_revision)

        self._record_success(desired.power, expected, reason)
        self.log.info("Sync terminado changed=%s desired=%s profile=%s", changed, desired.power, expected.name if expected else None)
        return {"changed": changed, "desired": desired, "physical": physical, "stale": False}

    def sync(self, reason: str = "sync", force: bool = False):
        self._record_command(reason)
        try:
            with FileLock(CONTROL_LOCK_PATH, timeout=15):
                return self._sync_locked(reason, force=force)
        except StaleIntentError as exc:
            self.log.info("%s", exc)
            return {"changed": False, "desired": None, "physical": None, "stale": True}
        except Exception as exc:
            self.state.record_error(reason, exc)
            self.log.error("%s falló: %s", reason, exc, exc_info=True)
            raise

    def manual_on(self) -> ProfileValues:
        night = is_night_now(self.cfg)
        now = epoch_now()
        state = self.state.bump_intent(
            "manual-on",
            manual_off_active=False,
            manual_off_until=0.0,
            manual_day_active=not night,
            manual_day_started_at=0.0 if night else now,
            external_override_active=False,
            external_override_until=0.0,
            external_override_profile=None,
            external_override_physical=None,
        )
        revision = int(state["intent_revision"])
        critical = int(state["critical_off_revision"])
        profile = resolve_profile(self.cfg, manual_day=not night)
        self._record_command("manual-on")
        try:
            with FileLock(CONTROL_LOCK_PATH, timeout=15):
                ip = self._wait_for_ip("on", fast=False)
                with self._send_lock:
                    self._guard(revision, critical, "manual-on")
                    self.client.set_power("on", ip=ip)
                with self._send_lock:
                    self._guard(revision, critical, "manual-on-profile")
                    self.client.apply_profile(profile, ip=ip)
                self._confirm_expected(ip, "on", profile, revision, critical)
                self._record_success("on", profile, "manual-on")
                return profile
        except Exception as exc:
            self.state.record_error("manual-on", exc)
            raise

    def manual_off(self) -> None:
        now = epoch_now()
        minutes = int(self.cfg.get("manual_off_override_minutes", 120))
        until = 0.0 if minutes <= 0 else now + minutes * 60
        state = self.state.bump_intent(
            "manual-off",
            critical_off=True,
            manual_day_active=False,
            manual_day_started_at=0.0,
            manual_off_active=True,
            manual_off_until=until,
            external_override_active=False,
            external_override_until=0.0,
            external_override_profile=None,
            external_override_physical=None,
        )
        self._record_command("manual-off")
        self._critical_off_send("manual-off", state, fast=False)
        critical_revision = int(state["critical_off_revision"])

        def reassert() -> None:
            time.sleep(0.25)
            self.reassert_critical_off("manual-off", critical_revision)

        threading.Thread(
            target=reassert, name="MijiaLampManualOffReassert", daemon=True
        ).start()

    def _critical_off_send(
        self,
        reason: str,
        state: dict,
        *,
        fast: bool,
        critical_timeout: float | None = None,
    ) -> None:
        revision = int(state["intent_revision"])
        critical = int(state["critical_off_revision"])
        ip = str(self.cfg["lamp_ip"])
        lock_timeout = (min(0.05, float(critical_timeout)) if critical_timeout is not None else 0.15) if fast else 10
        try:
            with FileLock(CONTROL_LOCK_PATH, timeout=lock_timeout):
                if not fast:
                    try:
                        ip = self._wait_for_ip("off", fast=False)
                    except CommunicationError:
                        ip = str(self.cfg["lamp_ip"])
                with self._send_lock:
                    self._guard(revision, critical, reason)
                    if critical_timeout is not None and hasattr(self.client, "set_power_critical_off"):
                        self.client.set_power_critical_off(
                            ip=ip, timeout=float(critical_timeout)
                        )
                    else:
                        self.client.set_power("off", ip=ip, fast=fast)
        except LockTimeoutError:
            # A previous command is likely waiting for its UDP response. The critical revision
            # has already invalidated its next action; sending OFF now makes the newest power
            # packet the final intent in the common case.
            self.log.warning("%s: control lock ocupado; enviando OFF crítico concurrente", reason)
            if critical_timeout is not None and hasattr(self.client, "set_power_critical_off"):
                self.client.set_power_critical_off(ip=ip, timeout=float(critical_timeout))
            else:
                self.client.set_power("off", ip=ip, fast=True)
        self._record_success("off", None, reason)

    def system_off(
        self,
        reason: str,
        *,
        fast: bool = True,
        clear_overrides: bool = True,
        critical_timeout: float | None = None,
    ) -> None:
        fields = {
            "display_on": False,
            "display_pending_off": False,
            "display_updated_at": epoch_now(),
        }
        if clear_overrides:
            fields.update(
                manual_day_active=False,
                manual_day_started_at=0.0,
                manual_off_active=False,
                manual_off_until=0.0,
                external_override_active=False,
                external_override_until=0.0,
                external_override_profile=None,
                external_override_physical=None,
            )
        state = self.state.bump_intent(reason, critical_off=True, **fields)
        self._record_command(reason)
        try:
            self._critical_off_send(
                reason, state, fast=fast, critical_timeout=critical_timeout
            )
        except Exception as exc:
            self.state.record_error(reason, exc)
            raise

    def reassert_critical_off(
        self, expected_reason: str, expected_critical_revision: int
    ) -> None:
        """Second short OFF only if the exact critical intent is still current."""
        state = self.state.read()
        if int(state.get("critical_off_revision", 0)) != int(expected_critical_revision):
            self.log.info("Reassert OFF cancelado: apareció una intención crítica más nueva")
            return
        if state.get("last_intent_reason") != expected_reason:
            self.log.info(
                "Reassert OFF cancelado: intent actual=%s, esperado=%s",
                state.get("last_intent_reason"),
                expected_reason,
            )
            return
        try:
            self.client.set_power("off", ip=str(self.cfg["lamp_ip"]), fast=True)
            self.log.info(
                "OFF crítico reassertado: %s rev=%s",
                expected_reason,
                expected_critical_revision,
            )
        except Exception as exc:
            self.log.warning("Reassert OFF falló (%s): %s", expected_reason, exc)

    def invalidate_interactive_state(self, event: str = "service-start") -> dict:
        """Fail-safe boot/service restart state: never assume an interactive user exists."""
        return self.state.bump_intent(
            event,
            display_on=None,
            display_pending_off=False,
            display_updated_at=0.0,
            session_locked=None,
            session_updated_at=0.0,
            user_presence=None,
            presence_updated_at=0.0,
            last_windows_event=event,
            last_windows_event_at=utc_now_iso(),
        )

    def update_interactive_snapshot(
        self,
        *,
        display_on: bool | None = None,
        session_locked: bool | None = None,
        user_presence: str | None = None,
        event: str = "agent-heartbeat",
    ) -> tuple[dict, bool]:
        if user_presence is not None and user_presence not in {
            "present",
            "not_present",
            "inactive",
        }:
            raise ValueError(f"presence inválida: {user_presence}")

        current = self.state.read()
        fields: dict = {}
        semantic_changed = False
        now = epoch_now()

        if display_on is not None:
            value = bool(display_on)
            if current.get("display_on") is not value:
                fields["display_on"] = value
                fields["display_pending_off"] = False
                semantic_changed = True
            # Heartbeats refresh freshness even if the value did not change. Otherwise a
            # continuously-on display would become "stale" and fail-safe OFF after N minutes.
            fields["display_updated_at"] = now

        if session_locked is not None:
            value = bool(session_locked)
            if current.get("session_locked") is not value:
                fields["session_locked"] = value
                semantic_changed = True
            fields["session_updated_at"] = now

        if user_presence is not None:
            if current.get("user_presence") != user_presence:
                fields["user_presence"] = user_presence
                semantic_changed = True
            fields["presence_updated_at"] = now

        fields.update(last_windows_event=event, last_windows_event_at=utc_now_iso())
        if semantic_changed:
            return self.state.bump_intent(event, **fields), True
        if fields:
            return self.state.update(**fields), False
        self.record_windows_event(event)
        return current, False

    def set_display(self, display_on: bool, *, pending_off: bool = False, event: str = "display") -> dict:
        return self.state.bump_intent(
            event,
            display_on=bool(display_on),
            display_pending_off=bool(pending_off),
            display_updated_at=epoch_now(),
            last_windows_event=event,
            last_windows_event_at=utc_now_iso(),
        )

    def set_session_locked(self, locked: bool, *, event: str) -> dict:
        return self.state.bump_intent(
            event,
            session_locked=bool(locked),
            session_updated_at=epoch_now(),
            last_windows_event=event,
            last_windows_event_at=utc_now_iso(),
        )

    def set_user_presence(self, presence: str, *, event: str = "presence") -> dict:
        if presence not in {"present", "not_present", "inactive"}:
            raise ValueError(f"presence inválida: {presence}")
        return self.state.bump_intent(
            event,
            user_presence=presence,
            presence_updated_at=epoch_now(),
            last_windows_event=event,
            last_windows_event_at=utc_now_iso(),
        )

    def record_windows_event(self, event: str) -> None:
        self.state.update(last_windows_event=event, last_windows_event_at=utc_now_iso())

    def record_resume_event(self, event: str) -> dict:
        """Invalidate pre-suspend work without assuming the display is visible."""
        return self.state.bump_intent(
            event,
            last_windows_event=event,
            last_windows_event_at=utc_now_iso(),
        )

    def set_automation_enabled(self, enabled: bool) -> dict:
        return self.state.bump_intent("automation-enabled" if enabled else "automation-disabled", automation_enabled=bool(enabled))

    def pause(self, seconds: float | None = None, *, until_tomorrow: bool = False) -> float:
        if until_tomorrow:
            tz = ZoneInfo(str(self.cfg["timezone"]))
            now = datetime.now(tz)
            hour, minute = map(int, self.cfg["pause_until_tomorrow_time"].split(":"))
            target = (now + timedelta(days=1)).replace(hour=hour, minute=minute, second=0, microsecond=0)
            until = target.timestamp()
        elif seconds is None or seconds < 0:
            until = -1.0
        else:
            until = epoch_now() + float(seconds)
        self.state.bump_intent("pause", automation_paused_until=until)
        return until

    def resume_automation(self) -> None:
        self.state.bump_intent(
            "resume-automation",
            automation_paused_until=0.0,
            external_override_active=False,
            external_override_until=0.0,
            external_override_profile=None,
            external_override_physical=None,
        )

    def network_changed(self) -> None:
        callback = getattr(self.client, "network_changed", None)
        if callable(callback):
            callback()
        self.state.bump_intent("network-change")
        self.record_windows_event("network-change")

    def doctor(self) -> dict:
        ip = str(self.cfg["lamp_ip"])
        try:
            model, did = self.client.probe_identity(ip)
        except CommunicationError:
            found = self.client.discover(force=True)
            if not found:
                raise
            ip = found
            model, did = self.client.probe_identity(ip)
        physical = self.client.read_state(ip)
        self._record_physical(physical)
        return {"ok": True, "ip": ip, "model": model, "device_id": did, "physical": asdict(physical), "token": "configured (not shown)"}

    def status(self, *, query_physical: bool = True) -> dict:
        state = self._expire_state()
        desired = calculate_desired(self.cfg, state)
        result = {"state": state, "desired": asdict(desired), "physical": None}
        if query_physical:
            try:
                result["physical"] = asdict(self.client.read_state(str(self.cfg["lamp_ip"])))
            except Exception as exc:
                result["physical_error"] = str(exc)
        return result

    def solar_status(self) -> dict:
        times = solar_times(self.cfg)
        profile = resolve_profile(self.cfg)
        return {
            "night": is_night_now(self.cfg),
            "profile": asdict(profile),
            "sunrise": times.get("sunrise"),
            "sunset": times.get("sunset"),
            "dawn": times.get("dawn"),
            "dusk": times.get("dusk"),
        }
