# Read the canonical version as data; do not execute Python during setup.
$script:MijiaLampVersionSource = Join-Path $PSScriptRoot 'mijialamp\__init__.py'

function Get-MijiaLampVersion {
    $text = [IO.File]::ReadAllText($script:MijiaLampVersionSource, [Text.Encoding]::UTF8)
    $match = [regex]::Match($text, '(?m)^__version__\s*=\s*"(?<Version>[0-9]+\.[0-9]+\.[0-9]+)"\s*$')
    if (-not $match.Success) { throw 'Cannot read the project version from mijialamp/__init__.py.' }
    return $match.Groups['Version'].Value
}
