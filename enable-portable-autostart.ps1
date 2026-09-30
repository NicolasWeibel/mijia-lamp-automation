$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Target = Join-Path $Root "start-portable.cmd"
if (!(Test-Path $Target)) { throw "No existe start-portable.cmd" }
$Startup = [Environment]::GetFolderPath("Startup")
$Link = Join-Path $Startup "MijiaLamp Portable.lnk"
$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($Link)
$Shortcut.TargetPath = $Target
$Shortcut.WorkingDirectory = $Root
$Shortcut.Description = "MijiaLamp Portable"
$Shortcut.Save()
Write-Host "Autostart de usuario habilitado: $Link" -ForegroundColor Green
