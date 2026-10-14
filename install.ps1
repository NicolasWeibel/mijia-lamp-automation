param(
    [string]$InstallDir = [IO.Path]::Combine([Environment]::GetFolderPath("CommonApplicationData"), "MijiaLamp"),
    [string]$ConfigPath = "",
    [string]$InteractiveUser = "",
    [string]$EncryptedTokenSource = "",
    [switch]$ShowTray,
    [switch]$EnableAutomation,
    [switch]$GuiProgress
)

. (Join-Path $PSScriptRoot 'i18n.ps1')
. (Join-Path $PSScriptRoot 'version.ps1')
Initialize-MijiaLampLanguage -ConfigPath $ConfigPath
$ErrorActionPreference = "Stop"
$SourceRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ServiceName = "MijiaLampService"
$ProjectVersion = Get-MijiaLampVersion
$PreparedRoot = Join-Path $SourceRoot "prepared-runtime"
$ManifestPath = Join-Path $PreparedRoot "manifest.json"
$PreparedPython = Join-Path $PreparedRoot "python"
$Staging = "$InstallDir.staging-$([Guid]::NewGuid().ToString('N'))"
$Backup = $null
$Swapped = $false
$PreparedManifest = $null
$StagingCreated = $false
$OldAutomationStopped = $false

function Write-InstallProgress([int]$Percent, [string]$Stage) {
    if ($GuiProgress) { Write-Host "[MijiaLamp:progress:$Percent] $Stage" }
}

function Assert-OfficialInstallDir {
    $expected = Join-Path ([Environment]::GetFolderPath("CommonApplicationData")) "MijiaLamp"
    $actualPath = [IO.Path]::GetFullPath($InstallDir).TrimEnd('\')
    $expectedPath = [IO.Path]::GetFullPath($expected).TrimEnd('\')
    if ($actualPath -ine $expectedPath) {
        throw (T 'msg_fcf42df1f1fc' -Arguments @(($expectedPath)))
    }
}

function Assert-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw (T 'msg_35e16243f665')
    }
}

function Assert-PrivateDirectory {
    param([string]$Path)
    $administrators = [Security.Principal.SecurityIdentifier]::new("S-1-5-32-544")
    $system = [Security.Principal.SecurityIdentifier]::new("S-1-5-18")
    $item = Get-Item -LiteralPath $Path -Force
    if (-not $item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw (T 'msg_38012655b200' -Arguments @(($Path)))
    }
    $actualAcl = Get-Acl -LiteralPath $Path
    if ($actualAcl.GetOwner([Security.Principal.SecurityIdentifier]).Value -ne $administrators.Value -or
        -not $actualAcl.AreAccessRulesProtected) {
        throw (T 'msg_fb084559c6d3' -Arguments @(($Path)))
    }
    $allowed = @($administrators.Value, $system.Value)
    $found = @()
    foreach ($entry in $actualAcl.Access) {
        $sid = $entry.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value
        if ($entry.AccessControlType -ne [Security.AccessControl.AccessControlType]::Allow -or
            $sid -notin $allowed) {
            throw (T 'msg_5f97399e6471' -Arguments @(($sid)))
        }
        $found += $sid
    }
    if (@($found | Sort-Object -Unique).Count -ne 2) {
        throw (T 'msg_9ae22b63f8f6' -Arguments @(($Path)))
    }
}

