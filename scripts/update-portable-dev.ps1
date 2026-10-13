param(
    [string]$DevDir = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Workspace = Split-Path -Parent $Root
if (-not $DevDir) { $DevDir = Join-Path $Workspace "MijiaLamp-Portable-Dev" }
$DevDir = (Resolve-Path -LiteralPath $DevDir).Path
$Workspace = (Resolve-Path -LiteralPath $Workspace).Path
if (-not $DevDir.StartsWith($Workspace + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw "The Dev folder must be inside the workspace: $Workspace"
}
foreach ($required in @("runtime\python.exe", "runtime-manifest.json", "config.json", "secrets\token.dpapi.json")) {
    if (-not (Test-Path -LiteralPath (Join-Path $DevDir $required) -PathType Leaf)) {
        throw "Missing $required in $DevDir; prepare the Dev copy before updating it."
    }
}
$DevPythonw = Join-Path $DevDir "runtime\pythonw.exe"
$running = @(Get-Process pythonw -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $DevPythonw })
if ($running.Count -gt 0) { throw "Close MijiaLamp Portable Dev from its tray icon before updating it." }

$BuildDir = Join-Path $Root "release\dev"
& (Join-Path $Root "scripts\build-release.ps1") -Mode Portable -OutputDir $BuildDir
$Zip = Get-ChildItem -LiteralPath $BuildDir -File -Filter "MijiaLamp-Portable-*.zip" |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $Zip) { throw "The local Portable ZIP was not created." }
$Expanded = Join-Path $BuildDir "expanded"
Expand-Archive -LiteralPath $Zip.FullName -DestinationPath $Expanded -Force
$Package = Join-Path $Expanded $Zip.BaseName
if (-not (Test-Path -LiteralPath (Join-Path $Package "portable.py") -PathType Leaf)) {
    throw "The local Portable ZIP does not contain portable.py."
}

# The local build contains only public source. Keep runtime, config, token, and state
# in Dev while refreshing all source files used by Portable.
foreach ($item in Get-ChildItem -LiteralPath $Package) {
    $destination = Join-Path $DevDir $item.Name
    if ($item.PSIsContainer) {
        New-Item -ItemType Directory -Force -Path $destination | Out-Null
        Copy-Item -Path (Join-Path $item.FullName '*') -Destination $destination -Recurse -Force
    } else {
        Copy-Item -LiteralPath $item.FullName -Destination $destination -Force
    }
}
Write-Host "Portable Dev updated from local source: $DevDir" -ForegroundColor Green
