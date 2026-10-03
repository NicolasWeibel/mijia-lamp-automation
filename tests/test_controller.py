import json
import tempfile
import threading
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from mijialamp.config import validate_config
from mijialamp.controller import LampController
from mijialamp.state import StateStore
from mijialamp.transport import LampPhysicalState, ProfileValues

ROOT = Path(__file__).resolve().parents[1]


class NullLogger:
    def __getattr__(self, _):
        return lambda *args, **kwargs: None


def config():
    with open(ROOT / "config.example.json", encoding="utf-8") as fh:
        cfg = validate_config(json.load(fh))
    cfg["night_mode"] = False
    cfg["profile_transition_mode"] = "stepped"
    cfg["network_wait_seconds_periodic"] = 0
    return cfg


class FakeTransport:
    def __init__(self, physical=None):
        self.physical = physical or LampPhysicalState("off", 10, 2700, "192.168.1.100")
        self.commands = []
        self.read_started = threading.Event()
        self.release_read = threading.Event()
        self.block_read = False

    def probe_identity(self, ip, timeout=None):
        return "yeelink.light.lamp22", "123456789"

    def read_state(self, ip, timeout=None):
        self.read_started.set()
        if self.block_read:
            self.release_read.wait(3)
        return self.physical

    def set_power(self, power, *, ip=None, fast=False):
        self.commands.append(("power", power, fast))
        self.physical = LampPhysicalState(
            power, self.physical.brightness, self.physical.kelvin, ip or self.physical.ip
        )

    def set_power_critical_off(self, *, ip=None, timeout=0.25):
        self.commands.append(("critical-off", timeout, ip))
        self.physical = LampPhysicalState(
            "off", self.physical.brightness, self.physical.kelvin, ip or self.physical.ip
        )

    def apply_profile(self, profile, *, ip=None, fast=False):
        self.commands.append(("profile", profile.name, fast))
        self.physical = LampPhysicalState("on", profile.brightness, profile.kelvin, ip or self.physical.ip)

    def discover(self, *, force=False):
        return None

    def ensure_reachable(self, wait_seconds, *, allow_discovery=True):
        return self.physical.ip


