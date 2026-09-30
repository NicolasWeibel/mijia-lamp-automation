from __future__ import annotations

from dataclasses import dataclass

from .profiles import resolve_profile
from .solar import is_night_now
from .util import epoch_now


@dataclass(frozen=True)
class DesiredState:
    power: str
    profile: str | None
    reason: str


def expire_overrides(
    cfg: dict, state: dict, now: float | None = None, *, night_now: bool | None = None
) -> bool:
    now = epoch_now() if now is None else float(now)
    changed = False

    if state.get("manual_day_active"):
        started = float(state.get("manual_day_started_at", 0) or 0)
        max_hours = float(cfg.get("manual_day_override_max_hours", 5))
        if max_hours > 0 and started > 0 and now >= started + max_hours * 3600:
            state["manual_day_active"] = False
            state["manual_day_started_at"] = 0.0
            changed = True

    if state.get("manual_off_active"):
        until = float(state.get("manual_off_until", 0) or 0)
        if until > 0 and now >= until:
            state["manual_off_active"] = False
            state["manual_off_until"] = 0.0
            changed = True

    pause_until = float(state.get("automation_paused_until", 0) or 0)
    if pause_until > 0 and now >= pause_until:
        state["automation_paused_until"] = 0.0
        changed = True

    if state.get("external_override_active"):
        policy = str(cfg.get("external_change_policy", "enforce"))
        if policy == "enforce":
            state["external_override_active"] = False
            state["external_override_until"] = 0.0
            state["external_override_profile"] = None
            state["external_override_physical"] = None
            changed = True
        elif policy == "respect_for_minutes":
            until = float(state.get("external_override_until", 0) or 0)
            if until > 0 and now >= until:
                state["external_override_active"] = False
                state["external_override_until"] = 0.0
                state["external_override_profile"] = None
                state["external_override_physical"] = None
                changed = True
        elif policy == "respect_until_next_profile":
            night = is_night_now(cfg) if night_now is None else bool(night_now)
            expected_name = resolve_profile(cfg).name if night else "daytime"
            captured = state.get("external_override_profile")
            if captured and captured != expected_name:
                state["external_override_active"] = False
                state["external_override_until"] = 0.0
                state["external_override_profile"] = None
                state["external_override_physical"] = None
                changed = True

    return changed


def _display_state(cfg: dict, state: dict, now: float) -> str:
    display = state.get("display_on")
    updated = float(state.get("display_updated_at", 0) or 0)
    stale_min = float(cfg.get("display_state_stale_minutes", 30))
    if display is not None and (updated <= 0 or stale_min <= 0 or now - updated <= stale_min * 60):
        return "on" if bool(display) else "off"
    return str(cfg.get("unknown_display_policy", "off"))


def calculate_desired(cfg: dict, state: dict, *, night_now: bool | None = None) -> DesiredState:
    state = dict(state)
    now = epoch_now()
    night = is_night_now(cfg) if night_now is None else bool(night_now)
    expire_overrides(cfg, state, now=now, night_now=night)

    if not bool(state.get("automation_enabled", True)):
        return DesiredState("hold", None, "automation disabled")

    pause_until = float(state.get("automation_paused_until", 0) or 0)
    if pause_until < 0 or pause_until > now:
        return DesiredState("hold", None, "automation paused")

    if state.get("manual_off_active"):
        return DesiredState("off", None, "manual-off override")

    if state.get("display_pending_off"):
        return DesiredState("hold", None, "display off pending confirmation")

    if bool(cfg.get("respect_session_lock", True)) and bool(cfg.get("off_on_session_lock", True)):
        if state.get("session_locked") is True:
            return DesiredState("off", None, "Windows session locked")

    if bool(cfg.get("respect_user_presence", True)):
        presence = state.get("user_presence")
        if presence == "not_present":
            return DesiredState("off", None, "user not present")
        if presence == "inactive" and bool(cfg.get("off_when_user_inactive", False)):
            return DesiredState("off", None, "user inactive")

    display = _display_state(cfg, state, now)
    if display == "off":
        return DesiredState("off", None, "display off/unknown")
    if display == "hold":
        return DesiredState("hold", None, "display state unknown")

    if state.get("external_override_active"):
        return DesiredState("hold", None, "external device change respected")

    if state.get("manual_day_active"):
        profile = resolve_profile(cfg, manual_day=not night)
        return DesiredState("on", profile.name, "manual-day override")

    if night:
        profile = resolve_profile(cfg)
        return DesiredState("on", profile.name, "night + active Windows session")

    return DesiredState("off", None, "daytime")
