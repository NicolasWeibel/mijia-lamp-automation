# Arquitectura v3.1

MijiaLamp comparte un único núcleo (`policy`, `StateStore`, `LampController`, `LampTransport`, `ServiceCore`) y ofrece dos hosts.

## Invariantes comunes

1. Una intención nueva invalida trabajo viejo (`intent_revision`).
2. OFF crítico gana (`critical_off_revision`).
3. Estado runtime no se confunde con estado físico.
4. Display/session/presence desconocidos no implican automáticamente ON.
5. Discovery valida modelo + DID antes de adoptar una IP.

## Portable host

`portable.py` crea `LampController + ServiceCore` en el proceso del usuario y abre `MijiaLamp-Portable-v3` para CLI/tray/eventos. Usa DPAPI `CurrentUser`.

No hay servicio ni código elevado. El shutdown de Windows es best-effort porque el proceso pertenece a la sesión interactiva.

## Service host

`service.py` aloja el mismo core bajo `LocalService`. `agent.py` sólo observa Windows y usa IPC; no importa `miio` ni `secrets_store`.

SCM entrega directamente Preshutdown/Shutdown/Power al servicio, por lo que el OFF no depende de iniciar una tarea durante el cierre del sistema.

## Install hardened

La release Service puede incluir un runtime privado ya preparado. Si no lo incluye, el usuario ejecuta primero `prepare-service-runtime.ps1` sin Admin. `install.ps1` verifica SHA-256, prepara staging, detiene la versión anterior sólo al final y hace swap. Si la instalación falla, restaura los archivos anteriores sin ejecutar su runtime con privilegios elevados; no reinicia la automatización hasta repetir una instalación verificada.

## IPC concurrente

Cada conexión tiene worker propio con un máximo acotado. Los eventos críticos del Agent usan mensajes one-way, evitando que `WM_POWERBROADCAST` espere a un `doctor` o sync lento.
