import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import agent
from mijialamp.i18n import language


class AgentSessionTests(unittest.TestCase):
    def test_tray_can_be_constructed_by_agent(self):
        tray = agent.TrayUI({}, None, None, lambda: None)
        self.assertEqual(tray.backend_label, "Service")

    def test_tray_controls_wait_for_runtime_and_use_clear_mode_specific_names(self):
        for backend in ("Service", "Portable"):
            with self.subTest(backend=backend), language("en"):
                tray = agent.TrayUI({}, mock.Mock(), mock.Mock(), lambda: None, backend_label=backend)
                fake = SimpleNamespace(
                    Menu=mock.Mock(side_effect=lambda *items: items), MenuItem=mock.Mock(), Icon=mock.Mock()
                )
                fake.Menu.SEPARATOR = object()
                fake.MenuItem.side_effect = lambda text, action, **options: SimpleNamespace(
                    text=text, action=action, **options
                )
                with (
                    mock.patch.dict("sys.modules", {"pystray": fake}),
                    mock.patch("agent.threading.Thread.start"),
                    mock.patch.object(tray, "_image", return_value=None),
                ):
                    tray.start()
                items = fake.Menu.call_args.args
                self.assertFalse(items[0].enabled)
                self.assertIn("Connecting", items[0].text(None))
                more = items[5]
                pause_menu = more.action[0]
                pauses = pause_menu.action
                self.assertEqual(more.text(None), "More options")
                self.assertEqual(pause_menu.text(None), "Pause automatic adjustments")
                self.assertFalse(pauses[0].enabled)
                self.assertEqual(pauses[2].text(None), "For 1 hour")
                self.assertEqual(pauses[3].text(None), "Until sunrise")
                controls = (*items[2:5], more, pause_menu, *pauses[2:], items[7])
                self.assertTrue(all(not item.enabled(None) for item in controls))
                tray._runtime_available = True
                self.assertTrue(all(item.enabled(None) for item in controls))
                self.assertEqual(items[3].text(None), "Turn off for 2 h")
                expected_exit = "Quit MijiaLamp Portable" if backend == "Portable" else "Close tray and agent"
                self.assertEqual(items[-1].text(None), expected_exit)
                with mock.patch.object(tray, "_call_async") as send:
                    items[4].action()
                    pauses[2].action()
                    pauses[3].action()
                self.assertEqual(
                    send.call_args_list,
                    [
                        mock.call("resume-automation"),
                        mock.call("pause", seconds=3600),
                        mock.call("pause-until-tomorrow"),
                    ],
                )

    def test_tray_reports_pause_and_manual_override_countdowns_in_both_languages(self):
        tray = agent.TrayUI({"manual_day_override_max_hours": 5}, None, None, lambda: None)
        tray._runtime_available = True
        with mock.patch("agent.time.time", return_value=1000):
            for code in ("en", "es"):
                with self.subTest(language=code), language(code):
                    for fields in (
                        {"manual_off_active": True, "manual_off_until": 1120},
                        {"manual_day_active": True, "manual_day_started_at": 1000 - 5 * 3600 + 120},
                        {"automation_paused_until": 1120},
                    ):
                        tray._last_state = {"automation_enabled": True, **fields}
                        self.assertIn("2 min", tray._menu_status())
                    tray._last_state = {"automation_enabled": True}
                    self.assertIn("auto", tray._menu_status())

    def test_tray_recovers_from_delayed_service_start(self):
        client = mock.Mock()
        client.request.side_effect = [RuntimeError("not ready"), {"state": {"automation_enabled": True}}]
        tray = agent.TrayUI({"notifications_enabled": False}, client, mock.Mock(), lambda: None)
        tray._stop = mock.Mock()
        tray._stop.wait.side_effect = [False, False, True]
        tray.icon = mock.Mock()
        captions = []
        tray.icon.update_menu.side_effect = lambda: captions.append(tray._menu_status())
        with language("en"), mock.patch.object(tray, "_image", return_value=None):
            tray._poll()
        self.assertTrue(tray._runtime_available)
        self.assertIn("not available", captions[0])
        self.assertEqual(captions[-1], "Mode: automatic")

    def test_tray_opens_config_editor_without_shell_command(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "config-gui.ps1").write_text("# editor", encoding="utf-8")
            tray = agent.TrayUI({}, None, None, lambda: None, backend_label="Service")
            with (
                mock.patch.object(agent, "ROOT", root),
                mock.patch.object(agent, "CONFIG_PATH", root / "config.json"),
                mock.patch.object(agent.subprocess, "Popen") as launch,
            ):
                tray._open_config()
            args = launch.call_args.args[0]
            self.assertEqual(args[args.index("-File") + 1], str(root / "config-gui.ps1"))
            self.assertEqual(args[args.index("-Mode") + 1], "Service")
            self.assertNotIn("shell", launch.call_args.kwargs)

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
