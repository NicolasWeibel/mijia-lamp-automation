. (Join-Path (Split-Path -Parent $PSScriptRoot) 'i18n.ps1')
. (Join-Path (Split-Path -Parent $PSScriptRoot) 'version.ps1')
$env:MIJIALAMP_LANGUAGE = 'es'
Initialize-MijiaLampLanguage -Language es
$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Add-Type -AssemblyName System.Windows.Forms
function Add-Status { param([string]$Text) }
function Set-OperationProgress { param([int]$Percent, [string]$Stage) }
function Write-PortableProgress { param([int]$Percent, [string]$Stage) }
foreach ($definition in @(
    @{ File = 'setup-gui.ps1'; Name = 'Ensure-Runtime' },
    @{ File = 'setup-portable.ps1'; Name = 'Verify-BundledRuntime' },
    @{ File = 'setup-portable.ps1'; Name = 'Copy-PreparedPortableRuntime' }
)) {
    $tokens = $null
    $errors = $null
    $ast = [Management.Automation.Language.Parser]::ParseFile((Join-Path $project $definition.File), [ref]$tokens, [ref]$errors)
    if ($errors.Count) { throw 'Error de sintaxis en el verificador.' }
    $function = $ast.FindAll({
        param($node)
        $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $definition.Name
    }, $false) | Select-Object -First 1
    if (-not $function) { throw 'Falta el verificador del runtime.' }
    . ([scriptblock]::Create($function.Extent.Text))
}
$tempBase = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')
$testRoot = Join-Path $tempBase ('mijialamp-gui-runtime-' + [Guid]::NewGuid().ToString('N'))
if (-not [IO.Path]::GetFullPath($testRoot).StartsWith($tempBase + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Ruta temporal insegura.'
}
$Root = Join-Path $testRoot 'bundle'
$runtime = Join-Path $Root 'prepared-runtime\python'
$manifestPath = Join-Path $Root 'prepared-runtime\manifest.json'
try {
    New-Item -ItemType Directory -Force -Path (Join-Path $runtime '__pycache__') | Out-Null
    $python = Join-Path $runtime 'python.exe'
    [IO.File]::WriteAllText($python, 'non-executable test fixture')
    @{ schema = 1; project_version = (Get-MijiaLampVersion); runtime_files = @(@{
        path = 'python.exe'; sha256 = (Get-FileHash -LiteralPath $python -Algorithm SHA256).Hash
    }) } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
    # GUI callbacks must verify hashes even when module autoload is unavailable.
    function Get-FileHash { throw 'Get-FileHash unavailable in GUI callback' }
    $script:RuntimeReady = $false
    Ensure-Runtime
    $original = [IO.File]::ReadAllText($python)
    [IO.File]::WriteAllText($python, 'tampered runtime')
    $rejected = $false
    $script:RuntimeReady = $false
    try { Ensure-Runtime } catch { $rejected = $true }
    if (-not $rejected) { throw 'El verificador acepta un runtime modificado.' }
    [IO.File]::WriteAllText($python, $original)
    Remove-Item Function:\Get-FileHash
    foreach ($checker in @(
        { $script:RuntimeReady = $false; Ensure-Runtime },
        { Verify-BundledRuntime -RuntimeDir $runtime -ManifestPath $manifestPath | Out-Null }
    )) {
        $cache = Join-Path $runtime '__pycache__\generated.cpython-312.pyc'
        [IO.File]::WriteAllText($cache, 'test cache')
        & $checker
        if (Test-Path -LiteralPath $cache) { throw 'El verificador deja bytecode extra que puede ser ejecutado.' }
        $unexpected = Join-Path $runtime 'unexpected.pth'
        [IO.File]::WriteAllText($unexpected, 'non-executable test fixture')
        $rejected = $false
        try { & $checker } catch { $rejected = $true }
        if (-not $rejected) { throw 'El verificador permite archivos extra de codigo.' }
        Remove-Item -LiteralPath $unexpected -Force
    }
    $destination = Join-Path $Root 'runtime'
    $destinationManifest = Join-Path $Root 'runtime-manifest.json'
    # Simulate a disk/copy failure after one file has been copied.
    function Copy-Item {
        param([string]$LiteralPath, [string]$Destination, [switch]$Recurse, [switch]$Force, [string]$ErrorAction)
        New-Item -ItemType Directory -Path (Join-Path $Destination 'python') | Out-Null
        [IO.File]::WriteAllText((Join-Path $Destination 'python\python.exe'), 'partial copy')
        throw 'Injected copy failure'
    }
    $failed = $false
    try { Copy-PreparedPortableRuntime (Split-Path -Parent $runtime) $destination $destinationManifest } catch { $failed = $true }
    Remove-Item Function:\Copy-Item
    if (-not $failed -or (Test-Path -LiteralPath $destination) -or
        @(Get-ChildItem -LiteralPath $Root -Filter '.mijialamp-runtime-*').Count) {
        throw 'Una copia fallida dejó un runtime parcial o archivos temporales.'
    }
    Copy-PreparedPortableRuntime (Split-Path -Parent $runtime) $destination $destinationManifest
    if (-not (Verify-BundledRuntime $destination $destinationManifest)) { throw 'El reintento no produjo un runtime verificado.' }
    Remove-Item -LiteralPath $destination -Recurse -Force
    function Move-Item {
        param([string]$LiteralPath, [string]$Destination, [string]$ErrorAction)
        throw 'Injected publication failure'
    }
    $failed = $false
    try { Copy-PreparedPortableRuntime (Split-Path -Parent $runtime) $destination $destinationManifest } catch { $failed = $true }
    Remove-Item Function:\Move-Item
    if (-not $failed -or (Test-Path -LiteralPath $destination)) { throw 'El fallo al publicar dejó una copia incompleta.' }
    $script:RuntimeReady = $false
    Ensure-Runtime
    if (-not $script:RuntimeReady) { throw 'El asistente no puede reabrirse tras el fallo al publicar.' }
    Copy-PreparedPortableRuntime (Split-Path -Parent $runtime) $destination $destinationManifest
    if (-not (Verify-BundledRuntime $destination $destinationManifest)) { throw 'No se pudo reintentar tras el fallo al publicar.' }
    Write-Host 'GUI + Portable: integridad, limpieza y reintento tras copia fallida OK'
} finally {
    if (Test-Path -LiteralPath $testRoot) { Remove-Item -LiteralPath $testRoot -Recurse -Force }
}
