import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from mijialamp.solar import next_sunrise


class SunriseTests(unittest.TestCase):
    def test_pause_before_dawn_resumes_this_morning_and_after_dawn_next_morning(self):
        tz = ZoneInfo("America/Argentina/Mendoza")
        cfg = {"timezone": str(tz), "latitude": -33.1, "longitude": -68.4}
        sunrise = Mock(
            side_effect=lambda _observer, date, tzinfo: datetime(
                date.year, date.month, date.day, 7, tzinfo=tzinfo
            )
        )
        modules = {"astral": SimpleNamespace(Observer=Mock()), "astral.sun": SimpleNamespace(sunrise=sunrise)}
        with patch.dict("sys.modules", modules):
            before = next_sunrise(cfg, datetime(2026, 10, 6, 2, tzinfo=tz))
            after = next_sunrise(cfg, datetime(2026, 10, 6, 9, tzinfo=tz))
        self.assertEqual(before, datetime(2026, 10, 6, 7, tzinfo=tz))
        self.assertEqual(after, datetime(2026, 10, 7, 7, tzinfo=tz))

    def test_missing_polar_sunrise_advances_to_next_available_date(self):
        tz = ZoneInfo("UTC")
        sunrise = Mock(side_effect=[ValueError("polar night"), datetime(2026, 1, 2, 7, tzinfo=tz)])
        with patch.dict(
            "sys.modules",
            {"astral": SimpleNamespace(Observer=Mock()), "astral.sun": SimpleNamespace(sunrise=sunrise)},
        ):
            result = next_sunrise(
                {"timezone": "UTC", "latitude": 80, "longitude": 0}, datetime(2026, 1, 1, tzinfo=tz)
            )
        self.assertEqual(result.day, 2)
