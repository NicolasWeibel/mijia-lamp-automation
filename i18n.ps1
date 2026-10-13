# Shared, data-only translations for Windows PowerShell 5.1 and PowerShell 7.
$script:MijiaLampCatalogRoot = Join-Path $PSScriptRoot 'mijialamp\locales'
$script:MijiaLampCatalogs = @{}
foreach ($code in @('en', 'es')) {
    $file = Join-Path $script:MijiaLampCatalogRoot ($code + '.json')
    $script:MijiaLampCatalogs[$code] = Get-Content -LiteralPath $file -Raw -Encoding UTF8 | ConvertFrom-Json

}

function Initialize-MijiaLampLanguage {
    param([string]$Language = '', [string]$ConfigPath = '')
    if (-not $Language) {
        $candidate = if ($ConfigPath) { $ConfigPath } else { Join-Path $PSScriptRoot 'config.json' }
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            try {
                $saved = Get-Content -LiteralPath $candidate -Raw -Encoding UTF8 | ConvertFrom-Json
                if ($saved.ui_language -in @('en', 'es')) { $Language = $saved.ui_language }
            } catch { # The actual configuration validator reports malformed configuration.
            }
        }
    }
    if (-not $Language -and $env:MIJIALAMP_LANGUAGE -in @('en', 'es')) {
        $Language = $env:MIJIALAMP_LANGUAGE
    }
    if (-not $Language) {
        $Language = if ([Globalization.CultureInfo]::CurrentUICulture.TwoLetterISOLanguageName -eq 'es') { 'es' } else { 'en' }
    }
    if ($Language -notin @('en', 'es')) { throw 'Unsupported interface language.' }
    $script:MijiaLampLanguage = $Language
}

function T {
    param([Parameter(Mandatory=$true)][string]$Key, [object[]]$Arguments = @())
    $value = $script:MijiaLampCatalogs[$script:MijiaLampLanguage].PSObject.Properties[$Key]
    if (-not $value) { $value = $script:MijiaLampCatalogs['en'].PSObject.Properties[$Key] }
    if (-not $value) { throw "Missing translation: $Key" }
    $text = [string]$value.Value
    if ($Arguments.Count) { return [string]::Format([Globalization.CultureInfo]::CurrentCulture, $text, $Arguments) }
    return $text
}

function Convert-MijiaLampText {
    param([string]$Text)
    foreach ($catalog in $script:MijiaLampCatalogs.Values) {
        foreach ($property in $catalog.PSObject.Properties) {
            if ($property.Value -ceq $Text) { return T $property.Name }
        }
    }
    return $Text
}

function Update-MijiaLampWindowLanguage {
    param($Window, $ToolTip = $null)
    $Window.Text = Convert-MijiaLampText $Window.Text
    if ($ToolTip) {
        $help = $ToolTip.GetToolTip($Window)
        if ($help) { $ToolTip.SetToolTip($Window, (Convert-MijiaLampText $help)) }
    }
    foreach ($child in $Window.Controls) { Update-MijiaLampWindowLanguage $child $ToolTip }
}
