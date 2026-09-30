param([string]$InstallDir = "C:\ProgramData\MijiaLamp")
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
$service = Get-Service MijiaLampService -ErrorAction Stop
if ($service.Status -ne "Running") {
    Start-Service MijiaLampService
    $service.WaitForStatus([System.ServiceProcess.ServiceControllerStatus]::Running, [TimeSpan]::FromSeconds(10))
}
& $Python $Cli service-status
if ($LASTEXITCODE -ne 0) { throw "MijiaLampService no responde por IPC; no habilité automatización." }
& $Python $Cli doctor
if ($LASTEXITCODE -ne 0) { throw "Doctor falló; no habilité automatización." }
& $Python $Cli enable
if ($LASTEXITCODE -ne 0) { throw "El servicio rechazó enable." }
$task = Get-ScheduledTask -TaskPath "\MijiaLamp\" -TaskName "Lamp Agent" -ErrorAction Stop
Enable-ScheduledTask -InputObject $task | Out-Null
Start-ScheduledTask -TaskPath "\MijiaLamp\" -TaskName "Lamp Agent"
Write-Host "Automatización habilitada: servicio + agente interactivo." -ForegroundColor Green
