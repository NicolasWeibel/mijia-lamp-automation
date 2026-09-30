# Troubleshooting

## Primero identificá el modo

### Portable

```powershell
& ".\runtime\python.exe" .\lampctl.py --mode portable runtime-status
```

### Service

```powershell
& ".\runtime\python.exe" .\lampctl.py service-status
Get-Service MijiaLampService
```

## Token

Portable:

```powershell
.\import-token.ps1 -Mode Portable
```

Service (Administrador):

```powershell
.\import-token.ps1 -Mode Service
```

Si `token-status` muestra un scope distinto al modo elegido, no copies el blob manualmente entre instalaciones: volvé a importarlo con el modo correcto.

## Doctor

Portable:

```powershell
& ".\runtime\python.exe" .\lampctl.py --mode portable doctor
```

Service:

```powershell
& ".\runtime\python.exe" .\lampctl.py doctor
```

## Service no instala

Antes de abrir PowerShell como Administrador, la release Service debe contener:

```text
prepared-runtime\manifest.json
prepared-runtime\python\python.exe
```

Si no están:

```powershell
# PowerShell normal
.\prepare-service-runtime.ps1 -Recreate
```

Después cerrá esa consola y abrí otra como Administrador para `install.ps1`.

## Security check falla

Ejecutá:

```powershell
.\security-check.ps1
```

No corrijas ACLs otorgando FullControl al usuario. Guardá la salida y revisá `logs\service.log`.

## Logs

Portable:

```text
logs\portable.log
```

Service:

```text
C:\ProgramData\MijiaLamp\logs\service.log
C:\ProgramData\MijiaLamp\logs\agent.log
```

Los logs redactan strings con forma de token miIO, pero igualmente conviene revisarlos antes de publicarlos.


> Si estás trabajando desde un clon sin runtime Portable empaquetado, usá `.venv\Scripts\python.exe` en los comandos Portable.
