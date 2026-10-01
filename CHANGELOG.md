# Changelog

Todos los cambios relevantes se documentan aquí. El proyecto usa versionado semántico y sigue la estructura de Keep a Changelog.

## [3.1.3] - 2026-09-30

### Changed

- Ruff completo, formato y mypy pasan a ser controles obligatorios de CI y del workflow de release.
- La documentación de verificación de artefactos identifica el repositorio público real.

### Fixed

- Corregido el arranque del Agent/Tray en ambos modos.
- Corregida la normalización de rutas del manifiesto durante la preparación e instalación Service.
- El manifiesto de source ya no incluye caches Python que se excluyen del ZIP.
- El build manual usa un nombre de SBOM seguro cuando la rama contiene `/`.

### Security

- El workflow verifica hashes, contenido del runtime y código de los ZIPs antes de publicar la release.
- Documentada la verificación de procedencia de una release oficial antes de elevar permisos.
- La publicación audita todos los pins de runtime y genera el manifest de wheels a partir del wheelhouse realmente usado.
- Las pruebas de Windows instalan `tzdata` antes de usar `ZoneInfo`; el tag de release debe coincidir con la versión del proyecto.
- `python-miio` usa un único pin explícito compartido por preparación, instalación, auditoría y SBOM.
- El runtime excluye los módulos opcionales `android_backup` y `micloud` de `python-miio`: no intervienen en el control local de la lámpara y no ofrecen wheels para Windows.

## [3.1.2] - 2026-09-30

### Fixed

- Suspend Portable ejecuta el OFF crítico directamente en el mismo proceso, sin esperar a un worker del Named Pipe.
- El OFF de Suspend usa la IP ya conocida, sin discovery, sin reintentos y con un timeout dedicado corto (`suspend_off_timeout_seconds`).
- Suspend ya no elimina `manual_day`, `manual_off` ni overrides externos: son estado lógico temporal que debe sobrevivir a Sleep/Resume.
- `resume-auto` y `resume-user` incrementan `intent_revision`, invalidando cualquier trabajo iniciado antes de dormir sin inventar Display ON.
- Los hints de Suspend enviados por el Agent al Service llevan un deadline monotónico; un evento que quedó en cola durante Sleep se descarta como `suspend-off-missed` en lugar de ejecutar un OFF obsoleto después de Resume.
- Suspend deja de programar un reassert diferido, evitando que un OFF tardío compita con un Display ON real después de Resume.
- `start-portable.cmd` detecta una instancia Portable ya activa y sale limpiamente en vez de provocar un `agent.lock`/`PermissionError` en el log.
- Shutdown/Preshutdown conservan el comportamiento fuerte anterior: limpian overrides y mantienen reassert cancelable.

### Added

- `suspend_off_timeout_seconds` (default `0.25`) y `suspend_event_deadline_seconds` (default `0.75`).
- Pruebas de regresión para OFF síncrono Portable, preservación de overrides, expiración de hints y cancelación de trabajo pre-Suspend.

## [3.1.1] - 2026-09-29

### Fixed

- `tools/migrate_legacy_config.py` ahora añade explícitamente la raíz del proyecto a `sys.path` cuando se ejecuta como script directo. Esto corrige `ModuleNotFoundError: No module named 'mijialamp'` durante `setup-portable.ps1` y el flujo equivalente del instalador.
- Añadida una prueba de regresión que ejecuta el migrador desde un directorio de trabajo ajeno al repositorio, reproduciendo la forma en que PowerShell lo invoca en una instalación real.

## [3.1.0] - 2026-09-29

### Added

- Modo **Portable** oficial sin Administrador ni Windows Service.
- Token Portable cifrado con DPAPI `CurrentUser` y Pipe separado por usuario.
- `setup-portable.ps1`, autostart de usuario, wrappers Portable y comandos `--mode portable`.
- Modo **Hardened Service** con runtime Python privado bajo `ProgramData`.
- `prepare-service-runtime.ps1`: descarga/instala dependencias sin elevación, exige wheels binarios, prueba reubicación y genera manifest SHA-256.
- `security-check.ps1` para auditar cuenta del servicio, ACL, runtime, privilegios, Named Pipe y ausencia de listeners TCP.
- Releases separadas `MijiaLamp-Portable-*` y `MijiaLamp-Service-*`.
- La release Portable oficial puede incluir runtime Python autocontenido verificado por `runtime-manifest.json`, por lo que funciona sin Python instalado ni `pip`.
- Portable acepta `-ConfigPath` y migra tokens plaintext legacy directamente a DPAPI `CurrentUser`.

### Security

- La fase elevada de `install.ps1` ya no descarga paquetes ni ejecuta `pip`.
- El servicio deja de depender de un Python potencialmente modificable bajo `%LOCALAPPDATA%`.
- `RequiredPrivileges` del servicio se reduce a `SeChangeNotifyPrivilege`.
- El runtime preparado excluye `site-packages`/Scripts preexistentes del Python origen y elimina herramientas de instalación del runtime final.
- El instalador verifica que no existan archivos de runtime no manifestados, rechaza reparse points y revalida hashes después de copiar a staging (mitigación TOCTOU).
- Named Pipe Service restringido al SID exacto del usuario + **Service SID específico**, sin ACE amplia para todos los procesos `LocalService`.
- `integrity-manifest.json` y `security-check.ps1` detectan alteraciones posteriores de código/runtime protegidos.
- Staging + swap transaccional + rollback best-effort ante fallos posteriores al reemplazo.
- DPAPI distingue explícitamente scopes `current-user` y `local-machine`; blobs legacy v2 continúan soportados.

