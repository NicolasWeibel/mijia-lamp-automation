# Seguridad v3.1

## Objetivos

1. Evitar secretos plaintext.
2. Evitar que código modificable por el usuario sea ejecutado por un servicio.
3. Evitar red/gestores de paquetes durante la fase elevada.
4. Limitar comunicación IPC a la máquina y usuario esperado.
5. Mantener una opción Portable que no requiera privilegios.

## Portable

El token se cifra con DPAPI `CurrentUser`. `portable.py`, controller y miIO viven en la misma sesión de usuario. El Pipe Portable usa un nombre diferente al del servicio y DACL ligada al SID actual.

Portable no pretende sobrevivir al cierre de sesión ni ofrecer Preshutdown SCM. A cambio elimina la frontera de privilegios y no requiere instalación administrativa.

## Hardened Service

### Runtime privado

El servicio **no usa** un Python instalado en `%LOCALAPPDATA%` u otra ubicación modificable por el usuario. `prepare-service-runtime.ps1` copia la instalación base, descarta `Lib/site-packages` y `Scripts`, instala exclusivamente el conjunto fijado y prueba la reubicación.

La preparación local de dependencias acepta sólo wheels binarios, para evitar ejecutar builds de paquetes fuente. Los 30 paquetes están fijados por versión y los locks incluyen hashes SHA-256 de los wheels para Windows x64 y Python 3.10–3.12. `pip --require-hashes` comprueba esos hashes tanto al descargarlos como al instalarlos sin conexión. Un wheel con bytes distintos se rechaza; al actualizar una dependencia hay que revisar el nuevo wheel y actualizar su hash de forma explícita.

Este control verifica que se instalen los bytes aprobados en el repositorio; no demuestra que esos bytes estén libres de malware ni protege frente a cambios maliciosos en el propio repositorio, Python base o el equipo de build. Otras arquitecturas no están cubiertas por estos hashes en la preparación local.

El runtime resultante se hash-ea archivo por archivo. El instalador Admin verifica que:

- no falten archivos;
- no haya archivos adicionales no manifestados;
- cada SHA-256 coincida;
- no existan reparse points en los artefactos preparados;
- los mismos hashes vuelvan a coincidir **después de copiarlos al staging**, cerrando la ventana TOCTOU entre verificación y copia.

Tras instalar, `integrity-manifest.json` registra los archivos inmutables y `security-check.ps1` vuelve a verificar sus hashes.

El directorio de staging nace con una ACL protegida que permite acceso sólo a Administradores y SYSTEM. El instalador verifica propietario y ACE antes de ejecutar el Python preparado, rechaza directorios anteriores con reparse points y detiene la instalación si `icacls` falla. El destino de backups se valida antes de detener el servicio anterior.

El instalador exige que `install.ps1` esté incluido en el manifiesto de source y, después de copiar, rechaza cualquier archivo de código o script en staging que no figure en ese manifiesto. La prueba de CI incluye un script de raíz agregado a último momento para comprobar el rechazo.

El modo Service sólo acepta la carpeta oficial `ProgramData\MijiaLamp`. Instalar bajo una carpeta cuyo padre pueda modificar el usuario rompería el aislamiento del staging; la desinstalación limita la ruta por el mismo motivo y para evitar borrados accidentales al usar `-DeleteFiles`.

Si la instalación falla después de detener la versión anterior, el rollback conserva sus archivos sin ejecutar su Python ni `service.py` como Administrador. No reinicia el Service ni el Agent: hay que comprobar su estado, revisar los archivos y repetir la instalación desde una release verificada. `uninstall.ps1` elimina el servicio mediante el administrador de servicios de Windows y tampoco ejecuta el runtime instalado con privilegios elevados.

Luego se copia a `C:\ProgramData\MijiaLamp\runtime`, donde el usuario sólo recibe `Read & Execute`.

### Elevación sin package manager

`install.ps1` no contiene `pip install`, `pip download`, `Invoke-WebRequest` ni `Invoke-RestMethod`. Toda resolución/instalación de paquetes sucede antes de elevar.

### Servicio

- cuenta: `NT AUTHORITY\LocalService`;
- Service SID habilitado;
- `RequiredPrivileges`: `SeChangeNotifyPrivilege`;
- reinicios SCM acotados;
- Preshutdown configurado;
- sin listener TCP/HTTP.

### ACLs

- raíz/código/runtime: usuario `RX`, Service SID `RX`;
- `config.json`: usuario `Modify`, servicio `Read`;
- `data/`: servicio `Modify`, usuario `Read`;
- `logs/`: ambos `Modify`;
- `secrets/`: Service SID/SYSTEM/Administradores únicamente.

`security-check.ps1` vuelve a auditar estas invariantes después del install.

## DPAPI

Los blobs incluyen metadata de scope:

- `current-user` para Portable;
- `local-machine` para Service;
- blobs v2 con `dpapi-local-machine-service-owned` se normalizan como `local-machine`.

La entropía DPAPI histórica se mantiene para migrar secretos existentes sin imprimirlos.

## Named Pipes

- Service: `\\.\pipe\MijiaLamp-v3`
- Portable: `\\.\pipe\MijiaLamp-Portable-v3`

Ambos usan mensajes JSON acotados y `PIPE_REJECT_REMOTE_CLIENTS`. Service autoriza el SID seleccionado durante instalación **y el Service SID exacto de `MijiaLampService`**; no concede acceso genérico a toda la cuenta `LocalService`. Portable usa el SID del proceso actual.

## Carreras y OFF crítico

La seguridad funcional también importa: `intent_revision` cancela decisiones antiguas y `critical_off_revision` da prioridad a Suspend/Shutdown/Manual OFF. Resume incrementa la revisión sin inventar presencia, y los hints de Suspend tienen deadline para impedir OFF tardíos. Un sync que quedó esperando red no puede enviar un ON después de una intención más reciente.


## Provenance de releases

El hash manifest protege integridad entre preparación e instalación, pero no sustituye una identidad criptográfica del publicador. El workflow de publicación está configurado para generar en Windows ZIPs con SHA-256, SBOM y GitHub Artifact Attestations. Una vez publicado el repositorio, para el modo Service preferí esos artefactos ya preparados frente a construir el runtime localmente. Sin Authenticode, un administrador debe verificar la procedencia del ZIP antes de elevar.

Procedimiento para una release oficial ya publicada:

1. Descargá el ZIP Service desde la página Releases del repositorio que elegiste confiar. Conservá el ZIP sin modificar.
2. Verificá su procedencia con `gh attestation verify .\MijiaLamp-Service-VERSION.zip -R NicolasWeibel/mijia-lamp-automation`, reemplazando `VERSION` por la versión descargada. La verificación debe terminar correctamente antes de extraer o elevar permisos.
3. Extraé el ZIP y ejecutá `install.ps1` desde una PowerShell elevada. El instalador comprueba hashes del runtime y código fuente antes y después de copiar; no usa Internet ni `pip`.
4. Tras la instalación, ejecutá `security-check.ps1` y `lampctl.py doctor` antes de habilitar la automatización.

La attestation demuestra qué repositorio y workflow produjeron esos bytes; no prueba ausencia de malware en el código, las dependencias o el runner. Un build local usa el Python y los paquetes disponibles en tu equipo y ofrece menos garantías de procedencia. Un `.sha256` entregado junto al ZIP sólo sirve para integridad accidental si no está autenticado por otro canal.

Después de modificar el código, publicá una versión nueva. Una attestation de una versión anterior no autentica la copia modificada, aunque conserve el mismo nombre de carpeta.
