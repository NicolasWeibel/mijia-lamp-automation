import threading
import unittest
from unittest import mock

import agent


class AgentSessionTests(unittest.TestCase):
    def test_tray_can_be_constructed_by_agent(self):
        tray = agent.TrayUI({}, None, None, lambda: None)
        self.assertEqual(tray.backend_label, "Service")

    def make_agent(self, *, ignore_remote=True):
        obj = object.__new__(agent.LampAgent)
        obj.cfg = {"ignore_remote_sessions": ignore_remote}
        obj.guard = threading.RLock()
        obj.pending_off_generation = 0
        obj.current_session_locked = None
        obj.current_presence = None
        calls = []

        def notify(command, **params):
            calls.append((command, params))

        obj._notify = notify
        obj._run_async = lambda _label, func: func()
        return obj, calls

    def test_lock_unlock_updates_snapshot(self):
        obj, calls = self.make_agent()
        obj.session_change(agent.WTS_SESSION_LOCK)
        self.assertTrue(obj.current_session_locked)
        self.assertEqual(calls[-1][0], "session")
        self.assertTrue(calls[-1][1]["locked"])

        obj.session_change(agent.WTS_SESSION_UNLOCK)
        self.assertFalse(obj.current_session_locked)
        self.assertEqual(obj.current_presence, "present")
        self.assertEqual([item[0] for item in calls[-2:]], ["session", "presence"])
        self.assertFalse(calls[-2][1]["locked"])
        self.assertEqual(calls[-1][1]["presence"], "present")

    def test_remote_session_is_not_physical_presence_by_default(self):
        obj, calls = self.make_agent(ignore_remote=True)
        obj.session_change(agent.WTS_REMOTE_CONNECT)
        self.assertTrue(obj.current_session_locked)
        self.assertEqual(obj.current_presence, "not_present")
        self.assertEqual([item[0] for item in calls], ["session", "presence"])

    def test_remote_session_can_be_allowed(self):
        obj, calls = self.make_agent(ignore_remote=False)
        obj.session_change(agent.WTS_REMOTE_CONNECT)
        self.assertFalse(obj.current_session_locked)
        self.assertEqual(obj.current_presence, "present")
        self.assertEqual([item[0] for item in calls], ["session", "presence"])
        self.assertEqual(calls[-1][1]["presence"], "present")

    def test_console_disconnect_marks_session_away(self):
        obj, calls = self.make_agent()
        obj.session_change(agent.WTS_CONSOLE_DISCONNECT)
        self.assertTrue(obj.current_session_locked)
        self.assertEqual(obj.current_presence, "not_present")
        self.assertEqual([item[0] for item in calls], ["session", "presence"])
        self.assertEqual(calls[-2][1]["event"], "session-away")
        self.assertEqual(calls[-1][1]["presence"], "not_present")


class AgentSuspendTests(unittest.TestCase):
    def make_agent(self):
        obj = object.__new__(agent.LampAgent)
        obj.cfg = {"suspend_event_deadline_seconds": 0.75}
        obj.guard = threading.RLock()
        obj.pending_off_generation = 0
        obj.log = type("Log", (), {"warning": lambda *args, **kwargs: None})()
        calls = []
        obj._notify = lambda command, **params: calls.append((command, params))
        return obj, calls

    def test_portable_suspend_handler_runs_synchronously_without_pipe(self):
        obj, calls = self.make_agent()
        direct = []
        obj.suspend_handler = lambda: direct.append("off")
        obj.suspend()
        self.assertEqual(direct, ["off"])
        self.assertEqual(calls, [])
        self.assertEqual(obj.pending_off_generation, 1)

    def test_service_suspend_hint_has_expiry_deadline(self):
        obj, calls = self.make_agent()
        obj.suspend_handler = None
        with mock.patch("agent.time.monotonic", return_value=100.0):
            obj.suspend()
        self.assertEqual(calls[0][0], "suspend")
        self.assertEqual(calls[0][1]["timeout"], 0.20)
        self.assertEqual(calls[0][1]["not_after_monotonic"], 100.75)


if __name__ == "__main__":
    unittest.main()
