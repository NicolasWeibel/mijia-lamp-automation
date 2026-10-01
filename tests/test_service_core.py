import time
import unittest
from unittest.mock import patch

from mijialamp.errors import MijiaLampError
from mijialamp.service_core import ServiceCore
from mijialamp.transport import ProfileValues


class NullLogger:
    def __getattr__(self, _):
        return lambda *args, **kwargs: None


class FakeState:
    def __init__(self):
        self.data = {"automation_enabled": False, "critical_off_revision": 0}

    def read(self):
        return dict(self.data)


class FakeController:
    def __init__(self):
        self.state = FakeState()
        self.calls = []
        self.snapshot_changed = True

    def invalidate_interactive_state(self, reason):
        self.calls.append(("invalidate", reason))

    def system_off(self, reason, fast=True, clear_overrides=True, critical_timeout=None):
        self.calls.append(("off", reason, fast, clear_overrides, critical_timeout))
        self.state.data["critical_off_revision"] += 1

    def reassert_critical_off(self, reason, revision):
        self.calls.append(("reassert", reason, revision))

    def record_windows_event(self, event):
        self.calls.append(("event", event))

    def record_resume_event(self, event):
        self.calls.append(("resume", event))

    def status(self, query_physical=True):
        self.calls.append(("status", query_physical))
        return {"status": True}

    def doctor(self):
        self.calls.append(("doctor",))
        return {"ok": True}

    def solar_status(self):
        self.calls.append(("solar",))
        return {"night": True}

    def sync(self, reason, force=False):
        self.calls.append(("sync", reason, force))
        return {"changed": False, "desired": None}

    def manual_on(self):
        self.calls.append(("manual-on",))
        return ProfileValues("manual_day", 4000, 45)

    def manual_off(self):
        self.calls.append(("manual-off",))

    def set_automation_enabled(self, enabled):
        self.calls.append(("enabled", enabled))
        self.state.data["automation_enabled"] = enabled

    def pause(self, seconds=None, *, until_tomorrow=False):
        self.calls.append(("pause", seconds, until_tomorrow))
        return 123.0

    def resume_automation(self):
        self.calls.append(("resume-automation",))

    def set_display(self, on, *, pending_off=False, event="display"):
        self.calls.append(("display", on, pending_off, event))

    def set_session_locked(self, locked, *, event="session"):
        self.calls.append(("session", locked, event))

    def set_user_presence(self, presence, *, event=None):
        self.calls.append(("presence", presence, event))

    def update_interactive_snapshot(self, **kwargs):
        self.calls.append(("snapshot", kwargs))
        return self.state.read(), self.snapshot_changed

    def network_changed(self):
        self.calls.append(("network-changed",))


