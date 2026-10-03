$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$installer = Join-Path $root "install.ps1"
$tokens = $null
$errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($installer, [ref]$tokens, [ref]$errors)
if ($errors.Count -gt 0) { throw "install.ps1 contiene errores de sintaxis" }
$verifyFunction = $ast.FindAll({
    param($node)
    $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
    $node.Name -eq "Verify-StagingAgainstPreparedManifest"
}, $false) | Select-Object -First 1
if (-not $verifyFunction) { throw "Falta Verify-StagingAgainstPreparedManifest" }
. ([scriptblock]::Create($verifyFunction.Extent.Text))
$preparedFunction = $ast.FindAll({
    param($node)
    $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
    $node.Name -eq "Verify-PreparedRuntime"
}, $false) | Select-Object -First 1
if (-not $preparedFunction) { throw "Falta Verify-PreparedRuntime" }
. ([scriptblock]::Create($preparedFunction.Extent.Text))
$pathFunction = $ast.FindAll({
    param($node)
    $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
    $node.Name -eq "Assert-OfficialInstallDir"
}, $false) | Select-Object -First 1
if (-not $pathFunction) { throw "Falta Assert-OfficialInstallDir" }
. ([scriptblock]::Create($pathFunction.Extent.Text))

$InstallDir = [IO.Path]::Combine([Environment]::GetFolderPath("CommonApplicationData"), "MijiaLamp")
Assert-OfficialInstallDir
$InstallDir = Join-Path ([IO.Path]::GetTempPath()) "MijiaLamp"
$rejected = $false
try { Assert-OfficialInstallDir } catch { $rejected = $_.Exception.Message -like "*sólo puede instalarse*" }
if (-not $rejected) { throw "Se aceptó una ruta de Service modificable por el usuario" }
$rejected = $false
try { & (Join-Path $root "uninstall.ps1") -InstallDir $InstallDir *> $null }
catch { $rejected = $_.Exception.Message -like "*sólo puede desinstalarse*" }
if (-not $rejected) { throw "La desinstalación aceptó una ruta arbitraria" }

$testRoot = Join-Path ([IO.Path]::GetTempPath()) "mijialamp-stage-$([Guid]::NewGuid().ToString('N'))"
$runtime = Join-Path $testRoot "runtime"
New-Item -ItemType Directory -Path $runtime -Force | Out-Null
try {
    $python = Join-Path $runtime "python.exe"
    $service = Join-Path $testRoot "service.py"
    Set-Content -LiteralPath $python -Value "runtime fixture"
    Set-Content -LiteralPath $service -Value "source fixture"
    $script:PreparedManifest = [pscustomobject]@{
        runtime_files = @([pscustomobject]@{
            path = "python.exe"
            sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $python).Hash.ToLowerInvariant()
        })
        source_files = @([pscustomobject]@{
            path = "service.py"
            sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $service).Hash.ToLowerInvariant()
        })
    }
    Verify-StagingAgainstPreparedManifest -StageRoot $testRoot

    Set-Content -LiteralPath (Join-Path $testRoot "uninstall.ps1") -Value "unmanifested script"
    $rejected = $false
    try { Verify-StagingAgainstPreparedManifest -StageRoot $testRoot }
    catch { $rejected = $_.Exception.Message -like "*source no manifestado*" }
    if (-not $rejected) { throw "Se aceptó un script agregado después de preparar el runtime" }

    $SourceRoot = Join-Path $testRoot "source-check"
    $PreparedPython = Join-Path $SourceRoot "prepared-runtime\python"
    $ManifestPath = Join-Path $SourceRoot "prepared-runtime\manifest.json"
    $ProjectVersion = "3.1.3"
    New-Item -ItemType Directory -Path $PreparedPython -Force | Out-Null
    $preparedExe = Join-Path $PreparedPython "python.exe"
    Set-Content -LiteralPath $preparedExe -Value "runtime fixture"
    $manifest = @{
        project_version = $ProjectVersion
        runtime_files = @(@{
            path = "python.exe"
            sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $preparedExe).Hash.ToLowerInvariant()
        })
        source_files = @()
    }
    $manifest | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $ManifestPath
    $rejected = $false
    try { Verify-PreparedRuntime }
    catch { $rejected = $_.Exception.Message -like "*no incluye install.ps1*" }
    if (-not $rejected) { throw "Se aceptó un manifiesto sin el instalador elevado" }
} finally {
    Remove-Item -LiteralPath $testRoot -Recurse -Force
}

Write-Host "Installer staging manifest: OK"
