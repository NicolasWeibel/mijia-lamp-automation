param(
    [string]$InstallDir = "C:\ProgramData\MijiaLamp",
    [string]$InteractiveUser = ""
)
$ErrorActionPreference = "Stop"
$ServiceName = "MijiaLampService"
$Failures = New-Object System.Collections.Generic.List[string]

function Fail([string]$Message) {
    $Failures.Add($Message)
    Write-Host "[FAIL] $Message" -ForegroundColor Red
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
            [Security.AccessControl.FileSystemRights]::CreateFiles -bor
            [Security.AccessControl.FileSystemRights]::AppendData -bor
            [Security.AccessControl.FileSystemRights]::Delete -bor
            [Security.AccessControl.FileSystemRights]::ChangePermissions -bor
            [Security.AccessControl.FileSystemRights]::TakeOwnership -bor
            [Security.AccessControl.FileSystemRights]::Modify -bor
            [Security.AccessControl.FileSystemRights]::FullControl
        if (($rights -band $dangerous) -ne 0) { return $true }
    }
    return $false
}

Write-Host "== MijiaLamp hardened security check ==" -ForegroundColor Cyan
$Sid = Resolve-UserSid $InteractiveUser
if (-not $Sid) { Fail "No pude resolver SID del usuario interactivo" } else { Pass "Usuario interactivo SID=$Sid" }

$svc = Get-CimInstance Win32_Service -Filter "Name='$ServiceName'" -ErrorAction SilentlyContinue
if (-not $svc) {
    Fail "$ServiceName no está instalado"
} else {
    if ($svc.StartName -ieq "NT AUTHORITY\LocalService") { Pass "Servicio usa LocalService" }
    else { Fail "Servicio usa cuenta inesperada: $($svc.StartName)" }
    if ($svc.PathName -and $svc.PathName.ToLowerInvariant().Contains($InstallDir.ToLowerInvariant())) {
        Pass "Ejecutable del servicio está dentro del árbol protegido"
    } else { Fail "ImagePath del servicio no apunta al runtime protegido: $($svc.PathName)" }
    if ($svc.State -eq "Running") { Pass "Servicio en ejecución" } else { Fail "Servicio no está Running ($($svc.State))" }

    if ($svc.ProcessId -gt 0) {
        try {
            $listeners = @(Get-NetTCPConnection -State Listen -OwningProcess $svc.ProcessId -ErrorAction SilentlyContinue)
            if ($listeners.Count -eq 0) { Pass "Servicio no expone listeners TCP" }
            else { Fail "Servicio tiene listeners TCP inesperados" }
        } catch { Write-Host "[WARN] No pude consultar listeners TCP." -ForegroundColor Yellow }
    }
}

$privPath = "HKLM:\SYSTEM\CurrentControlSet\Services\$ServiceName"
try {
    $required = @((Get-ItemProperty $privPath -Name RequiredPrivileges -ErrorAction Stop).RequiredPrivileges)
    $normalized = @($required | Where-Object { $_ })
    if ($normalized.Count -eq 1 -and $normalized[0] -eq "SeChangeNotifyPrivilege") {
        Pass "RequiredPrivileges reducido a SeChangeNotifyPrivilege"
    } else { Fail "RequiredPrivileges inesperados: $($normalized -join ', ')" }
} catch { Fail "No pude validar RequiredPrivileges" }

foreach ($path in @($InstallDir, (Join-Path $InstallDir "runtime"), (Join-Path $InstallDir "mijialamp"))) {
    if (User-HasWriteAce $path $Sid) { Fail "Usuario tiene ACE de escritura en código/runtime: $path" }
    else { Pass "Usuario sin escritura en código/runtime: $path" }
}
$Secrets = Join-Path $InstallDir "secrets"
if (User-HasWriteAce $Secrets $Sid) { Fail "Usuario tiene escritura en secrets" }
else {
    $acl = Get-Acl $Secrets
    $hasUserAce = $false
    foreach ($rule in $acl.Access) {
        try { $ruleSid = $rule.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value }
        catch { continue }
        if ($ruleSid -eq $Sid) { $hasUserAce = $true }
    }
    if ($hasUserAce) { Fail "Usuario tiene ACE explícita sobre secrets" }
    else { Pass "secrets no concede acceso al usuario interactivo" }
}


$IntegrityPath = Join-Path $InstallDir "integrity-manifest.json"
if (!(Test-Path $IntegrityPath -PathType Leaf)) {
    Fail "Falta integrity-manifest.json"
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
        if ($bad.Count -eq 0) { Pass "Código/runtime coinciden con integrity-manifest.json" }
        else { Fail "Integridad de archivos protegidos falló: $($bad -join ', ')" }
    } catch { Fail "No pude validar integrity-manifest.json: $($_.Exception.Message)" }
}

$Python = Join-Path $InstallDir "runtime\python.exe"
if (Test-Path $Python) {
    & $Python -c "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('pip') is None else 1)"
    if ($LASTEXITCODE -eq 0) { Pass "Runtime del servicio no contiene pip" }
    else { Fail "Runtime del servicio todavía contiene pip" }
    & $Python (Join-Path $InstallDir "lampctl.py") service-status *> $null
    if ($LASTEXITCODE -eq 0) { Pass "Named Pipe local responde" } else { Fail "Named Pipe no responde" }
    if (Test-Path (Join-Path $InstallDir "secrets\token.dpapi.json")) {
        & $Python -c "from mijialamp.secrets_store import token_metadata; import sys; sys.exit(0 if token_metadata().get('scope') == 'local-machine' else 1)"
        if ($LASTEXITCODE -eq 0) { Pass "Token DPAPI usa scope LocalMachine" }
        else { Fail "Token existente no usa scope LocalMachine" }
    }
} else { Fail "Falta runtime\python.exe" }

if ($Failures.Count -gt 0) {
    Write-Host "Security check: $($Failures.Count) fallo(s)." -ForegroundColor Red
    exit 1
}
Write-Host "Security check: OK" -ForegroundColor Green
exit 0
