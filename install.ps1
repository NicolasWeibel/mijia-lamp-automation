param(
    [string]$InstallDir = "C:\ProgramData\MijiaLamp",
    [string]$ConfigPath = "",
    [string]$InteractiveUser = "",
    [switch]$EnableAutomation
)

$ErrorActionPreference = "Stop"
$SourceRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ServiceName = "MijiaLampService"
$ProjectVersion = "3.1.3"
$PreparedRoot = Join-Path $SourceRoot "prepared-runtime"
$ManifestPath = Join-Path $PreparedRoot "manifest.json"
$PreparedPython = Join-Path $PreparedRoot "python"
$Staging = "$InstallDir.staging-$([Guid]::NewGuid().ToString('N'))"
$Backup = $null
$OldTaskXml = $null
$OldTaskEnabled = $false
$Swapped = $false
$PreparedManifest = $null

function Assert-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Abrí PowerShell como Administrador y ejecutá install.ps1 nuevamente."
    }
}

function Resolve-InteractiveIdentity {
    param([string]$Override)
    $name = $Override
    if (-not $name) {
        try { $name = (Get-CimInstance Win32_ComputerSystem -ErrorAction Stop).UserName } catch {}
    }
    if (-not $name) { throw "No pude detectar el usuario de escritorio. Usá -InteractiveUser DOMINIO\Usuario." }
    try {
        $account = New-Object Security.Principal.NTAccount($name)
        $sid = $account.Translate([Security.Principal.SecurityIdentifier]).Value
    } catch {
        throw "No pude resolver el usuario interactivo '$name'. Usá -InteractiveUser DOMINIO\Usuario."
    }
    return @{ Name = $name; Sid = $sid }
}

