$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $projectRoot 'i18n.ps1')
Initialize-MijiaLampLanguage -Language en
$tokens = $null
$parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile(
    (Join-Path $projectRoot 'config-gui.ps1'), [ref]$tokens, [ref]$parseErrors
)
if ($parseErrors.Count) { throw 'Settings script could not be parsed.' }
$saveFunction = $ast.Find({
    param($item)
    $item -is [Management.Automation.Language.FunctionDefinitionAst] -and $item.Name -eq 'Save-ConfigJson'
}, $true)
if (-not $saveFunction) { throw 'Settings save function is missing.' }
. ([scriptblock]::Create($saveFunction.Extent.Text))

$testDir = Join-Path ([IO.Path]::GetTempPath()) ('mijialamp-settings-acl-' + [Guid]::NewGuid().ToString('N'))
$ConfigPath = Join-Path $testDir 'config.json'
try {
    Save-ConfigJson '{"phase":"initial"}'
    foreach ($protect in @($false, $true)) {
        # A non-default group reproduces the descriptor change during Replace.
        # Test both inherited permissions and a protected DACL.
        $acl = Get-Acl -LiteralPath $ConfigPath
        $acl.SetGroup([Security.Principal.SecurityIdentifier]::new('S-1-5-32-545'))
        $acl.SetAccessRuleProtection($protect, $true)
        Set-Acl -LiteralPath $ConfigPath -AclObject $acl
        $before = (Get-Acl -LiteralPath $ConfigPath).Sddl
        Save-ConfigJson '{"phase":"updated"}'
        $after = (Get-Acl -LiteralPath $ConfigPath).Sddl
        if ($after -ne $before) {
            throw "Settings save changed the security descriptor (protected=$protect). Before=$before After=$after"
        }
        $saved = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($saved.phase -ne 'updated') { throw 'Settings content was not updated.' }
        if (@(Get-ChildItem -LiteralPath $testDir -Force).Count -ne 1) {
            throw 'Settings save left temporary or backup files behind.'
        }
    }
} finally {
    if (Test-Path -LiteralPath $ConfigPath) { Remove-Item -LiteralPath $ConfigPath -Force }
    if (Test-Path -LiteralPath $testDir) { Remove-Item -LiteralPath $testDir }
}

Write-Host 'Settings save: content, owner, group, inherited/protected DACLs and cleanup OK'
