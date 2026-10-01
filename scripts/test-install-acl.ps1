$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$installer = Join-Path $root "install.ps1"
$tokens = $null
$errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($installer, [ref]$tokens, [ref]$errors)
if ($errors.Count -gt 0) { throw "install.ps1 contiene errores de sintaxis" }

# Load only the ACL helpers; the installer's top-level code must never run in CI.
$names = @("Assert-PrivateDirectory", "New-PrivateDirectory", "Invoke-CheckedIcacls")
foreach ($function in $ast.FindAll({
    param($node)
    $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -in $names
}, $false)) {
    . ([scriptblock]::Create($function.Extent.Text))
}
foreach ($name in $names) {
    if (-not (Get-Command $name -CommandType Function -ErrorAction SilentlyContinue)) {
        throw "Falta helper del instalador: $name"
    }
}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Esta prueba requiere el token elevado del runner Windows"
}

$testRoot = Join-Path $env:RUNNER_TEMP "mijialamp-acl-$([Guid]::NewGuid().ToString('N'))"
New-Item -ItemType Directory -Path $testRoot | Out-Null
try {
    $private = Join-Path $testRoot "private"
    New-PrivateDirectory -Path $private
    Assert-PrivateDirectory -Path $private

    $duplicateRejected = $false
    try { New-PrivateDirectory -Path $private } catch { $duplicateRejected = $true }
    if (-not $duplicateRejected) { throw "Se aceptó un directorio preexistente" }

    $unsafe = Join-Path $testRoot "unsafe"
    New-Item -ItemType Directory -Path $unsafe | Out-Null
    $unsafeRejected = $false
    try { Assert-PrivateDirectory -Path $unsafe } catch { $unsafeRejected = $true }
    if (-not $unsafeRejected) { throw "Se aceptó un directorio con ACL heredada" }

    $icaclsRejected = $false
    try { Invoke-CheckedIcacls (Join-Path $testRoot "missing") @('/inheritance:r') }
    catch { $icaclsRejected = $true }
    if (-not $icaclsRejected) { throw "Se ignoró un fallo de icacls" }
} finally {
    Remove-Item -LiteralPath $testRoot -Recurse -Force
}

Write-Host "Installer ACL helpers: OK"
