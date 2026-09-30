# Configuración

`config.json` es local y está ignorado por Git. Empezá desde `config.example.json`; el archivo incluye `$schema` para validación/autocompletado.

## Identidad

- `lamp_ip`: IPv4 unicast conocida.
- `device_id`: DID esperado.
- `expected_model`: modelo miIO esperado.
- `expected_mac`: opcional pero recomendado; permite resolver la IP desde Windows Neighbor antes de escanear.

La IP descubierta dinámicamente se guarda en `data/device_cache.json`; no se reescribe el config.

## Solar

- `latitude`, `longitude`, `elevation_meters`, `timezone`.
- `night_start` / `night_end`: `dawn`, `sunrise`, `sunset` o `dusk`.
- offsets en minutos para ajustar la ventana.

## Perfiles

`light_profiles` exige:

- `evening`
- `wind_down`
- `pre_sleep`
- `after_bedtime`
- `manual_day`

Cada uno tiene `kelvin` y `brightness` validados.

### `profile_transition_mode`

- `stepped`: cambios discretos.
- `continuous`: interpolación entre anchors nocturnos.

## Cambios externos

`external_change_policy`:

- `enforce`
- `respect_for_minutes`
- `respect_until_next_profile`

`profile_brightness_tolerance` y `profile_kelvin_tolerance` evitan tratar pequeñas diferencias de redondeo como intervención externa.

## Windows 11

- `respect_session_lock`
- `off_on_session_lock`
- `on_on_session_unlock`
- `respect_user_presence`
- `off_when_user_inactive`
- `ignore_remote_sessions`
- `display_event_debounce_seconds`
- `display_off_confirm_seconds`

`unknown_display_policy` debería mantenerse en `off` para un comportamiento fail-safe después de reinicios.

## Discovery/red

- `network_wait_seconds_on/off/periodic`
- `miio_timeout_seconds`
- `miio_fast_timeout_seconds`
- `retries`
- `discovery_neighbor_enabled`
- `discovery_mdns_seconds`
- `discovery_scan_enabled`
- `discovery_scan_prefix`: v3 sólo permite `/24`.
- `discovery_scan_workers`: máximo acotado.
- `discovery_cooldown_seconds`
- `discovery_backoff_max_seconds`
- `discovery_full_scan_cooldown_seconds`

## UX y observabilidad

- `tray_enabled`
- `notifications_enabled`
- `notify_after_failure_seconds`
- `event_log_enabled`
- `log_max_bytes`
- `log_backup_count`

## Validación

La validación runtime es deliberadamente estricta: un string `"false"` no se acepta donde corresponde un booleano, una IPv6 no se acepta en `lamp_ip` y una clave desconocida se rechaza. Esto hace que un typo no quede silenciosamente ignorado.

```powershell
# Portable
& ".\runtime\python.exe" .\lampctl.py --mode portable config-check

# Service
& ".\runtime\python.exe" .\lampctl.py config-check
```

## Suspend

- `suspend_off_timeout_seconds`: límite corto para el OFF crítico de Suspend. No hace discovery ni reintentos. Default: `0.25`.
- `suspend_event_deadline_seconds`: vida máxima de un hint Suspend one-way enviado al Service. Si se procesa después, se descarta para evitar un OFF tardío tras Resume. Default: `0.75`.

Estos valores son intencionalmente pequeños: el objetivo es enviar OFF antes de que Windows retire la interfaz de red, no esperar a que la red vuelva.
