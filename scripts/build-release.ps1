param(
    [string]$OutputDir = "",
    [ValidateSet("All", "Portable", "Service", "Setup")]
    [string]$Mode = "All",
    [switch]$IncludePreparedRuntime
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
. (Join-Path $Root 'version.ps1')
if ($OutputDir -eq "") { $OutputDir = Join-Path $Root "release" }
$Version = Get-MijiaLampVersion
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

$CommonFiles = @(
    "README.md", "README.es.md", "CHANGELOG.md", "CHANGELOG.es.md", "CONTRIBUTING.md", "CONTRIBUTING.es.md", "SECURITY.md", "SECURITY.es.md", "LICENSE", "THIRD_PARTY_NOTICES.md",
    "pyproject.toml", "config.example.json", "config.schema.json",
    "requirements.lock.txt", "requirements.windows.lock.txt", "requirements.miio.lock.txt",
    "i18n.ps1", "version.ps1", "lampctl.py", "sleepnow.py", "import-token.ps1", "config-gui.ps1", "setup-gui.ps1", "setup-gui.cmd", "setup-gui.vbs", "onboarding-gui.ps1"
)
$CommonDirs = @("mijialamp", "tools", "docs")

function New-ReleaseZip {
    param([string]$Flavor)
    $Name = "MijiaLamp-$Flavor-$Version"
    $TempParent = Join-Path ([System.IO.Path]::GetTempPath()) ("mijialamp-release-" + [Guid]::NewGuid().ToString("N"))
    $Staging = Join-Path $TempParent $Name
    $tempBase = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\', '/')
    $tempTarget = [IO.Path]::GetFullPath($TempParent)
    if (-not $tempTarget.StartsWith($tempBase + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase) -or
        [IO.Path]::GetFileName($tempTarget) -notlike "mijialamp-release-*") {
        throw "Unsafe release temporary path: $tempTarget"
    }
    New-Item -ItemType Directory -Force -Path $Staging | Out-Null
    foreach ($file in $CommonFiles) { Copy-Item -Force (Join-Path $Root $file) (Join-Path $Staging $file) }
    foreach ($dir in $CommonDirs) { Copy-Item -Recurse -Force (Join-Path $Root $dir) (Join-Path $Staging $dir) }

    if ($Flavor -in @("Portable", "Setup")) {
        $files = @(
            "agent.py", "portable.py", "setup-portable.ps1", "start-portable.cmd",
            "portable-status.cmd", "portable-on.cmd", "portable-off.cmd", "portable-sleep-now.cmd",
            "enable-portable-autostart.ps1", "disable-portable-autostart.ps1",
            "enable-portable-automation.ps1", "disable-portable-automation.ps1"
        )
        foreach ($file in $files) { Copy-Item -Force (Join-Path $Root $file) (Join-Path $Staging $file) }
        if ($IncludePreparedRuntime -and $Flavor -eq "Portable") {
            $prepared = Join-Path $Root "prepared-runtime"
            if (!(Test-Path (Join-Path $prepared "manifest.json"))) { throw "-IncludePreparedRuntime requires prepare-service-runtime.ps1" }
            Copy-Item -Recurse -Force (Join-Path $prepared "python") (Join-Path $Staging "runtime")
            Copy-Item -Force (Join-Path $prepared "manifest.json") (Join-Path $Staging "runtime-manifest.json")
        }
    }
    if ($Flavor -in @("Service", "Setup")) {
        $files = @(
            "agent.py", "portable.py", "service.py", "install.ps1", "prepare-service-runtime.ps1", "security-check.ps1",
            "uninstall.ps1", "enable-automation.ps1", "disable-automation.ps1",
            "manual-on.cmd", "manual-off.cmd", "status.cmd", "sync.cmd", "sleep-now.cmd"
        )
        foreach ($file in $files) { Copy-Item -Force (Join-Path $Root $file) (Join-Path $Staging $file) }
        if ($IncludePreparedRuntime) {
            $prepared = Join-Path $Root "prepared-runtime"
            if (!(Test-Path (Join-Path $prepared "manifest.json"))) { throw "-IncludePreparedRuntime requires prepare-service-runtime.ps1" }
            $dst = Join-Path $Staging "prepared-runtime"
            New-Item -ItemType Directory -Force -Path $dst | Out-Null
            Copy-Item -Recurse -Force (Join-Path $prepared "python") (Join-Path $dst "python")
            Copy-Item -Force (Join-Path $prepared "manifest.json") (Join-Path $dst "manifest.json")
            if ($Flavor -eq "Service") {
                $manifestPath = Join-Path $dst "manifest.json"
                $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
                # Keep the recorded hashes, but omit Portable-only launchers that
                # are deliberately absent from this flavor.
                $manifest.source_files = @($manifest.source_files | Where-Object {
                    Test-Path -LiteralPath (Join-Path $Staging ([string]$_.path)) -PathType Leaf
                })
                $manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
            }
        }
    }

    $stageBase = (Resolve-Path -LiteralPath $Staging).Path.TrimEnd('\', '/')
    $stageItems = @(Get-ChildItem -LiteralPath $Staging -Recurse -Force)
    if (@($stageItems | Where-Object { ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 }).Count -gt 0) {
        throw "Release staging contains reparse points."
    }
    foreach ($cache in @($stageItems | Where-Object { $_.PSIsContainer -and $_.Name -eq "__pycache__" } | Sort-Object FullName -Descending)) {
        $cachePath = [IO.Path]::GetFullPath($cache.FullName)
        if (-not $cachePath.StartsWith($stageBase + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Cache is outside staging: $cachePath"
        }
        Remove-Item -LiteralPath $cachePath -Recurse -Force
    }
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
if ($Mode -in @("All", "Setup")) { New-ReleaseZip -Flavor "Setup" }