### Changed

- El modo Portable pasa a ser la forma recomendada para empezar y Service queda como opción de máxima fiabilidad.
- Los scripts instalados usan `runtime\python.exe`; `.venv` queda reservado al modo Portable/desarrollo.
- GitHub Release en Windows construye los runtimes preparados para Service y Portable a partir del mismo conjunto de dependencias fijadas.
- Suite ampliada a 91 tests y gate de cobertura del core elevado a 85%.

## [3.0.0] - 2026-09-29

- `enable-automation.ps1` y `disable-automation.ps1` ahora exigen elevación explícita, validan IPC/Doctor y fallan de forma segura ante tareas o servicio inconsistentes.

### Security

- El token y el acceso miIO pasan a un Windows Service ejecutado como `LocalService`; el Agent interactivo ya no puede leer el secreto.
- Named Pipe local con ACL limitada al usuario autorizado, Service SID específico, SYSTEM y Administradores.
- Named Pipe concurrente con límite de workers y notificaciones one-way para eventos de Windows.
- Service SID específico y ACL endurecidas para código, configuración, datos, logs y secretos.
- Migración automática de tokens plaintext legacy a DPAPI sin imprimirlos.
- GitHub Actions fijadas por SHA; release con SBOM, hashes y attestations.

### Fixed

- Eliminada la carrera que permitía a un sync viejo enviar ON después de un Suspend/OFF más reciente mediante `intent_revision` y validación antes de cada acción física.
- OFF crítico con reassert cancelable; una intención más nueva impide que un reassert viejo apague/encienda incorrectamente.
- Suspend/Shutdown/Preshutdown ya no dependen de una Scheduled Task iniciada tarde durante el apagado.
- `PBT_APMRESUMEAUTOMATIC` no inventa presencia ni display ON.
- Un reinicio del servicio invalida el estado interactivo en lugar de asumir pantalla activa.
- `SetSuspendState` habilita `SeShutdownPrivilege` explícitamente con prototipos Win32 seguros para x64.
- `Sleep Now` usa OFF one-way acotado por defecto; `--require-lamp-off` tiene espera total limitada y ya no puede bloquear la suspensión indefinidamente.
- Agent/CLI dejan de intentar crear/tocar `secrets/` o `data/` del servicio después de endurecer ACL.
- `device_cache.json` corrupto se pone en cuarentena y no impide el arranque.
- Discovery incorpora cooldown/exponential backoff para evitar escaneos repetitivos.
- Heartbeat refresca timestamps de Display/WTS/Presence aunque los valores no cambien, evitando falsos stale durante sesiones largas.
- Prototipos `ctypes` explícitos evitan truncamiento de HWND/HANDLE en Windows x64.
- `GUID_SESSION_USER_PRESENCE` pasa a ser opcional: su ausencia no derriba el Agent.

### Added

- Windows Service con soporte de Preshutdown/Shutdown/Power events.
- Agent interactivo para Display, WTS Lock/Unlock, User Presence y tray.
- Heartbeat Agent → Service para recuperar contexto después de reinicios.
- Búsqueda por MAC usando Windows Neighbor antes de mDNS y `/24`; el importador puede cachear la MAC observada desde `mihome-ctl`.
- Network-change watcher que invalida throttles de discovery y reconcilia cuando corresponde.
- Configuración v3 estricta y `config.schema.json`.
- Política para respetar cambios externos (`enforce`, `respect_for_minutes`, `respect_until_next_profile`).
- Perfiles nocturnos continuos con interpolación opcional.
- Tray con ON/OFF/Auto/Pause/Sync y notificaciones de fallos persistentes.
- Event Viewer además de logs rotativos.
- Interfaz `LampTransport` para desacoplar `python-miio` y facilitar tests/migraciones futuras.
- CLI empaquetada `mijialamp`.
- Ruff, mypy, coverage core, PSScriptAnalyzer, `pip-audit` y matriz Python 3.10–3.12.
- GPL-3.0-only explícita.

### Changed

- Se elimina Startup Sync que asumía display ON antes de iniciar sesión.
- Se eliminan las Scheduled Tasks privilegiadas de Boot/Shutdown; sólo queda `Lamp Agent` al logon.
- La automatización continúa instalándose deshabilitada hasta que `doctor` pase correctamente.
- El instalador exige un smoke test real `service-status` del servicio/ACL/Named Pipe antes de finalizar.
- Configuración v3 rechaza claves desconocidas y el migrador convierte/elimina campos operativos legacy.
- Backups de migración con posible material sensible se guardan fuera del runtime y quedan ACL sólo para SYSTEM/Administradores; se limpian artefactos legacy conocidos.

## [2.1.0] - 2026-09-28

### Added

- Estructura preparada para repositorio público de GitHub.
- `config.example.json` y exclusión de `config.json` del control de versiones.
- GitHub Actions, Dependabot, plantillas, documentación y empaquetado de releases.

### Changed

- Instalador preserva configuración local y `import-token.ps1` deja de tener datos de una instalación concreta.

## [2.0.0] - 2026-09-28

### Added

- Agente único para Display/Resume/Suspend y sincronización periódica.
- Locks, escrituras atómicas, reconciliación física, discovery limitado, DPAPI y logging rotativo.
