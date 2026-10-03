param([string]$InstallDir = [IO.Path]::Combine([Environment]::GetFolderPath("CommonApplicationData"), "MijiaLamp"), [switch]$DeleteFiles, [switch]$DeleteSecrets)
$ErrorActionPreference = "Stop"
$expected = Join-Path ([Environment]::GetFolderPath("CommonApplicationData")) "MijiaLamp"
if ([IO.Path]::GetFullPath($InstallDir).TrimEnd('\') -ine [IO.Path]::GetFullPath($expected).TrimEnd('\')) {
    throw "Por seguridad, Service sólo puede desinstalarse desde $expected."
}
if (Test-Path -LiteralPath $InstallDir) {
    $installedItem = Get-Item -LiteralPath $InstallDir -Force
    if (-not $installedItem.PSIsContainer -or ($installedItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "La carpeta de instalación no es un directorio normal: $InstallDir"
    }
}
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw "Ejecutá PowerShell como Administrador." }
$task = Get-ScheduledTask -TaskPath "\MijiaLamp\" -TaskName "Lamp Agent" -ErrorAction SilentlyContinue
if ($task) {
    if ($task.State -eq "Running") {
        Stop-ScheduledTask -TaskPath "\MijiaLamp\" -TaskName "Lamp Agent" -ErrorAction Stop
    }
    Unregister-ScheduledTask -TaskPath "\MijiaLamp\" -TaskName "Lamp Agent" -Confirm:$false -ErrorAction Stop
}
$service = Get-Service -Name MijiaLampService -ErrorAction SilentlyContinue
if ($service) {
    & sc.exe config MijiaLampService start= disabled | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "No se pudo deshabilitar MijiaLampService" }
    if ($service.Status -ne [ServiceProcess.ServiceControllerStatus]::Stopped) {
        Stop-Service -Name MijiaLampService -Force -ErrorAction Stop
        $service.WaitForStatus([ServiceProcess.ServiceControllerStatus]::Stopped, [TimeSpan]::FromSeconds(15))
    }
    & sc.exe delete MijiaLampService | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "No se pudo eliminar MijiaLampService" }
}
if ($DeleteSecrets) { Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $InstallDir "secrets\token.dpapi.json") }
if ($DeleteFiles) { Remove-Item -Recurse -Force $InstallDir }
Write-Host "MijiaLampService y Lamp Agent eliminados."
