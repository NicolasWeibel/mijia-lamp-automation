import copy
import json
import unittest
from pathlib import Path

from mijialamp.config import validate_config
from mijialamp.policy import calculate_desired, expire_overrides
from mijialamp.state import DEFAULT_STATE

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_CONFIG = ROOT / "config.example.json"


def example_config() -> dict:
    with open(EXAMPLE_CONFIG, "r", encoding="utf-8") as fh:
        return validate_config(json.load(fh))


class PolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = example_config()
        cls.cfg["profile_transition_mode"] = "stepped"

    def state(self, **updates):
        value = copy.deepcopy(DEFAULT_STATE)
        value.update({"automation_enabled": True, "display_on": True, "display_updated_at": 10_000_000_000.0})
        value.update(updates)
        return value

    def test_daytime_is_off_without_override(self):
        desired = calculate_desired(self.cfg, self.state(), night_now=False)
        self.assertEqual(desired.power, "off")

    def test_night_is_on(self):
        desired = calculate_desired(self.cfg, self.state(), night_now=True)
        self.assertEqual(desired.power, "on")
        self.assertIsNotNone(desired.profile)

    def test_manual_day_allows_day_on(self):
        desired = calculate_desired(
            self.cfg,
            self.state(manual_day_active=True, manual_day_started_at=10_000_000_000.0),
            night_now=False,
        )
        self.assertEqual(desired.power, "on")
        self.assertEqual(desired.profile, "manual_day")

    def test_display_off_beats_manual_day(self):
        desired = calculate_desired(
            self.cfg,
            self.state(
                display_on=False,
                manual_day_active=True,
                manual_day_started_at=10_000_000_000.0,
            ),
            night_now=False,
        )
        self.assertEqual(desired.power, "off")

    def test_manual_off_beats_night(self):
        desired = calculate_desired(
            self.cfg,
            self.state(manual_off_active=True, manual_off_until=0),
            night_now=True,
        )
        self.assertEqual(desired.power, "off")

    def test_pending_display_off_holds(self):
        desired = calculate_desired(
            self.cfg,
            self.state(display_pending_off=True),
            night_now=True,
        )
        self.assertEqual(desired.power, "hold")

    def test_override_expiration(self):
        state = self.state(
            manual_day_active=True,
            manual_day_started_at=1000,
            manual_off_active=True,
            manual_off_until=1100,
        )
        changed = expire_overrides(self.cfg, state, now=1000 + 6 * 3600)
        self.assertTrue(changed)
        self.assertFalse(state["manual_day_active"])
        self.assertFalse(state["manual_off_active"])

    def test_automation_disabled_and_paused_hold(self):
        cfg = self.cfg
        state = self.state()
        state["automation_enabled"] = False
        self.assertEqual(calculate_desired(cfg, state, night_now=True).power, "hold")
        state["automation_enabled"] = True
        state["automation_paused_until"] = -1
        self.assertEqual(calculate_desired(cfg, state, night_now=True).power, "hold")

    def test_session_lock_and_presence_are_safety_off(self):
        cfg = self.cfg
        state = self.state()
        state["session_locked"] = True
        self.assertEqual(calculate_desired(cfg, state, night_now=True).reason, "Windows session locked")
        state["session_locked"] = False
        state["user_presence"] = "not_present"
        self.assertEqual(calculate_desired(cfg, state, night_now=True).reason, "user not present")

    def test_external_override_holds_non_safety_intent(self):
        cfg = self.cfg
        state = self.state()
        state["external_override_active"] = True
        desired = calculate_desired(cfg, state, night_now=True)
        self.assertEqual(desired.power, "hold")
        self.assertIn("external", desired.reason)


if __name__ == "__main__":
    unittest.main()
