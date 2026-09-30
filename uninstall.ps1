param([string]$InstallDir = "C:\ProgramData\MijiaLamp", [switch]$DeleteFiles, [switch]$DeleteSecrets)
$ErrorActionPreference = "Stop"
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw "Ejecutá PowerShell como Administrador." }
try { Stop-ScheduledTask -TaskPath "\MijiaLamp\" -TaskName "Lamp Agent" -ErrorAction SilentlyContinue } catch {}
try { Unregister-ScheduledTask -TaskPath "\MijiaLamp\" -TaskName "Lamp Agent" -Confirm:$false -ErrorAction SilentlyContinue } catch {}
try { Stop-Service MijiaLampService -Force -ErrorAction SilentlyContinue } catch {}
$Python = Join-Path $InstallDir "runtime\python.exe"
$ServiceScript = Join-Path $InstallDir "service.py"
if ((Test-Path $Python) -and (Test-Path $ServiceScript)) { & $Python $ServiceScript remove *> $null }
if ($DeleteSecrets) { Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $InstallDir "secrets\token.dpapi.json") }
if ($DeleteFiles) { Remove-Item -Recurse -Force $InstallDir }
Write-Host "MijiaLampService y Lamp Agent eliminados."
