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
& $Python $Cli --mode portable doctor
if ($LASTEXITCODE -ne 0) { throw (T 'msg_90702cb6227b') }
& $Python $Cli --mode portable enable
if ($LASTEXITCODE -ne 0) { throw (T 'msg_4cd969734b44') }
Write-Host (T 'msg_2f8b0f5b2222') -ForegroundColor Green
