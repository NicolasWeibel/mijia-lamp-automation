param(
    [string]$OutputDir = "",
    [ValidateSet("All", "Portable", "Service")]
    [string]$Mode = "All",
    [switch]$IncludePreparedRuntime
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
if ($OutputDir -eq "") { $OutputDir = Join-Path $Root "release" }
$VersionText = Get-Content (Join-Path $Root "mijialamp\__init__.py") -Raw
if ($VersionText -notmatch '__version__\s*=\s*"([^"]+)"') { throw "No pude determinar versión" }
$Version = $Matches[1]
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

$CommonFiles = @(
    "README.md", "CHANGELOG.md", "CONTRIBUTING.md", "SECURITY.md", "LICENSE",
    "pyproject.toml", "config.example.json", "config.schema.json",
    "requirements.lock.txt", "requirements.windows.lock.txt", "requirements.miio.lock.txt",
    "lampctl.py", "sleepnow.py", "import-token.ps1"
)
$CommonDirs = @("mijialamp", "tools", "docs")

function New-ReleaseZip {
    param([string]$Flavor)
    $Name = "MijiaLamp-$Flavor-$Version"
    $TempParent = Join-Path ([System.IO.Path]::GetTempPath()) ("mijialamp-release-" + [Guid]::NewGuid().ToString("N"))
    $Staging = Join-Path $TempParent $Name
    New-Item -ItemType Directory -Force -Path $Staging | Out-Null
    foreach ($file in $CommonFiles) { Copy-Item -Force (Join-Path $Root $file) (Join-Path $Staging $file) }
    foreach ($dir in $CommonDirs) { Copy-Item -Recurse -Force (Join-Path $Root $dir) (Join-Path $Staging $dir) }

    if ($Flavor -eq "Portable") {
        $files = @(
            "agent.py", "portable.py", "setup-portable.ps1", "start-portable.cmd",
            "portable-status.cmd", "portable-on.cmd", "portable-off.cmd", "portable-sleep-now.cmd",
            "enable-portable-autostart.ps1", "disable-portable-autostart.ps1",
            "enable-portable-automation.ps1", "disable-portable-automation.ps1"
        )
        foreach ($file in $files) { Copy-Item -Force (Join-Path $Root $file) (Join-Path $Staging $file) }
        if ($IncludePreparedRuntime) {
            $prepared = Join-Path $Root "prepared-runtime"
            if (!(Test-Path (Join-Path $prepared "manifest.json"))) { throw "-IncludePreparedRuntime requiere prepare-service-runtime.ps1" }
            Copy-Item -Recurse -Force (Join-Path $prepared "python") (Join-Path $Staging "runtime")
            Copy-Item -Force (Join-Path $prepared "manifest.json") (Join-Path $Staging "runtime-manifest.json")
        }
    } else {
        $files = @(
            "agent.py", "portable.py", "service.py", "install.ps1", "prepare-service-runtime.ps1", "security-check.ps1",
            "uninstall.ps1", "enable-automation.ps1", "disable-automation.ps1",
            "manual-on.cmd", "manual-off.cmd", "status.cmd", "sync.cmd", "sleep-now.cmd"
        )
        foreach ($file in $files) { Copy-Item -Force (Join-Path $Root $file) (Join-Path $Staging $file) }
        if ($IncludePreparedRuntime) {
            $prepared = Join-Path $Root "prepared-runtime"
            if (!(Test-Path (Join-Path $prepared "manifest.json"))) { throw "-IncludePreparedRuntime requiere prepare-service-runtime.ps1" }
            $dst = Join-Path $Staging "prepared-runtime"
            New-Item -ItemType Directory -Force -Path $dst | Out-Null
            Copy-Item -Recurse -Force (Join-Path $prepared "python") (Join-Path $dst "python")
            Copy-Item -Force (Join-Path $prepared "manifest.json") (Join-Path $dst "manifest.json")
        }
    }

    Get-ChildItem $Staging -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    Get-ChildItem $Staging -Recurse -File -Include "*.pyc", ".coverage" | Remove-Item -Force -ErrorAction SilentlyContinue
    $ZipPath = Join-Path $OutputDir "$Name.zip"
    $HashPath = "$ZipPath.sha256"
    Remove-Item -Force -ErrorAction SilentlyContinue $ZipPath, $HashPath
    Compress-Archive -Path $Staging -DestinationPath $ZipPath -CompressionLevel Optimal
    $Hash = (Get-FileHash -Algorithm SHA256 $ZipPath).Hash.ToLowerInvariant()
    "$Hash  $Name.zip" | Set-Content -Encoding ascii $HashPath
    Remove-Item -Recurse -Force $TempParent
    Write-Host "$Flavor release: $ZipPath"
    Write-Host "SHA256: $Hash"
}

if ($Mode -in @("All", "Portable")) { New-ReleaseZip -Flavor "Portable" }
if ($Mode -in @("All", "Service")) { New-ReleaseZip -Flavor "Service" }
