# Troubleshooting

[English](troubleshooting.md) | [Español](es/troubleshooting.md)


## Identify the mode first

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

Service (Administrator):

```powershell
.\import-token.ps1 -Mode Service
```

If `token-status` shows a scope different from the selected mode, do not copy the blob manually between installations; import it again using the correct mode.

## Doctor

Portable:

```powershell
& ".\runtime\python.exe" .\lampctl.py --mode portable doctor
```

Service:

```powershell
& ".\runtime\python.exe" .\lampctl.py doctor
```

## Service installation fails

Before opening PowerShell as Administrator, the Service release must contain:

```text
prepared-runtime\manifest.json
prepared-runtime\python\python.exe
```

If they are missing:

```powershell
# Standard PowerShell
.\prepare-service-runtime.ps1 -Recreate
```

Then close that console and open another as Administrator to run `install.ps1`.

## Security check fails

Run:

```powershell
.\security-check.ps1
```

Do not fix ACLs by granting FullControl to the user. Save the output and inspect `logs\service.log`.

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

Logs redact strings that look like miIO tokens, but review them before publishing anyway.

> If you are working from a clone without the packaged Portable runtime, use `.venv\Scripts\python.exe` in Portable commands.
