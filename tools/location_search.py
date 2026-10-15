"""Worldwide city lookup for the unelevated settings editor (Open-Meteo/GeoNames)."""

from __future__ import annotations

import base64
import codecs
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from zoneinfo import ZoneInfo

import requests

from mijialamp.i18n import get_language, tr

ENDPOINT = "https://geocoding-api.open-meteo.com/v1/search"


def normalize_location(item: dict) -> dict:
    latitude, longitude = float(item["latitude"]), float(item["longitude"])
    elevation = float(item.get("elevation", 0))
    timezone = str(item["timezone"])
    ZoneInfo(timezone)
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180 and math.isfinite(elevation)):
        raise ValueError(tr("msg_dda31c358c29"))
    names = [str(item.get(key, "")).strip() for key in ("name", "admin1", "country")]
    label = ", ".join(dict.fromkeys(name for name in names if name))
    if not names[0] or len(label) > 300:
        raise ValueError(tr("msg_1ff0155c7b6c"))
    return {
        "location_name": label,
        "latitude": latitude,
        "longitude": longitude,
        "elevation_meters": elevation,
        "timezone": timezone,
    }


def search_locations(query: str) -> list[dict]:
    query = query.strip()
    if not 2 <= len(query) <= 150:
        raise ValueError(tr("msg_a6a1643e934e"))
    with requests.get(
        ENDPOINT,
        params={"name": query, "count": 20, "language": get_language(), "format": "json"},
        timeout=(5, 15),
        allow_redirects=False,
        stream=True,
    ) as response:
        if response.status_code != 200:
            raise ValueError(tr("msg_8e8157aeaf97"))
        body = bytearray()
        for chunk in response.iter_content(8192):
            body.extend(chunk)
            if len(body) > 1_000_000:
                raise ValueError(tr("msg_0d6a9962b4c5"))
        data = json.loads(body)
    return [normalize_location(item) for item in data.get("results", [])[:20]]


def main() -> int:
    try:
        # Read bytes to tolerate PowerShell's UTF-8 BOM without relying on
        # the console's text encoding. Keep support for both input formats.
        raw = sys.stdin.buffer.read(4096).removeprefix(codecs.BOM_UTF8).strip()
        if not raw.startswith(b"{"):
            raw = base64.b64decode(raw, validate=True)
        query = json.loads(raw.decode("utf-8"))["query"]
        result = {"ok": True, "locations": search_locations(query)}
    except requests.RequestException:
        result = {"ok": False, "message": tr("msg_3d3b37d034c6")}
    except Exception as exc:
        result = {"ok": False, "message": str(exc)}
    print(json.dumps(result, ensure_ascii=True), flush=True)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
