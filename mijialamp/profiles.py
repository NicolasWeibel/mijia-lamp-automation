from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .solar import night_profile_name, solar_times
from .transport import ProfileValues


def _parse_hhmm(value: str) -> tuple[int, int]:
    hour, minute = map(int, value.split(":"))
    return hour, minute


def _at_local_date(
    base: datetime, hhmm: str, *, roll_to_next_day_if_before: datetime | None = None
) -> datetime:
    hour, minute = _parse_hhmm(hhmm)
    candidate = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if roll_to_next_day_if_before is not None and candidate <= roll_to_next_day_if_before:
        candidate += timedelta(days=1)
    return candidate


def _profile(cfg: dict, name: str) -> ProfileValues:
    data = cfg["light_profiles"][name]
    return ProfileValues(name=name, kelvin=int(data["kelvin"]), brightness=int(data["brightness"]))


def _lerp_int(a: int, b: int, ratio: float) -> int:
    ratio = min(1.0, max(0.0, ratio))
    return int(round(a + (b - a) * ratio))


def resolve_profile(cfg: dict, when: datetime | None = None, *, manual_day: bool = False) -> ProfileValues:
    """Return either the stepped profile or a continuously interpolated night profile."""
    if manual_day:
        return _profile(cfg, "manual_day")

    if str(cfg.get("profile_transition_mode", "stepped")).lower() != "continuous":
        return _profile(cfg, night_profile_name(cfg, when))

    tz = ZoneInfo(str(cfg["timezone"]))
    now = when.astimezone(tz) if when is not None else datetime.now(tz)
    times = solar_times(cfg, now)
    start_key = str(cfg.get("night_start", "sunset")).lower()
    if start_key not in times:
        start_key = "sunset"
    start = times[start_key] + timedelta(minutes=int(cfg.get("night_start_offset_minutes", 0)))

    # Anchor times can cross midnight. Each later anchor is rolled forward as needed.
    wind = _at_local_date(start, cfg["wind_down_start"], roll_to_next_day_if_before=start)
    pre = _at_local_date(wind, cfg["pre_sleep_start"], roll_to_next_day_if_before=wind)
    bed = _at_local_date(pre, cfg["bedtime"], roll_to_next_day_if_before=pre)

    anchors = [
        (start, _profile(cfg, "evening")),
        (wind, _profile(cfg, "wind_down")),
        (pre, _profile(cfg, "pre_sleep")),
        (bed, _profile(cfg, "after_bedtime")),
    ]

    if now <= anchors[0][0]:
        return anchors[0][1]
    if now >= anchors[-1][0]:
        return anchors[-1][1]

    for (t0, p0), (t1, p1) in zip(anchors, anchors[1:], strict=False):
        if t0 <= now <= t1:
            span = max(1.0, (t1 - t0).total_seconds())
            ratio = (now - t0).total_seconds() / span
            return ProfileValues(
                name=f"continuous:{p0.name}->{p1.name}",
                kelvin=_lerp_int(p0.kelvin, p1.kelvin, ratio),
                brightness=_lerp_int(p0.brightness, p1.brightness, ratio),
            )

    return _profile(cfg, night_profile_name(cfg, when))
