param(
    [string]$InstallDir = "C:\ProgramData\MijiaLamp",
    [switch]$TurnOffLamp
)
$ErrorActionPreference = "Stop"

function Assert-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Ejecutá este script desde PowerShell como Administrador."
    }
}

Assert-Administrator
$Python = Join-Path $InstallDir "runtime\python.exe"
$Cli = Join-Path $InstallDir "lampctl.py"
if (!(Test-Path $Python)) { throw "No existe el runtime protegido del servicio." }
if (!(Test-Path $Cli)) { throw "No existe lampctl.py en $InstallDir." }

if ($TurnOffLamp) {
    & $Python $Cli manual-off
    if ($LASTEXITCODE -ne 0) { throw "No pude apagar la lámpara; no continué con disable." }
}
& $Python $Cli disable
if ($LASTEXITCODE -ne 0) { throw "El servicio rechazó disable." }
try { Stop-ScheduledTask -TaskPath "\MijiaLamp\" -TaskName "Lamp Agent" -ErrorAction SilentlyContinue } catch {}
Disable-ScheduledTask -TaskPath "\MijiaLamp\" -TaskName "Lamp Agent" -ErrorAction Stop | Out-Null
Write-Host "Automatización automática deshabilitada. El servicio queda disponible para control manual." -ForegroundColor Yellow
