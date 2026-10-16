param(
    [switch]$RecreateVenv,
    [switch]$Offline,
    [string]$ConfigPath = "",
    [switch]$GuiProgress
)
. (Join-Path $PSScriptRoot 'i18n.ps1')
. (Join-Path $PSScriptRoot 'version.ps1')
Initialize-MijiaLampLanguage -ConfigPath $ConfigPath
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
function Write-PortableProgress([int]$Percent, [string]$Stage) {
    if ($GuiProgress) { Write-Host "[MijiaLamp:progress:$Percent] $Stage" }
}

function Assert-NotElevated {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw (T 'msg_f001aa8ecfa0')
    }
}

function Get-PythonLauncher {
    if (Get-Command py.exe -ErrorAction SilentlyContinue) {
        foreach ($version in @("3.12", "3.11", "3.10")) {
            & py.exe "-$version" -c "import sys; print(sys.executable)" *> $null
            if ($LASTEXITCODE -eq 0) { return @("py.exe", "-$version") }
        }
    }
    if (Get-Command python.exe -ErrorAction SilentlyContinue) {
        & python.exe -c "import sys; assert (3,10) <= sys.version_info[:2] < (3,13)" *> $null
        if ($LASTEXITCODE -eq 0) { return @("python.exe") }
    }
    throw (T 'msg_09059d3602ce')
}

