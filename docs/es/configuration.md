# Configuración

[English](../configuration.md) | [Español](configuration.md)


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
- `continuous`: interpolación entre los horarios de referencia nocturnos.

En modo continuo, la reducción empieza al comienzo de la noche: los valores del perfil inicial se acercan gradualmente a los del perfil de relajación hasta `wind_down_start`, y luego a los del perfil previo al sueño hasta `pre_sleep_start`. Esas horas indican cuándo se alcanza cada nivel, no cuándo comienza cada reducción. El brillo se redondea a puntos porcentuales enteros y se aplica al sincronizar, por lo que la lámpara recibe pequeños ajustes separados. Cada ajuste solicita la transición de `profile_transition_ms` (700 ms por defecto); si el dispositivo rechaza los comandos suaves, se aplica el cambio inmediato. El porcentaje de brillo es un ajuste del dispositivo, no una medición de la luz emitida.

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


## Idioma de la interfaz

`ui_language` admite `en` (inglés) o `es` (español). El instalador guarda la elección del primer paso. Podés cambiarla desde el selector de idioma en Preferencias: guardá y volvé a abrir el editor. Service se reinicia para aplicar los ajustes; Portable debe reiniciarse cuando se indique. La ciudad y la zona horaria son independientes del idioma. Las configuraciones anteriores sin esta clave siguen siendo válidas.

## Controles de la bandeja

Las pausas temporales están en **Más opciones → Pausar ajustes automáticos**, con **1 hora** y **Hasta el amanecer**. El submenú aclara que la pausa no enciende ni apaga la lámpara por sí sola.

La primera fila muestra el modo actual, el tiempo restante de una pausa o acción manual, o la disponibilidad del programa. Los controles de la lámpara se habilitan cuando el runtime responde. Service tiene inicio automático retrasado: el icono puede aparecer antes de que el servicio esté listo.

| Control | Comportamiento |
| --- | --- |
| Encender manualmente | Enciende inmediatamente y cancela el apagado manual y los cambios externos respetados. De día crea una excepción de hasta `manual_day_override_max_hours` (5 horas por defecto); de noche usa el perfil nocturno actual sin crear ese temporizador diurno. |
| Apagar durante … | Apaga inmediatamente e impide el encendido automático durante `manual_off_override_minutes` (120 minutos por defecto). El nombre muestra la duración configurada. Cero significa sin temporizador. |
| Volver al modo automático | Activa la automatización, cancela pausas y excepciones manuales o externas, y aplica inmediatamente las reglas de pantalla, presencia y horario solar. El automático puede mantener la lámpara apagada. |
| Más opciones → Pausar ajustes automáticos → 1 hora | Conserva el estado y la iluminación actuales durante una hora. No enciende ni apaga por sí solo. |
| Más opciones → Pausar ajustes automáticos → Hasta el amanecer | La misma pausa, hasta el próximo amanecer de la ubicación configurada. |
| Aplicar reglas actuales ahora | Consulta la lámpara y aplica las reglas vigentes. Conserva las pausas y excepciones manuales activas. |
| Abrir logs / Editar configuración | Abre los registros de diagnóstico o las preferencias. No cambia la lámpara por sí solo. |
| Cerrar icono y agente | En Service cierra el agente interactivo y la bandeja; el servicio de Windows continúa. Dejan de llegar las actualizaciones de pantalla, sesión y presencia del agente. |
| Cerrar MijiaLamp Portable | En Portable cierra el programa y la bandeja. Esta acción no envía un apagado por sí sola. |

El encendido manual no garantiza cinco horas de luz: la automatización sin pausa sigue las reglas configuradas de pantalla y sesión. Las acciones manuales no cancelan una pausa existente ni activan una automatización deshabilitada. Las pausas también suspenden el seguimiento normal de pantalla y perfiles; el apagado crítico al suspender o apagar Windows sigue activo. Al vencer un temporizador deciden las reglas restantes: no hay un encendido o apagado incondicional. **Volver al modo automático** cancela todas las excepciones inmediatamente.

Las duraciones manuales se editan en las opciones avanzadas de comportamiento. En esta versión actualizada, volver al automático cancela las excepciones manuales; las instalaciones anteriores solamente cancelaban pausas y cambios externos.
