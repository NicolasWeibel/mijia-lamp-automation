$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$tokens = $null
$parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile(
    (Join-Path $projectRoot 'config-gui.ps1'), [ref]$tokens, [ref]$parseErrors
)
if ($parseErrors.Count) { throw 'Settings script could not be parsed.' }
$selector = $ast.Find({
    param($item)
    $item -is [Management.Automation.Language.FunctionDefinitionAst] -and $item.Name -eq 'Get-ValidatorPython'
}, $true)
if (-not $selector) { throw 'Settings Python selector is missing.' }

# Isolate command discovery and file checks without starting a real interpreter.
& {
    param([string]$Definition)
    $Root = 'C:\settings-python-test'
    $script:TestPythonFiles = @()
    $script:TestPythonCommands = @{
        'python.exe' = 'C:\configured-python\python.exe'
        'py.exe' = 'C:\Windows\py.exe'
    }
    function Get-Command {
        param([string]$Name, [string]$ErrorAction)
        if ($script:TestPythonCommands.ContainsKey($Name)) {
            return [pscustomobject]@{ Source = $script:TestPythonCommands[$Name] }
        }
    }
    function Test-Path {
        param([string]$LiteralPath, [string]$PathType)
        return $LiteralPath -in $script:TestPythonFiles
    }
    . ([scriptblock]::Create($Definition))
    if ((Get-ValidatorPython) -ne $script:TestPythonCommands['python.exe']) {
        throw 'Settings must prefer the configured PATH Python over py.exe.'
    }
    foreach ($relative in @('.venv\Scripts\python.exe', 'prepared-runtime\python\python.exe', 'runtime\python.exe')) {
        $candidate = Join-Path $Root $relative
        $script:TestPythonFiles += $candidate
        if ((Get-ValidatorPython) -ne $candidate) { throw "Project runtime priority is incorrect: $relative" }
    }
    $script:TestPythonFiles = @()
    $script:TestPythonCommands.Remove('python.exe')
    if ((Get-ValidatorPython) -ne $script:TestPythonCommands['py.exe']) {
        throw 'The Python launcher fallback is missing.'
    }
} $selector.Extent.Text

Write-Host 'Settings Python selection: PATH, private runtimes and launcher fallback OK'
