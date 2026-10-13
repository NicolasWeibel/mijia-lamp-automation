import json
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from mijialamp.config import validate_config
from mijialamp.profiles import resolve_profile

ROOT = Path(__file__).resolve().parents[1]


class ProfileTests(unittest.TestCase):
    def test_all_day_continuous_uses_daylight_profile_after_sunrise(self):
        cfg = validate_config(json.loads((ROOT / "config.example.json").read_text(encoding="utf-8")))
        cfg.update(timezone="UTC", night_mode=False)
        tz = ZoneInfo("UTC")
        times = {"sunrise": datetime(2026, 1, 1, 7, tzinfo=tz), "sunset": datetime(2026, 1, 1, 20, tzinfo=tz)}
        with patch("mijialamp.profiles.solar_times", return_value=times):
            profile = resolve_profile(cfg, datetime(2026, 1, 1, 10, tzinfo=tz))
        self.assertEqual(profile.name, "manual_day")

    def test_stepped_manual_day(self):
        with open(ROOT / "config.example.json", encoding="utf-8") as fh:
            cfg = validate_config(json.load(fh))
        cfg["profile_transition_mode"] = "stepped"
        p = resolve_profile(cfg, manual_day=True)
        self.assertEqual(p.name, "manual_day")
        self.assertEqual(p.brightness, 45)

    def test_continuous_interpolates(self):
        with open(ROOT / "config.example.json", encoding="utf-8") as fh:
            cfg = validate_config(json.load(fh))
        cfg["timezone"] = "UTC"
        cfg["profile_transition_mode"] = "continuous"
        fake_times = {"sunset": datetime(2026, 1, 1, 20, 0, tzinfo=ZoneInfo("UTC"))}
        with patch("mijialamp.profiles.solar_times", return_value=fake_times):
            p = resolve_profile(cfg, datetime(2026, 1, 1, 21, 45, tzinfo=ZoneInfo("UTC")))
        self.assertTrue(p.name.startswith("continuous:"))
        self.assertTrue(2700 <= p.kelvin <= 3000)
        self.assertTrue(25 <= p.brightness <= 35)

    def test_continuous_keeps_same_night_across_midnight(self):
        cfg = validate_config(json.loads((ROOT / "config.example.json").read_text(encoding="utf-8")))
        cfg["timezone"] = "UTC"
        cfg["night_start_offset_minutes"] = 0

        def times(_cfg, when):
            return {"sunset": when.replace(hour=20, minute=0)}

        with patch("mijialamp.profiles.solar_times", side_effect=times):
            midnight = resolve_profile(cfg, datetime(2026, 1, 2, 0, 30, tzinfo=ZoneInfo("UTC")))
            morning = resolve_profile(cfg, datetime(2026, 1, 2, 5, 0, tzinfo=ZoneInfo("UTC")))
        self.assertLess(midnight.brightness, cfg["light_profiles"]["evening"]["brightness"])
        self.assertEqual(morning.name, "after_bedtime")
        self.assertEqual(morning.brightness, cfg["light_profiles"]["after_bedtime"]["brightness"])

    def test_late_sunset_does_not_push_bedtime_to_next_night(self):
        cfg = validate_config(json.loads((ROOT / "config.example.json").read_text(encoding="utf-8")))
        cfg.update(timezone="UTC", wind_down_start="19:00", pre_sleep_start="20:00", bedtime="21:00")
        with patch(
            "mijialamp.profiles.solar_times",
            return_value={"sunset": datetime(2026, 1, 1, 20, tzinfo=ZoneInfo("UTC"))},
        ):
            profile = resolve_profile(cfg, datetime(2026, 1, 1, 22, tzinfo=ZoneInfo("UTC")))
        self.assertEqual(profile.name, "after_bedtime")


if __name__ == "__main__":
    unittest.main()