class ControllerRaceTests(unittest.TestCase):
    def evening_profile(self):
        profile = ProfileValues(name="evening", brightness=35, kelvin=3000)
        stack = ExitStack()
        stack.enter_context(patch("mijialamp.policy.is_night_now", return_value=True))
        stack.enter_context(patch("mijialamp.policy.resolve_profile", return_value=profile))
        stack.enter_context(patch("mijialamp.controller.resolve_profile", return_value=profile))
        return stack

    def make_controller(self, td, transport):
        cfg = config()
        controller = LampController(cfg, NullLogger(), transport=transport)
        root = Path(td)
        controller.state = StateStore(root / "state.json", root / "state.lock")
        controller.state.update(automation_enabled=True, display_on=True, display_updated_at=10**10)
        return controller

    def test_suspend_invalidates_blocked_sync_before_on(self):
        with tempfile.TemporaryDirectory() as td:
            transport = FakeTransport()
            transport.block_read = True
            controller = self.make_controller(td, transport)
            lock = Path(td) / "control.lock"
            result = {}
            with patch("mijialamp.controller.CONTROL_LOCK_PATH", lock):
                thread = threading.Thread(
                    target=lambda: result.setdefault("sync", controller.sync("periodic-sync"))
                )
                thread.start()
                self.assertTrue(transport.read_started.wait(1))
                controller.system_off("suspend", fast=True, clear_overrides=False, critical_timeout=0.25)
                transport.release_read.set()
                thread.join(3)
            self.assertFalse(thread.is_alive())
            self.assertNotIn(("power", "on", False), transport.commands)
            self.assertTrue(any(cmd[0] in {"power", "critical-off"} for cmd in transport.commands))
            self.assertTrue(result["sync"].get("stale"))

    def test_suspend_preserves_manual_day_and_resume_only_invalidates_old_work(self):
        with tempfile.TemporaryDirectory() as td:
            transport = FakeTransport(LampPhysicalState("on", 45, 4000, "192.168.1.100"))
            controller = self.make_controller(td, transport)
            controller.state.update(
                manual_day_active=True,
                manual_day_started_at=123.0,
                session_locked=True,
                user_presence="inactive",
            )
            with patch("mijialamp.controller.CONTROL_LOCK_PATH", Path(td) / "control.lock"):
                controller.system_off(
                    "suspend",
                    fast=True,
                    clear_overrides=False,
                    critical_timeout=0.25,
                )
            suspended = controller.state.read()
            self.assertTrue(suspended["manual_day_active"])
            self.assertEqual(suspended["manual_day_started_at"], 123.0)
            self.assertFalse(suspended["display_on"])
            self.assertTrue(any(cmd[0] == "critical-off" for cmd in transport.commands))

            before = suspended["intent_revision"]
            controller.record_resume_event("resume-auto")
            resumed = controller.state.read()
            self.assertGreater(resumed["intent_revision"], before)
            self.assertTrue(resumed["manual_day_active"])
            self.assertFalse(resumed["display_on"])
            self.assertEqual(resumed["last_windows_event"], "resume-auto")

    def test_external_profile_change_is_respected(self):
        with tempfile.TemporaryDirectory() as td:
            transport = FakeTransport(LampPhysicalState("on", 99, 5000, "192.168.1.100"))
            controller = self.make_controller(td, transport)
            controller.state.update(
                last_success_at="previous",
                last_desired_state="on",
                last_desired_profile="evening",
                last_desired_brightness=35,
                last_desired_kelvin=3000,
            )
            with (
                self.evening_profile(),
                patch("mijialamp.controller.CONTROL_LOCK_PATH", Path(td) / "control.lock"),
            ):
                result = controller.sync("periodic-sync")
            self.assertTrue(result.get("external_override"))
            self.assertTrue(controller.state.read()["external_override_active"])
            self.assertFalse(any(cmd[0] == "profile" for cmd in transport.commands))

    def test_sync_turns_on_and_applies_profile(self):
        with tempfile.TemporaryDirectory() as td:
            transport = FakeTransport(LampPhysicalState("off", 10, 2700, "192.168.1.100"))
            controller = self.make_controller(td, transport)
            controller.cfg["external_change_policy"] = "enforce"
            with (
                self.evening_profile(),
                patch("mijialamp.controller.CONTROL_LOCK_PATH", Path(td) / "control.lock"),
                patch("mijialamp.controller.time.sleep", return_value=None),
            ):
                result = controller.sync("test-on")
            self.assertTrue(result["changed"])
            self.assertIn(("power", "on", False), transport.commands)
            self.assertTrue(any(cmd[0] == "profile" for cmd in transport.commands))
            state = controller.state.read()
            self.assertEqual(state["last_desired_state"], "on")
            self.assertEqual(state["last_desired_brightness"], 35)
            self.assertEqual(state["last_desired_kelvin"], 3000)

    def test_sync_scheduled_profile_change_is_not_external_override(self):
        with tempfile.TemporaryDirectory() as td:
            transport = FakeTransport(LampPhysicalState("on", 35, 3000, "192.168.1.100"))
            controller = self.make_controller(td, transport)
            # Current policy target is evening, but the previous settled segment was wind_down.
            controller.state.update(
                last_success_at="previous",
                last_desired_state="on",
                last_desired_profile="wind_down",
                last_desired_brightness=25,
                last_desired_kelvin=2700,
            )
            with (
                self.evening_profile(),
                patch("mijialamp.controller.CONTROL_LOCK_PATH", Path(td) / "control.lock"),
                patch("mijialamp.controller.time.sleep", return_value=None),
            ):
                result = controller.sync("profile-boundary")
            self.assertFalse(result.get("external_override", False))
            self.assertFalse(controller.state.read()["external_override_active"])

    def test_manual_on_sets_day_override_and_profile(self):
        with tempfile.TemporaryDirectory() as td:
            transport = FakeTransport(LampPhysicalState("off", 10, 2700, "192.168.1.100"))
            controller = self.make_controller(td, transport)
            with (
                patch("mijialamp.controller.CONTROL_LOCK_PATH", Path(td) / "control.lock"),
                patch("mijialamp.controller.is_night_now", return_value=False),
                patch("mijialamp.controller.time.sleep", return_value=None),
            ):
                profile = controller.manual_on()
            self.assertEqual(profile.name, "manual_day")
            self.assertTrue(controller.state.read()["manual_day_active"])
            self.assertIn(("power", "on", False), transport.commands)

    def test_manual_off_sets_timed_override(self):
        with tempfile.TemporaryDirectory() as td:
            transport = FakeTransport(LampPhysicalState("on", 35, 3000, "192.168.1.100"))
            controller = self.make_controller(td, transport)
            with (
                patch("mijialamp.controller.CONTROL_LOCK_PATH", Path(td) / "control.lock"),
                patch("mijialamp.controller.threading.Thread.start", return_value=None),
            ):
                controller.manual_off()
            state = controller.state.read()
            self.assertTrue(state["manual_off_active"])
            self.assertGreater(state["manual_off_until"], 0)
            self.assertTrue(any(cmd[0:2] == ("power", "off") for cmd in transport.commands))

    def test_reassert_is_cancelled_by_newer_intent(self):
        with tempfile.TemporaryDirectory() as td:
            transport = FakeTransport(LampPhysicalState("off", 35, 3000, "192.168.1.100"))
            controller = self.make_controller(td, transport)
            state = controller.state.bump_intent("suspend", critical_off=True)
            critical = state["critical_off_revision"]
            controller.state.bump_intent("manual-on")
            controller.reassert_critical_off("suspend", critical)
            self.assertEqual(transport.commands, [])

    def test_doctor_and_status_do_not_expose_token(self):
        with tempfile.TemporaryDirectory() as td:
            transport = FakeTransport(LampPhysicalState("on", 35, 3000, "192.168.1.100"))
            controller = self.make_controller(td, transport)
            doctor = controller.doctor()
            self.assertTrue(doctor["ok"])
            self.assertEqual(doctor["token"], "configured (not shown)")
            status = controller.status(query_physical=True)
            self.assertEqual(status["physical"]["power"], "on")

    def test_pause_and_resume_modify_intent(self):
        with tempfile.TemporaryDirectory() as td:
            controller = self.make_controller(td, FakeTransport())
            until = controller.pause(120)
            self.assertGreater(until, 0)
            self.assertGreater(controller.state.read()["automation_paused_until"], 0)
            controller.resume_automation()
            self.assertEqual(controller.state.read()["automation_paused_until"], 0)

    def test_windows_state_setters_bump_revision(self):
        with tempfile.TemporaryDirectory() as td:
            controller = self.make_controller(td, FakeTransport())
            before = controller.state.read()["intent_revision"]
            controller.set_display(False, pending_off=True, event="test-display")
            controller.set_session_locked(True, event="test-lock")
            controller.set_user_presence("not_present")
            state = controller.state.read()
            self.assertGreaterEqual(state["intent_revision"], before + 3)
            self.assertTrue(state["session_locked"])
            self.assertEqual(state["user_presence"], "not_present")
            with self.assertRaises(ValueError):
                controller.set_user_presence("invalid")

    def test_heartbeat_refreshes_display_freshness_without_bumping_intent(self):
        with tempfile.TemporaryDirectory() as td:
            controller = self.make_controller(td, FakeTransport())
            controller.state.update(display_on=True, display_updated_at=1.0)
            before = controller.state.read()["intent_revision"]
            with patch("mijialamp.controller.epoch_now", return_value=1234.0):
                state, changed = controller.update_interactive_snapshot(
                    display_on=True, event="agent-heartbeat"
                )
            self.assertFalse(changed)
            self.assertEqual(state["intent_revision"], before)
            self.assertEqual(state["display_updated_at"], 1234.0)


if __name__ == "__main__":
    unittest.main()
