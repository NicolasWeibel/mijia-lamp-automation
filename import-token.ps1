param(
    [string]$Source = "",
    [string]$Did = "",
    [ValidateSet("Service", "Portable")]
    [string]$Mode = "Service"
)
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
    throw "No existe un runtime Python preparado. Ejecutá setup-portable.ps1 en modo Portable o prepare-service-runtime.ps1 antes de instalar el modo Service."
}

if ($Mode -eq "Service") {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Modo Service: ejecutá import-token.ps1 desde PowerShell como Administrador."
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
& $Python @ArgsList
$ExitCode = $LASTEXITCODE

if ($ExitCode -eq 0) {
    if ($Mode -eq "Service") {
        Restart-Service MijiaLampService -ErrorAction SilentlyContinue
        Write-Host "Token Service importado y servicio reiniciado; el valor nunca fue mostrado." -ForegroundColor Green
    } else {
        Write-Host "Token Portable importado con DPAPI CurrentUser; el valor nunca fue mostrado." -ForegroundColor Green
    }
}
exit $ExitCode
