param(
    [switch]$Recreate,
    [switch]$AllowElevatedForCI
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$PreparedRoot = Join-Path $Root "prepared-runtime"
$RuntimePython = Join-Path $PreparedRoot "python"
$Wheelhouse = Join-Path $PreparedRoot "wheelhouse"
$ManifestPath = Join-Path $PreparedRoot "manifest.json"

function Assert-NotElevated {
    if ($AllowElevatedForCI -and $env:GITHUB_ACTIONS -eq "true") { return }
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Prepará el runtime desde PowerShell NORMAL. La fase con Administrador debe ser offline y sin pip."
    }
}

function Get-PythonLauncher {
    if (Get-Command py.exe -ErrorAction SilentlyContinue) {
        foreach ($version in @("3.12", "3.11", "3.10")) {
            $path = (& py.exe "-$version" -c "import sys; print(sys.executable)" 2>$null)
            if ($LASTEXITCODE -eq 0 -and $path) { return @("py.exe", "-$version") }
        }
    }
    if (Get-Command python.exe -ErrorAction SilentlyContinue) {
        & python.exe -c "import sys; assert (3,10) <= sys.version_info[:2] < (3,13)" *> $null
        if ($LASTEXITCODE -eq 0) { return @("python.exe") }
    }
    throw "Necesitás Python 3.10, 3.11 o 3.12 para preparar el runtime."
}

function Invoke-Python {
    param([string[]]$Launcher, [string[]]$Arguments)
    if ($Launcher.Count -eq 2) { & $Launcher[0] $Launcher[1] @Arguments }
    else { & $Launcher[0] @Arguments }
    if ($LASTEXITCODE -ne 0) { throw "Python falló: $($Arguments -join ' ')" }
}