class ServiceCoreTests(unittest.TestCase):
    def make_core(self, cfg=None):
        controller = FakeController()
        core = ServiceCore(controller, cfg or {"sync_interval_seconds": 60}, NullLogger())
        return core, controller

    def test_resume_auto_never_invents_display_on(self):
        core, controller = self.make_core()
        result = core.dispatch({"command": "resume-auto"})
        self.assertEqual(result, {"recorded": True})
        self.assertEqual(controller.calls, [("resume", "resume-auto")])

    def test_suspend_is_bounded_preserves_overrides_and_does_not_reassert(self):
        core, controller = self.make_core({"sync_interval_seconds": 60, "suspend_off_timeout_seconds": 0.25})
        result = core.dispatch({"command": "suspend"})
        self.assertTrue(result["off"])
        self.assertEqual(controller.calls, [("off", "suspend", True, False, 0.25)])

    def test_expired_suspend_hint_is_discarded_after_resume_window(self):
        core, controller = self.make_core()
        with patch("mijialamp.service_core.time.monotonic", return_value=10.0):
            result = core.dispatch({"command": "suspend", "not_after_monotonic": 9.0})
        self.assertEqual(result, {"off": False, "reason": "suspend", "expired": True})
        self.assertEqual(controller.calls, [("event", "suspend-off-missed")])

    def test_shutdown_still_clears_overrides_and_reasserts(self):
        core, controller = self.make_core({"sync_interval_seconds": 60, "miio_fast_timeout_seconds": 0.55})
        result = core.dispatch({"command": "shutdown"})
        self.assertTrue(result["off"])
        self.assertEqual(controller.calls[0], ("off", "shutdown", True, True, 0.55))
        deadline = time.time() + 1
        while len(controller.calls) < 2 and time.time() < deadline:
            time.sleep(0.02)
        self.assertEqual(controller.calls[1], ("reassert", "shutdown", 1))

    def test_dispatch_control_surface(self):
        core, controller = self.make_core({"sync_interval_seconds": 60, "on_on_session_unlock": True})
        self.assertIsNone(core.dispatch({"command": "_wake"}))
        self.assertEqual(core.dispatch({"command": "ping"})["service"], "MijiaLampService")
        with patch("mijialamp.service_core.token_exists", return_value=True):
            self.assertEqual(core.dispatch({"command": "token-status"}), {"configured": True})
        self.assertEqual(core.dispatch({"command": "status", "physical": False}), {"status": True})
        self.assertEqual(core.dispatch({"command": "doctor"}), {"ok": True})
        self.assertEqual(core.dispatch({"command": "night-status"}), {"night": True})
        self.assertFalse(core.dispatch({"command": "sync", "reason": "test", "force": True})["changed"])
        self.assertEqual(core.dispatch({"command": "manual-on"})["name"], "manual_day")
        self.assertEqual(core.dispatch({"command": "manual-off"}), {"off": True})
        self.assertIn("changed", core.dispatch({"command": "enable"}))
        self.assertEqual(core.dispatch({"command": "disable"}), {"enabled": False})
        self.assertEqual(core.dispatch({"command": "pause", "seconds": 60}), {"paused_until": 123.0})
        self.assertEqual(core.dispatch({"command": "pause-until-tomorrow"}), {"paused_until": 123.0})
        self.assertIn("changed", core.dispatch({"command": "resume-automation"}))
        self.assertEqual(
            core.dispatch({"command": "display", "on": False, "pending": True, "event": "display-off"}),
            {"pending": True},
        )
        self.assertIn("changed", core.dispatch({"command": "display", "on": True, "event": "display-on"}))
        self.assertIn("changed", core.dispatch({"command": "session", "locked": True, "event": "lock"}))
        self.assertIn("changed", core.dispatch({"command": "session", "locked": False, "event": "unlock"}))
        self.assertIn("changed", core.dispatch({"command": "presence", "presence": "present"}))
        self.assertIn("changed", core.dispatch({"command": "agent-start", "display_on": True}))
        controller.snapshot_changed = False
        self.assertEqual(
            core.dispatch({"command": "agent-heartbeat", "display_on": True}),
            {"changed": False, "recorded": True},
        )
        with self.assertRaises(MijiaLampError):
            core.dispatch({"command": "unknown"})

    def test_session_unlock_can_be_record_only(self):
        core, controller = self.make_core({"sync_interval_seconds": 60, "on_on_session_unlock": False})
        result = core.dispatch({"command": "session", "locked": False})
        self.assertEqual(result, {"recorded": True, "sync": False})
        self.assertFalse(any(call[0] == "sync" for call in controller.calls))

    def test_start_is_idempotent_and_invalidates_interactive_state(self):
        core, controller = self.make_core(
            {"sync_interval_seconds": 3600, "network_change_poll_seconds": 3600}
        )
        with (
            patch.object(core, "_periodic_loop", return_value=None),
            patch.object(core, "_network_loop", return_value=None),
        ):
            core.start()
            first = core._periodic_thread
            core.start()
            if first:
                first.join(1)
        self.assertIn(("invalidate", "service-start"), controller.calls)

    def test_network_signature_handles_socket_error(self):
        with patch("mijialamp.service_core.socket.getaddrinfo", side_effect=OSError("offline")):
            self.assertEqual(ServiceCore._network_signature(), ())


if __name__ == "__main__":
    unittest.main()
