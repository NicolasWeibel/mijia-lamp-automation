param(
    [string]$Source = "",
    [string]$EncryptedSource = "",
    [string]$Did = "",
    [ValidateSet("Service", "Portable")]
    [string]$Mode = "Service"
)
. (Join-Path $PSScriptRoot 'i18n.ps1')
Initialize-MijiaLampLanguage -ConfigPath $ConfigPath
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = if ($Mode -eq "Service") {
    $candidate = Join-Path $Root "runtime\python.exe"
    if (Test-Path $candidate) { $candidate } else { Join-Path $Root ".venv\Scripts\python.exe" }
} else {
    $candidate = Join-Path $Root "runtime\python.exe"
    if (Test-Path $candidate) { $candidate } else { Join-Path $Root ".venv\Scripts\python.exe" }
}
$Importer = Join-Path $Root "tools\import_mihome_token.py"

if (!(Test-Path $Python)) {
    throw (T 'msg_aafaa7a415a2')
}

if ($Mode -eq "Service") {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw (T 'msg_dcf2135919f0')
    }
    $Scope = "local-machine"
} else {
    # CurrentUser is intentional: the portable secret can only be decrypted by this
    # Windows user and never requires elevation.
    $Scope = "current-user"
}

$ArgsList = @($Importer, "--scope", $Scope)
if ($Did) { $ArgsList += @("--did", $Did) }
if ($Source) { $ArgsList += @("--source", $Source) }
if ($EncryptedSource) { $ArgsList += @("--encrypted-source", $EncryptedSource) }
& $Python @ArgsList
$ExitCode = $LASTEXITCODE

if ($ExitCode -eq 0) {
    if ($Mode -eq "Service") {
        Restart-Service MijiaLampService -ErrorAction SilentlyContinue
        Write-Host (T 'msg_95dd5c2acfc6') -ForegroundColor Green
    } else {
        Write-Host (T 'msg_6d951dba5f33') -ForegroundColor Green
    }
}
exit $ExitCode