function Verify-PreparedRuntime {
    if (!(Test-Path $ManifestPath) -or !(Test-Path (Join-Path $PreparedPython "python.exe"))) {
        throw "Falta prepared-runtime. Cerrá esta consola elevada, ejecutá .\prepare-service-runtime.ps1 como usuario normal y luego volvé a ejecutar install.ps1 como Administrador."
    }
    $manifestItem = Get-Item -LiteralPath $ManifestPath -Force
    if (($manifestItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw "manifest.json no puede ser reparse point" }
    $reparse = @(Get-ChildItem -LiteralPath $PreparedPython -Force -Recurse -ErrorAction Stop | Where-Object { ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 })
    if ($reparse.Count -gt 0) { throw "prepared-runtime contiene reparse points; volvé a prepararlo desde una carpeta normal." }
    $manifest = Get-Content $ManifestPath -Raw | ConvertFrom-Json
    $script:PreparedManifest = $manifest
    if ([string]$manifest.project_version -ne $ProjectVersion) {
        throw "prepared-runtime corresponde a v$($manifest.project_version), pero este instalador es v$ProjectVersion."
    }
    $expected = @{}
    foreach ($entry in $manifest.runtime_files) {
        $rel = [string]$entry.path
        if (-not $rel -or $rel.Contains("..") -or [IO.Path]::IsPathRooted($rel)) { throw "Manifest contiene ruta insegura: $rel" }
        $full = Join-Path $PreparedPython ($rel.Replace('/', '\'))
        if (!(Test-Path -LiteralPath $full -PathType Leaf)) { throw "Runtime preparado incompleto: $rel" }
        $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $full).Hash.ToLowerInvariant()
        if ($hash -ne ([string]$entry.sha256).ToLowerInvariant()) { throw "Hash inválido en runtime preparado: $rel" }
        $expected[$rel.ToLowerInvariant()] = $true
    }
    $actual = @(Get-ChildItem -Path $PreparedPython -File -Recurse | ForEach-Object {
        $_.FullName.Substring((Resolve-Path $PreparedPython).Path.Length).TrimStart('\','/').Replace('\','/').ToLowerInvariant()
    })
    if ($actual.Count -ne $expected.Count) { throw "Runtime preparado contiene archivos no manifestados o faltantes." }
    foreach ($rel in $actual) { if (-not $expected.ContainsKey($rel)) { throw "Archivo no manifestado en runtime preparado: $rel" } }

    foreach ($entry in $manifest.source_files) {
        $rel = [string]$entry.path
        if (-not $rel -or $rel.Contains("..") -or [IO.Path]::IsPathRooted($rel)) { throw "Manifest source contiene ruta insegura: $rel" }
        $full = Join-Path $SourceRoot ($rel.Replace('/', '\'))
        if (!(Test-Path -LiteralPath $full -PathType Leaf)) { throw "Archivo fuente preparado faltante: $rel" }
        $item = Get-Item -LiteralPath $full -Force
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw "Source manifestado no puede ser reparse point: $rel" }
        $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $full).Hash.ToLowerInvariant()
        if ($hash -ne ([string]$entry.sha256).ToLowerInvariant()) {
            throw "El source cambió después de preparar el runtime: $rel. Volvé a ejecutar prepare-service-runtime.ps1."
        }
    }
    Write-Host "Runtime + source verificados; fase elevada offline." -ForegroundColor Green
}


function Verify-StagingAgainstPreparedManifest {
    param([string]$StageRoot)
    if (-not $script:PreparedManifest) { throw "Prepared manifest no está cargado en memoria" }

    $RuntimeRoot = Join-Path $StageRoot "runtime"
    $runtimeExpected = @{}
    foreach ($entry in $script:PreparedManifest.runtime_files) {
        $rel = [string]$entry.path
        $full = Join-Path $RuntimeRoot ($rel.Replace('/', '\'))
        if (!(Test-Path -LiteralPath $full -PathType Leaf)) { throw "Staging runtime incompleto: $rel" }
        $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $full).Hash.ToLowerInvariant()
        if ($hash -ne ([string]$entry.sha256).ToLowerInvariant()) { throw "TOCTOU/hash inválido tras copiar runtime: $rel" }
        $runtimeExpected[$rel.ToLowerInvariant()] = $true
    }
    $runtimeBase = (Resolve-Path $RuntimeRoot).Path
    $runtimeActual = @(Get-ChildItem -Path $RuntimeRoot -File -Recurse | ForEach-Object {
        $_.FullName.Substring($runtimeBase.Length).TrimStart('\','/').Replace('\','/').ToLowerInvariant()
    })
    if ($runtimeActual.Count -ne $runtimeExpected.Count) { throw "TOCTOU: staging runtime contiene archivos extra o faltantes." }
    foreach ($rel in $runtimeActual) {
        if (-not $runtimeExpected.ContainsKey($rel)) { throw "TOCTOU: archivo runtime no manifestado tras copia: $rel" }
    }

    $sourceExpected = @{}
    foreach ($entry in $script:PreparedManifest.source_files) {
        $rel = [string]$entry.path
        $full = Join-Path $StageRoot ($rel.Replace('/', '\'))
        # Not every release-only source file is installed (for example install.ps1 itself).
        # If it is part of the installed image, it must still match the hash captured before elevation.
        if (Test-Path -LiteralPath $full -PathType Leaf) {
            $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $full).Hash.ToLowerInvariant()
            if ($hash -ne ([string]$entry.sha256).ToLowerInvariant()) { throw "TOCTOU/hash inválido tras copiar source: $rel" }
            $sourceExpected[$rel.ToLowerInvariant()] = $true
        }
    }
    foreach ($dir in @("mijialamp", "tools")) {
        $dirPath = Join-Path $StageRoot $dir
        $base = (Resolve-Path $StageRoot).Path
        foreach ($item in Get-ChildItem -Path $dirPath -File -Recurse) {
            $rel = $item.FullName.Substring($base.Length).TrimStart('\','/').Replace('\','/').ToLowerInvariant()
            if (-not $sourceExpected.ContainsKey($rel)) { throw "TOCTOU: source no manifestado tras copia: $rel" }
        }
    }
}

function Copy-ProjectFiles {
    param([string]$Destination)
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    $files = @(
        "agent.py", "portable.py", "service.py", "lampctl.py", "sleepnow.py",
        "config.example.json", "config.schema.json", "requirements.lock.txt", "requirements.windows.lock.txt", "requirements.miio.lock.txt",
        "pyproject.toml", "LICENSE", "README.md", "CHANGELOG.md", "SECURITY.md", "CONTRIBUTING.md",
        "import-token.ps1", "manual-on.cmd", "manual-off.cmd", "status.cmd", "sync.cmd", "sleep-now.cmd",
        "enable-automation.ps1", "disable-automation.ps1", "uninstall.ps1", "security-check.ps1"
    )
    foreach ($file in $files) {
        $src = Join-Path $SourceRoot $file
        if (Test-Path $src) { Copy-Item -Force $src (Join-Path $Destination $file) }
    }
    foreach ($dir in @("mijialamp", "tools")) {
        $sourceDir = Join-Path $SourceRoot $dir
        $destinationDir = Join-Path $Destination $dir
        New-Item -ItemType Directory -Force -Path $destinationDir | Out-Null
        Get-ChildItem -LiteralPath $sourceDir -File -Recurse -Filter "*.py" | ForEach-Object {
            $relative = $_.FullName.Substring($sourceDir.Length).TrimStart('\','/')
            $target = Join-Path $destinationDir $relative
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
            Copy-Item -LiteralPath $_.FullName -Destination $target -Force
        }
    }
}


function Write-IntegrityManifest {
    param([string]$RootPath)
    $rootResolved = (Resolve-Path $RootPath).Path
    $mutableTop = @("config.json", "data", "logs", "secrets", "integrity-manifest.json")
    $entries = @(Get-ChildItem -Path $RootPath -File -Recurse | Where-Object {
        $relative = $_.FullName.Substring($rootResolved.Length).TrimStart('\','/').Replace('\','/')
        $top = ($relative -split '/')[0]
        -not ($mutableTop -contains $top)
    } | Sort-Object FullName | ForEach-Object {
        $relative = $_.FullName.Substring($rootResolved.Length).TrimStart('\','/').Replace('\','/')
        [ordered]@{
            path = $relative
            size = $_.Length
            sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash.ToLowerInvariant()
        }
    })
    $payload = [ordered]@{
        schema = 1
        project_version = $ProjectVersion
        created_at_utc = [DateTime]::UtcNow.ToString("o")
        files = $entries
    }
    $payload | ConvertTo-Json -Depth 6 | Set-Content -Encoding UTF8 (Join-Path $RootPath "integrity-manifest.json")
}

function Copy-SafeRegularFile {
    param([string]$Source, [string]$Destination)
    if (!(Test-Path -LiteralPath $Source -PathType Leaf)) { return }
    $item = Get-Item -LiteralPath $Source -Force
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "No copio un archivo persistente que sea reparse point: $Source"
    }
    Copy-Item -LiteralPath $Source -Destination $Destination -Force
}

function Stop-And-SnapshotOldAutomation {
    try {
        $task = Get-ScheduledTask -TaskPath "\MijiaLamp\" -TaskName "Lamp Agent" -ErrorAction SilentlyContinue
        if ($task) {
            $script:OldTaskXml = Export-ScheduledTask -TaskPath "\MijiaLamp\" -TaskName "Lamp Agent"
            $script:OldTaskEnabled = $task.State -ne "Disabled"
            Stop-ScheduledTask -TaskPath "\MijiaLamp\" -TaskName "Lamp Agent" -ErrorAction SilentlyContinue
            Unregister-ScheduledTask -TaskPath "\MijiaLamp\" -TaskName "Lamp Agent" -Confirm:$false -ErrorAction SilentlyContinue
        }
    } catch {}
    try { Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue } catch {}
}

function Delete-ServiceDefinition {
    if (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue) {
        & sc.exe delete $ServiceName | Out-Null
        for ($i=0; $i -lt 30; $i++) {
            if (!(Get-Service -Name $ServiceName -ErrorAction SilentlyContinue)) { break }
            Start-Sleep -Milliseconds 200
        }
    }
}

function Install-Service {
    param([string]$Python)
    $script = Join-Path $InstallDir "service.py"
    Delete-ServiceDefinition
    & $Python $script --startup auto install
    if ($LASTEXITCODE -ne 0) { throw "No se pudo instalar $ServiceName" }
    & sc.exe config $ServiceName obj= "NT AUTHORITY\LocalService" password= "" start= delayed-auto | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "No se pudo configurar LocalService" }
    & sc.exe sidtype $ServiceName unrestricted | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "No se pudo habilitar Service SID" }
    # Drop optional token privileges from LocalService. MijiaLamp does not impersonate
    # clients and only needs ordinary file/network access plus traverse checking.
    & sc.exe privs $ServiceName SeChangeNotifyPrivilege | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "No se pudo limitar RequiredPrivileges del servicio" }
    & sc.exe failure $ServiceName reset= 86400 actions= restart/5000/restart/15000/restart/60000 | Out-Null
    & $Python (Join-Path $InstallDir "tools\configure_windows_service.py")
    if ($LASTEXITCODE -ne 0) { throw "No se pudo completar configuración del servicio" }
}

function Set-SecureAcls {
    param([string]$UserSid)
    $svc = "NT SERVICE\$ServiceName"
    & icacls.exe $InstallDir /inheritance:r /grant:r `
        "*S-1-5-18:(OI)(CI)F" "*S-1-5-32-544:(OI)(CI)F" "*${UserSid}:(OI)(CI)RX" "${svc}:(OI)(CI)RX" | Out-Null
    foreach ($name in @("runtime", "mijialamp", "tools")) {
        $path = Join-Path $InstallDir $name
        if (Test-Path $path) {
            & icacls.exe $path /inheritance:r /grant:r `
                "*S-1-5-18:(OI)(CI)F" "*S-1-5-32-544:(OI)(CI)F" "*${UserSid}:(OI)(CI)RX" "${svc}:(OI)(CI)RX" /T /C | Out-Null
        }
    }
    $data = Join-Path $InstallDir "data"
    & icacls.exe $data /inheritance:r /grant:r `
        "*S-1-5-18:(OI)(CI)F" "*S-1-5-32-544:(OI)(CI)F" "${svc}:(OI)(CI)M" "*${UserSid}:(OI)(CI)R" /T /C | Out-Null
    $logs = Join-Path $InstallDir "logs"
    & icacls.exe $logs /inheritance:r /grant:r `
        "*S-1-5-18:(OI)(CI)F" "*S-1-5-32-544:(OI)(CI)F" "${svc}:(OI)(CI)M" "*${UserSid}:(OI)(CI)M" /T /C | Out-Null
    $secrets = Join-Path $InstallDir "secrets"
    & icacls.exe $secrets /inheritance:r /grant:r `
        "*S-1-5-18:(OI)(CI)F" "*S-1-5-32-544:(OI)(CI)F" "${svc}:(OI)(CI)F" /T /C | Out-Null
    $cfg = Join-Path $InstallDir "config.json"
    & icacls.exe $cfg /inheritance:r /grant:r `
        "*S-1-5-18:F" "*S-1-5-32-544:F" "${svc}:R" "*${UserSid}:M" | Out-Null
}

function Register-AgentTask {
    param([string]$UserName, [string]$Pythonw)
    $action = New-ScheduledTaskAction -Execute $Pythonw -Argument ('"' + (Join-Path $InstallDir "agent.py") + '"') -WorkingDirectory $InstallDir
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $UserName
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero)
    try { $settings.RestartCount = 999; $settings.RestartInterval = "PT1M" } catch {}
    $principal = New-ScheduledTaskPrincipal -UserId $UserName -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskPath "\MijiaLamp\" -TaskName "Lamp Agent" -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
    Disable-ScheduledTask -TaskPath "\MijiaLamp\" -TaskName "Lamp Agent" | Out-Null
}

function Restore-PreviousInstall {
    try { Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue } catch {}
    try { Delete-ServiceDefinition } catch {}
    try { Unregister-ScheduledTask -TaskPath "\MijiaLamp\" -TaskName "Lamp Agent" -Confirm:$false -ErrorAction SilentlyContinue } catch {}
    if (Test-Path $InstallDir) {
        $failed = "$InstallDir.failed-$([DateTime]::UtcNow.ToString('yyyyMMddHHmmss'))"
        try { Move-Item -Force $InstallDir $failed } catch { Remove-Item -Recurse -Force $InstallDir -ErrorAction SilentlyContinue }
    }
    if ($script:Backup -and (Test-Path $script:Backup)) {
        Move-Item -Force $script:Backup $InstallDir
        Write-Warning "Archivos anteriores restaurados en $InstallDir."
        # Best-effort restore of a previous v3 service.
        $oldPython = @(
            (Join-Path $InstallDir "runtime\python.exe"),
            (Join-Path $InstallDir ".venv\Scripts\python.exe")
        ) | Where-Object { Test-Path $_ } | Select-Object -First 1
        if ($oldPython -and (Test-Path (Join-Path $InstallDir "service.py"))) {
            try {
                & $oldPython (Join-Path $InstallDir "service.py") --startup auto install *> $null
                & sc.exe config $ServiceName obj= "NT AUTHORITY\LocalService" password= "" start= delayed-auto | Out-Null
                Start-Service $ServiceName -ErrorAction SilentlyContinue
            } catch {}
        }
    }
    if ($script:OldTaskXml) {
        try {
            Register-ScheduledTask -TaskPath "\MijiaLamp\" -TaskName "Lamp Agent" -Xml $script:OldTaskXml -Force | Out-Null
            if (-not $script:OldTaskEnabled) { Disable-ScheduledTask -TaskPath "\MijiaLamp\" -TaskName "Lamp Agent" | Out-Null }
        } catch {}
    }
}

Assert-Administrator
if ((Resolve-Path $SourceRoot).Path -eq $InstallDir -or $SourceRoot -like "$InstallDir\*") {
    throw "Por seguridad transaccional, ejecutá install.ps1 desde la release extraída fuera de $InstallDir."
}
Verify-PreparedRuntime
$InteractiveIdentity = Resolve-InteractiveIdentity -Override $InteractiveUser
$UserName = $InteractiveIdentity.Name
$UserSid = $InteractiveIdentity.Sid
Write-Host "== MijiaLamp v$ProjectVersion hardened service install ==" -ForegroundColor Cyan
Write-Host "Usuario interactivo: $UserName ($UserSid)"
Write-Host "La fase elevada NO usa pip ni Internet." -ForegroundColor Green

try {
    if (Test-Path $Staging) { Remove-Item -Recurse -Force $Staging }
    Copy-ProjectFiles -Destination $Staging
    Copy-Item -Recurse -Force $PreparedPython (Join-Path $Staging "runtime")
    Verify-StagingAgainstPreparedManifest -StageRoot $Staging
    foreach ($dir in @("data", "logs", "secrets")) { New-Item -ItemType Directory -Force -Path (Join-Path $Staging $dir) | Out-Null }

    # Preserve only known regular files. Do not recursively copy logs or arbitrary
    # user-controlled trees with an elevated token (junction/reparse-point hardening).
    if (Test-Path $InstallDir) {
        Copy-SafeRegularFile (Join-Path $InstallDir "config.json") (Join-Path $Staging "config.json")
        Copy-SafeRegularFile (Join-Path $InstallDir "data\runtime_state.json") (Join-Path $Staging "data\runtime_state.json")
        Copy-SafeRegularFile (Join-Path $InstallDir "data\device_cache.json") (Join-Path $Staging "data\device_cache.json")
        Copy-SafeRegularFile (Join-Path $InstallDir "secrets\token.dpapi.json") (Join-Path $Staging "secrets\token.dpapi.json")
    }

    $DestinationConfig = Join-Path $Staging "config.json"
    $CreatedExampleConfig = $false
    if ($ConfigPath) {
        Copy-Item -Force (Resolve-Path $ConfigPath).Path $DestinationConfig
    } elseif (!(Test-Path $DestinationConfig)) {
        Copy-Item -Force (Join-Path $Staging "config.example.json") $DestinationConfig
        $CreatedExampleConfig = $true
    }

    $ServiceMeta = @{ version = 1; authorized_user_sid = $UserSid; authorized_user = $UserName }
    $ServiceMeta | ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $Staging "data\service_meta.json")

    $StagePython = Join-Path $Staging "runtime\python.exe"
    Push-Location $Staging
    try {
        & $StagePython -m compileall -q .\mijialamp .\tools .\agent.py .\service.py .\lampctl.py .\sleepnow.py
        if ($LASTEXITCODE -ne 0) { throw "compileall falló" }
        & $StagePython .\tools\migrate_legacy_config.py --scope local-machine $DestinationConfig
        if ($LASTEXITCODE -ne 0) { throw "Falló migración segura de config" }
        & $StagePython .\lampctl.py config-check
        if ($LASTEXITCODE -ne 0) { throw "config.json no pasó validación" }
        & $StagePython -c "import miio, win32service, win32serviceutil, astral, cryptography, mijialamp; print('runtime-smoke: OK')"
        if ($LASTEXITCODE -ne 0) { throw "Runtime privado no pasó smoke test" }
    } finally { Pop-Location }

    # Do not install import caches as mutable executable artifacts. The protected runtime
    # can import source directly and the service has no reason to write into code dirs.
    Get-ChildItem $Staging -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    Get-ChildItem $Staging -Recurse -File -Include "*.pyc", "*.pyo" -ErrorAction SilentlyContinue |
        Remove-Item -Force -ErrorAction SilentlyContinue
    Write-IntegrityManifest -RootPath $Staging

    Stop-And-SnapshotOldAutomation
    if (Test-Path $InstallDir) {
        $backupRoot = Join-Path (Split-Path -Parent $InstallDir) "MijiaLamp-backups"
        New-Item -ItemType Directory -Force -Path $backupRoot | Out-Null
        $script:Backup = Join-Path $backupRoot (Get-Date -Format "yyyyMMdd-HHmmss")
        Move-Item $InstallDir $script:Backup
        & icacls.exe $backupRoot /inheritance:r /grant:r "*S-1-5-18:(OI)(CI)F" "*S-1-5-32-544:(OI)(CI)F" /T /C | Out-Null
    }
    Move-Item $Staging $InstallDir
    $Swapped = $true

    $Python = Join-Path $InstallDir "runtime\python.exe"
    $Pythonw = Join-Path $InstallDir "runtime\pythonw.exe"
    Install-Service -Python $Python
    Set-SecureAcls -UserSid $UserSid
    Register-AgentTask -UserName $UserName -Pythonw $Pythonw
    Start-Service -Name $ServiceName

    $ServiceReady = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        & $Python (Join-Path $InstallDir "lampctl.py") service-status *> $null
        if ($LASTEXITCODE -eq 0) { $ServiceReady = $true; break }
        Start-Sleep -Milliseconds 400
    }
    if (-not $ServiceReady) { throw "MijiaLampService no respondió por Named Pipe." }

    & (Join-Path $InstallDir "security-check.ps1") -InstallDir $InstallDir -InteractiveUser $UserName
    if ($LASTEXITCODE -ne 0) { throw "security-check.ps1 detectó una configuración insegura" }

    if ($CreatedExampleConfig) {
        Write-Host "IMPORTANTE: editá $InstallDir\config.json con tus datos reales." -ForegroundColor Yellow
    }
    if (Test-Path (Join-Path $InstallDir "secrets\token.dpapi.json")) {
        Write-Host "Token Service existente conservado. Ejecutá doctor antes de habilitar." -ForegroundColor Green
    } else {
        Write-Host "Falta importar token Service: .\import-token.ps1 -Mode Service" -ForegroundColor Yellow
    }

    if ($EnableAutomation -and (Test-Path (Join-Path $InstallDir "secrets\token.dpapi.json"))) {
        & $Python (Join-Path $InstallDir "lampctl.py") doctor
        if ($LASTEXITCODE -eq 0) { & (Join-Path $InstallDir "enable-automation.ps1") -InstallDir $InstallDir }
    } else {
        Write-Host "Automatización instalada DESHABILITADA por seguridad." -ForegroundColor Yellow
    }
    Write-Host "Instalación hardened v$ProjectVersion finalizada." -ForegroundColor Green
} catch {
    Write-Host "Instalación falló: $($_.Exception.Message)" -ForegroundColor Red
    if ($Swapped -or $Backup) { Restore-PreviousInstall }
    if (Test-Path $Staging) { Remove-Item -Recurse -Force $Staging -ErrorAction SilentlyContinue }
    throw
}
