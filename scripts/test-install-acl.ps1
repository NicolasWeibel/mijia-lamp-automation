$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$installer = Join-Path $root "install.ps1"
$tokens = $null
$errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($installer, [ref]$tokens, [ref]$errors)
if ($errors.Count -gt 0) { throw "install.ps1 contiene errores de sintaxis" }

# Load only the ACL helpers; the installer's top-level code must never run in CI.
$names = @("Assert-PrivateDirectory", "New-PrivateDirectory", "Invoke-CheckedIcacls", "Set-SecureTreeAcl", "Write-Utf8NoBom")
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

$securityAst = [Management.Automation.Language.Parser]::ParseFile(
    (Join-Path $root "security-check.ps1"), [ref]$tokens, [ref]$errors)
if ($errors.Count -gt 0) { throw "security-check.ps1 contiene errores de sintaxis" }
$writeCheck = $securityAst.Find({
    param($node)
    $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq "User-HasWriteAce"
}, $false)
if (-not $writeCheck) { throw "Falta User-HasWriteAce" }
. ([scriptblock]::Create($writeCheck.Extent.Text))

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

    $tree = Join-Path $testRoot "secure-tree"
    $nested = Join-Path $tree "nested"
    $child = Join-Path $nested "sample.exe"
    New-Item -ItemType Directory -Path $nested | Out-Null
    Set-Content -LiteralPath $child -Value "sample"
    Invoke-CheckedIcacls $child @('/grant:r', '*S-1-1-0:F')

    $userSid = $identity.User.Value
    Set-SecureTreeAcl $tree @('*S-1-5-18:(OI)(CI)F', '*S-1-5-32-544:(OI)(CI)F', "*${userSid}:(OI)(CI)RX")
    $childSids = @((Get-Acl $child).Access | ForEach-Object {
        $_.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value
    })
    if ('S-1-1-0' -in $childSids -or 'S-1-5-18' -notin $childSids -or $userSid -notin $childSids) {
        throw "Los archivos hijos no heredaron solamente la ACL restringida"
    }
    if (User-HasWriteAce $child $userSid) { throw "RX fue clasificado como escritura" }
    Invoke-CheckedIcacls $child @('/grant:r', "*${userSid}:M")
    if (-not (User-HasWriteAce $child $userSid)) { throw "Modify no fue detectado como escritura" }

    $jsonPath = Join-Path $testRoot "utf8.json"
    Write-Utf8NoBom $jsonPath '{"valid":true}'
    $bytes = [IO.File]::ReadAllBytes($jsonPath)
    if ($bytes.Length -lt 3 -or ($bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF)) {
        throw "Write-Utf8NoBom generó BOM o archivo vacío"
    }
} finally {
    Remove-Item -LiteralPath $testRoot -Recurse -Force
}

Write-Host "Installer ACL helpers: OK"
exit 0
