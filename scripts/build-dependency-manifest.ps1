param([string]$OutputDir = "")
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
if ($OutputDir -eq "") { $OutputDir = Join-Path $Root "release\dependencies" }
$Wheelhouse = Join-Path $Root "prepared-runtime\wheelhouse"
$PreparedManifest = Join-Path $Root "prepared-runtime\manifest.json"
if (!(Test-Path -LiteralPath $PreparedManifest -PathType Leaf) -or !(Test-Path -LiteralPath $Wheelhouse -PathType Container)) {
    throw "Prepará primero el runtime Service; el manifest de dependencias debe describir los wheels realmente usados."
}

$manifest = Get-Content -LiteralPath $PreparedManifest -Raw | ConvertFrom-Json
if ([string]$manifest.project_version -ne "3.1.3") { throw "Versión de prepared-runtime inesperada" }
$expected = @{}
foreach ($entry in $manifest.wheelhouse_files) {
    $relative = [string]$entry.path
    if (-not $relative -or $relative.Contains("..") -or [IO.Path]::IsPathRooted($relative)) {
        throw "Ruta insegura en wheelhouse manifest: $relative"
    }
    $path = Join-Path $Wheelhouse ($relative.Replace('/', '\'))
    if (!(Test-Path -LiteralPath $path -PathType Leaf)) { throw "Wheel ausente: $relative" }
    $item = Get-Item -LiteralPath $path -Force
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw "Wheel no puede ser reparse point: $relative" }
    $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash.ToLowerInvariant()
    if ($item.Length -ne [long]$entry.size -or $hash -ne ([string]$entry.sha256).ToLowerInvariant()) {
        throw "Wheel cambió después de preparar runtime: $relative"
    }
    $expected[$relative.ToLowerInvariant()] = "$hash  $relative"
}
$base = (Resolve-Path -LiteralPath $Wheelhouse).Path
$actual = @(Get-ChildItem -LiteralPath $Wheelhouse -File -Recurse | ForEach-Object {
    $_.FullName.Substring($base.Length).TrimStart('\','/').Replace('\','/').ToLowerInvariant()
})
if ($actual.Count -ne $expected.Count) { throw "Wheelhouse contiene archivos extra o faltantes" }
foreach ($relative in $actual) {
    if (-not $expected.ContainsKey($relative)) { throw "Wheel no manifestado: $relative" }
}

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
$OutputManifest = Join-Path $OutputDir "dependency-sha256.txt"
$expected.Keys | Sort-Object | ForEach-Object { $expected[$_] } | Set-Content -Encoding ascii $OutputManifest
Write-Host "Dependency manifest: $OutputManifest"
