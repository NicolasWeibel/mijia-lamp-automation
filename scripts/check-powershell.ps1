$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$ErrorsFound = @()

Get-ChildItem -Path $Root -Recurse -File -Filter "*.ps1" |
    Where-Object { $_.FullName -notmatch '[\\/](\.venv|release)[\\/]' } |
    ForEach-Object {
        $tokens = $null
        $errors = $null
        [void][System.Management.Automation.Language.Parser]::ParseFile(
            $_.FullName,
            [ref]$tokens,
            [ref]$errors
        )
        foreach ($error in $errors) {
            $ErrorsFound += "{0}:{1}:{2}: {3}" -f $_.FullName, $error.Extent.StartLineNumber, $error.Extent.StartColumnNumber, $error.Message
        }
    }

if ($ErrorsFound.Count -gt 0) {
    $ErrorsFound | ForEach-Object { Write-Error $_ }
    exit 1
}

Write-Host "PowerShell syntax: OK"
