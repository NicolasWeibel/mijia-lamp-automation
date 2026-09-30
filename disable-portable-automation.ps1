param([switch]$TurnOffLamp)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root "runtime\python.exe"
if (!(Test-Path $Python)) { $Python = Join-Path $Root ".venv\Scripts\python.exe" }
$Cli = Join-Path $Root "lampctl.py"
if ($TurnOffLamp) {
    & $Python $Cli --mode portable manual-off
    if ($LASTEXITCODE -ne 0) { throw "No pude apagar la lámpara." }
}
& $Python $Cli --mode portable disable
if ($LASTEXITCODE -ne 0) { throw "Portable rechazó disable." }
Write-Host "Automatización Portable deshabilitada." -ForegroundColor Yellow
