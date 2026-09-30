from __future__ import annotations

import ipaddress
import json
import os
import re
from pathlib import Path
from zoneinfo import ZoneInfo

from .errors import ConfigError
from .locking import FileLock
from .paths import CONFIG_PATH, DEVICE_CACHE_LOCK_PATH, DEVICE_CACHE_PATH
from .util import atomic_write_json, epoch_now, utc_now_iso

_REQUIRED_PROFILES = ("evening", "wind_down", "pre_sleep", "after_bedtime", "manual_day")
_SOLAR_KEYS = {"sunrise", "sunset", "dawn", "dusk"}
_MAC_RE = re.compile(r"^(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$")

DEFAULTS: dict = {
    "version": 3,
    "expected_mac": "",
    "night_mode": True,
    "night_start": "sunset",
    "night_end": "sunrise",
    "night_start_offset_minutes": -20,
    "night_end_offset_minutes": 20,
    "manual_day_override_max_hours": 5,
    "manual_off_override_minutes": 120,
    "profile_transition_mode": "stepped",
    "profile_transition_ms": 700,
    "power_transition_ms": 0,
    "profile_brightness_tolerance": 1,
    "profile_kelvin_tolerance": 25,
    "sync_interval_seconds": 60,
    "network_change_poll_seconds": 10,
    "display_state_stale_minutes": 30,
    "unknown_display_policy": "off",
    "display_event_debounce_seconds": 2.0,
    "display_off_confirm_seconds": 5.0,
    "suppress_off_after_start_seconds": 10.0,
    "suppress_off_after_resume_seconds": 10.0,
    "respect_session_lock": True,
    "off_on_session_lock": True,
    "on_on_session_unlock": True,
    "respect_user_presence": True,
    "off_when_user_inactive": False,
    "ignore_remote_sessions": True,
    "network_wait_seconds_on": 20,
    "network_wait_seconds_off": 3,
    "network_wait_seconds_periodic": 3,
    "miio_timeout_seconds": 2.5,
    "miio_fast_timeout_seconds": 0.55,
    "suspend_off_timeout_seconds": 0.25,
    "suspend_event_deadline_seconds": 0.75,
    "retries": 2,
    "retry_delay_seconds": 1.0,
    "discovery_enabled": True,
    "discovery_neighbor_enabled": True,
    "discovery_mdns_seconds": 2.0,
    "discovery_scan_enabled": True,
    "discovery_scan_prefix": 24,
    "discovery_scan_workers": 16,
    "discovery_scan_timeout_seconds": 0.4,
    "discovery_cooldown_seconds": 300,
    "discovery_backoff_max_seconds": 1800,
    "discovery_full_scan_cooldown_seconds": 1800,
    "external_change_policy": "respect_until_next_profile",
    "external_change_respect_minutes": 60,
    "pause_until_tomorrow_time": "08:00",
    "notifications_enabled": True,
    "notify_after_failure_seconds": 900,
    "event_log_enabled": True,
    "tray_enabled": True,
    "log_max_bytes": 5 * 1024 * 1024,
    "log_backup_count": 5,
}
_KNOWN_CONFIG_KEYS = set(DEFAULTS) | {
    "$schema",
    "lamp_ip",
    "expected_model",
    "device_id",
    "location_name",
    "latitude",
    "longitude",
    "elevation_meters",
    "timezone",
    "wind_down_start",
    "pre_sleep_start",
    "bedtime",
    "light_profiles",
}



def _strict_bool(cfg: dict, key: str) -> bool:
    value = cfg.get(key)
    if type(value) is not bool:  # noqa: E721 - intentionally reject 0/1 and strings
        raise ConfigError(f"{key} debe ser true o false (booleano JSON real)")
    return value


def _number(cfg: dict, key: str, *, minimum: float | None = None, maximum: float | None = None) -> float:
    value = cfg.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{key} debe ser numérico")
    num = float(value)
    if minimum is not None and num < minimum:
        raise ConfigError(f"{key} debe ser >= {minimum}")
    if maximum is not None and num > maximum:
        raise ConfigError(f"{key} debe ser <= {maximum}")
    return num


def _integer(cfg: dict, key: str, *, minimum: int | None = None, maximum: int | None = None) -> int:
    value = cfg.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{key} debe ser un entero")
    if minimum is not None and value < minimum:
        raise ConfigError(f"{key} debe ser >= {minimum}")
    if maximum is not None and value > maximum:
        raise ConfigError(f"{key} debe ser <= {maximum}")
    return value


def _hhmm(value: str, key: str) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"{key} debe ser texto HH:MM")
    try:
        hour_s, minute_s = value.strip().split(":", 1)
        hour, minute = int(hour_s), int(minute_s)
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
        return f"{hour:02d}:{minute:02d}"
    except Exception as exc:
        raise ConfigError(f"{key} debe tener formato HH:MM") from exc


