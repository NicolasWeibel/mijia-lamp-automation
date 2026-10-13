param(
    [switch]$Recreate,
    [switch]$RefreshSourceOnly,
    [switch]$AllowElevatedForCI
)
. (Join-Path $PSScriptRoot 'i18n.ps1')
Initialize-MijiaLampLanguage -ConfigPath $ConfigPath
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
        throw (T 'msg_1d2542719a2a')
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
    throw (T 'msg_95ae66d058cd')
}

function Invoke-Python {
    param([string[]]$Launcher, [string[]]$Arguments)
    if ($Launcher.Count -eq 2) { & $Launcher[0] $Launcher[1] -I @Arguments }
    else { & $Launcher[0] -I @Arguments }
    if ($LASTEXITCODE -ne 0) { throw (T 'msg_0d374114ba89' -Arguments @(($Arguments -join ' '))) }
}


function Get-ProjectSourceEntries {
    $files = @(
        "agent.py", "portable.py", "service.py", "lampctl.py", "sleepnow.py",
        "config.example.json", "config.schema.json", "requirements.lock.txt", "requirements.windows.lock.txt", "requirements.miio.lock.txt",
        "pyproject.toml", "LICENSE", "THIRD_PARTY_NOTICES.md", "README.md", "README.es.md", "CHANGELOG.md", "CHANGELOG.es.md", "SECURITY.md", "SECURITY.es.md", "CONTRIBUTING.md", "CONTRIBUTING.es.md",
        "import-token.ps1", "manual-on.cmd", "manual-off.cmd", "status.cmd", "sync.cmd", "sleep-now.cmd",
        "enable-automation.ps1", "disable-automation.ps1", "uninstall.ps1", "security-check.ps1", "install.ps1",
        "i18n.ps1", "config-gui.ps1", "setup-gui.ps1", "setup-gui.cmd", "setup-gui.vbs", "onboarding-gui.ps1", "prepare-service-runtime.ps1",
        "setup-portable.ps1", "start-portable.cmd", "portable-status.cmd", "portable-on.cmd", "portable-off.cmd", "portable-sleep-now.cmd",
        "enable-portable-autostart.ps1", "disable-portable-autostart.ps1", "enable-portable-automation.ps1", "disable-portable-automation.ps1"
    )
    $paths = New-Object System.Collections.Generic.List[string]
    foreach ($file in $files) {
        $full = Join-Path $Root $file
        if (Test-Path $full -PathType Leaf) { $paths.Add($full) }
    }
    foreach ($dir in @("mijialamp", "tools", "docs")) {
        Get-ChildItem -Path (Join-Path $Root $dir) -File -Recurse |
            Where-Object { $_.Extension -in @(".py", ".json", ".md") } |
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

function Remove-UnmanifestedBytecode {
    param([object[]]$ExpectedEntries)
    $base = (Resolve-Path -LiteralPath $RuntimePython).Path.TrimEnd('\', '/')
    $items = @(Get-ChildItem -LiteralPath $base -Force -Recurse -ErrorAction Stop)
    if (@($items | Where-Object { ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 }).Count -gt 0) {
        throw (T 'msg_8e500cdfbff5')
    }
    $expected = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach ($entry in $ExpectedEntries) { [void]$expected.Add([string]$entry.path) }
    $actual = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    $extra = New-Object System.Collections.Generic.List[object]
    foreach ($file in @($items | Where-Object { -not $_.PSIsContainer })) {
        $full = [IO.Path]::GetFullPath($file.FullName)
        if (-not $full.StartsWith($base + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
            throw (T 'runtime.outside' -Arguments @($full))
        }
        $relative = $full.Substring($base.Length + 1).Replace('\', '/')
        [void]$actual.Add($relative)
        if (-not $expected.Contains($relative)) {
            if ($relative -notmatch '(^|/)__pycache__/.*\.(pyc|pyo)$') {
                throw (T 'msg_8ca8df2e78da' -Arguments @(($relative)))
            }
            $extra.Add($file)
        }
    }
    foreach ($entry in $ExpectedEntries) {
        if (-not $actual.Contains([string]$entry.path)) {
            throw (T 'msg_ac327ff02046' -Arguments @(($entry.path)))
        }
    }
    foreach ($file in $extra) { Remove-Item -LiteralPath $file.FullName -Force -ErrorAction Stop }
    Write-Host (T 'msg_dc7a05930750' -Arguments @(($extra.Count)))
}

Assert-NotElevated
if ($RefreshSourceOnly) {
    if ($Recreate) { throw (T 'msg_fa2de186c289') }
    if (!(Test-Path -LiteralPath $ManifestPath -PathType Leaf) -or
        !(Test-Path -LiteralPath (Join-Path $RuntimePython "python.exe") -PathType Leaf)) {
        throw (T 'msg_ed9b93a3ff9a')
    }
    $manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
    if ([string]$manifest.project_version -ne "3.1.3") {
        throw (T 'msg_01e9b3cedb28')
    }
    if ([string]$manifest.runtime_isolation -ne "python-dll-pth-v1") {
        throw (T 'msg_763cb0614c80')
    }
    Remove-UnmanifestedBytecode -ExpectedEntries @($manifest.runtime_files)
    $manifest.source_files = @(Get-ProjectSourceEntries)
    $manifest | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 -LiteralPath $ManifestPath
    Write-Host (T 'msg_ae676de396f6') -ForegroundColor Green
    Write-Host (T 'msg_2d59d935d20a') -ForegroundColor Green
    return
}
Write-Host (T 'msg_f71b97ffd568') -ForegroundColor Cyan
Write-Host (T 'msg_6ec8cd0d1032')

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
    throw (T 'msg_d66b68df4b57' -Arguments @(($BasePrefix)))
}
if ($Architecture -ne "AMD64") {
    throw (T 'msg_877ee647a8dd' -Arguments @(($Architecture)))
}

Write-Host (T 'runtime.python_source' -Arguments @($BasePrefix, $PythonVersion, $Architecture))
Write-Host "Descargando wheels binarios fijados..."
Invoke-Python $launcher @("-m", "pip", "download", "--disable-pip-version-check", "--require-hashes", "--only-binary=:all:", "--dest", $Wheelhouse, "-r", (Join-Path $Root "requirements.lock.txt"), "-r", (Join-Path $Root "requirements.windows.lock.txt"))
Invoke-Python $launcher @("-m", "pip", "download", "--disable-pip-version-check", "--require-hashes", "--only-binary=:all:", "--no-deps", "--dest", $Wheelhouse, "-r", (Join-Path $Root "requirements.miio.lock.txt"))

Write-Host (T 'msg_6d83e68be303')
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

# A copied CPython otherwise adds the current user's site-packages to sys.path.
# Pin every import path to this runtime and the protected install root. Do not
# import site here: it would add the user's packages and process their .pth files.
$PythonParts = $PythonVersion.Split('.')
$PythonTag = "$($PythonParts[0])$($PythonParts[1])"
$IsolatedPaths = @(
    "python${PythonTag}.zip", "DLLs", "Lib", ".", "Lib/site-packages",
    "Lib/site-packages/win32", "Lib/site-packages/win32/lib",
    "Lib/site-packages/pythonwin", ".."
)
$IsolatedPaths | Set-Content -Encoding ASCII (Join-Path $RuntimePython "python${PythonTag}._pth")

$PrivatePython = Join-Path $RuntimePython "python.exe"
& $PrivatePython -m ensurepip --upgrade
if ($LASTEXITCODE -ne 0) { throw (T 'msg_d7b13677cac4') }
& $PrivatePython -m pip install --disable-pip-version-check --require-hashes --only-binary=:all: --no-index --find-links $Wheelhouse -r (Join-Path $Root "requirements.lock.txt") -r (Join-Path $Root "requirements.windows.lock.txt")
if ($LASTEXITCODE -ne 0) { throw (T 'msg_bd7e3bb1d2fb') }
& $PrivatePython -m pip install --disable-pip-version-check --require-hashes --only-binary=:all: --no-index --find-links $Wheelhouse --no-deps -r (Join-Path $Root "requirements.miio.lock.txt")
if ($LASTEXITCODE -ne 0) { throw (T 'msg_dbb9140bbd83') }
# python-miio declares backup/cloud helpers that this LAN-only project deliberately
# omits, so pip check would reject the documented minimal runtime.

# With site disabled, pywin32's .pth bootstrap does not run. Keep its DLLs
# beside python.exe, where the Windows loader can find them after relocation.
$Pywin32DllRoot = Join-Path $RuntimePython "Lib\site-packages\pywin32_system32"
foreach ($dll in @("pywintypes${PythonTag}.dll", "pythoncom${PythonTag}.dll")) {
    $source = Join-Path $Pywin32DllRoot $dll
    if (!(Test-Path -LiteralPath $source -PathType Leaf)) { throw (T 'msg_fa6fa8bc82cb' -Arguments @(($dll))) }
    Copy-Item -LiteralPath $source -Destination (Join-Path $RuntimePython $dll) -Force
}

& $PrivatePython -c "import sys, site, yaml, six, colorama, pycparser, miio, win32service; assert site.getusersitepackages() not in sys.path; print('isolated-runtime: OK')"
if ($LASTEXITCODE -ne 0) { throw (T 'msg_6778cd39da50') }

# Remove package installers from the service runtime after construction. The installed
# service has no reason to run pip/setuptools/wheel at all.
& $PrivatePython -m pip uninstall -y pip setuptools wheel *> $null
if ($LASTEXITCODE -ne 0) { throw (T 'msg_ab6463ab3d57') }

# Relocation smoke test: the protected runtime will live under ProgramData, not here.
$Relocated = Join-Path $PreparedRoot "python-relocation-test"
if (Test-Path $Relocated) { Remove-Item -Recurse -Force $Relocated }
Rename-Item $RuntimePython $Relocated
try {
    $RelocatedPython = Join-Path $Relocated "python.exe"
    & $RelocatedPython -c "import miio, win32service, win32serviceutil, astral, cryptography, yaml, six, colorama, pycparser; print('relocation-smoke: OK')"
    if ($LASTEXITCODE -ne 0) { throw (T 'msg_11d8c3aa60e6') }
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
    runtime_isolation = "python-dll-pth-v1"
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
Write-Host (T 'msg_08aa64b5ef31')