function Verify-BundledRuntime {
    param([string]$RuntimeDir, [string]$ManifestPath)
    if (!(Test-Path (Join-Path $RuntimeDir "python.exe") -PathType Leaf)) { return $false }
    if (!(Test-Path $ManifestPath -PathType Leaf)) {
        throw (T 'msg_4155acb5cfbc')
    }
    $manifest = Get-Content $ManifestPath -Raw | ConvertFrom-Json
    $items = @(Get-Item -LiteralPath $RuntimeDir -Force) + @(Get-ChildItem -LiteralPath $RuntimeDir -Recurse -Force)
    if (@($items | Where-Object { ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 }).Count) {
        throw (T 'msg_08b521112374')
    }
    if ([string]$manifest.project_version -ne (Get-MijiaLampVersion)) {
        throw (T 'msg_9e51b78b3843' -Arguments @(($manifest.project_version)))
    }
    $expected = @{}
    foreach ($entry in $manifest.runtime_files) {
        $rel = [string]$entry.path
        if (-not $rel -or $rel.Contains("..") -or [IO.Path]::IsPathRooted($rel)) {
            throw (T 'msg_f43f3708551b' -Arguments @(($rel)))
        }
        $full = Join-Path $RuntimeDir ($rel.Replace('/', '\'))
        if (!(Test-Path -LiteralPath $full -PathType Leaf)) { throw (T 'msg_23a9acd27bfa' -Arguments @(($rel))) }
        $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $full).Hash.ToLowerInvariant()
        if ($hash -ne ([string]$entry.sha256).ToLowerInvariant()) { throw (T 'msg_82d8d73eacae' -Arguments @(($rel))) }
        $expected[$rel.ToLowerInvariant()] = $true
    }
    $base = (Resolve-Path $RuntimeDir).Path
    $actual = @($items | Where-Object { -not $_.PSIsContainer } | ForEach-Object {
        $relative = $_.FullName.Substring($base.Length).TrimStart('\','/').Replace('\','/').ToLowerInvariant()
        if (-not $expected.ContainsKey($relative) -and $relative -match '(^|/)__pycache__/.*\.(pyc|pyo)$') {
            Remove-Item -LiteralPath $_.FullName -Force
        } else { $relative }
    })
    if ($actual.Count -ne $expected.Count) { throw (T 'msg_643074309fe1') }
    foreach ($rel in $actual) {
        if (-not $expected.ContainsKey($rel)) { throw (T 'msg_17ce110cdecf' -Arguments @(($rel))) }
    }
    return $true
}

function Copy-PreparedPortableRuntime {
    param([string]$PreparedDir, [string]$RuntimeDir, [string]$ManifestPath)
    if (Test-Path -LiteralPath $RuntimeDir) {
        throw (T 'msg_a43d4c4972c1')
    }
    $preparedManifest = Join-Path $PreparedDir 'manifest.json'
    if (-not (Verify-BundledRuntime -RuntimeDir (Join-Path $PreparedDir 'python') -ManifestPath $preparedManifest)) {
        throw (T 'msg_57f19e29a34d')
    }
    $stage = Join-Path $Root ('.mijialamp-runtime-' + [Guid]::NewGuid().ToString('N'))
    $stagePath = [IO.Path]::GetFullPath($stage)
    $rootPath = [IO.Path]::GetFullPath($Root).TrimEnd('\')
    if (-not $stagePath.StartsWith($rootPath + '\.mijialamp-runtime-', [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Ruta temporal de copia insegura.'
    }
    try {
        New-Item -ItemType Directory -Path $stage -ErrorAction Stop | Out-Null
        Write-PortableProgress 15 (T 'msg_f9be5df62f1d')
        Copy-Item -LiteralPath (Join-Path $PreparedDir 'python') -Destination $stage -Recurse -ErrorAction Stop
        $stageRuntime = Join-Path $stage 'python'
        if (-not (Verify-BundledRuntime -RuntimeDir $stageRuntime -ManifestPath $preparedManifest)) {
            throw (T 'msg_936955c66c43')
        }
        # Publish the manifest first: if it fails, no runtime is left behind.
        # The prepared tree remains intact so the next attempt can start fresh.
        Copy-Item -LiteralPath $preparedManifest -Destination $ManifestPath -Force -ErrorAction Stop
        Move-Item -LiteralPath $stageRuntime -Destination $RuntimeDir -ErrorAction Stop
    } finally {
        if (Test-Path -LiteralPath $stagePath) { Remove-Item -LiteralPath $stagePath -Recurse -Force }
    }
}

Assert-NotElevated
Write-PortableProgress 0 (T 'msg_37fb7c601fd1')
Write-Host "== MijiaLamp Portable setup ==" -ForegroundColor Cyan
Write-Host "Carpeta: $Root"

$Config = Join-Path $Root "config.json"
if ($ConfigPath) {
    $resolvedConfig = (Resolve-Path -LiteralPath $ConfigPath).Path
    if ($resolvedConfig -ne $Config) { Copy-Item -LiteralPath $resolvedConfig -Destination $Config -Force }
    Write-Host (T 'msg_7eef31f99e25' -Arguments @(($resolvedConfig))) -ForegroundColor Green
} elseif (!(Test-Path $Config)) {
    Copy-Item -Force (Join-Path $Root "config.example.json") $Config
    Write-Host (T 'msg_88d2c268baca') -ForegroundColor Yellow
}
foreach ($dir in @("data", "logs", "secrets")) {
    New-Item -ItemType Directory -Force -Path (Join-Path $Root $dir) | Out-Null
}

$BundledRuntime = Join-Path $Root "runtime"
$BundledManifest = Join-Path $Root "runtime-manifest.json"
if (-not (Test-Path -LiteralPath (Join-Path $BundledRuntime 'python.exe')) -and
    (Test-Path -LiteralPath (Join-Path $Root 'prepared-runtime\manifest.json'))) {
    Copy-PreparedPortableRuntime -PreparedDir (Join-Path $Root 'prepared-runtime') -RuntimeDir $BundledRuntime -ManifestPath $BundledManifest
}
Write-PortableProgress 20 (T 'msg_eb4fce01cdeb')
if (Verify-BundledRuntime -RuntimeDir $BundledRuntime -ManifestPath $BundledManifest) {
    Write-PortableProgress 65 (T 'msg_ce3874d4d91f')
    $Python = Join-Path $BundledRuntime "python.exe"
    & $Python -c "import miio, win32api, pystray, PIL, astral, cryptography, mijialamp; print('portable-runtime: OK')"
    if ($LASTEXITCODE -ne 0) { throw (T 'msg_38d7c722ab97') }
    Write-PortableProgress 85 (T 'msg_8e2f6c6415b9')
    & $Python .\tools\migrate_legacy_config.py --scope current-user $Config
    if ($LASTEXITCODE -ne 0) { throw (T 'msg_0a6792d046b9') }
    & $Python .\lampctl.py --mode portable config-check
    if ($LASTEXITCODE -ne 0) { Write-Host (T 'msg_6a38fd4abfbb') -ForegroundColor Yellow }
    Write-Host (T 'msg_7172c875369f') -ForegroundColor Green
    Write-Host (T 'msg_5d402dededce')
    Write-PortableProgress 100 (T 'msg_3a43dce83c32')
    exit 0
}

$Venv = Join-Path $Root ".venv"
if ($RecreateVenv -and (Test-Path $Venv)) { Remove-Item -Recurse -Force $Venv }
if (!(Test-Path $Venv)) {
    $launcher = Get-PythonLauncher
    if ($launcher.Count -eq 2) { & $launcher[0] $launcher[1] -m venv $Venv }
    else { & $launcher[0] -m venv $Venv }
    if ($LASTEXITCODE -ne 0) { throw (T 'msg_54167d5ee015') }
}

$Python = Join-Path $Venv "Scripts\python.exe"
$Architecture = (& $Python -c "import platform; print(platform.machine())").Trim()
if ($LASTEXITCODE -ne 0) { throw (T 'msg_abb19a593106') }
if ($Architecture -ne "AMD64") {
    throw (T 'msg_075aa842000d' -Arguments @(($Architecture)))
}
$Wheelhouse = Join-Path $Root "wheelhouse"
$PipCommon = @("-m", "pip", "install", "--disable-pip-version-check", "--require-hashes", "--only-binary=:all:", "--force-reinstall")
if ($Offline) {
    if (!(Test-Path $Wheelhouse)) { throw (T 'msg_65f293ce7aad') }
    $PipCommon += @("--no-index", "--find-links", $Wheelhouse)
}

& $Python @PipCommon -r (Join-Path $Root "requirements.lock.txt") -r (Join-Path $Root "requirements.windows.lock.txt")
if ($LASTEXITCODE -ne 0) { throw "Fallaron dependencias base/Windows" }
& $Python @PipCommon --no-deps -r (Join-Path $Root "requirements.miio.lock.txt")
if ($LASTEXITCODE -ne 0) { throw (T 'msg_848d6de6daee') }
Push-Location $Root
try {
    & $Python -m compileall -q .\mijialamp .\tools .\agent.py .\portable.py .\lampctl.py .\sleepnow.py
    if ($LASTEXITCODE -ne 0) { throw (T 'msg_4daddb8156bb') }
    & $Python -c "import miio, win32api, pystray, PIL, astral, cryptography, mijialamp; print('portable-smoke: OK')"
    if ($LASTEXITCODE -ne 0) { throw (T 'msg_003dc0a0e585') }
    & $Python .\tools\migrate_legacy_config.py --scope current-user $Config
    if ($LASTEXITCODE -ne 0) { throw (T 'msg_0a6792d046b9') }
    & $Python .\lampctl.py --mode portable config-check
    if ($LASTEXITCODE -ne 0) { Write-Host (T 'msg_6a38fd4abfbb') -ForegroundColor Yellow }
} finally { Pop-Location }

Write-Host (T 'msg_7b54974db205') -ForegroundColor Green
Write-PortableProgress 100 (T 'msg_3a43dce83c32')
Write-Host (T 'msg_5d402dededce')
