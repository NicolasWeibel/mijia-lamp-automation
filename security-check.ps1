param(
    [string]$InstallDir = "C:\ProgramData\MijiaLamp",
    [string]$InteractiveUser = ""
)
. (Join-Path $PSScriptRoot 'i18n.ps1')
Initialize-MijiaLampLanguage -ConfigPath $ConfigPath
$ErrorActionPreference = "Stop"
$ServiceName = "MijiaLampService"
$Failures = New-Object System.Collections.Generic.List[string]

function Fail([string]$Message) {
    $Failures.Add($Message)
    Write-Host "[FAIL] $Message" -ForegroundColor (T 'msg_ba19e9c3d5f4')
}
function Pass([string]$Message) { Write-Host "[ OK ] $Message" -ForegroundColor Green }

function Resolve-UserSid([string]$Name) {
    if (-not $Name) {
        try { $Name = (Get-CimInstance Win32_ComputerSystem -ErrorAction Stop).UserName } catch {}
    }
    if (-not $Name) { return $null }
    try {
        $account = New-Object Security.Principal.NTAccount($Name)
        return $account.Translate([Security.Principal.SecurityIdentifier]).Value
    } catch { return $null }
}

function User-HasWriteAce([string]$Path, [string]$Sid) {
    if (!(Test-Path $Path) -or -not $Sid) { return $false }
    $acl = Get-Acl $Path
    foreach ($rule in $acl.Access) {
        try { $ruleSid = $rule.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value }
        catch { continue }
        if ($ruleSid -ne $Sid -or $rule.AccessControlType -ne "Allow") { continue }
        $rights = [Security.AccessControl.FileSystemRights]$rule.FileSystemRights
        $dangerous = [Security.AccessControl.FileSystemRights]::WriteData -bor
            [Security.AccessControl.FileSystemRights]::AppendData -bor
            [Security.AccessControl.FileSystemRights]::WriteExtendedAttributes -bor
            [Security.AccessControl.FileSystemRights]::WriteAttributes -bor
            [Security.AccessControl.FileSystemRights]::Delete -bor
            [Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles -bor
            [Security.AccessControl.FileSystemRights]::ChangePermissions -bor
            [Security.AccessControl.FileSystemRights]::TakeOwnership
        if (($rights -band $dangerous) -ne 0) { return $true }
    }
    return $false
}

Write-Host "== MijiaLamp hardened security check ==" -ForegroundColor Cyan
$Sid = Resolve-UserSid $InteractiveUser
if (-not $Sid) { Fail (T 'msg_78466ccee83b') } else { Pass (T 'msg_b659ae05a03a' -Arguments @(($Sid))) }

$svc = Get-CimInstance Win32_Service -Filter "Name='$ServiceName'" -ErrorAction SilentlyContinue
if (-not $svc) {
    Fail (T 'msg_f53bf45a6b6e' -Arguments @(($ServiceName)))
} else {
    if ($svc.StartName -ieq "NT AUTHORITY\LocalService") { Pass "Servicio usa LocalService" }
    else { Fail "Servicio usa cuenta inesperada: $($svc.StartName)" }
    if ($svc.PathName -and $svc.PathName.ToLowerInvariant().Contains($InstallDir.ToLowerInvariant())) {
        Pass (T 'msg_46726ac23fe5')
    } else { Fail (T 'msg_de0153d9a088' -Arguments @(($svc.PathName))) }
    if ($svc.State -eq "Running") { Pass (T 'msg_29198fce68a1') } else { Fail (T 'msg_41ac307315f8' -Arguments @(($svc.State))) }

    if ($svc.ProcessId -gt 0) {
        try {
            $listeners = @(Get-NetTCPConnection -State Listen -OwningProcess $svc.ProcessId -ErrorAction SilentlyContinue)
            if ($listeners.Count -eq 0) { Pass (T 'msg_4fb74e808510') }
            else { Fail (T 'msg_923050c63d4a') }
        } catch { Write-Host (T 'msg_76a16f31f5cb') -ForegroundColor Yellow }
    }
}

$privPath = "HKLM:\SYSTEM\CurrentControlSet\Services\$ServiceName"
try {
    $required = @((Get-ItemProperty $privPath -Name RequiredPrivileges -ErrorAction Stop).RequiredPrivileges)
    $normalized = @($required | Where-Object { $_ })
    if ($normalized.Count -eq 1 -and $normalized[0] -eq "SeChangeNotifyPrivilege") {
        Pass "RequiredPrivileges reducido a SeChangeNotifyPrivilege"
    } else { Fail "RequiredPrivileges inesperados: $($normalized -join ', ')" }
} catch { Fail (T 'msg_8c644e1c9eae') }

foreach ($path in @($InstallDir, (Join-Path $InstallDir "runtime"), (Join-Path $InstallDir "mijialamp"))) {
    if (User-HasWriteAce $path $Sid) { Fail (T 'msg_bcaa8c0ccae0' -Arguments @(($path))) }
    else { Pass (T 'msg_f0b87aa7db1a' -Arguments @(($path))) }
}
$Secrets = Join-Path $InstallDir "secrets"
if (User-HasWriteAce $Secrets $Sid) { Fail (T 'msg_988568dd077e') }
else {
    $acl = Get-Acl $Secrets
    $hasUserAce = $false
    foreach ($rule in $acl.Access) {
        try { $ruleSid = $rule.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value }
        catch { continue }
        if ($ruleSid -eq $Sid) { $hasUserAce = $true }
    }
    if ($hasUserAce) { Fail (T 'msg_354e3d0c0b54') }
    else { Pass (T 'msg_2c5d03c0662c') }
}


$IntegrityPath = Join-Path $InstallDir "integrity-manifest.json"
if (!(Test-Path $IntegrityPath -PathType Leaf)) {
    Fail (T 'msg_8be3864097aa')
} else {
    try {
        $integrity = Get-Content $IntegrityPath -Raw | ConvertFrom-Json
        $bad = New-Object System.Collections.Generic.List[string]
        foreach ($entry in $integrity.files) {
            $rel = [string]$entry.path
            if (-not $rel -or $rel.Contains("..") -or [IO.Path]::IsPathRooted($rel)) {
                $bad.Add("ruta insegura:$rel")
                continue
            }
            $full = Join-Path $InstallDir ($rel.Replace('/', '\'))
            if (!(Test-Path -LiteralPath $full -PathType Leaf)) {
                $bad.Add("falta:$rel")
                continue
            }
            $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $full).Hash.ToLowerInvariant()
            if ($hash -ne ([string]$entry.sha256).ToLowerInvariant()) { $bad.Add("hash:$rel") }
        }
        if ($bad.Count -eq 0) { Pass (T 'msg_a32f1621ba67') }
        else { Fail (T 'msg_ee24f3dfe248' -Arguments @(($bad -join ', '))) }
    } catch { Fail (T 'msg_bef5f04beaf0' -Arguments @(($_.Exception.Message))) }
}

$Python = Join-Path $InstallDir "runtime\python.exe"
if (Test-Path $Python) {
    & $Python -c "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('pip') is None else 1)"
    if ($LASTEXITCODE -eq 0) { Pass (T 'msg_9cac14293558') }
    else { Fail (T 'msg_6736c71dba77') }
    & $Python (Join-Path $InstallDir "lampctl.py") service-status *> $null
    if ($LASTEXITCODE -eq 0) { Pass "Named Pipe local responde" } else { Fail (T 'msg_63052775fe01') }
    if (Test-Path (Join-Path $InstallDir "secrets\token.dpapi.json")) {
        & $Python -c "from mijialamp.secrets_store import token_metadata; import sys; sys.exit(0 if token_metadata().get('scope') == 'local-machine' else 1)"
        if ($LASTEXITCODE -eq 0) { Pass "Token DPAPI usa scope LocalMachine" }
        else { Fail (T 'msg_0318f9d81331') }
    }
} else { Fail (T 'msg_3563a00782f2') }

if ($Failures.Count -gt 0) {
    Write-Host (T 'msg_fe8623e72889' -Arguments @(($Failures.Count))) -ForegroundColor (T 'msg_ba19e9c3d5f4')
    exit 1
}
Write-Host "Security check: OK" -ForegroundColor Green
exit 0
