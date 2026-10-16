. (Join-Path $PSScriptRoot 'i18n.ps1')
Initialize-MijiaLampLanguage -ConfigPath $ConfigPath
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Target = Join-Path $Root "start-portable.cmd"
if (!(Test-Path $Target)) { throw (T 'msg_66c575dce336') }
$Startup = [Environment]::GetFolderPath("Startup")
$Link = Join-Path $Startup "MijiaLamp Portable.lnk"
$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($Link)
$Shortcut.TargetPath = $Target
$Shortcut.WorkingDirectory = $Root
$Shortcut.Description = "MijiaLamp Portable"
$Shortcut.Save()
Write-Host (T 'msg_1b5f803a2228' -Arguments @(($Link))) -ForegroundColor Green
