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


if __name__ == "__main__":
    unittest.main()