function Get-ProjectSourceEntries {
    $files = @(
        "agent.py", "portable.py", "service.py", "lampctl.py", "sleepnow.py",
        "config.example.json", "config.schema.json", "requirements.lock.txt", "requirements.windows.lock.txt", "requirements.miio.lock.txt",
        "pyproject.toml", "LICENSE", "README.md", "CHANGELOG.md", "SECURITY.md", "CONTRIBUTING.md",
        "import-token.ps1", "manual-on.cmd", "manual-off.cmd", "status.cmd", "sync.cmd", "sleep-now.cmd",
        "enable-automation.ps1", "disable-automation.ps1", "uninstall.ps1", "security-check.ps1", "install.ps1"
    )
    $paths = New-Object System.Collections.Generic.List[string]
    foreach ($file in $files) {
        $full = Join-Path $Root $file
        if (Test-Path $full -PathType Leaf) { $paths.Add($full) }
    }
    foreach ($dir in @("mijialamp", "tools")) {
        Get-ChildItem -Path (Join-Path $Root $dir) -File -Recurse |
            Where-Object { $_.Extension -eq ".py" } |
            ForEach-Object { $paths.Add($_.FullName) }
    }
    return @($paths | Sort-Object | ForEach-Object {
        $rel = $_.Substring((Resolve-Path $Root).Path.Length).TrimStart('\','/').Replace('\','/')
        [ordered]@{
            path = $rel
            size = (Get-Item $_).Length
            sha256 = (Get-FileHash -Algorithm SHA256 $_).Hash.ToLowerInvariant()
        }
    })
}

function Get-ManifestEntries {
    param([string]$BasePath)
    $base = (Resolve-Path $BasePath).Path
    return @(Get-ChildItem -Path $base -File -Recurse | Sort-Object FullName | ForEach-Object {
        $relative = $_.FullName.Substring($base.Length).TrimStart('\','/').Replace('\','/')
        [ordered]@{
            path = $relative
            size = $_.Length
            sha256 = (Get-FileHash -Algorithm SHA256 $_.FullName).Hash.ToLowerInvariant()
        }
    })
}

Assert-NotElevated
Write-Host "== Preparación segura del runtime Service ==" -ForegroundColor Cyan
Write-Host "Esta fase puede usar Internet, pero NO tiene privilegios administrativos."

if ($Recreate -and (Test-Path $PreparedRoot)) { Remove-Item -Recurse -Force $PreparedRoot }
New-Item -ItemType Directory -Force -Path $PreparedRoot, $Wheelhouse | Out-Null
$launcher = Get-PythonLauncher
$BasePrefix = if ($launcher.Count -eq 2) {
    (& $launcher[0] $launcher[1] -c "import sys; print(sys.base_prefix)").Trim()
} else {
    (& $launcher[0] -c "import sys; print(sys.base_prefix)").Trim()
}
$PythonVersion = if ($launcher.Count -eq 2) {
    (& $launcher[0] $launcher[1] -c "import platform; print(platform.python_version())").Trim()
} else {
    (& $launcher[0] -c "import platform; print(platform.python_version())").Trim()
}
$Architecture = if ($launcher.Count -eq 2) {
    (& $launcher[0] $launcher[1] -c "import platform; print(platform.machine())").Trim()
} else {
    (& $launcher[0] -c "import platform; print(platform.machine())").Trim()
}

if (!(Test-Path (Join-Path $BasePrefix "python.exe"))) {
    throw "La instalación base de Python no se puede copiar de forma segura: $BasePrefix"
}
if ($Architecture -ne "AMD64") {
    throw "Los hashes del runtime sólo cubren Windows x64 (AMD64). Arquitectura detectada: $Architecture"
}

Write-Host "Python origen: $BasePrefix ($PythonVersion / $Architecture)"
Write-Host "Descargando wheels binarios fijados..."
Invoke-Python $launcher @("-m", "pip", "download", "--disable-pip-version-check", "--require-hashes", "--only-binary=:all:", "--dest", $Wheelhouse, "-r", (Join-Path $Root "requirements.lock.txt"), "-r", (Join-Path $Root "requirements.windows.lock.txt"))
Invoke-Python $launcher @("-m", "pip", "download", "--disable-pip-version-check", "--require-hashes", "--only-binary=:all:", "--no-deps", "--dest", $Wheelhouse, "-r", (Join-Path $Root "requirements.miio.lock.txt"))

Write-Host "Construyendo copia privada de Python (sin site-packages del usuario)..."
if (Test-Path $RuntimePython) { Remove-Item -Recurse -Force $RuntimePython }
New-Item -ItemType Directory -Force -Path $RuntimePython | Out-Null
# Copy the CPython installation itself, then deliberately discard all existing third-party
# packages and Scripts so a user-writable global package cannot become service code.
Get-ChildItem -Force $BasePrefix | ForEach-Object {
    if ($_.Name -in @("Lib", "Scripts")) { return }
    Copy-Item -Recurse -Force $_.FullName $RuntimePython
}
New-Item -ItemType Directory -Force -Path (Join-Path $RuntimePython "Lib") | Out-Null
Get-ChildItem -Force (Join-Path $BasePrefix "Lib") | ForEach-Object {
    if ($_.Name -eq "site-packages") { return }
    Copy-Item -Recurse -Force $_.FullName (Join-Path $RuntimePython "Lib")
}
New-Item -ItemType Directory -Force -Path (Join-Path $RuntimePython "Lib\site-packages") | Out-Null

$PrivatePython = Join-Path $RuntimePython "python.exe"
& $PrivatePython -m ensurepip --upgrade
if ($LASTEXITCODE -ne 0) { throw "ensurepip falló en runtime privado" }
& $PrivatePython -m pip install --disable-pip-version-check --require-hashes --only-binary=:all: --no-index --find-links $Wheelhouse -r (Join-Path $Root "requirements.lock.txt") -r (Join-Path $Root "requirements.windows.lock.txt")
if ($LASTEXITCODE -ne 0) { throw "No pude instalar requirements base/Windows en runtime privado" }
& $PrivatePython -m pip install --disable-pip-version-check --require-hashes --only-binary=:all: --no-index --find-links $Wheelhouse --no-deps -r (Join-Path $Root "requirements.miio.lock.txt")
if ($LASTEXITCODE -ne 0) { throw "No pude instalar python-miio en runtime privado" }

# Remove package installers from the service runtime after construction. The installed
# service has no reason to run pip/setuptools/wheel at all.
& $PrivatePython -m pip uninstall -y pip setuptools wheel *> $null

# Relocation smoke test: the protected runtime will live under ProgramData, not here.
$Relocated = Join-Path $PreparedRoot "python-relocation-test"
if (Test-Path $Relocated) { Remove-Item -Recurse -Force $Relocated }
Rename-Item $RuntimePython $Relocated
try {
    $RelocatedPython = Join-Path $Relocated "python.exe"
    & $RelocatedPython -c "import miio, win32service, win32serviceutil, astral, cryptography; print('relocation-smoke: OK')"
    if ($LASTEXITCODE -ne 0) { throw "El runtime privado no superó la prueba de reubicación" }
} finally {
    Rename-Item $Relocated $RuntimePython
}

# Keep the manifest deterministic and avoid shipping import caches created by smoke tests.
Get-ChildItem $RuntimePython -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem $RuntimePython -Recurse -File -Include "*.pyc", "*.pyo" -ErrorAction SilentlyContinue |
    Remove-Item -Force -ErrorAction SilentlyContinue

$RuntimeEntries = Get-ManifestEntries $RuntimePython
$WheelEntries = Get-ManifestEntries $Wheelhouse
$SourceEntries = Get-ProjectSourceEntries
$Manifest = [ordered]@{
    schema = 1
    project_version = "3.1.3"
    prepared_at_utc = [DateTime]::UtcNow.ToString("o")
    python_version = $PythonVersion
    architecture = $Architecture
    runtime_files = $RuntimeEntries
    wheelhouse_files = $WheelEntries
    source_files = $SourceEntries
}
$Manifest | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 $ManifestPath

Write-Host "Runtime Service preparado y hash-eado." -ForegroundColor Green
Write-Host "Manifest: $ManifestPath"
Write-Host "Ahora abrí OTRA PowerShell como Administrador y ejecutá .\install.ps1"
