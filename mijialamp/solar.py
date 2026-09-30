from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


def solar_times(cfg: dict, when: datetime | None = None) -> dict:
    from astral import Observer
    from astral.sun import sun

    tz = ZoneInfo(str(cfg["timezone"]))
    now = when.astimezone(tz) if when is not None else datetime.now(tz)
    observer = Observer(
        latitude=float(cfg["latitude"]),
        longitude=float(cfg["longitude"]),
        elevation=float(cfg.get("elevation_meters", 0)),
    )
    return sun(observer, date=now.date(), tzinfo=tz)


def is_night_now(cfg: dict, when: datetime | None = None) -> bool:
    if not bool(cfg.get("night_mode", True)):
        return True
    tz = ZoneInfo(str(cfg["timezone"]))
    now = when.astimezone(tz) if when is not None else datetime.now(tz)
    times = solar_times(cfg, now)
    start_key = str(cfg.get("night_start", "sunset")).lower()
    end_key = str(cfg.get("night_end", "sunrise")).lower()
    if start_key not in times:
        start_key = "sunset"
    if end_key not in times:
        end_key = "sunrise"
    night_start = times[start_key] + timedelta(
        minutes=int(cfg.get("night_start_offset_minutes", 0))
    )
    night_end = times[end_key] + timedelta(
        minutes=int(cfg.get("night_end_offset_minutes", 0))
    )
    return now >= night_start or now < night_end


def current_minutes(cfg: dict, when: datetime | None = None) -> int:
    tz = ZoneInfo(str(cfg["timezone"]))
    now = when.astimezone(tz) if when is not None else datetime.now(tz)
    return now.hour * 60 + now.minute


def _parse_hhmm(value: str) -> int:
    hour, minute = map(int, value.split(":"))
    return hour * 60 + minute


def _in_range(now_min: int, start_min: int, end_min: int) -> bool:
    if start_min <= end_min:
        return start_min <= now_min < end_min
    return now_min >= start_min or now_min < end_min


def night_profile_name(cfg: dict, when: datetime | None = None) -> str:
    now_min = current_minutes(cfg, when)
    wind_down = _parse_hhmm(cfg["wind_down_start"])
    pre_sleep = _parse_hhmm(cfg["pre_sleep_start"])
    bedtime = _parse_hhmm(cfg["bedtime"])

    # After bedtime until noon (sunrise policy still decides whether power is allowed).
    if _in_range(now_min, bedtime, 12 * 60):
        return "after_bedtime"
    if _in_range(now_min, pre_sleep, bedtime):
        return "pre_sleep"
    if _in_range(now_min, wind_down, pre_sleep):
        return "wind_down"
    return "evening"
