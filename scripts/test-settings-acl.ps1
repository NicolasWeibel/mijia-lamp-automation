param([switch]$InterfaceTest)
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

# Test-only native API to reproduce older inherited descriptors (D: rather
# than D:AI) on a disposable file, matching the hosted runner's initial state.
if (-not ('SettingsAclFixture' -as [type])) {
    Add-Type -TypeDefinition @'
using System.Runtime.InteropServices;
public static class SettingsAclFixture {
    [DllImport("advapi32.dll", EntryPoint="SetFileSecurityW", CharSet=CharSet.Unicode, SetLastError=true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool SetFileSecurity(string name, uint information, byte[] descriptor);
}
'@
}

function Get-SecuritySignature {
    param([string]$Sddl)
    $descriptor = [Security.AccessControl.RawSecurityDescriptor]::new($Sddl)
    $autoInherited = [int][Security.AccessControl.ControlFlags]::DiscretionaryAclAutoInherited
    $descriptor.SetFlags($descriptor.ControlFlags -band (-bnot $autoInherited))
    return $descriptor.GetSddlForm('All')
}

function Set-LegacySecurityDescriptor {
    param([string]$Path, [Security.Principal.SecurityIdentifier]$Group = $null)
    $descriptor = [Security.AccessControl.RawSecurityDescriptor]::new((Get-Acl -LiteralPath $Path).Sddl)
    $information = 4
    if ($Group) { $descriptor.Group = $Group; $information = 6 }
    $autoInherited = [int][Security.AccessControl.ControlFlags]::DiscretionaryAclAutoInherited
    $descriptor.SetFlags($descriptor.ControlFlags -band (-bnot $autoInherited))
    $bytes = [byte[]]::new($descriptor.BinaryLength)
    $descriptor.GetBinaryForm($bytes, 0)
    if (-not [SettingsAclFixture]::SetFileSecurity($Path, $information, $bytes)) {
        throw [ComponentModel.Win32Exception]::new([Runtime.InteropServices.Marshal]::GetLastWin32Error())
    }
}

$testDir = Join-Path ([IO.Path]::GetTempPath()) ('mijialamp-settings-acl-' + [Guid]::NewGuid().ToString('N'))
$ConfigPath = Join-Path $testDir 'config.json'
$legacyParent = Join-Path $testDir 'legacy-parent'
$uiTemp = Join-Path $testDir 'ui-temp'
try {
    foreach ($scenario in @('inherited', 'protected', 'legacy-default', 'legacy-inherited')) {
        if (Test-Path -LiteralPath $ConfigPath) { Remove-Item -LiteralPath $ConfigPath -Force }
        if ($scenario -like 'legacy-*') {
            # Legacy ancestors, not just the file, are necessary to reproduce
            # the hosted runner's duplicate explicit grants during Replace.
            if (-not (Test-Path -LiteralPath $legacyParent)) {
                Set-LegacySecurityDescriptor -Path $testDir
                New-Item -ItemType Directory -Path $legacyParent | Out-Null
                Set-LegacySecurityDescriptor -Path $legacyParent
            }
            $ConfigPath = Join-Path $legacyParent 'config.json'
        }
        Save-ConfigJson '{"phase":"initial"}'
        # Creating a stream can normalize an old descriptor, so create it
        # before installing the legacy fixture's raw security descriptor.
        Set-Content -LiteralPath $ConfigPath -Stream 'mijialamp_acl_fixture' -Value 'retained metadata' -NoNewline -Encoding UTF8
        # A non-default group reproduces the descriptor change during Replace.
        $acl = Get-Acl -LiteralPath $ConfigPath
        $group = [Security.Principal.SecurityIdentifier]::new('S-1-5-32-545')
        if ($scenario -like 'legacy-*') {
            if ($scenario -eq 'legacy-inherited') {
                Set-LegacySecurityDescriptor -Path $ConfigPath -Group $group
            } else {
                Set-LegacySecurityDescriptor -Path $ConfigPath
            }
            $autoInherited = [int][Security.AccessControl.ControlFlags]::DiscretionaryAclAutoInherited
            $fixtureAcl = [Security.AccessControl.RawSecurityDescriptor]::new((Get-Acl -LiteralPath $ConfigPath).Sddl)
            if (($fixtureAcl.ControlFlags -band $autoInherited) -ne 0) { throw 'Legacy ACL fixture was normalized too early.' }
        } else {
            $acl.SetGroup($group)
            $acl.SetAccessRuleProtection(($scenario -eq 'protected'), $true)
            Set-Acl -LiteralPath $ConfigPath -AclObject $acl
        }
        $before = (Get-Acl -LiteralPath $ConfigPath).Sddl
        $creationTime = (Get-Item -LiteralPath $ConfigPath).CreationTimeUtc
        if ($scenario -like 'legacy-*') {
            # The comparison must still reject added explicit grants, such
            # as the duplicate permissions reported by the hosted runner.
            $expanded = [Security.AccessControl.RawSecurityDescriptor]::new($before)
            $grant = [Security.AccessControl.CommonAce]::new(
                [Security.AccessControl.AceFlags]::None,
                [Security.AccessControl.AceQualifier]::AccessAllowed,
                [int][Security.AccessControl.FileSystemRights]::FullControl, $group, $false, $null
            )
            $expanded.DiscretionaryAcl.InsertAce(0, $grant)
            if ((Get-SecuritySignature $expanded.GetSddlForm('All')) -eq (Get-SecuritySignature $before)) {
                throw 'Security comparison accepted an additional explicit grant.'
            }
        }
        foreach ($attempt in 1..3) {
            Save-ConfigJson '{"phase":"updated"}'
            $after = (Get-Acl -LiteralPath $ConfigPath).Sddl
            # Ignore only the AI bookkeeping flag. Extra explicit grants,
            # ACE ordering, inheritance/protection, owner and group must match.
            if ((Get-SecuritySignature $after) -ne (Get-SecuritySignature $before)) {
                throw "Settings save changed the security descriptor ($scenario, attempt=$attempt). Before=$before After=$after"
            }
            if ((Get-Item -LiteralPath $ConfigPath).CreationTimeUtc -ne $creationTime -or
                (Get-Content -LiteralPath $ConfigPath -Stream 'mijialamp_acl_fixture' -Encoding UTF8) -ne 'retained metadata') {
                throw 'Settings save changed the creation time or removed alternate file streams.'
            }
        }
        $saved = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($saved.phase -ne 'updated') { throw 'Settings content was not updated.' }
        if (@(Get-ChildItem -LiteralPath (Split-Path -Parent $ConfigPath) -Force).Count -ne 1) {
            throw 'Settings save left temporary or backup files behind.'
        }
    }
    $contentBeforeFailure = [Convert]::ToBase64String([IO.File]::ReadAllBytes($ConfigPath))
    $aclBeforeFailure = (Get-Acl -LiteralPath $ConfigPath).Sddl
    $locked = [IO.File]::Open($ConfigPath, 'Open', 'Read', 'Read')
    $failureDetected = $false
    try {
        try { Save-ConfigJson '{"phase":"must-not-commit"}' }
        catch { $failureDetected = $true }
    } finally { $locked.Dispose() }
    if (-not $failureDetected) { throw 'Saving unexpectedly replaced a locked destination.' }
    if ([Convert]::ToBase64String([IO.File]::ReadAllBytes($ConfigPath)) -ne $contentBeforeFailure -or
        (Get-Acl -LiteralPath $ConfigPath).Sddl -ne $aclBeforeFailure -or
        @(Get-ChildItem -LiteralPath (Split-Path -Parent $ConfigPath) -Force).Count -ne 1) {
        throw 'Failed save changed the original settings or left temporary files.'
    }
    if ($InterfaceTest) {
        # Exercise the actual UI save path in a child process, with a temp
        # directory using the runner's legacy inheritance representation.
        New-Item -ItemType Directory -Path $uiTemp | Out-Null
        Set-LegacySecurityDescriptor -Path $uiTemp
        $previousTemp = $env:TEMP
        $previousTmp = $env:TMP
        try {
            $env:TEMP = $env:TMP = $uiTemp
            & (Get-Process -Id $PID).Path -NoProfile -ExecutionPolicy Bypass -File (Join-Path $projectRoot 'config-gui.ps1') -SelfTest -Language en
            if ($LASTEXITCODE -ne 0) { throw 'Settings interface failed with legacy temporary-directory permissions.' }
        } finally { $env:TEMP = $previousTemp; $env:TMP = $previousTmp }
    }
} finally {
    if (Test-Path -LiteralPath $ConfigPath) { Remove-Item -LiteralPath $ConfigPath -Force }
    if (Test-Path -LiteralPath $legacyParent) { Remove-Item -LiteralPath $legacyParent }
    if (Test-Path -LiteralPath $uiTemp) {
        $resolvedUi = [IO.Path]::GetFullPath($uiTemp)
        $resolvedRoot = [IO.Path]::GetFullPath($testDir).TrimEnd('\') + '\'
        if (-not $resolvedUi.StartsWith($resolvedRoot, [StringComparison]::OrdinalIgnoreCase)) {
            throw 'Unsafe interface fixture cleanup path.'
        }
        Remove-Item -LiteralPath $uiTemp -Recurse -Force
    }
    if (Test-Path -LiteralPath $testDir) { Remove-Item -LiteralPath $testDir }
}

Write-Host 'Settings save: repeated updates, security metadata, NTFS streams and failed-save recovery OK'
