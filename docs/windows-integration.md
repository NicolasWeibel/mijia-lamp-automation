# Integración con Windows 10/11

## Eventos interactivos

`agent.py` crea una ventana Win32 oculta y registra:

- `GUID_SESSION_DISPLAY_STATUS`;
- `GUID_SESSION_USER_PRESENCE` cuando está disponible;
- `WTSRegisterSessionNotification` para Lock/Unlock/Logon/Logoff/console/RDP;
- `WM_POWERBROADCAST` para Suspend/Resume.

Los dos modos comparten este Agent.

## Portable

`portable.py` aloja el core en el mismo proceso del usuario. El Agent envía eventos al Pipe `MijiaLamp-Portable-v3`. El proceso existe sólo mientras la sesión está activa.

Puede agregarse al Startup del usuario con `enable-portable-autostart.ps1`; esto no requiere Administrador.

Limitación deliberada: shutdown/logoff es **best effort**. Windows puede terminar la sesión antes de completar un comando LAN.

## Service

`MijiaLampService` corre como `LocalService` y recibe además controles SCM:

- `SERVICE_CONTROL_PRESHUTDOWN`;
- `SERVICE_CONTROL_SHUTDOWN`;
- `SERVICE_CONTROL_POWEREVENT`.

Por eso el OFF de cierre/suspensión no depende de iniciar procesos nuevos al final del shutdown.

El servicio no supone que iniciar Windows equivale a presencia. Un service restart invalida Display/WTS/Presence hasta que Agent vuelva a publicar un snapshot real.

## Suspend / Resume

En Portable, `PBT_APMSUSPEND` ejecuta el OFF crítico **directamente en el proceso**, sin Named Pipe, discovery ni reintentos. Usa la IP conocida y un timeout corto dedicado. El OFF físico no borra overrides temporales como `manual_day`: Sleep no equivale a una decisión del usuario de salir de ese modo.

En Service, SCM sigue siendo la autoridad principal de power events. El hint one-way del Agent lleva un deadline monotónico para que un mensaje retenido durante Sleep no pueda convertirse en un OFF obsoleto después de Resume.

`PBT_APMRESUMEAUTOMATIC` y `PBT_APMRESUMESUSPEND` invalidan trabajo anterior incrementando `intent_revision`, pero nunca asignan `display_on=True` ni `user_presence=present`.

La vuelta a ON requiere una señal interactiva real, principalmente Display ON. Por eso un wake automático de mantenimiento no enciende la lámpara; si el usuario mueve el mouse y aparece la pantalla de login, el Display ON real puede restaurar el perfil previo incluso antes de desbloquear Windows.

## Modern Standby

El Agent mantiene los handlers muy cortos. Display/WTS/Presence usan notificaciones one-way. Suspend Portable usa un OFF síncrono con timeout corto; Service recibe además el evento de energía directamente desde SCM.

## Sleep Now

`Sleep Now` pide OFF antes de llamar a `SetSuspendState`. El helper habilita `SeShutdownPrivilege` explícitamente. En modo Service utiliza el Pipe del servicio; en Portable usa el Pipe Portable.
