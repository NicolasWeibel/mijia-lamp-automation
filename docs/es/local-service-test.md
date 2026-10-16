# Probar Service desde el código local, sin PR

[English](../local-service-test.md) | [Español](local-service-test.md)


Este procedimiento instala la copia local en `C:\ProgramData\MijiaLamp`. No sube código a GitHub ni requiere commit. Las pruebas unitarias y el empaquetado no demuestran por sí solos que la pantalla de login en Session 0 genere los eventos esperados; eso se verifica al reiniciar.

## 1. Preparar una configuración separada

En PowerShell 7 normal, desde la raíz del repositorio:

```powershell
$cfg = Get-Content ..\MijiaLamp-Portable-Dev\config.json -Raw | ConvertFrom-Json
if ($cfg.PSObject.Properties.Name -contains 'token') { throw 'No copies un token en texto plano' }
$cfg | Add-Member -NotePropertyName service_prelogin_display -NotePropertyValue $true -Force
$cfg | Add-Member -NotePropertyName off_on_session_lock -NotePropertyValue $false -Force
$cfg | Add-Member -NotePropertyName respect_user_presence -NotePropertyValue $false -Force
$cfg | ConvertTo-Json -Depth 20 | Set-Content ..\MijiaLamp-Service-Test-config.json -Encoding utf8
```

El archivo queda fuera del repositorio y no incluye el token DPAPI del Portable. Service importa su propio token con alcance LocalMachine después de instalarse.

## 2. Verificar y preparar el código local

Todavía en PowerShell normal:

```powershell
& ..\MijiaLamp-Portable-Dev\runtime\python.exe -m unittest discover -s tests -q
& ..\MijiaLamp-Portable-Dev\runtime\python.exe -c "from pathlib import Path; from mijialamp.config import load_config; load_config(Path('../MijiaLamp-Service-Test-config.json')); print('config OK')"
.\prepare-service-runtime.ps1 -Recreate
```

La primera preparación descarga wheels con hashes fijados y crea `prepared-runtime` sin privilegios de Administrador. Puede tardar y ocupar espacio. Después de cada cambio de código, si el runtime ya existe, basta con actualizar el manifiesto del source sin reconstruir Python:

```powershell
.\prepare-service-runtime.ps1 -RefreshSourceOnly
```

El instalador vuelve a verificar todos los hashes antes de copiar y ejecutar los archivos elevados. No modifiques archivos del repositorio después de preparar o refrescar el manifiesto; si lo hacés, repetí `-RefreshSourceOnly`.

## 3. Detener Portable

Cerrá `MijiaLamp-Portable-Dev` desde su icono de bandeja. Comprobá que no quede su proceso:

```powershell
Get-Process pythonw -ErrorAction SilentlyContinue | Where-Object {
    $_.Path -like '*\MijiaLamp-Portable-Dev\runtime\pythonw.exe'
} | Select-Object Id, Path
```

La consulta debe quedar vacía. Si tenés el inicio automático del Portable activado, ejecutá `..\MijiaLamp-Portable-Dev\disable-portable-autostart.ps1` antes de reiniciar. No mantengas Portable y Service controlando la misma lámpara.

## 4. Instalar Service

Abrí **PowerShell como Administrador**, entrá en la raíz del repositorio y ejecutá:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\install.ps1 -ConfigPath ..\MijiaLamp-Service-Test-config.json
```

No uses `-EnableAutomation` en la primera instalación de prueba. La instalación conserva una copia de seguridad de una instalación previa y deja la automatización deshabilitada. La fase elevada no descarga paquetes.

## 5. Importar el token y comprobar control manual

En la misma PowerShell elevada:

```powershell
cd C:\ProgramData\MijiaLamp
.\import-token.ps1 -Mode Service
& .\runtime\python.exe .\lampctl.py service-status
& .\runtime\python.exe .\lampctl.py doctor
.\security-check.ps1
```

Si no encuentra `mi-tokens.json`, repetí la importación con `-Source` apuntando al archivo de `mihome-ctl`. El token no se muestra. `doctor` debe confirmar modelo, DID, IP y estado físico.

## 6. Activar y probar

En PowerShell elevada:

```powershell
.\enable-automation.ps1
& .\runtime\python.exe .\lampctl.py status
```

Para la prueba automática, `automation_enabled` debe ser `true`, `manual_off_active` debe ser `false` y `last_error` debe ser `null`. De noche, verificá esta secuencia:

1. Con la sesión iniciada y pantalla encendida, la lámpara sigue el perfil nocturno.
2. Bloqueá con `Win+L`: debe permanecer encendida mientras la pantalla siga encendida y apagarse cuando Windows apague la pantalla.
3. Mové el mouse: al volver la pantalla, debe encenderse sin desbloquear.
4. Reiniciá. **Antes de iniciar sesión**, esperá a que Windows tenga red local: con la pantalla de login visible la lámpara debe encenderse; cuando la pantalla se apague, también debe apagarse la lámpara. Después de iniciar sesión, comprobá `status` y `C:\ProgramData\MijiaLamp\logs\service.log` (eventos `Console display: on/off`).

El primer encendido puede retrasarse hasta que la red y la lámpara respondan. Si no aparece ningún evento de consola antes del login, esa función todavía no está verificada para Session 0 en esta PC; dejá `service_prelogin_display` desactivado y conservá los logs para investigar.

## 7. Repetir o volver a Portable

Para probar otro cambio local, repetí pruebas, `-RefreshSourceOnly` y `install.ps1 -ConfigPath ...`; el instalador reemplaza la instalación y la deja deshabilitada para que vuelvas a ejecutar `doctor` y `enable-automation.ps1`.

Para detener la automatización y apagar la lámpara, desde `C:\ProgramData\MijiaLamp` en PowerShell elevada:

```powershell
.\disable-automation.ps1 -TurnOffLamp
```

Para retirar Service y su tarea sin borrar configuración ni token cifrado:

```powershell
.\uninstall.ps1
```

Después podés volver a iniciar Portable desde su carpeta Dev. No borres manualmente `C:\ProgramData\MijiaLamp` ni sus copias de seguridad durante las pruebas.
