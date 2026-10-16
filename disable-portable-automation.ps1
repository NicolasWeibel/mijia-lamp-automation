param([switch]$TurnOffLamp)
. (Join-Path $PSScriptRoot 'i18n.ps1')
Initialize-MijiaLampLanguage -ConfigPath $ConfigPath
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root "runtime\python.exe"
if (!(Test-Path $Python)) { $Python = Join-Path $Root ".venv\Scripts\python.exe" }
$Cli = Join-Path $Root "lampctl.py"
Write-Host (T 'msg_9786c3b6d35a')
$ready = $false
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    & $Python $Cli --mode portable runtime-status *> $null
    if ($LASTEXITCODE -eq 0) { $ready = $true; break }
    Start-Sleep -Milliseconds 400
}
if (-not $ready) { throw (T 'msg_2019fd8b0821') }
if ($TurnOffLamp) {
    & $Python $Cli --mode portable manual-off
    if ($LASTEXITCODE -ne 0) { throw (T 'msg_f518bb973477') }
}
& $Python $Cli --mode portable disable
if ($LASTEXITCODE -ne 0) { throw (T 'msg_7f020570d0da') }
Write-Host (T 'msg_e5f1dde09431') -ForegroundColor Yellow
