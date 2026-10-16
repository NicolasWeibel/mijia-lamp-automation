param(
    [string]$InstallDir = "C:\ProgramData\MijiaLamp",
    [switch]$TurnOffLamp
)
. (Join-Path $PSScriptRoot 'i18n.ps1')
Initialize-MijiaLampLanguage -ConfigPath $ConfigPath
$ErrorActionPreference = "Stop"

function Assert-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw (T 'msg_f682b62507ae')
    }
}

Assert-Administrator
$Python = Join-Path $InstallDir "runtime\python.exe"
$Cli = Join-Path $InstallDir "lampctl.py"
if (!(Test-Path $Python)) { throw (T 'msg_0bf175c97a65') }
if (!(Test-Path $Cli)) { throw (T 'msg_40a8cdf999ca' -Arguments @(($InstallDir))) }

if ($TurnOffLamp) {
    & $Python $Cli manual-off
    if ($LASTEXITCODE -ne 0) { throw (T 'msg_20c4e986950d') }
}
& $Python $Cli disable
if ($LASTEXITCODE -ne 0) { throw (T 'msg_a46dc9d5a019') }
try { Stop-ScheduledTask -TaskPath "\MijiaLamp\" -TaskName "Lamp Agent" -ErrorAction SilentlyContinue } catch {}
Disable-ScheduledTask -TaskPath "\MijiaLamp\" -TaskName "Lamp Agent" -ErrorAction Stop | Out-Null
Write-Host (T 'msg_2f7b93466a56') -ForegroundColor Yellow
