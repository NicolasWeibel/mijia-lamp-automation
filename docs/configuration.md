# Configuration

[English](configuration.md) | [Español](es/configuration.md)


`config.json` is local and ignored by Git. Start from `config.example.json`; it includes `$schema` for validation and autocomplete.

## Identity

- `lamp_ip`: known unicast IPv4 address.
- `device_id`: expected DID.
- `expected_model`: expected miIO model.
- `expected_mac`: optional but recommended; lets Windows Neighbor resolve the IP before scanning.

A dynamically discovered IP is saved to `data/device_cache.json`; the config is not rewritten.

## Solar

- `latitude`, `longitude`, `elevation_meters`, `timezone`.
- `night_start` / `night_end`: `dawn`, `sunrise`, `sunset`, or `dusk`.
- Offsets in minutes adjust the window.

## Profiles

`light_profiles` requires:

- `evening`
- `wind_down`
- `pre_sleep`
- `after_bedtime`
- `manual_day`

Each has validated `kelvin` and `brightness` values.

### `profile_transition_mode`

- `stepped`: discrete changes.
- `continuous`: interpolation between nighttime anchors.

In continuous mode, dimming starts at the beginning of the night: the evening values gradually approach the wind-down values by `wind_down_start`, then the pre-sleep values by `pre_sleep_start`. These times are targets, rather than the start of each reduction. Brightness is rounded to whole percentage points and applied during synchronization, so the lamp receives small separate adjustments rather than a fade lasting all evening. Each adjustment requests the `profile_transition_ms` fade (700 ms by default); devices that reject smooth commands receive an immediate change instead. Brightness percentage is a device setting, not a measurement of light output.

## External changes

`external_change_policy`:

- `enforce`
- `respect_for_minutes`
- `respect_until_next_profile`

`profile_brightness_tolerance` and `profile_kelvin_tolerance` prevent small rounding differences from being treated as external changes.

## Windows 11

- `respect_session_lock`
- `off_on_session_lock`
- `on_on_session_unlock`
- `respect_user_presence`
- `off_when_user_inactive`
- `ignore_remote_sessions`
- `display_event_debounce_seconds`
- `display_off_confirm_seconds`

`unknown_display_policy` should remain `off` for fail-safe behavior after restarts.

## Discovery/network

- `network_wait_seconds_on/off/periodic`
- `miio_timeout_seconds`
- `miio_fast_timeout_seconds`
- `retries`
- `discovery_neighbor_enabled`
- `discovery_mdns_seconds`
- `discovery_scan_enabled`
- `discovery_scan_prefix`: v3 allows only `/24`.
- `discovery_scan_workers`: bounded maximum.
- `discovery_cooldown_seconds`
- `discovery_backoff_max_seconds`
- `discovery_full_scan_cooldown_seconds`

## UX and observability

- `tray_enabled`
- `notifications_enabled`
- `notify_after_failure_seconds`
- `event_log_enabled`
- `log_max_bytes`
- `log_backup_count`

## Validation

Runtime validation is deliberately strict: a string `"false"` is not accepted where a boolean is required, IPv6 is not accepted for `lamp_ip`, and unknown keys are rejected. This prevents typos from being silently ignored.

```powershell
# Portable
& ".\runtime\python.exe" .\lampctl.py --mode portable config-check

# Service
& ".\runtime\python.exe" .\lampctl.py config-check
```

## Suspend

- `suspend_off_timeout_seconds`: short limit for critical Suspend OFF. It does not discover devices or retry. Default: `0.25`.
- `suspend_event_deadline_seconds`: maximum lifetime of a one-way Suspend hint sent to the Service. If processed later, it is discarded to prevent a delayed OFF after Resume. Default: `0.75`.

These values are intentionally small: the goal is to send OFF before Windows removes the network interface, not to wait for the network to return.


## Interface language

`ui_language` accepts `en` (English) or `es` (Spanish). The installer saves the first-step choice. Change it from the language selector in Preferences, then save and reopen the editor. Service restarts to apply settings; Portable should be restarted when prompted. City and time zone are independent of the interface language. Existing configurations without this key remain valid.

## Tray controls

Temporary pauses are grouped under **More options → Pause automatic adjustments**, with **For 1 hour** and **Until sunrise**. The submenu explains that pausing does not itself turn the lamp on or off.

The first menu row reports the current mode, remaining manual/pause time, or runtime availability. Lamp commands become available after the runtime responds. Service uses delayed automatic startup; the tray can appear before the service is ready.

| Control | Behavior |
| --- | --- |
| Turn on manually | Turns the lamp on immediately and clears manual OFF and respected external changes. During the day, it creates an exception for up to `manual_day_override_max_hours` (default 5 hours); at night, it uses the current night profile without creating that daytime timer. |
| Turn off for … | Turns the lamp off immediately and prevents automatic ON for `manual_off_override_minutes` (default 120 minutes). The caption follows the configured duration. Zero means no timer. |
| Return to automatic mode | Enables automation, clears pauses and all manual/external overrides, then applies the current display, presence, and solar rules immediately. Automatic mode can legitimately keep the lamp off. |
| More options → Pause automatic adjustments → For 1 hour | Leaves power and brightness as they are for an hour. It does not turn the lamp on or off. |
| More options → Pause automatic adjustments → Until sunrise | Same pause, ending at the next sunrise for the configured location. |
| Apply current rules now | Rechecks the lamp and applies the current rules. It preserves active pauses and manual overrides. |
| Open logs / Edit settings | Opens diagnostics or preferences. These do not change the lamp by themselves. |
| Close tray and agent | In Service mode, closes the interactive agent and tray; the Windows service continues. Agent display/session/presence updates stop. |
| Quit MijiaLamp Portable | In Portable mode, closes the runtime and tray. This does not itself send OFF. |

Manual ON is not a guarantee that the light stays on for five hours: unpaused automation still follows the configured display/session rules. Manual actions do not cancel an existing pause or enable disabled automation. Pauses suspend normal display/profile reconciliation too; critical Suspend/Shutdown OFF remains active. When a timer expires, the remaining rules decide the state: there is no unconditional ON or OFF at expiry. Click **Return to automatic mode** to cancel all exceptions immediately.

The manual durations are configured under Advanced behavior settings. Returning to automatic mode cancels manual overrides in this updated version; older installations only canceled pauses and external overrides.
