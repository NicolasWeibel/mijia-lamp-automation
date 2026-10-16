import base64
import codecs
import importlib.util
import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from mijialamp.i18n import language


class LocationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[1] / "tools" / "location_search.py"
        spec = importlib.util.spec_from_file_location("location_search", path)
        cls.module = importlib.util.module_from_spec(spec)
        with patch.dict(
            "sys.modules", {"requests": SimpleNamespace(get=Mock(), RequestException=RuntimeError)}
        ):
            spec.loader.exec_module(cls.module)

    def test_stdin_preserves_accented_cities_in_both_formats_with_or_without_bom(self):
        raw = json.dumps({"query": "San Martín"}, ensure_ascii=False).encode("utf-8")
        for payload in (raw, base64.b64encode(raw)):
            for prefix in (b"", codecs.BOM_UTF8):
                with self.subTest(payload=payload, prefix=prefix):
                    output = io.StringIO()
                    stdin = SimpleNamespace(buffer=io.BytesIO(prefix + payload + b"\r\n"))
                    with (
                        patch("sys.stdin", stdin),
                        patch.object(self.module, "search_locations", return_value=[]) as search,
                        redirect_stdout(output),
                    ):
                        self.assertEqual(self.module.main(), 0)
                    search.assert_called_once_with("San Martín")
                    self.assertEqual(json.loads(output.getvalue()), {"ok": True, "locations": []})

    def test_invalid_base64_does_not_start_a_city_search(self):
        with (
            patch("sys.stdin", SimpleNamespace(buffer=io.BytesIO(codecs.BOM_UTF8 + b"not!base64"))),
            patch.object(self.module, "search_locations") as search,
            redirect_stdout(io.StringIO()) as output,
        ):
            self.assertEqual(self.module.main(), 1)
        search.assert_not_called()
        self.assertFalse(json.loads(output.getvalue())["ok"])

    def test_city_resolves_location_and_timezone_together(self):
        city = self.module.normalize_location(
            {
                "name": "San Martín",
                "admin1": "Mendoza",
                "country": "Argentina",
                "latitude": -33.08,
                "longitude": -68.46,
                "elevation": 640,
                "timezone": "America/Argentina/Mendoza",
            }
        )
        self.assertEqual(city["location_name"], "San Martín, Mendoza, Argentina")
        self.assertEqual(city["timezone"], "America/Argentina/Mendoza")
        self.assertEqual(city["elevation_meters"], 640)

    def test_rejects_invalid_coordinates_and_timezone(self):
        for overrides in ({"latitude": 100}, {"longitude": float("nan")}, {"timezone": "Missing/Timezone"}):
            with self.subTest(overrides=overrides), self.assertRaises((ValueError, KeyError)):
                self.module.normalize_location(
                    {"name": "City", "latitude": 0, "longitude": 0, "timezone": "UTC", **overrides}
                )

    def test_search_does_not_follow_redirects_or_accept_oversized_responses(self):
        response = Mock(status_code=200)
        response.iter_content.return_value = [b"x" * 1_000_001]
        self.module.requests.get.return_value.__enter__ = Mock(return_value=response)
        self.module.requests.get.return_value.__exit__ = Mock(return_value=False)
        with language("en"), self.assertRaisesRegex(ValueError, "large"):
            self.module.search_locations("Mendoza")
        self.assertFalse(self.module.requests.get.call_args.kwargs["allow_redirects"])
