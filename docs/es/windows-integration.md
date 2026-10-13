# Integración con Windows 10/11

[English](../windows-integration.md) | [Español](windows-integration.md)


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

### Luz antes de iniciar sesión (opcional)

Con `service_prelogin_display: true`, Service se registra en `GUID_CONSOLE_DISPLAY_STATE` y recibe el estado actual de la pantalla de la consola, además de cambios posteriores. Si la pantalla de inicio de sesión está encendida y es de noche según la configuración, la automatización puede encender la lámpara antes de entrar a Windows. Al apagarse la pantalla, la política ordena OFF. El callback sólo pone el evento en cola; el control LAN ocurre fuera del callback de Windows. Portable no puede realizar esta función porque se inicia dentro de la sesión del usuario.

Para mantener la lámpara encendida también en la pantalla bloqueada, configurar `off_on_session_lock: false` y `respect_user_presence: false`. La automatización debe estar habilitada, la red local debe estar disponible y el token del Service debe haberse importado con alcance LocalMachine. Los overrides de apagado y pausa siguen teniendo prioridad. Si Windows no entrega una señal de pantalla válida, se conserva `unknown_display_policy: "off"` para evitar un encendido no solicitado.

Esta opción requiere una prueba real en Service tras reiniciar Windows sin iniciar sesión: verificar ON con la pantalla visible y OFF al apagarse la pantalla. El registro se probó en una sesión interactiva de Windows, pero todavía no se verificó en Session 0 en la PC del usuario.

## Suspend / Resume

En Portable, `PBT_APMSUSPEND` ejecuta el OFF crítico **directamente en el proceso**, sin Named Pipe, escaneo de red ni reintentos largos. Usa la IP conocida y un timeout corto dedicado. El OFF físico no borra overrides temporales como `manual_day`: Sleep no equivale a una decisión del usuario de salir de ese modo.

El aviso de suspensión puede llegar cuando Windows ya está cortando la red. El cliente miIO reutiliza una sesión reciente para evitar un handshake nuevo; si todavía no existe, intenta un único handshake unicast dentro del presupuesto corto. Esto reduce la demora, pero no garantiza que la lámpara reciba el OFF si la conexión desaparece primero. Para una suspensión iniciada por el usuario en la que el apagado sea condición, ejecutá desde Portable `& ".\runtime\python.exe" .\sleepnow.py --mode portable --require-lamp-off`: el helper intenta apagar antes de pedir la suspensión y no suspende si no recibe confirmación.

La suspensión iniciada desde el menú Inicio de Windows no pasa por `sleepnow.py`: Portable sólo recibe `PBT_APMSUSPEND` inmediatamente antes de dormir y el OFF LAN es best effort. Service recibe además el evento de energía por SCM y no depende de que el agente de la sesión esté activo, pero tampoco puede garantizar un OFF si la red o la lámpara deja de responder en ese momento. Para exigir confirmación de OFF antes de suspender, usá `sleepnow.py --require-lamp-off` en el modo que estés ejecutando.

No ejecutes simultáneamente Portable y una instalación anterior que controle la misma lámpara. Antes de probar Suspend, comprobá que el runtime Portable responde a `runtime-status`; si el Pipe deja de responder, cerrá el proceso Portable antiguo y reinicialo desde la sesión interactiva normal.

Para probar cambios locales antes de un PR, mantené `config.json`, `secrets/`, `data/` y `logs/` fuera del repositorio. Usá una carpeta `MijiaLamp-Portable-Dev` separada, cerrá el Portable anterior desde su icono de bandeja y ejecutá `scripts/update-portable-dev.ps1` desde el repositorio. El script actualiza el código de Dev y conserva su runtime, configuración, token y estado. Iniciá Dev desde una PowerShell normal y comprobá que el proceso `pythonw.exe` usa el runtime de esa carpeta; `runtime-status` por sí solo puede responder desde otra instancia porque ambas comparten el mismo Pipe.

En Service, SCM sigue siendo la autoridad principal de power events. El hint one-way del Agent lleva un deadline monotónico para que un mensaje retenido durante Sleep no pueda convertirse en un OFF obsoleto después de Resume.

`PBT_APMRESUMEAUTOMATIC` y `PBT_APMRESUMESUSPEND` invalidan trabajo anterior incrementando `intent_revision`, pero nunca asignan `display_on=True` ni `user_presence=present`.

La vuelta a ON requiere una señal interactiva real, principalmente Display ON. Por eso un wake automático de mantenimiento no enciende la lámpara; si el usuario mueve el mouse y aparece la pantalla de login, el Display ON real puede restaurar el perfil previo incluso antes de desbloquear Windows.

## Modern Standby

El Agent mantiene los handlers muy cortos. Display/WTS/Presence usan notificaciones one-way. Suspend Portable usa un OFF síncrono con timeout corto; Service recibe además el evento de energía directamente desde SCM.

## Sleep Now

`Sleep Now` pide OFF antes de llamar a `SetSuspendState`. El helper habilita `SeShutdownPrivilege` explícitamente. En modo Service utiliza el Pipe del servicio; en Portable usa el Pipe Portable.