def _normalize_mac(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    if not _MAC_RE.fullmatch(value):
        raise ConfigError("expected_mac debe tener formato AA:BB:CC:DD:EE:FF")
    return value.replace("-", ":").upper()


def _apply_defaults(cfg: dict) -> dict:
    merged = dict(DEFAULTS)
    merged.update(cfg)
    # v2 compatibility: remove obsolete fallback instead of silently using it.
    merged.pop("resume_user_fallback_seconds", None)
    merged["version"] = 3
    return merged


def validate_config(cfg: dict) -> dict:
    if not isinstance(cfg, dict):
        raise ConfigError("config.json debe contener un objeto JSON")

    raw_version = cfg.get("version")
    if isinstance(raw_version, bool) or not isinstance(raw_version, int) or raw_version != 3:
        raise ConfigError("version debe ser exactamente 3; ejecutá el migrador/instalador v3")

    unknown = sorted(set(cfg) - _KNOWN_CONFIG_KEYS)
    if unknown:
        raise ConfigError(
            "Claves desconocidas en config.json: " + ", ".join(unknown)
            + ". Corregí posibles typos o ejecutá la migración v3."
        )

    cfg = _apply_defaults(cfg)

    try:
        ip = ipaddress.ip_address(str(cfg["lamp_ip"]))
        if not isinstance(ip, ipaddress.IPv4Address) or ip.is_multicast or ip.is_unspecified:
            raise ValueError
        cfg["lamp_ip"] = str(ip)
    except Exception as exc:
        raise ConfigError("lamp_ip debe ser una IPv4 unicast válida") from exc

    cfg["expected_mac"] = _normalize_mac(str(cfg.get("expected_mac", "")))

    schema_hint = cfg.get("$schema")
    if schema_hint is not None and not isinstance(schema_hint, str):
        raise ConfigError("$schema debe ser texto")
    location_name = cfg.get("location_name", "")
    if not isinstance(location_name, str):
        raise ConfigError("location_name debe ser texto")

    model = str(cfg.get("expected_model", "")).strip()
    if not model:
        raise ConfigError("expected_model es obligatorio")
    cfg["expected_model"] = model

    did = str(cfg.get("device_id", "")).strip()
    if not did.isdigit() or int(did) <= 0:
        raise ConfigError("device_id debe ser un entero decimal positivo")
    cfg["device_id"] = did

    try:
        ZoneInfo(str(cfg["timezone"]))
    except Exception as exc:
        raise ConfigError("timezone no es válida") from exc

    lat = _number(cfg, "latitude", minimum=-90, maximum=90)
    lon = _number(cfg, "longitude", minimum=-180, maximum=180)
    cfg["latitude"], cfg["longitude"] = lat, lon
    _number(cfg, "elevation_meters", minimum=-500, maximum=9000)

    for key in ("night_mode", "respect_session_lock", "off_on_session_lock", "on_on_session_unlock",
                "respect_user_presence", "off_when_user_inactive", "ignore_remote_sessions",
                "discovery_enabled", "discovery_neighbor_enabled", "discovery_scan_enabled",
                "notifications_enabled", "event_log_enabled", "tray_enabled"):
        _strict_bool(cfg, key)

    for key in ("night_start", "night_end"):
        value = str(cfg.get(key, "")).lower()
        if value not in _SOLAR_KEYS:
            raise ConfigError(f"{key} debe ser uno de: {', '.join(sorted(_SOLAR_KEYS))}")
        cfg[key] = value

    _integer(cfg, "night_start_offset_minutes", minimum=-360, maximum=360)
    _integer(cfg, "night_end_offset_minutes", minimum=-360, maximum=360)

    for key in ("wind_down_start", "pre_sleep_start", "bedtime", "pause_until_tomorrow_time"):
        cfg[key] = _hhmm(cfg.get(key, ""), key)

    profiles = cfg.get("light_profiles")
    if not isinstance(profiles, dict):
        raise ConfigError("light_profiles debe ser un objeto")
    for name in _REQUIRED_PROFILES:
        profile = profiles.get(name)
        if not isinstance(profile, dict):
            raise ConfigError(f"Falta light_profiles.{name}")
        kelvin = profile.get("kelvin")
        brightness = profile.get("brightness")
        if isinstance(kelvin, bool) or not isinstance(kelvin, int) or not 2700 <= kelvin <= 6500:
            raise ConfigError(f"{name}.kelvin debe ser un entero entre 2700 y 6500")
        if isinstance(brightness, bool) or not isinstance(brightness, int) or not 1 <= brightness <= 100:
            raise ConfigError(f"{name}.brightness debe ser un entero entre 1 y 100")

    if cfg["profile_transition_mode"] not in {"stepped", "continuous"}:
        raise ConfigError("profile_transition_mode debe ser 'stepped' o 'continuous'")
    if cfg["unknown_display_policy"] not in {"off", "hold", "assume_on"}:
        raise ConfigError("unknown_display_policy debe ser off, hold o assume_on")
    if cfg["external_change_policy"] not in {"enforce", "respect_for_minutes", "respect_until_next_profile"}:
        raise ConfigError("external_change_policy inválida")

    number_ranges = {
        "manual_day_override_max_hours": (0, 72),
        "manual_off_override_minutes": (0, 1440),
        "profile_transition_ms": (0, 10000),
        "power_transition_ms": (0, 10000),
        "sync_interval_seconds": (10, 3600),
        "network_change_poll_seconds": (5, 300),
        "display_state_stale_minutes": (1, 1440),
        "display_event_debounce_seconds": (0, 30),
        "display_off_confirm_seconds": (0, 60),
        "suppress_off_after_start_seconds": (0, 120),
        "suppress_off_after_resume_seconds": (0, 120),
        "network_wait_seconds_on": (0, 120),
        "network_wait_seconds_off": (0, 30),
        "network_wait_seconds_periodic": (0, 30),
        "miio_timeout_seconds": (0.2, 10),
        "miio_fast_timeout_seconds": (0.1, 2),
        "suspend_off_timeout_seconds": (0.1, 1.0),
        "suspend_event_deadline_seconds": (0.2, 3.0),
        "retry_delay_seconds": (0, 30),
        "discovery_mdns_seconds": (0, 15),
        "discovery_scan_timeout_seconds": (0.1, 2),
        "discovery_cooldown_seconds": (0, 86400),
        "discovery_backoff_max_seconds": (0, 86400),
        "discovery_full_scan_cooldown_seconds": (0, 86400),
        "external_change_respect_minutes": (1, 1440),
        "notify_after_failure_seconds": (0, 86400),
    }
    for key, (low, high) in number_ranges.items():
        _number(cfg, key, minimum=low, maximum=high)

    for key, low, high in (
        ("profile_brightness_tolerance", 0, 20),
        ("profile_kelvin_tolerance", 0, 500),
        ("retries", 1, 10),
        ("discovery_scan_workers", 1, 32),
        ("log_backup_count", 1, 50),
        ("log_max_bytes", 65536, 100 * 1024 * 1024),
    ):
        _integer(cfg, key, minimum=low, maximum=high)

    prefix = _integer(cfg, "discovery_scan_prefix", minimum=24, maximum=24)
    if prefix != 24:
        raise ConfigError("Por seguridad sólo se permite discovery_scan_prefix=24")

    return cfg


def _preserve_corrupt_cache(exc: Exception) -> None:
    stamp = int(epoch_now())
    corrupt = DEVICE_CACHE_PATH.with_name(f"{DEVICE_CACHE_PATH.stem}.corrupt-{stamp}{DEVICE_CACHE_PATH.suffix}")
    try:
        os.replace(DEVICE_CACHE_PATH, corrupt)
    except OSError:
        pass


def read_device_cache() -> dict:
    if not DEVICE_CACHE_PATH.is_file():
        return {}
    with FileLock(DEVICE_CACHE_LOCK_PATH, timeout=3):
        try:
            with open(DEVICE_CACHE_PATH, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                raise json.JSONDecodeError("cache root is not object", "", 0)
            return data
        except FileNotFoundError:
            return {}
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            _preserve_corrupt_cache(exc)
            return {}


def update_device_cache(**fields) -> dict:
    with FileLock(DEVICE_CACHE_LOCK_PATH, timeout=5):
        data: dict = {}
        try:
            with open(DEVICE_CACHE_PATH, "r", encoding="utf-8") as fh:
                loaded = json.load(fh)
            if isinstance(loaded, dict):
                data.update(loaded)
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            pass
        data.update(fields)
        data["version"] = 2
        data["updated_at"] = utc_now_iso()
        atomic_write_json(DEVICE_CACHE_PATH, data)
        return data


def _read_cached_ip() -> str | None:
    data = read_device_cache()
    value = data.get("lamp_ip")
    if not value:
        return None
    try:
        ip = ipaddress.ip_address(str(value))
        return str(ip) if isinstance(ip, ipaddress.IPv4Address) else None
    except ValueError:
        return None


def load_config(path: Path = CONFIG_PATH) -> dict:
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            cfg = json.load(fh)
    except FileNotFoundError as exc:
        raise ConfigError(f"No existe {path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"JSON inválido en {path}: {exc}") from exc
    cfg = validate_config(cfg)
    cached_ip = _read_cached_ip()
    if cached_ip:
        cfg["lamp_ip"] = cached_ip
    return cfg


def update_lamp_ip(new_ip: str) -> bool:
    ip_obj = ipaddress.ip_address(new_ip)
    if not isinstance(ip_obj, ipaddress.IPv4Address):
        raise ConfigError("La IP descubierta debe ser IPv4")
    ip = str(ip_obj)
    previous = read_device_cache().get("lamp_ip")
    if previous == ip:
        return False
    update_device_cache(lamp_ip=ip)
    return True
