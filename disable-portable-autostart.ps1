$ErrorActionPreference = "Stop"
$Startup = [Environment]::GetFolderPath("Startup")
$Link = Join-Path $Startup "MijiaLamp Portable.lnk"
Remove-Item -Force -ErrorAction SilentlyContinue $Link
Write-Host "Autostart Portable deshabilitado." -ForegroundColor Yellow
