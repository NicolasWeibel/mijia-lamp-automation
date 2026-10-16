param([string]$OutputDir = "")
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
. (Join-Path $Root 'version.ps1')
if ($OutputDir -eq "") { $OutputDir = Join-Path $Root "release\dependencies" }
$Wheelhouse = Join-Path $Root "prepared-runtime\wheelhouse"
$PreparedManifest = Join-Path $Root "prepared-runtime\manifest.json"
if (!(Test-Path -LiteralPath $PreparedManifest -PathType Leaf) -or !(Test-Path -LiteralPath $Wheelhouse -PathType Container)) {
    throw "Prepare the Service runtime first; the dependency manifest must describe the wheels actually used."
}

$manifest = Get-Content -LiteralPath $PreparedManifest -Raw | ConvertFrom-Json
if ([string]$manifest.project_version -ne (Get-MijiaLampVersion)) { throw "Unexpected prepared-runtime version" }
$expected = @{}
foreach ($entry in $manifest.wheelhouse_files) {
    $relative = [string]$entry.path
    if (-not $relative -or $relative.Contains("..") -or [IO.Path]::IsPathRooted($relative)) {
        throw "Unsafe path in wheelhouse manifest: $relative"
    }
    $path = Join-Path $Wheelhouse ($relative.Replace('/', '\'))
    if (!(Test-Path -LiteralPath $path -PathType Leaf)) { throw "Wheel is missing: $relative" }
    $item = Get-Item -LiteralPath $path -Force
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw "Wheel cannot be a reparse point: $relative" }
    $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash.ToLowerInvariant()
    if ($item.Length -ne [long]$entry.size -or $hash -ne ([string]$entry.sha256).ToLowerInvariant()) {
        throw "Wheel changed after runtime preparation: $relative"
    }
    $expected[$relative.ToLowerInvariant()] = "$hash  $relative"
}
$base = (Resolve-Path -LiteralPath $Wheelhouse).Path
$actual = @(Get-ChildItem -LiteralPath $Wheelhouse -File -Recurse | ForEach-Object {
    $_.FullName.Substring($base.Length).TrimStart('\','/').Replace('\','/').ToLowerInvariant()
})
if ($actual.Count -ne $expected.Count) { throw "Wheelhouse contains extra or missing files" }
foreach ($relative in $actual) {
    if (-not $expected.ContainsKey($relative)) { throw "Wheel is not manifested: $relative" }
}

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
$OutputManifest = Join-Path $OutputDir "dependency-sha256.txt"
$expected.Keys | Sort-Object | ForEach-Object { $expected[$_] } | Set-Content -Encoding ascii $OutputManifest
Write-Host "Dependency manifest: $OutputManifest"
