param([string]$InstallDir = "C:\ProgramData\MijiaLamp")
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
$service = Get-Service MijiaLampService -ErrorAction Stop
if ($service.Status -ne "Running") {
    Start-Service MijiaLampService
    $service.WaitForStatus([System.ServiceProcess.ServiceControllerStatus]::Running, [TimeSpan]::FromSeconds(10))
}
& $Python $Cli service-status
if ($LASTEXITCODE -ne 0) { throw (T 'msg_c5f5d85ea624') }
& $Python $Cli doctor
if ($LASTEXITCODE -ne 0) { throw (T 'msg_90702cb6227b') }
& $Python $Cli enable
if ($LASTEXITCODE -ne 0) { throw (T 'msg_aa700a91ac71') }
$task = Get-ScheduledTask -TaskPath "\MijiaLamp\" -TaskName "Lamp Agent" -ErrorAction Stop
Enable-ScheduledTask -InputObject $task | Out-Null
Start-ScheduledTask -TaskPath "\MijiaLamp\" -TaskName "Lamp Agent"
Write-Host (T 'msg_46523be03208') -ForegroundColor Green
