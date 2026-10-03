$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

function Read-ScriptAst {
    param([string]$Path)
    $tokens = $null
    $errors = $null
    $ast = [Management.Automation.Language.Parser]::ParseFile($Path, [ref]$tokens, [ref]$errors)
    if ($errors.Count -gt 0) { throw "Errores de sintaxis en $Path" }
    return $ast
}

$installerAst = Read-ScriptAst (Join-Path $root "install.ps1")
$rollback = $installerAst.FindAll({
    param($node)
    $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
    $node.Name -eq "Restore-PreviousInstall"
}, $false) | Select-Object -First 1
if (-not $rollback) { throw "Falta Restore-PreviousInstall" }

$rollbackCommands = @($rollback.FindAll({
    param($node)
    $node -is [Management.Automation.Language.CommandAst]
}, $true))
foreach ($command in $rollbackCommands) {
    if ($command.InvocationOperator -ne [Management.Automation.Language.TokenKind]::Unknown -or
        $command.GetCommandName() -in @("Start-Service", "Register-ScheduledTask", "Start-Process", "Invoke-Expression", "python.exe", "service.py")) {
        throw "El rollback intenta ejecutar o reactivar código anterior: $($command.Extent.Text)"
    }
}

$uninstallerAst = Read-ScriptAst (Join-Path $root "uninstall.ps1")
$uninstallCommands = @($uninstallerAst.FindAll({
    param($node)
    $node -is [Management.Automation.Language.CommandAst]
}, $true))
foreach ($command in $uninstallCommands) {
    if (($command.InvocationOperator -ne [Management.Automation.Language.TokenKind]::Unknown -and
        $command.GetCommandName() -ne "sc.exe") -or
        $command.GetCommandName() -in @("Start-Process", "Invoke-Expression", "python.exe", "service.py")) {
        throw "El desinstalador invoca un ejecutable no controlado: $($command.Extent.Text)"
    }
}

# Exercise file restoration without touching a real Windows service.
. ([scriptblock]::Create($rollback.Extent.Text))
function Stop-Service { param($Name, [switch]$Force, $ErrorAction) $script:stopped = $true }
function Disable-ServiceDefinition { $script:disabled = $true }
function Delete-ServiceDefinition { $script:deleted = $true }
function Unregister-ScheduledTask { param($TaskPath, $TaskName, $Confirm, $ErrorAction) }

$testRoot = Join-Path ([IO.Path]::GetTempPath()) "mijialamp-recovery-$([Guid]::NewGuid().ToString('N'))"
$InstallDir = Join-Path $testRoot "installed"
$script:Backup = Join-Path $testRoot "previous"
$ServiceName = "MijiaLampService"
New-Item -ItemType Directory -Path $InstallDir, $script:Backup -Force | Out-Null
Set-Content -LiteralPath (Join-Path $InstallDir "new.txt") -Value "failed installation"
Set-Content -LiteralPath (Join-Path $script:Backup "old.txt") -Value "previous installation"
try {
    Restore-PreviousInstall
    if (-not $script:stopped -or -not $script:disabled -or -not $script:deleted) {
        throw "No se detuvo/deshabilitó/eliminó el servicio nuevo"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $InstallDir "old.txt"))) { throw "No se restauraron los archivos anteriores" }
    if (Test-Path -LiteralPath (Join-Path $InstallDir "new.txt")) { throw "La instalación fallida quedó en el destino" }
    if (@(Get-ChildItem -LiteralPath $testRoot -Directory -Filter "installed.failed-*").Count -ne 1) {
        throw "No se apartó la instalación fallida"
    }
} finally {
    Remove-Item -LiteralPath $testRoot -Recurse -Force
}

Write-Host "Installer recovery: OK"
