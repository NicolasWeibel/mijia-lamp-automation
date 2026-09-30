from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Callable

from .locking import FileLock
from .paths import STATE_LOCK_PATH, STATE_PATH
from .util import atomic_write_json, epoch_now, redact_secrets, utc_now_iso


DEFAULT_STATE = {
    "version": 3,
    "automation_enabled": False,
    "automation_paused_until": 0.0,
    "intent_revision": 0,
    "critical_off_revision": 0,
    "display_on": None,
    "display_pending_off": False,
    "display_updated_at": 0.0,
    "session_locked": None,
    "session_updated_at": 0.0,
    "user_presence": None,
    "presence_updated_at": 0.0,
    "manual_day_active": False,
    "manual_day_started_at": 0.0,
    "manual_off_active": False,
    "manual_off_until": 0.0,
    "external_override_active": False,
    "external_override_until": 0.0,
    "external_override_profile": None,
    "external_override_physical": None,
    "last_command": None,
    "last_command_at": None,
    "last_success_at": None,
    "last_desired_state": None,
    "last_desired_profile": None,
    "last_desired_brightness": None,
    "last_desired_kelvin": None,
    "last_physical": None,
    "last_windows_event": None,
    "last_windows_event_at": None,
    "last_error": None,
    "consecutive_failures": 0,
    "first_failure_at": 0.0,
    "last_failure_at": 0.0,
}


class StateStore:
    def __init__(self, path: Path = STATE_PATH, lock_path: Path = STATE_LOCK_PATH, logger=None):
        self.path = Path(path)
        self.lock_path = Path(lock_path)
        self.log = logger

    def _read_unlocked(self) -> dict:
        state = copy.deepcopy(DEFAULT_STATE)
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                loaded = json.load(fh)
            if not isinstance(loaded, dict):
                raise json.JSONDecodeError("runtime root is not an object", "", 0)
            state.update(loaded)
            return state
        except FileNotFoundError:
            return state
        except json.JSONDecodeError as exc:
            stamp = int(epoch_now())
            corrupt = self.path.with_name(f"{self.path.stem}.corrupt-{stamp}{self.path.suffix}")
            try:
                os.replace(self.path, corrupt)
            except OSError:
                corrupt = None
            if self.log:
                self.log.error(
                    "runtime_state corrupto: %s; backup=%s; se reinicia estado lógico",
                    exc,
                    corrupt,
                )
            return state

    def read(self) -> dict:
        with FileLock(self.lock_path, timeout=5):
            return self._read_unlocked()

    def replace(self, state: dict) -> dict:
        with FileLock(self.lock_path, timeout=5):
            merged = copy.deepcopy(DEFAULT_STATE)
            merged.update(state)
            atomic_write_json(self.path, merged)
            return copy.deepcopy(merged)

    def update(self, **fields) -> dict:
        return self.mutate(lambda state: state.update(fields))

    def mutate(self, callback: Callable[[dict], None]) -> dict:
        with FileLock(self.lock_path, timeout=5):
            state = self._read_unlocked()
            callback(state)
            state["updated_at"] = epoch_now()
            state["updated_at_iso"] = utc_now_iso()
            atomic_write_json(self.path, state)
            return copy.deepcopy(state)

    def bump_intent(self, reason: str, *, critical_off: bool = False, **fields) -> dict:
        """Atomically mutate intent and increment revision used to cancel stale work."""
        def mutate(state: dict) -> None:
            state["intent_revision"] = int(state.get("intent_revision", 0)) + 1
            if critical_off:
                state["critical_off_revision"] = int(state.get("critical_off_revision", 0)) + 1
            state["last_intent_reason"] = reason
            state["last_intent_at"] = utc_now_iso()
            state.update(fields)

        return self.mutate(mutate)

    def revision(self) -> tuple[int, int]:
        state = self.read()
        return int(state.get("intent_revision", 0)), int(state.get("critical_off_revision", 0))

    def record_error(self, action: str, exc: Exception) -> None:
        now = epoch_now()
        def mutate(state: dict) -> None:
            if int(state.get("consecutive_failures", 0)) <= 0:
                state["first_failure_at"] = now
            state["consecutive_failures"] = int(state.get("consecutive_failures", 0)) + 1
            state["last_failure_at"] = now
            state["last_error"] = {
                "at": utc_now_iso(),
                "action": action,
                "type": type(exc).__name__,
                "message": redact_secrets(exc)[:500],
            }
        self.mutate(mutate)

    def record_success(self) -> None:
        self.update(consecutive_failures=0, first_failure_at=0.0, last_failure_at=0.0, last_error=None)

    def clear_error(self) -> None:
        self.record_success()