function New-PrivateDirectory {
    param([string]$Path)
    if (Test-Path -LiteralPath $Path) { throw "Directorio ya existe: $Path" }

    $administrators = [Security.Principal.SecurityIdentifier]::new("S-1-5-32-544")
    $system = [Security.Principal.SecurityIdentifier]::new("S-1-5-18")
    $acl = New-Object Security.AccessControl.DirectorySecurity
    $acl.SetOwner($administrators)
    $acl.SetAccessRuleProtection($true, $false)
    $inheritance = [Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
        [Security.AccessControl.InheritanceFlags]::ObjectInherit
    foreach ($trustee in @($administrators, $system)) {
        $rule = [Security.AccessControl.FileSystemAccessRule]::new(
            $trustee,
            [Security.AccessControl.FileSystemRights]::FullControl,
            $inheritance,
            [Security.AccessControl.PropagationFlags]::None,
            [Security.AccessControl.AccessControlType]::Allow
        )
        $acl.AddAccessRule($rule)
    }

    if ($PSVersionTable.PSVersion.Major -ge 6) {
        [IO.FileSystemAclExtensions]::CreateDirectory($acl, $Path) | Out-Null
    } else {
        [IO.Directory]::CreateDirectory($Path, $acl) | Out-Null
    }
    # CreateDirectory may return an existing directory if one appears in the race.
    # Only the verified directory can be cleaned up after a failed installation.
    Assert-PrivateDirectory -Path $Path
}

function Invoke-CheckedIcacls {
    param([string]$Path, [string[]]$AclArguments)
    & icacls.exe $Path @AclArguments | Out-Null
    if ($LASTEXITCODE -ne 0) { throw (T 'msg_cd22448b907f' -Arguments @(($Path))) }
}

function Write-Utf8NoBom {
    param([string]$Path, [string]$Content)
    [IO.File]::WriteAllText($Path, $Content, [Text.UTF8Encoding]::new($false))
}

function Set-SecureTreeAcl {
    param([string]$Path, [string[]]$Grants)
    # /inheritance:r with /T strips inherited ACEs from child files. Set the
    # restricted ACL on the directory first, then reset descendants to inherit it.
    Invoke-CheckedIcacls $Path (@('/inheritance:r', '/grant:r') + $Grants)
    if (Get-ChildItem -LiteralPath $Path -Force | Select-Object -First 1) {
        Invoke-CheckedIcacls (Join-Path $Path '*') @('/reset', '/T')
    }
}

function Resolve-InteractiveIdentity {
    param([string]$Override)
    $name = $Override
    if (-not $name) {
        try { $name = (Get-CimInstance Win32_ComputerSystem -ErrorAction Stop).UserName } catch {}
    }
    if (-not $name) { throw (T 'msg_78478b3a5111') }
    try {
        $account = New-Object Security.Principal.NTAccount($name)
        $sid = $account.Translate([Security.Principal.SecurityIdentifier]).Value
    } catch {
        throw (T 'msg_ddb968c256ec' -Arguments @(($name)))
    }
    return @{ Name = $name; Sid = $sid }
}

function Verify-PreparedRuntime {
    if (!(Test-Path $ManifestPath) -or !(Test-Path (Join-Path $PreparedPython "python.exe"))) {
        throw (T 'msg_dd686e55e770')
    }
    $manifestItem = Get-Item -LiteralPath $ManifestPath -Force
    if (($manifestItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw (T 'msg_b7e7c73bb638') }
    $reparse = @(Get-ChildItem -LiteralPath $PreparedPython -Force -Recurse -ErrorAction Stop | Where-Object { ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 })
    if ($reparse.Count -gt 0) { throw (T 'msg_0709f12c57a4') }
    $manifest = Get-Content $ManifestPath -Raw | ConvertFrom-Json
    $script:PreparedManifest = $manifest
    if ([string]$manifest.project_version -ne $ProjectVersion) {
        throw "prepared-runtime corresponde a v$($manifest.project_version), pero este instalador es v$ProjectVersion."
    }
    if ([string]$manifest.runtime_isolation -ne "python-dll-pth-v1") {
        throw (T 'msg_50cf7b23c8d6')
    }
    $expected = @{}
    $verifiedCount = 0
    foreach ($entry in $manifest.runtime_files) {
        $rel = [string]$entry.path
        if (-not $rel -or $rel.Contains("..") -or [IO.Path]::IsPathRooted($rel)) { throw (T 'msg_046facbb7d60' -Arguments @(($rel))) }
        $full = Join-Path $PreparedPython ($rel.Replace('/', '\'))
        if (!(Test-Path -LiteralPath $full -PathType Leaf)) { throw (T 'msg_cd19bafbf2a7' -Arguments @(($rel))) }
        $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $full).Hash.ToLowerInvariant()
        if ($hash -ne ([string]$entry.sha256).ToLowerInvariant()) { throw (T 'msg_994a0eddc03d' -Arguments @(($rel))) }
        $expected[$rel.ToLowerInvariant()] = $true
        $verifiedCount++
        if ($verifiedCount % 100 -eq 0 -or $verifiedCount -eq $manifest.runtime_files.Count) {
            Write-InstallProgress ([int](15 * $verifiedCount / $manifest.runtime_files.Count)) (T 'msg_d0eb49810648')
        }
    }
    $actual = @(Get-ChildItem -Path $PreparedPython -File -Recurse | ForEach-Object {
        $_.FullName.Substring((Resolve-Path $PreparedPython).Path.Length).TrimStart('\','/').Replace('\','/').ToLowerInvariant()
    })
    if ($actual.Count -ne $expected.Count) { throw (T 'msg_8b7b34ce0e78') }
    foreach ($rel in $actual) { if (-not $expected.ContainsKey($rel)) { throw (T 'msg_a3e5479ec449' -Arguments @(($rel))) } }

    $sourceExpected = @{}
    foreach ($entry in $manifest.source_files) {
        $rel = [string]$entry.path
        if (-not $rel -or $rel.Contains("..") -or [IO.Path]::IsPathRooted($rel)) { throw (T 'msg_5036d63555a8' -Arguments @(($rel))) }
        $sourceExpected[$rel.ToLowerInvariant()] = $true
        $full = Join-Path $SourceRoot ($rel.Replace('/', '\'))
        if (!(Test-Path -LiteralPath $full -PathType Leaf)) { throw (T 'msg_7f00fed0e6c8' -Arguments @(($rel))) }
        $item = Get-Item -LiteralPath $full -Force
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw (T 'msg_fe1c44c3e146' -Arguments @(($rel))) }
        $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $full).Hash.ToLowerInvariant()
        if ($hash -ne ([string]$entry.sha256).ToLowerInvariant()) {
            throw (T 'msg_7af85f6d90b3' -Arguments @(($rel)))
        }
    }
    if (-not $sourceExpected.ContainsKey("install.ps1")) {
        throw (T 'msg_87eac2f01935')
    }
    Write-Host (T 'msg_9dea9351ca50') -ForegroundColor Green
}


function Verify-StagingAgainstPreparedManifest {
    param([string]$StageRoot)
    if (-not $script:PreparedManifest) { throw (T 'msg_eba4751ff7af') }

    $RuntimeRoot = Join-Path $StageRoot "runtime"
    $runtimeExpected = @{}
    foreach ($entry in $script:PreparedManifest.runtime_files) {
        $rel = [string]$entry.path
        $full = Join-Path $RuntimeRoot ($rel.Replace('/', '\'))
        if (!(Test-Path -LiteralPath $full -PathType Leaf)) { throw (T 'msg_172b95618f17' -Arguments @(($rel))) }
        $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $full).Hash.ToLowerInvariant()
        if ($hash -ne ([string]$entry.sha256).ToLowerInvariant()) { throw (T 'msg_bd62f917fbcc' -Arguments @(($rel))) }
        $runtimeExpected[$rel.ToLowerInvariant()] = $true
    }
    $runtimeBase = (Resolve-Path $RuntimeRoot).Path
    $runtimeActual = @(Get-ChildItem -Path $RuntimeRoot -File -Recurse | ForEach-Object {
        $_.FullName.Substring($runtimeBase.Length).TrimStart('\','/').Replace('\','/').ToLowerInvariant()
    })
    if ($runtimeActual.Count -ne $runtimeExpected.Count) { throw (T 'msg_43b97560fa5f') }
    foreach ($rel in $runtimeActual) {
        if (-not $runtimeExpected.ContainsKey($rel)) { throw (T 'msg_c77972b0edf1' -Arguments @(($rel))) }
    }

    $sourceExpected = @{}
    foreach ($entry in $script:PreparedManifest.source_files) {
        $rel = [string]$entry.path
        $full = Join-Path $StageRoot ($rel.Replace('/', '\'))
        # Not every release-only source file is installed (for example install.ps1 itself).
        # If it is part of the installed image, it must still match the hash captured before elevation.
        if (Test-Path -LiteralPath $full -PathType Leaf) {
            $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $full).Hash.ToLowerInvariant()
            if ($hash -ne ([string]$entry.sha256).ToLowerInvariant()) { throw (T 'msg_848f08624375' -Arguments @(($rel))) }
            $sourceExpected[$rel.ToLowerInvariant()] = $true
        }
    }
    $base = (Resolve-Path $StageRoot).Path
    foreach ($item in Get-ChildItem -LiteralPath $StageRoot -Force -Recurse -File) {
        $rel = $item.FullName.Substring($base.Length).TrimStart('\','/').Replace('\','/').ToLowerInvariant()
        if ($rel.StartsWith("runtime/")) { continue }
        if (-not $sourceExpected.ContainsKey($rel)) { throw (T 'msg_3b61d162c173' -Arguments @(($rel))) }
    }
}

function Copy-ProjectFiles {
    param([string]$Destination)
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    $files = @(
        "agent.py", "portable.py", "service.py", "lampctl.py", "sleepnow.py",
        "config.example.json", "config.schema.json", "requirements.lock.txt", "requirements.windows.lock.txt", "requirements.miio.lock.txt",
        "pyproject.toml", "LICENSE", "THIRD_PARTY_NOTICES.md", "README.md", "README.es.md", "CHANGELOG.md", "CHANGELOG.es.md", "SECURITY.md", "SECURITY.es.md", "CONTRIBUTING.md", "CONTRIBUTING.es.md",
        "import-token.ps1", "manual-on.cmd", "manual-off.cmd", "status.cmd", "sync.cmd", "sleep-now.cmd",
        "enable-automation.ps1", "disable-automation.ps1", "uninstall.ps1", "security-check.ps1", "config-gui.ps1", "i18n.ps1", "version.ps1"
    )
    foreach ($file in $files) {
        $src = Join-Path $SourceRoot $file
        if (-not (Test-Path -LiteralPath $src -PathType Leaf)) { throw (T 'msg_f3e5143111a3' -Arguments @(($file))) }
        Copy-Item -LiteralPath $src -Destination (Join-Path $Destination $file) -Force
    }
    foreach ($dir in @("mijialamp", "tools", "docs")) {
        $sourceDir = Join-Path $SourceRoot $dir
        $destinationDir = Join-Path $Destination $dir
        New-Item -ItemType Directory -Force -Path $destinationDir | Out-Null
        Get-ChildItem -LiteralPath $sourceDir -File -Recurse | Where-Object { $_.Extension -in @(".py", ".json", ".md") } | ForEach-Object {
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
    Write-Utf8NoBom (Join-Path $RootPath "integrity-manifest.json") ($payload | ConvertTo-Json -Depth 6)
}

function Copy-SafeRegularFile {
    param([string]$Source, [string]$Destination)
    if (!(Test-Path -LiteralPath $Source -PathType Leaf)) { return }
    $item = Get-Item -LiteralPath $Source -Force
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw (T 'msg_14e7c226a2e1' -Arguments @(($Source)))
    }
    Copy-Item -LiteralPath $Source -Destination $Destination -Force
}

function Assert-RegularDirectoryIfPresent {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return }
    $item = Get-Item -LiteralPath $Path -Force
    if (-not $item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw (T 'msg_8250f6cea0fc' -Arguments @(($Path)))
    }
}

function Stop-OldAutomation {
    $task = Get-ScheduledTask -TaskPath "\MijiaLamp\" -TaskName "Lamp Agent" -ErrorAction SilentlyContinue
    if ($task) {
        if ($task.State -eq "Running") {
            Stop-ScheduledTask -TaskPath "\MijiaLamp\" -TaskName "Lamp Agent" -ErrorAction Stop
        }
        Unregister-ScheduledTask -TaskPath "\MijiaLamp\" -TaskName "Lamp Agent" -Confirm:$false -ErrorAction Stop
    }
    $service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if ($service -and $service.Status -ne [ServiceProcess.ServiceControllerStatus]::Stopped) {
        Stop-Service -Name $ServiceName -Force -ErrorAction Stop
        $service.WaitForStatus([ServiceProcess.ServiceControllerStatus]::Stopped, [TimeSpan]::FromSeconds(15))
    }
}

function Delete-ServiceDefinition {
    if (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue) {
        & sc.exe delete $ServiceName | Out-Null
        if ($LASTEXITCODE -ne 0) { throw (T 'msg_9d40c95ba6d4' -Arguments @(($ServiceName))) }
        for ($i=0; $i -lt 30; $i++) {
            if (!(Get-Service -Name $ServiceName -ErrorAction SilentlyContinue)) { break }
            Start-Sleep -Milliseconds 200
        }
        if (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue) {
            throw (T 'msg_53e4aac104bd' -Arguments @(($ServiceName)))
        }
    }
}

function Disable-ServiceDefinition {
    if (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue) {
        & sc.exe config $ServiceName start= disabled | Out-Null
        if ($LASTEXITCODE -ne 0) { throw (T 'msg_b3dd8051993e' -Arguments @(($ServiceName))) }
    }
}

function Install-Service {
    param([string]$Python)
    $script = Join-Path $InstallDir "service.py"
    Delete-ServiceDefinition
    & $Python $script --startup auto install
    if ($LASTEXITCODE -ne 0) { throw (T 'msg_802e26656fad' -Arguments @(($ServiceName))) }
    & sc.exe config $ServiceName obj= "NT AUTHORITY\LocalService" start= delayed-auto | Out-Null
    if ($LASTEXITCODE -ne 0) { throw (T 'msg_33772dcf2cd3') }
    & sc.exe sidtype $ServiceName unrestricted | Out-Null
    if ($LASTEXITCODE -ne 0) { throw (T 'msg_b93c92b55a42') }
    # Drop optional token privileges from LocalService. MijiaLamp does not impersonate
    # clients and only needs ordinary file/network access plus traverse checking.
    & sc.exe privs $ServiceName SeChangeNotifyPrivilege | Out-Null
    if ($LASTEXITCODE -ne 0) { throw (T 'msg_dbc06bae4165') }
    & sc.exe failure $ServiceName reset= 86400 actions= restart/5000/restart/15000/restart/60000 | Out-Null
    & $Python (Join-Path $InstallDir "tools\configure_windows_service.py")
    if ($LASTEXITCODE -ne 0) { throw (T 'msg_e837ec9864a3') }
}

function Set-SecureAcls {
    param([string]$UserSid)
    $svc = "NT SERVICE\$ServiceName"
    Set-SecureTreeAcl $InstallDir @(
        '*S-1-5-18:(OI)(CI)F', '*S-1-5-32-544:(OI)(CI)F', "*${UserSid}:(OI)(CI)RX", "${svc}:(OI)(CI)RX")
    foreach ($name in @("runtime", "mijialamp", "tools")) {
        $path = Join-Path $InstallDir $name
        if (Test-Path $path) {
            Set-SecureTreeAcl $path @(
                '*S-1-5-18:(OI)(CI)F', '*S-1-5-32-544:(OI)(CI)F', "*${UserSid}:(OI)(CI)RX", "${svc}:(OI)(CI)RX")
        }
    }
    $data = Join-Path $InstallDir "data"
    Set-SecureTreeAcl $data @(
        '*S-1-5-18:(OI)(CI)F', '*S-1-5-32-544:(OI)(CI)F', "${svc}:(OI)(CI)M", "*${UserSid}:(OI)(CI)R")
    $logs = Join-Path $InstallDir "logs"
    Set-SecureTreeAcl $logs @(
        '*S-1-5-18:(OI)(CI)F', '*S-1-5-32-544:(OI)(CI)F', "${svc}:(OI)(CI)M", "*${UserSid}:(OI)(CI)M")
    $secrets = Join-Path $InstallDir "secrets"
    Set-SecureTreeAcl $secrets @(
        '*S-1-5-18:(OI)(CI)F', '*S-1-5-32-544:(OI)(CI)F', "${svc}:(OI)(CI)F")
    $cfg = Join-Path $InstallDir "config.json"
    Invoke-CheckedIcacls $cfg @('/inheritance:r', '/grant:r',
        '*S-1-5-18:F', '*S-1-5-32-544:F', "${svc}:R", "*${UserSid}:M")
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
    try { Stop-Service -Name $ServiceName -Force -ErrorAction Stop } catch { Write-Warning $_.Exception.Message }
    try { Disable-ServiceDefinition } catch { Write-Warning $_.Exception.Message }
    try { Delete-ServiceDefinition } catch { Write-Warning $_.Exception.Message }
    try { Unregister-ScheduledTask -TaskPath "\MijiaLamp\" -TaskName "Lamp Agent" -Confirm:$false -ErrorAction SilentlyContinue } catch {}
    if (Test-Path $InstallDir) {
        $failed = "$InstallDir.failed-$([DateTime]::UtcNow.ToString('yyyyMMddHHmmss'))"
        Move-Item -LiteralPath $InstallDir -Destination $failed -ErrorAction Stop
    }
    if ($script:Backup -and (Test-Path $script:Backup)) {
        Move-Item -LiteralPath $script:Backup -Destination $InstallDir -ErrorAction Stop
        Write-Warning "Archivos anteriores restaurados en $InstallDir."
    }
    Write-Warning (T 'msg_9d2743ef985e')
}

Assert-OfficialInstallDir
Assert-Administrator
if ((Resolve-Path $SourceRoot).Path -eq $InstallDir -or $SourceRoot -like "$InstallDir\*") {
    throw (T 'msg_58ab8c73a44c' -Arguments @(($InstallDir)))
}
Write-InstallProgress 0 'Comprobando archivos y permisos'
Verify-PreparedRuntime
Write-InstallProgress 18 'Archivos comprobados'
$InteractiveIdentity = Resolve-InteractiveIdentity -Override $InteractiveUser
$UserName = $InteractiveIdentity.Name
$UserSid = $InteractiveIdentity.Sid
Write-Host "== MijiaLamp v$ProjectVersion hardened service install ==" -ForegroundColor Cyan
Write-Host (T 'msg_1ff3ef6d4ebd' -Arguments @(($UserName), ($UserSid)))
Write-Host "La fase elevada NO usa pip ni Internet." -ForegroundColor Green

try {
    foreach ($path in @($InstallDir, (Join-Path $InstallDir "data"), (Join-Path $InstallDir "secrets"))) {
        Assert-RegularDirectoryIfPresent -Path $path
    }
    New-PrivateDirectory -Path $Staging
    $StagingCreated = $true
    Write-InstallProgress 20 (T 'msg_ec9c6a6905c5')
    Copy-ProjectFiles -Destination $Staging
    Copy-Item -Recurse -Force $PreparedPython (Join-Path $Staging "runtime")
    Write-InstallProgress 36 (T 'msg_d7f45d0f79bf')
    Verify-StagingAgainstPreparedManifest -StageRoot $Staging
    Write-InstallProgress 48 (T 'msg_7ba7765586eb')
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
    Write-Utf8NoBom (Join-Path $Staging "data\service_meta.json") ($ServiceMeta | ConvertTo-Json)

    $StagePython = Join-Path $Staging "runtime\python.exe"
    Push-Location $Staging
    try {
        & $StagePython -m compileall -q .\mijialamp .\tools .\agent.py .\service.py .\lampctl.py .\sleepnow.py
        if ($LASTEXITCODE -ne 0) { throw (T 'msg_4daddb8156bb') }
        & $StagePython .\tools\migrate_legacy_config.py --scope local-machine $DestinationConfig
        if ($LASTEXITCODE -ne 0) { throw (T 'msg_09ff808bb0c3') }
        & $StagePython .\lampctl.py config-check
        if ($LASTEXITCODE -ne 0) { throw (T 'msg_8c0092965ef6') }
        # A previous installation may have automation_enabled=true in its saved state.
        # Keep its other state for recovery, but never start a new installation active
        # unless -EnableAutomation explicitly requests that after doctor succeeds.
        & $StagePython -c "from mijialamp.state import StateStore; StateStore().update(automation_enabled=False)"
        if ($LASTEXITCODE -ne 0) { throw (T 'msg_4fd9ac361aaa') }
        & $StagePython -c "import sys, site, pathlib, miio, win32service, win32serviceutil, astral, cryptography, mijialamp; root = pathlib.Path(sys.executable).resolve().parent.parent; assert site.getusersitepackages() not in sys.path; assert all(pathlib.Path(p).resolve().is_relative_to(root) for p in sys.path); print('runtime-smoke: OK')"
        if ($LASTEXITCODE -ne 0) { throw (T 'msg_320ece8f74da') }
    } finally { Pop-Location }
    Write-InstallProgress 60 (T 'msg_469318675f10')

    # Do not install import caches as mutable executable artifacts. The protected runtime
    # can import source directly and the service has no reason to write into code dirs.
    Get-ChildItem $Staging -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    Get-ChildItem $Staging -Recurse -File -Include "*.pyc", "*.pyo" -ErrorAction SilentlyContinue |
        Remove-Item -Force -ErrorAction SilentlyContinue
    if (Test-Path $InstallDir) {
        $backupRoot = Join-Path (Split-Path -Parent $InstallDir) "MijiaLamp-backups"
        if (Test-Path -LiteralPath $backupRoot) {
            Assert-PrivateDirectory -Path $backupRoot
        } else {
            New-PrivateDirectory -Path $backupRoot
        }
    }
    $OldAutomationStopped = $true
    Stop-OldAutomation
    if (Test-Path $InstallDir) {
        $backupPath = Join-Path $backupRoot (Get-Date -Format "yyyyMMdd-HHmmss-$([Guid]::NewGuid().ToString('N'))")
        Move-Item $InstallDir $backupPath
        $script:Backup = $backupPath
    }
    Move-Item $Staging $InstallDir
    $Swapped = $true
    Write-InstallProgress 68 (T 'msg_e1721c328a7c')

    $Python = Join-Path $InstallDir "runtime\python.exe"
    $Pythonw = Join-Path $InstallDir "runtime\pythonw.exe"
    Install-Service -Python $Python
    # pywin32 moves pythonservice.exe and copies a DLL into runtime during install.
    # Record the final protected tree so the security check sees the actual files.
    Write-IntegrityManifest -RootPath $InstallDir
    Set-SecureAcls -UserSid $UserSid
    Register-AgentTask -UserName $UserName -Pythonw $Pythonw
    Write-InstallProgress 78 (T 'msg_c1738417af82')
    Start-Service -Name $ServiceName

    $ServiceReady = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        & $Python (Join-Path $InstallDir "lampctl.py") service-status *> $null
        if ($LASTEXITCODE -eq 0) { $ServiceReady = $true; break }
        Start-Sleep -Milliseconds 400
    }
    if (-not $ServiceReady) { throw (T 'msg_fc784b4c7755') }
    Write-InstallProgress 84 (T 'msg_5865177baf13')

    if ($EncryptedTokenSource) {
        $tokenSourceItem = Get-Item -LiteralPath $EncryptedTokenSource -Force
        if ($tokenSourceItem.PSIsContainer -or $tokenSourceItem.Length -gt 8192 -or
            ($tokenSourceItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw (T 'msg_1e71d3b5a69d')
        }
        Write-Host (T 'msg_5942ec50db54')
        & (Join-Path $InstallDir "import-token.ps1") -Mode Service -EncryptedSource $EncryptedTokenSource
        if ($LASTEXITCODE -ne 0) { throw (T 'msg_63d832967a8d') }
        $ServiceReady = $false
        for ($attempt = 0; $attempt -lt 30; $attempt++) {
            & $Python (Join-Path $InstallDir "lampctl.py") service-status *> $null
            if ($LASTEXITCODE -eq 0) { $ServiceReady = $true; break }
            Start-Sleep -Milliseconds 400
        }
        if (-not $ServiceReady) { throw (T 'msg_7c57fee1a77a') }
    }
    Write-InstallProgress 89 (T 'msg_ce1e26e33ee8')
    & (Join-Path $InstallDir "security-check.ps1") -InstallDir $InstallDir -InteractiveUser $UserName
    if ($LASTEXITCODE -ne 0) { throw (T 'msg_b95d4d442b97') }

    if ($CreatedExampleConfig) {
        Write-Host (T 'msg_257d16ede8da' -Arguments @(($InstallDir))) -ForegroundColor Yellow
    }
    if (Test-Path (Join-Path $InstallDir "secrets\token.dpapi.json")) {
        Write-Host (T 'msg_a1b20d5425a3') -ForegroundColor Green
    } else {
        Write-Host (T 'msg_a79a9a65580e') -ForegroundColor Yellow
    }

    Write-InstallProgress 95 (T 'msg_68438a6b9007')
    if ($EnableAutomation -and (Test-Path (Join-Path $InstallDir "secrets\token.dpapi.json"))) {
        & (Join-Path $InstallDir "enable-automation.ps1") -InstallDir $InstallDir
        if ($LASTEXITCODE -ne 0) { throw (T 'msg_b1f936e329bf') }
    } else {
        Write-Host (T 'msg_3331411241dc') -ForegroundColor Yellow
    }
    if ($ShowTray -and -not $EnableAutomation) {
        Enable-ScheduledTask -TaskPath "\MijiaLamp\" -TaskName "Lamp Agent" | Out-Null
        Start-ScheduledTask -TaskPath "\MijiaLamp\" -TaskName "Lamp Agent"
    }
    Write-Host (T 'msg_34850f22b786' -Arguments @(($ProjectVersion))) -ForegroundColor Green
    Write-InstallProgress 100 'Servicio instalado y comprobado'
} catch {
    Write-Host (T 'msg_6cc311e5eec3' -Arguments @(($_.Exception.Message))) -ForegroundColor (T 'msg_ba19e9c3d5f4')
    if ($Swapped -or $Backup) {
        Restore-PreviousInstall
    } elseif ($OldAutomationStopped) {
        # The previous files are still in place; do not execute or resume them after failure.
        try { Stop-Service -Name $ServiceName -Force -ErrorAction Stop } catch { Write-Warning $_.Exception.Message }
        try { Disable-ServiceDefinition } catch { Write-Warning $_.Exception.Message }
        Write-Warning (T 'msg_3f6b286dc974')
    }
    if ($StagingCreated -and (Test-Path -LiteralPath $Staging)) {
        Remove-Item -LiteralPath $Staging -Recurse -Force -ErrorAction SilentlyContinue
    }
    throw
}
