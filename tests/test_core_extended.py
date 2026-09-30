from __future__ import annotations

import copy
import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import mijialamp.config as config_mod
from mijialamp.config import validate_config
from mijialamp.controller import LampController
from mijialamp.errors import CommunicationError, ConfigError
from mijialamp.solar import _in_range, _parse_hhmm, current_minutes, is_night_now, night_profile_name
from mijialamp.state import StateStore
from mijialamp.transport import LampPhysicalState
from mijialamp.util import atomic_write_json, cleanup_temp_files, redact_secrets

ROOT = Path(__file__).resolve().parents[1]


class NullLogger:
    def __getattr__(self, _name):
        return lambda *args, **kwargs: None


def raw_config() -> dict:
    return json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))


def valid_config() -> dict:
    cfg = validate_config(raw_config())
    cfg["night_mode"] = False
    cfg["profile_transition_mode"] = "stepped"
    cfg["network_wait_seconds_periodic"] = 0
    return cfg


class ExtendedConfigTests(unittest.TestCase):
    def test_mac_normalization_and_defaults(self):
        cfg = raw_config()
        cfg["expected_mac"] = "aa-bb-cc-dd-ee-ff"
        out = validate_config(cfg)
        self.assertEqual(out["expected_mac"], "AA:BB:CC:DD:EE:FF")
        self.assertEqual(out["version"], 3)

    def test_structural_validation_errors(self):
        cases = []
        cfg = raw_config(); cfg["$schema"] = 1; cases.append(cfg)
        cfg = raw_config(); cfg["location_name"] = 123; cases.append(cfg)
        cfg = raw_config(); cfg["expected_model"] = " "; cases.append(cfg)
        cfg = raw_config(); cfg["device_id"] = "0"; cases.append(cfg)
        cfg = raw_config(); cfg["timezone"] = "Mars/Olympus"; cases.append(cfg)
        cfg = raw_config(); cfg["latitude"] = 100; cases.append(cfg)
        cfg = raw_config(); cfg["longitude"] = -181; cases.append(cfg)
        cfg = raw_config(); cfg["elevation_meters"] = True; cases.append(cfg)
        cfg = raw_config(); cfg["night_start"] = "midnight"; cases.append(cfg)
        cfg = raw_config(); cfg["wind_down_start"] = "25:99"; cases.append(cfg)
        cfg = raw_config(); cfg["light_profiles"] = []; cases.append(cfg)
        cfg = raw_config(); del cfg["light_profiles"]["manual_day"]; cases.append(cfg)
        cfg = raw_config(); cfg["light_profiles"]["evening"]["kelvin"] = 1000; cases.append(cfg)
        cfg = raw_config(); cfg["light_profiles"]["evening"]["brightness"] = True; cases.append(cfg)
        cfg = raw_config(); cfg["profile_transition_mode"] = "magic"; cases.append(cfg)
        cfg = raw_config(); cfg["unknown_display_policy"] = "maybe"; cases.append(cfg)
        cfg = raw_config(); cfg["external_change_policy"] = "maybe"; cases.append(cfg)
        cfg = raw_config(); cfg["sync_interval_seconds"] = 1; cases.append(cfg)
        cfg = raw_config(); cfg["retries"] = 0; cases.append(cfg)
        cfg = raw_config(); cfg["expected_mac"] = "bad"; cases.append(cfg)
        for candidate in cases:
            with self.subTest(candidate=candidate):
                with self.assertRaises(ConfigError):
                    validate_config(candidate)

    def test_non_object_config_rejected(self):
        with self.assertRaises(ConfigError):
            validate_config([])

    def test_device_cache_roundtrip_and_ip_override(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cache = root / "device_cache.json"
            lock = root / "device_cache.lock"
            config_path = root / "config.json"
            config_path.write_text(json.dumps(raw_config()), encoding="utf-8")
            with patch.object(config_mod, "DEVICE_CACHE_PATH", cache), patch.object(
                config_mod, "DEVICE_CACHE_LOCK_PATH", lock
            ):
                self.assertEqual(config_mod.read_device_cache(), {})
                out = config_mod.update_device_cache(lamp_ip="192.168.50.20", marker="x")
                self.assertEqual(out["version"], 2)
                self.assertEqual(config_mod.read_device_cache()["marker"], "x")
                loaded = config_mod.load_config(config_path)
                self.assertEqual(loaded["lamp_ip"], "192.168.50.20")
                self.assertFalse(config_mod.update_lamp_ip("192.168.50.20"))
                self.assertTrue(config_mod.update_lamp_ip("192.168.50.21"))
                with self.assertRaises(ConfigError):
                    config_mod.update_lamp_ip("::1")

    def test_load_config_errors(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "missing.json"
            with self.assertRaises(ConfigError):
                config_mod.load_config(path)
            path.write_text("{broken", encoding="utf-8")
            with self.assertRaises(ConfigError):
                config_mod.load_config(path)


class StateAndUtilTests(unittest.TestCase):
    def test_state_corruption_replace_revisions_and_error_lifecycle(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "state.json"
            lock = root / "state.lock"
            path.write_text("{broken", encoding="utf-8")
            store = StateStore(path, lock, logger=NullLogger())
            state = store.read()
            self.assertEqual(state["intent_revision"], 0)
            self.assertTrue(list(root.glob("state.corrupt-*.json")))
            replaced = store.replace({"display_on": True})
            self.assertTrue(replaced["display_on"])
            bumped = store.bump_intent("critical", critical_off=True, marker=1)
            self.assertEqual(store.revision(), (1, 1))
            self.assertEqual(bumped["marker"], 1)
            store.record_error("test", RuntimeError("secret=" + "ab" * 16))
            failed = store.read()
            self.assertEqual(failed["consecutive_failures"], 1)
            self.assertNotIn("ab" * 16, failed["last_error"]["message"])
            store.record_error("test2", ValueError("again"))
            self.assertEqual(store.read()["consecutive_failures"], 2)
            store.clear_error()
            self.assertEqual(store.read()["consecutive_failures"], 0)

    def test_atomic_json_and_temp_cleanup(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out = root / "x.json"
            atomic_write_json(out, {"ñ": 1})
            self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["ñ"], 1)
            old = root / ".old.tmp"
            fresh = root / ".fresh.tmp"
            old.write_text("x")
            fresh.write_text("x")
            old_time = time.time() - 7200
            os.utime(old, (old_time, old_time))
            self.assertEqual(cleanup_temp_files(root, older_than_seconds=3600), 1)
            self.assertFalse(old.exists())
            self.assertTrue(fresh.exists())
            self.assertEqual(cleanup_temp_files(root / "missing"), 0)
            self.assertEqual(redact_secrets("x=" + "ab" * 16), "x=<redacted-token>")


class SolarTests(unittest.TestCase):
    def setUp(self):
        self.cfg = valid_config()
        self.cfg["timezone"] = "UTC"
        self.cfg["wind_down_start"] = "23:30"
        self.cfg["pre_sleep_start"] = "00:45"
        self.cfg["bedtime"] = "01:45"

    def test_helpers_and_profiles_across_midnight(self):
        self.assertEqual(_parse_hhmm("01:30"), 90)
        self.assertTrue(_in_range(10, 1380, 60))
        self.assertFalse(_in_range(120, 1380, 60))
        self.assertTrue(_in_range(600, 500, 700))
        cases = [
            (datetime(2026, 1, 1, 23, 45, tzinfo=timezone.utc), "wind_down"),
            (datetime(2026, 1, 2, 1, 0, tzinfo=timezone.utc), "pre_sleep"),
            (datetime(2026, 1, 2, 2, 0, tzinfo=timezone.utc), "after_bedtime"),
            (datetime(2026, 1, 2, 20, 0, tzinfo=timezone.utc), "evening"),
        ]
        for when, expected in cases:
            with self.subTest(when=when):
                self.assertEqual(night_profile_name(self.cfg, when), expected)
        self.assertEqual(current_minutes(self.cfg, datetime(2026, 1, 1, 2, 5, tzinfo=timezone.utc)), 125)

    def test_is_night_boundaries_and_disabled_mode(self):
        self.cfg["night_mode"] = True
        fake = {
            "sunset": datetime(2026, 1, 1, 18, 0, tzinfo=timezone.utc),
            "sunrise": datetime(2026, 1, 1, 6, 0, tzinfo=timezone.utc),
            "dawn": datetime(2026, 1, 1, 5, 30, tzinfo=timezone.utc),
            "dusk": datetime(2026, 1, 1, 18, 30, tzinfo=timezone.utc),
        }
        self.cfg["night_start_offset_minutes"] = 0
        self.cfg["night_end_offset_minutes"] = 0
        with patch("mijialamp.solar.solar_times", return_value=fake):
            self.assertTrue(is_night_now(self.cfg, datetime(2026, 1, 1, 19, tzinfo=timezone.utc)))
            self.assertTrue(is_night_now(self.cfg, datetime(2026, 1, 1, 5, tzinfo=timezone.utc)))
            self.assertFalse(is_night_now(self.cfg, datetime(2026, 1, 1, 12, tzinfo=timezone.utc)))
        self.cfg["night_mode"] = False
        self.assertTrue(is_night_now(self.cfg, datetime(2026, 1, 1, 12, tzinfo=timezone.utc)))


class ControllerEdgeTransport:
    def __init__(self):
        self.physical = LampPhysicalState("off", 35, 3000, "192.168.1.100")
        self.commands = []
        self.fail_read = False
        self.fail_probe_once = False
        self.network_changed_calls = 0

    def probe_identity(self, ip, timeout=None):
        if self.fail_probe_once:
            self.fail_probe_once = False
            raise CommunicationError("probe")
        return "yeelink.light.lamp22", "123456789"

    def read_state(self, ip, timeout=None):
        if self.fail_read:
            raise CommunicationError("read")
        return self.physical

    def set_power(self, power, *, ip=None, fast=False):
        self.commands.append(("power", power, fast))
        self.physical = LampPhysicalState(power, self.physical.brightness, self.physical.kelvin, ip or self.physical.ip)

    def apply_profile(self, profile, *, ip=None, fast=False):
        self.commands.append(("profile", profile.name, fast))
        self.physical = LampPhysicalState("on", profile.brightness, profile.kelvin, ip or self.physical.ip)

    def discover(self, *, force=False):
        return "192.168.1.200"

    def ensure_reachable(self, wait_seconds, *, allow_discovery=True):
        if self.fail_read:
            raise CommunicationError("offline")
        return self.physical.ip

    def network_changed(self):
        self.network_changed_calls += 1


class ControllerExtendedTests(unittest.TestCase):
    def make_controller(self, td, transport=None):
        transport = transport or ControllerEdgeTransport()
        ctl = LampController(valid_config(), NullLogger(), transport=transport)
        root = Path(td)
        ctl.state = StateStore(root / "state.json", root / "state.lock")
        ctl.state.update(automation_enabled=True, display_on=True, display_updated_at=10**10)
        return ctl, transport

    def test_doctor_discovery_fallback_and_status_error(self):
        with tempfile.TemporaryDirectory() as td:
            ctl, tr = self.make_controller(td)
            tr.fail_probe_once = True
            doctor = ctl.doctor()
            self.assertEqual(doctor["ip"], "192.168.1.200")
            tr.fail_read = True
            status = ctl.status(query_physical=True)
            self.assertIn("physical_error", status)
            status2 = ctl.status(query_physical=False)
            self.assertIsNone(status2["physical"])

    def test_blind_off_when_read_and_recovery_fail(self):
        with tempfile.TemporaryDirectory() as td:
            ctl, tr = self.make_controller(td)
            ctl.state.update(display_on=False)
            tr.fail_read = True
            with patch("mijialamp.controller.CONTROL_LOCK_PATH", Path(td) / "control.lock"):
                result = ctl.sync("blind-off")
            self.assertTrue(result["changed"])
            self.assertIn(("power", "off", False), tr.commands)

    def test_network_pause_presence_and_reassert_paths(self):
        with tempfile.TemporaryDirectory() as td:
            ctl, tr = self.make_controller(td)
            before = ctl.state.read()["intent_revision"]
            ctl.network_changed()
            self.assertEqual(tr.network_changed_calls, 1)
            self.assertGreater(ctl.state.read()["intent_revision"], before)
            forever = ctl.pause(None)
            self.assertEqual(forever, -1.0)
            tomorrow = ctl.pause(until_tomorrow=True)
            self.assertGreater(tomorrow, time.time())
            with self.assertRaises(ValueError):
                ctl.update_interactive_snapshot(user_presence="bogus")
            state = ctl.state.bump_intent("suspend", critical_off=True)
            ctl.reassert_critical_off("suspend", state["critical_off_revision"])
            self.assertIn(("power", "off", True), tr.commands)

    def test_status_solar_and_automation_setters(self):
        with tempfile.TemporaryDirectory() as td:
            ctl, _tr = self.make_controller(td)
            ctl.set_automation_enabled(False)
            self.assertFalse(ctl.state.read()["automation_enabled"])
            ctl.set_automation_enabled(True)
            ctl.record_windows_event("unit-test")
            self.assertEqual(ctl.state.read()["last_windows_event"], "unit-test")
            fake_times = {
                "sunrise": datetime(2026, 1, 1, 6, tzinfo=timezone.utc),
                "sunset": datetime(2026, 1, 1, 18, tzinfo=timezone.utc),
                "dawn": datetime(2026, 1, 1, 5, 30, tzinfo=timezone.utc),
                "dusk": datetime(2026, 1, 1, 18, 30, tzinfo=timezone.utc),
            }
            with patch("mijialamp.controller.solar_times", return_value=fake_times), patch(
                "mijialamp.controller.is_night_now", return_value=True
            ):
                solar = ctl.solar_status()
            self.assertTrue(solar["night"])
            self.assertEqual(solar["sunset"], fake_times["sunset"])


if __name__ == "__main__":
    unittest.main()

class PolicyAndLoopCoverageTests(unittest.TestCase):
    def test_policy_override_expiration_modes_and_unknown_display(self):
        from mijialamp.policy import calculate_desired, expire_overrides

        cfg = valid_config()
        state = {
            "automation_enabled": True,
            "display_on": None,
            "display_updated_at": 0,
            "manual_day_active": False,
            "manual_off_active": False,
            "automation_paused_until": 0,
            "external_override_active": True,
            "external_override_until": 1,
            "external_override_profile": "evening",
            "external_override_physical": {"power": "on"},
        }
        cfg["external_change_policy"] = "enforce"
        self.assertTrue(expire_overrides(cfg, state, now=2, night_now=False))
        self.assertFalse(state["external_override_active"])

        state.update(external_override_active=True, external_override_until=1, external_override_profile="daytime")
        cfg["external_change_policy"] = "respect_for_minutes"
        self.assertTrue(expire_overrides(cfg, state, now=2, night_now=False))

        state.update(external_override_active=True, external_override_until=0, external_override_profile="other")
        cfg["external_change_policy"] = "respect_until_next_profile"
        self.assertTrue(expire_overrides(cfg, state, now=2, night_now=False))

        base = {
            "automation_enabled": True,
            "display_on": None,
            "display_updated_at": 0,
            "manual_day_active": False,
            "manual_off_active": False,
            "automation_paused_until": 0,
            "external_override_active": False,
            "session_locked": False,
            "user_presence": "present",
        }
        cfg["unknown_display_policy"] = "hold"
        self.assertEqual(calculate_desired(cfg, base, night_now=False).power, "hold")
        cfg["unknown_display_policy"] = "assume_on"
        self.assertEqual(calculate_desired(cfg, base, night_now=False).power, "off")
        cfg["unknown_display_policy"] = "off"
        self.assertEqual(calculate_desired(cfg, base, night_now=False).power, "off")

    def test_locking_timeout_and_release_noop(self):
        from mijialamp.errors import LockTimeoutError
        from mijialamp.locking import FileLock

        with tempfile.TemporaryDirectory() as td:
            lock = FileLock(Path(td) / "x.lock", timeout=0, poll=0)
            with patch.object(lock, "_lock_now", side_effect=OSError("busy")):
                with self.assertRaises(LockTimeoutError):
                    lock.acquire()
            lock.release()  # already released on timeout; must be harmless

    def test_path_directory_roles(self):
        import mijialamp.paths as paths

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with patch.object(paths, "DATA_DIR", root / "data"), patch.object(
                paths, "LOG_DIR", root / "logs"
            ), patch.object(paths, "SECRETS_DIR", root / "secrets"), patch.object(
                paths, "USER_DATA_DIR", root / "user"
            ):
                paths.ensure_service_dirs()
                self.assertTrue((root / "secrets").is_dir())
                paths.ensure_agent_dirs()
                self.assertTrue((root / "user").is_dir())
                paths.ensure_dirs()
                self.assertTrue((root / "data").is_dir())

    def test_service_core_periodic_and_network_loops(self):
        from mijialamp.service_core import ServiceCore
        from tests.test_service_core import FakeController, NullLogger as CoreLogger

        controller = FakeController()
        controller.state.data["automation_enabled"] = True
        core = ServiceCore(
            controller,
            {"sync_interval_seconds": 10, "network_change_poll_seconds": 5},
            CoreLogger(),
        )
        with patch.object(core._stop, "wait", side_effect=[False, True]):
            core._periodic_loop()
        self.assertIn(("sync", "periodic-sync", False), controller.calls)

        controller.calls.clear()
        with patch.object(core, "_network_signature", side_effect=[("10.0.0.1",), ("10.0.0.2",)]), patch.object(
            core._stop, "wait", side_effect=[False, True]
        ):
            core._network_loop()
        self.assertIn(("network-changed",), controller.calls)
        self.assertIn(("sync", "network-change", False), controller.calls)

    def test_controller_hold_force_profile_and_errors(self):
        with tempfile.TemporaryDirectory() as td:
            ctl, tr = ControllerExtendedTests().make_controller(td)
            # automation disabled exercises hold path
            ctl.state.update(automation_enabled=False)
            with patch("mijialamp.controller.CONTROL_LOCK_PATH", Path(td) / "control.lock"):
                held = ctl.sync("disabled")
            self.assertFalse(held["changed"])
            self.assertEqual(held["desired"].power, "hold")

            # Force while already ON reapplies power/profile and confirms.
            ctl.state.update(automation_enabled=True, display_on=True, display_updated_at=10**10)
            tr.physical = LampPhysicalState("on", 35, 3000, "192.168.1.100")
            ctl.cfg["external_change_policy"] = "enforce"
            with patch("mijialamp.controller.CONTROL_LOCK_PATH", Path(td) / "control.lock"), patch(
                "mijialamp.controller.time.sleep", return_value=None
            ):
                forced = ctl.sync("force", force=True)
            self.assertTrue(forced["changed"])
            self.assertTrue(any(c[0] == "profile" for c in tr.commands))

            # Invalid physical profile triggers apply-profile branch without power-on.
            tr.commands.clear()
            tr.physical = LampPhysicalState("on", 1, 6500, "192.168.1.100")
            with patch("mijialamp.controller.CONTROL_LOCK_PATH", Path(td) / "control.lock"), patch(
                "mijialamp.controller.time.sleep", return_value=None
            ):
                corrected = ctl.sync("profile-correct")
            self.assertTrue(corrected["changed"])
            self.assertFalse(any(c[:2] == ("power", "on") for c in tr.commands))
            self.assertTrue(any(c[0] == "profile" for c in tr.commands))

    def test_controller_error_recording_paths(self):
        class BrokenTransport(ControllerEdgeTransport):
            def ensure_reachable(self, wait_seconds, *, allow_discovery=True):
                raise CommunicationError("offline")

            def read_state(self, ip, timeout=None):
                raise CommunicationError("offline")

            def set_power(self, power, *, ip=None, fast=False):
                raise CommunicationError("send failed")

        with tempfile.TemporaryDirectory() as td:
            ctl, _tr = ControllerExtendedTests().make_controller(td, BrokenTransport())
            with patch("mijialamp.controller.CONTROL_LOCK_PATH", Path(td) / "control.lock"):
                with self.assertRaises(CommunicationError):
                    ctl.sync("expected-failure")
            state = ctl.state.read()
            self.assertGreater(state["consecutive_failures"], 0)
            self.assertEqual(state["last_error"]["action"], "expected-failure")

            with patch("mijialamp.controller.CONTROL_LOCK_PATH", Path(td) / "control2.lock"):
                with self.assertRaises(CommunicationError):
                    ctl.system_off("shutdown", fast=True)
            self.assertEqual(ctl.state.read()["last_error"]["action"], "shutdown")
