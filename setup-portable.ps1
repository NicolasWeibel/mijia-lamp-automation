param(
    [switch]$RecreateVenv,
    [switch]$Offline,
    [string]$ConfigPath = ""
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path

function Assert-NotElevated {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "MijiaLamp Portable debe prepararse como usuario normal, no desde PowerShell elevado."
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
    throw "MijiaLamp requiere Python 3.10, 3.11 o 3.12 cuando la release no incluye runtime portable."
}

function Verify-BundledRuntime {
    param([string]$RuntimeDir, [string]$ManifestPath)
    if (!(Test-Path (Join-Path $RuntimeDir "python.exe") -PathType Leaf)) { return $false }
    if (!(Test-Path $ManifestPath -PathType Leaf)) {
        throw "La release contiene runtime\python.exe pero falta runtime-manifest.json. No lo ejecuto sin manifest."
    }
    $manifest = Get-Content $ManifestPath -Raw | ConvertFrom-Json
    if ([string]$manifest.project_version -ne "3.1.3") {
        throw "runtime-manifest.json corresponde a otra versión: $($manifest.project_version)"
    }
    $expected = @{}
    foreach ($entry in $manifest.runtime_files) {
        $rel = [string]$entry.path
        if (-not $rel -or $rel.Contains("..") -or [IO.Path]::IsPathRooted($rel)) {
            throw "Manifest runtime contiene ruta insegura: $rel"
        }
        $full = Join-Path $RuntimeDir ($rel.Replace('/', '\'))
        if (!(Test-Path -LiteralPath $full -PathType Leaf)) { throw "Runtime incompleto: $rel" }
        $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $full).Hash.ToLowerInvariant()
        if ($hash -ne ([string]$entry.sha256).ToLowerInvariant()) { throw "Hash inválido en runtime portable: $rel" }
        $expected[$rel.ToLowerInvariant()] = $true
    }
    $base = (Resolve-Path $RuntimeDir).Path
    $actual = @(Get-ChildItem -Path $RuntimeDir -File -Recurse | ForEach-Object {
        $_.FullName.Substring($base.Length).TrimStart('\','/').Replace('\','/').ToLowerInvariant()
    })
    if ($actual.Count -ne $expected.Count) { throw "Runtime portable contiene archivos no manifestados o faltantes." }
    foreach ($rel in $actual) {
        if (-not $expected.ContainsKey($rel)) { throw "Archivo no manifestado en runtime portable: $rel" }
    }
    return $true
}

Assert-NotElevated
Write-Host "== MijiaLamp Portable setup ==" -ForegroundColor Cyan
Write-Host "Carpeta: $Root"

$Config = Join-Path $Root "config.json"
if ($ConfigPath) {
    $resolvedConfig = (Resolve-Path -LiteralPath $ConfigPath).Path
    if ($resolvedConfig -ne $Config) { Copy-Item -LiteralPath $resolvedConfig -Destination $Config -Force }
    Write-Host "Configuración local copiada desde $resolvedConfig" -ForegroundColor Green
} elseif (!(Test-Path $Config)) {
    Copy-Item -Force (Join-Path $Root "config.example.json") $Config
    Write-Host "Creé config.json desde el ejemplo. Editalo antes de usar doctor." -ForegroundColor Yellow
}
foreach ($dir in @("data", "logs", "secrets")) {
    New-Item -ItemType Directory -Force -Path (Join-Path $Root $dir) | Out-Null
}

$BundledRuntime = Join-Path $Root "runtime"
$BundledManifest = Join-Path $Root "runtime-manifest.json"
if (Verify-BundledRuntime -RuntimeDir $BundledRuntime -ManifestPath $BundledManifest) {
    $Python = Join-Path $BundledRuntime "python.exe"
    & $Python -c "import miio, win32api, pystray, PIL, astral, cryptography, mijialamp; print('portable-runtime: OK')"
    if ($LASTEXITCODE -ne 0) { throw "El runtime portable no pasó el smoke test" }
    & $Python .\tools\migrate_legacy_config.py --scope current-user $Config
    if ($LASTEXITCODE -ne 0) { throw "No pude migrar config.json al modo Portable" }
    & $Python .\lampctl.py --mode portable config-check
    if ($LASTEXITCODE -ne 0) { Write-Host "config.json todavía necesita tus datos reales." -ForegroundColor Yellow }
    Write-Host "Portable listo: usa runtime autocontenido y no instaló nada." -ForegroundColor Green
    Write-Host "Siguiente: .\import-token.ps1 -Mode Portable ; .\start-portable.cmd"
    exit 0
}

$Venv = Join-Path $Root ".venv"
if ($RecreateVenv -and (Test-Path $Venv)) { Remove-Item -Recurse -Force $Venv }
if (!(Test-Path $Venv)) {
    $launcher = Get-PythonLauncher
    if ($launcher.Count -eq 2) { & $launcher[0] $launcher[1] -m venv $Venv }
    else { & $launcher[0] -m venv $Venv }
    if ($LASTEXITCODE -ne 0) { throw "No pude crear .venv" }
}

$Python = Join-Path $Venv "Scripts\python.exe"
$Architecture = (& $Python -c "import platform; print(platform.machine())").Trim()
if ($LASTEXITCODE -ne 0) { throw "No pude detectar la arquitectura del Python Portable" }
if ($Architecture -ne "AMD64") {
    throw "Los hashes de las dependencias sólo cubren Windows x64 (AMD64). Arquitectura detectada: $Architecture"
}
$Wheelhouse = Join-Path $Root "wheelhouse"
$PipCommon = @("-m", "pip", "install", "--disable-pip-version-check", "--require-hashes", "--only-binary=:all:", "--force-reinstall")
if ($Offline) {
    if (!(Test-Path $Wheelhouse)) { throw "-Offline requiere la carpeta wheelhouse." }
    $PipCommon += @("--no-index", "--find-links", $Wheelhouse)
}

& $Python @PipCommon -r (Join-Path $Root "requirements.lock.txt") -r (Join-Path $Root "requirements.windows.lock.txt")
if ($LASTEXITCODE -ne 0) { throw "Fallaron dependencias base/Windows" }
& $Python @PipCommon --no-deps -r (Join-Path $Root "requirements.miio.lock.txt")
if ($LASTEXITCODE -ne 0) { throw "Falló python-miio" }
Push-Location $Root
try {
    & $Python -m compileall -q .\mijialamp .\tools .\agent.py .\portable.py .\lampctl.py .\sleepnow.py
    if ($LASTEXITCODE -ne 0) { throw "compileall falló" }
    & $Python -c "import miio, win32api, pystray, PIL, astral, cryptography, mijialamp; print('portable-smoke: OK')"
    if ($LASTEXITCODE -ne 0) { throw "Smoke test portable falló" }
    & $Python .\tools\migrate_legacy_config.py --scope current-user $Config
    if ($LASTEXITCODE -ne 0) { throw "No pude migrar config.json al modo Portable" }
    & $Python .\lampctl.py --mode portable config-check
    if ($LASTEXITCODE -ne 0) { Write-Host "config.json todavía necesita tus datos reales." -ForegroundColor Yellow }
} finally { Pop-Location }

Write-Host "Portable preparado sin privilegios administrativos." -ForegroundColor Green
Write-Host "Siguiente: .\import-token.ps1 -Mode Portable ; .\start-portable.cmd"
