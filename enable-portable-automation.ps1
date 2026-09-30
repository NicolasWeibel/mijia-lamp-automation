$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root "runtime\python.exe"
if (!(Test-Path $Python)) { $Python = Join-Path $Root ".venv\Scripts\python.exe" }
$Cli = Join-Path $Root "lampctl.py"
& $Python $Cli --mode portable runtime-status
if ($LASTEXITCODE -ne 0) { throw "Portable no está ejecutándose. Abrí start-portable.cmd." }
& $Python $Cli --mode portable doctor
if ($LASTEXITCODE -ne 0) { throw "Doctor falló; no habilité automatización." }
& $Python $Cli --mode portable enable
if ($LASTEXITCODE -ne 0) { throw "Portable rechazó enable." }
Write-Host "Automatización Portable habilitada." -ForegroundColor Green
