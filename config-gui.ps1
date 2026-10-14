param(
    [string]$ConfigPath = "",
    [ValidateSet("Portable", "Service")][string]$Mode = "Portable",
    [switch]$Setup,
    [string]$ApplyConfig = "",
    [ValidateSet("en", "es")][string]$Language = "",
    [switch]$SelfTest
)
. (Join-Path $PSScriptRoot 'i18n.ps1')
Initialize-MijiaLampLanguage -Language $Language -ConfigPath $ConfigPath
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$EditorScript = $MyInvocation.MyCommand.Path
if (-not $ConfigPath) { $ConfigPath = Join-Path $Root "config.json" }
$ConfigPath = [IO.Path]::GetFullPath($ConfigPath)
$TemplatePath = Join-Path $Root "config.example.json"
$SchemaPath = Join-Path $Root "config.schema.json"

function Test-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

# The installed editor is protected by the installer ACL. Elevate only to change
# the installed Service configuration; ordinary Portable/setup edits stay unelevated.
$InstalledConfig = [IO.Path]::GetFullPath(
    (Join-Path ([Environment]::GetFolderPath("CommonApplicationData")) "MijiaLamp\config.json")
)
if ($Mode -eq "Service" -and $ConfigPath -ieq $InstalledConfig -and
    $Root -ine (Split-Path -Parent $InstalledConfig)) {
    throw (T 'msg_7787ad964358')
}
# Keep the editor and city lookup unelevated; elevate only a validated save.

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

if (-not (Test-Path -LiteralPath $TemplatePath -PathType Leaf)) {
    throw (T 'msg_9aa07426cf29')
}
$script:ConfigObject = Get-Content -LiteralPath $TemplatePath -Raw -Encoding UTF8 | ConvertFrom-Json
$script:Schema = Get-Content -LiteralPath $SchemaPath -Raw -Encoding UTF8 | ConvertFrom-Json

function Merge-ConfigObject {
    param([object]$Target, [object]$Source)
    foreach ($property in $Source.PSObject.Properties) {
        $existing = $Target.PSObject.Properties[$property.Name]
        if ($existing -and $existing.Value -is [pscustomobject] -and $property.Value -is [pscustomobject]) {
            Merge-ConfigObject $existing.Value $property.Value
        } else {
            $Target | Add-Member -NotePropertyName $property.Name -NotePropertyValue $property.Value -Force
        }
    }
}

if (Test-Path -LiteralPath $ConfigPath -PathType Leaf) {
    $existingConfig = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($existingConfig.PSObject.Properties["token"]) {
        throw (T 'msg_7a799091fd85')
    }
    Merge-ConfigObject $script:ConfigObject $existingConfig
}

$script:ConfigObject | Add-Member -NotePropertyName ui_language -NotePropertyValue $script:MijiaLampLanguage -Force
$script:ControlsByPath = @{}
$script:ToolTip = New-Object System.Windows.Forms.ToolTip
$script:Labels = @{
    lamp_ip = (T 'msg_f8d543ad0d56'); expected_model = (T 'msg_a5ab3212dad1'); device_id = (T 'msg_f97396954840')
    expected_mac = (T 'msg_f33d49b62677'); location_name = (T 'msg_efcbd8e9deb9'); latitude = (T 'msg_b7a91311229d')
    longitude = (T 'msg_dc8528ecd0fc'); elevation_meters = (T 'msg_4a1d656f797f'); timezone = (T 'msg_43b228654bb9')
    night_mode = (T 'msg_f6bae5c21537'); night_start = (T 'msg_e8d5fb646ccd')
    night_end = (T 'msg_de7547d9e951'); night_start_offset_minutes = (T 'msg_bf1aafa4e6ab')
    night_end_offset_minutes = (T 'msg_829f32747d7d'); wind_down_start = (T 'msg_0bd1293d0916')
    pre_sleep_start = (T 'msg_d0d32f505c0d'); bedtime = (T 'msg_28e81ac6f648')
    manual_day_override_max_hours = (T 'msg_525cc0535646')
    manual_off_override_minutes = (T 'msg_e236be8c4272')
    respect_session_lock = (T 'msg_703216f90cba')
    off_on_session_lock = (T 'msg_ed65d786e884')
    on_on_session_unlock = (T 'msg_6b56b84a1ddf')
    respect_user_presence = (T 'msg_212ec7f3b524')
    off_when_user_inactive = (T 'msg_a32bad0345e9')
    service_prelogin_display = (T 'msg_0b23c700d255')
    tray_enabled = (T 'msg_147def2290b2'); notifications_enabled = (T 'msg_80dade6fab6f')
    profile_transition_mode = (T 'msg_7f562ecd0cfe')
    profile_transition_ms = (T 'msg_3fdb34b99293')
    power_transition_ms = (T 'msg_346999c9d343')
    profile_brightness_tolerance = (T 'msg_812ac2c4b38a')
    profile_kelvin_tolerance = (T 'msg_69667dcdfcfd')
    external_change_policy = (T 'msg_9efc201d3ddc')
    external_change_respect_minutes = (T 'msg_62a4c1b16f08')
    sync_interval_seconds = (T 'msg_969c132a6b96')
    network_change_poll_seconds = (T 'msg_e0aa8be82478')
    display_state_stale_minutes = (T 'msg_0434be5d0068')
    unknown_display_policy = (T 'msg_cf2499eda533')
    display_event_debounce_seconds = (T 'msg_f421887369fc')
    display_off_confirm_seconds = (T 'msg_955386fdde95')
    suppress_off_after_start_seconds = (T 'msg_fa68f37c3393')
    suppress_off_after_resume_seconds = (T 'msg_fe5d47e3bf96')
    ignore_remote_sessions = (T 'msg_e04b0abee1c6')
    network_wait_seconds_on = (T 'msg_7a7f92f78b53')
    network_wait_seconds_off = (T 'msg_62f4ace2b052')
    network_wait_seconds_periodic = (T 'msg_2f9d0e9e2216')
    miio_timeout_seconds = (T 'msg_5b7bb00e8cc5')
    miio_fast_timeout_seconds = (T 'msg_d61c5858ddf8')
    suspend_off_timeout_seconds = (T 'msg_7cc61abfe322')
    suspend_event_deadline_seconds = (T 'msg_c82afd153c5d')
    retries = (T 'msg_f3912fc6957c')
    discovery_enabled = (T 'msg_c48b7bf796b8')
    discovery_neighbor_enabled = (T 'msg_78ea5cb5df88')
    discovery_mdns_seconds = (T 'msg_864564949c69')
    discovery_scan_enabled = (T 'msg_79ca1e8b8612')
    discovery_scan_prefix = (T 'msg_dc3224dabb62')
    discovery_scan_workers = (T 'msg_1b4719ed9951')
    discovery_scan_timeout_seconds = (T 'msg_6e7858771fe2')
    discovery_cooldown_seconds = (T 'msg_f31092939665')
    discovery_backoff_max_seconds = (T 'msg_a11ba5498464')
    discovery_full_scan_cooldown_seconds = (T 'msg_64f095be31d2')
    notify_after_failure_seconds = (T 'msg_db28f0da24af')
    event_log_enabled = (T 'msg_7d656e5cedf2')
    log_max_bytes = (T 'msg_68eece2e1650')
    log_backup_count = (T 'msg_28ebd93b2032')
}
$script:Labels.night_start_offset_minutes = (T 'msg_df81d8ea9128')
$script:Labels.night_end_offset_minutes = (T 'msg_d4225493b3cb')
$script:HelpByName = @{
    lamp_ip = (T 'msg_166802634b0e')
    expected_model = (T 'msg_1b5ad7ef7dac')
    device_id = (T 'msg_8dda35edd2c2')
    expected_mac = (T 'msg_39480241921b')
    location_name = (T 'msg_79e571b1bd39')
    latitude = (T 'msg_0536fe6efdd0')
    longitude = (T 'msg_9ca33ba5cffb')
    elevation_meters = (T 'msg_8d9ef46f729c')
    timezone = (T 'msg_446529474094')
    night_start = (T 'msg_45c38845e591')
    night_end = (T 'msg_663e5b73a9d2')
    night_start_offset_minutes = (T 'msg_808dbb13b1b3')
    night_end_offset_minutes = (T 'msg_58132c859b7b')
    wind_down_start = (T 'msg_f1a4e983446e')
    pre_sleep_start = (T 'msg_8ceccd8719e1')
    brightness = (T 'msg_d81047a1b56c')
    kelvin = (T 'msg_ad6e004ce636')
    profile_transition_mode = (T 'msg_77c04e64b2b6')
    profile_transition_ms = (T 'msg_93c9b70aee77')
    power_transition_ms = (T 'msg_91c6a92ff353')
    profile_brightness_tolerance = (T 'msg_3474ab996009')
    profile_kelvin_tolerance = (T 'msg_576fd04f386b')
    manual_day_override_max_hours = (T 'msg_1ebd8436dcfa')
    manual_off_override_minutes = (T 'msg_da54107e1be5')
    external_change_policy = (T 'msg_918b526e1e76')
    external_change_respect_minutes = (T 'msg_4c56e2b661fd')
    sync_interval_seconds = (T 'msg_716a9c4d65ee')
    network_change_poll_seconds = (T 'msg_a561324077cb')
    display_state_stale_minutes = (T 'msg_526203e7e8c8')
    unknown_display_policy = (T 'msg_f0be387f02b9')
    display_event_debounce_seconds = (T 'msg_12778513c8b6')
    display_off_confirm_seconds = (T 'msg_2d0566bc75b7')
    suppress_off_after_start_seconds = (T 'msg_6caa3dea41c8')
    suppress_off_after_resume_seconds = (T 'msg_f457bb8b5ff8')
    respect_session_lock = (T 'msg_652380c97109')
    off_on_session_lock = (T 'msg_d264574f4709')
    on_on_session_unlock = (T 'msg_e863da26ce75')
    respect_user_presence = (T 'msg_dc7fdb620208')
    off_when_user_inactive = (T 'msg_bac4d5c515f8')
    ignore_remote_sessions = (T 'msg_c36843ac7f31')
    service_prelogin_display = (T 'msg_fda38e17a238')
    network_wait_seconds_on = (T 'msg_164534d54006')
    network_wait_seconds_off = (T 'msg_1f86c8b4bc43')
    network_wait_seconds_periodic = (T 'msg_6d2d86356c85')
    miio_timeout_seconds = (T 'msg_a90fd48b4cf6')
    miio_fast_timeout_seconds = (T 'msg_9a1e74fde181')
    suspend_off_timeout_seconds = (T 'msg_11c209608727')
    suspend_event_deadline_seconds = (T 'msg_56b879760096')
    retries = (T 'msg_96f403227a00')
    discovery_enabled = (T 'msg_27bc721adcfb')
    discovery_neighbor_enabled = (T 'msg_150ad2eac776')
    discovery_mdns_seconds = (T 'msg_c052926caffe')
    discovery_scan_enabled = (T 'msg_42d2d7915153')
    discovery_scan_prefix = (T 'msg_073eb1ba3fe1')
    discovery_scan_workers = (T 'msg_4a35df7025ef')
    discovery_scan_timeout_seconds = (T 'msg_353032813214')
    discovery_cooldown_seconds = (T 'msg_57479fbbbbe3')
    discovery_backoff_max_seconds = (T 'msg_c7ae8478a605')
    discovery_full_scan_cooldown_seconds = (T 'msg_16cf135696fd')
    tray_enabled = (T 'msg_c0d6c8b79a4c')
    notifications_enabled = (T 'msg_a89097c92282')
    notify_after_failure_seconds = (T 'msg_58955ba7b622')
    event_log_enabled = (T 'msg_c87fc0ddef33')
    log_max_bytes = (T 'msg_df92e05c1e24')
    log_backup_count = (T 'msg_b296537c0842')
}
$script:ChoiceLabels = @{
    sunrise = (T 'msg_71159c9785f2'); sunset = (T 'msg_10201fc4ea49'); dawn = (T 'msg_d1b977c44255'); dusk = (T 'msg_1c38094c6446')
    stepped = (T 'msg_7bcb55c65546'); continuous = (T 'msg_960a6a2f1973')
    enforce = (T 'msg_41da3a4a75e9'); respect_for_minutes = (T 'msg_6845fa6f440b')
    respect_until_next_profile = (T 'msg_29a79925ccf0')
    off = (T 'msg_139b47f179e3'); hold = (T 'msg_3472f2f98885'); assume_on = (T 'msg_e1a45ef15e09')
}
$script:ChoicesByPath = @{}

function Get-ValueAtPath {
    param([object]$Object, [string]$Path)
    foreach ($part in $Path.Split('.')) { $Object = $Object.PSObject.Properties[$part].Value }
    return $Object
}

function Set-ValueAtPath {
    param([object]$Object, [string]$Path, [object]$Value)
    $parts = $Path.Split('.')
    for ($i = 0; $i -lt $parts.Length - 1; $i++) { $Object = $Object.PSObject.Properties[$parts[$i]].Value }
    $Object | Add-Member -NotePropertyName $parts[-1] -NotePropertyValue $Value -Force
}

function Get-ValidatorPython {
    foreach ($candidate in @(
        (Join-Path $Root "runtime\python.exe"),
        (Join-Path $Root "prepared-runtime\python\python.exe"),
        (Join-Path $Root ".venv\Scripts\python.exe")
    )) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    }
    # Honor the interpreter selected by a virtual environment or setup-python.
    # The launcher can select a different installation without our dependencies.
    $command = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    $command = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    throw (T 'msg_702b5c56191f')
}

function Test-ConfigJson {
    param([string]$Json)
    $python = Get-ValidatorPython
    $validator = Join-Path $Root 'tools\validate_config.py'
    $encodedJson = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($Json))
    # Keep the pipeline ASCII. The validator also handles an optional UTF-8
    # BOM as bytes, independently of the runner's Python text encoding.
    $previousEncoding = $OutputEncoding
    try {
        $OutputEncoding = [Text.Encoding]::ASCII
        $output = $encodedJson | & $python -B $validator
        $validationExitCode = $LASTEXITCODE
    } finally {
        $OutputEncoding = $previousEncoding
    }
    $result = $output | ConvertFrom-Json
    if ($validationExitCode -ne 0 -or -not $result.ok) { throw [string]$result.message }
}

function Save-ConfigJson {
    param([string]$Json)
    $parent = Split-Path -Parent $ConfigPath
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    $parentItem = Get-Item -LiteralPath $parent -Force
    if (($parentItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw (T 'msg_90b7f46b6b88')
    }
    if (Test-Path -LiteralPath $ConfigPath) {
        $item = Get-Item -LiteralPath $ConfigPath -Force
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or $item.PSIsContainer) {
            throw (T 'msg_b63ea195c9d1')
        }
    }
    $temporary = Join-Path $parent (".mijialamp-config-" + [Guid]::NewGuid().ToString("N") + ".tmp")
    $backup = Join-Path $parent (".mijialamp-config-" + [Guid]::NewGuid().ToString("N") + ".bak")
    try {
        [IO.File]::WriteAllText($temporary, $Json + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
        if (Test-Path -LiteralPath $ConfigPath -PathType Leaf) {
            [IO.File]::Replace($temporary, $ConfigPath, $backup)
        } else {
            [IO.File]::Move($temporary, $ConfigPath)
        }
    } finally {
        if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force }
        if (Test-Path -LiteralPath $backup) { Remove-Item -LiteralPath $backup -Force }
    }
}

if ($ApplyConfig) {
    if ($Mode -ne "Service" -or $ConfigPath -ine $InstalledConfig -or -not (Test-Administrator)) {
        throw (T 'msg_4b544bec8752')
    }
    $json = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($ApplyConfig))
    Test-ConfigJson $json
    Save-ConfigJson $json
    Restart-Service -Name MijiaLampService -ErrorAction Stop
    $task = Get-ScheduledTask -TaskPath "\MijiaLamp\" -TaskName "Lamp Agent" -ErrorAction SilentlyContinue
    if ($task -and $task.State -ne "Disabled") {
        Stop-ScheduledTask -InputObject $task -ErrorAction SilentlyContinue
        Start-ScheduledTask -InputObject $task -ErrorAction Stop
    }
    return
}

$identityFields = @("lamp_ip", "expected_model", "device_id", "expected_mac", "location_name", "latitude", "longitude", "elevation_meters", "timezone")
$scheduleFields = @("night_mode", "night_start", "night_end", "night_start_offset_minutes", "night_end_offset_minutes", "wind_down_start", "pre_sleep_start", "bedtime", "pause_until_tomorrow_time")
$behaviorFields = @("manual_day_override_max_hours", "manual_off_override_minutes", "respect_session_lock", "off_on_session_lock", "on_on_session_unlock", "respect_user_presence", "off_when_user_inactive", "service_prelogin_display", "tray_enabled", "notifications_enabled")
$allNamed = @($identityFields + $scheduleFields + $behaviorFields)
$advancedFields = @($script:ConfigObject.PSObject.Properties.Name | Where-Object {
    $_ -notin ($allNamed + @('$schema', 'version', 'light_profiles', 'retry_delay_seconds', 'ui_language'))
})

$script:Form = New-Object System.Windows.Forms.Form
$modeName = if ($Mode -eq "Service") { (T 'msg_d883fd467448') } else { (T 'msg_6d06f4959dbf') }
$script:Form.Text = (T 'msg_7e5870313d1a' -Arguments @(($modeName)))
$script:Form.Size = New-Object System.Drawing.Size(850, 700)
$script:Form.MinimumSize = New-Object System.Drawing.Size(850, 520)
$script:Form.StartPosition = "CenterScreen"
$script:Form.Font = New-Object System.Drawing.Font("Segoe UI", 10)
$script:Form.BackColor = [Drawing.Color]::White
$layout = New-Object System.Windows.Forms.TableLayoutPanel
$layout.Dock = "Fill"
$layout.ColumnCount = 1
$layout.RowCount = 4
[void]$layout.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle("Percent", 100)))
foreach ($height in @(48, 30, -1, 72)) {
    if ($height -lt 0) { [void]$layout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle("Percent", 100))) }
    else { [void]$layout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle("Absolute", $height))) }
}
$script:Form.Controls.Add($layout)

$header = New-Object System.Windows.Forms.Label
$header.Text = (T 'msg_9c8ccdd662e9')
$header.Font = New-Object System.Drawing.Font("Segoe UI Semibold", 17)
$header.Dock = "Fill"
$header.Padding = New-Object System.Windows.Forms.Padding(12, 8, 0, 0)
$layout.Controls.Add($header, 0, 0)

$description = New-Object System.Windows.Forms.Label
$description.Text = (T 'msg_d4a0868bbcb6')
$description.Dock = "Fill"
$description.Padding = New-Object System.Windows.Forms.Padding(14, 0, 0, 0)
$layout.Controls.Add($description, 0, 1)

$tabs = New-Object System.Windows.Forms.TabControl
$tabs.Dock = "Fill"
$layout.Controls.Add($tabs, 0, 2)

function Add-FieldTab {
    param([string]$Title, [string[]]$Fields)
    $page = New-Object System.Windows.Forms.TabPage
    $page.Text = $Title
    $flow = New-Object System.Windows.Forms.FlowLayoutPanel
    $flow.Dock = "Fill"
    $flow.AutoScroll = $true
    $flow.FlowDirection = "TopDown"
    $flow.WrapContents = $false
    $page.Controls.Add($flow)
    [void]$tabs.TabPages.Add($page)
    foreach ($path in $Fields) {
        $value = Get-ValueAtPath $script:ConfigObject $path
        $name = $path.Split('.')[-1]
        $labelText = $script:Labels[$name]
        if ($path -like 'light_profiles.*.*') {
            $profileLabels = @{
                evening = (T 'msg_a1e674691653'); wind_down = (T 'msg_1cb16e4c8c67'); pre_sleep = (T 'msg_7c3ea21a90fb')
                after_bedtime = "Madrugada"; manual_day = (T 'msg_c6574035f8dc')
            }
            $profile = $path.Split('.')[1]
            $profileName = if ($profileLabels.ContainsKey($profile)) { $profileLabels[$profile] } else { $profile }
            $unit = if ($name -eq "kelvin") { (T 'msg_167b0dddee27') } else { (T 'msg_7e8d4ac226be') }
            $labelText = "$profileName · $unit"
        }
        $row = New-Object System.Windows.Forms.Panel
        $row.Width = 770
        $row.Height = 39
        $label = New-Object System.Windows.Forms.Label
        $label.Text = $labelText
        $label.Left = 10
        $label.Top = 10
        $label.Width = 310
        $label.Height = 28
        $label.AutoEllipsis = $true
        $row.Controls.Add($label)
        $help = New-Object Windows.Forms.Label
        $help.Text = "?"
        $help.ForeColor = [Drawing.Color]::RoyalBlue
        $help.Font = New-Object Drawing.Font("Segoe UI", 10, [Drawing.FontStyle]::Bold)
        $help.SetBounds(735, 8, 24, 24)
        $row.Controls.Add($help)
        $explanation = $script:HelpByName[$name]
        if (-not $labelText -or -not $explanation) { throw (T 'msg_c0cbe432a83b' -Arguments @(($path))) }
        $script:ToolTip.SetToolTip($help, $explanation)
        $script:ToolTip.SetToolTip($label, $explanation)
        $enum = $null
        if ($path -notlike '*.*') {
            $schemaProperty = $script:Schema.properties.PSObject.Properties[$path]
            if ($schemaProperty) { $enum = $schemaProperty.Value.enum }
        }
        if ($value -is [bool]) {
            $control = New-Object System.Windows.Forms.CheckBox
            $control.Checked = $value
            $control.Text = (T 'msg_0a0ca661486c')
        } elseif ($enum) {
            $control = New-Object System.Windows.Forms.ComboBox
            $control.DropDownStyle = "DropDownList"
            $choices = @{}
            foreach ($choice in $enum) {
                $translated = $script:ChoiceLabels[[string]$choice]
                if (-not $translated) { throw (T 'msg_55510900f1ad' -Arguments @(($choice))) }
                [void]$control.Items.Add($translated)
                $choices[$translated] = [string]$choice
            }
            $script:ChoicesByPath[$path] = $choices
            $control.SelectedItem = $script:ChoiceLabels[[string]$value]
        } else {
            $control = New-Object System.Windows.Forms.TextBox
            $control.Text = [string]$value
        }
        $control.Left = 325
        $control.Top = 5
        $control.Width = 395
        $control.Tag = $path
        $control.AccessibleName = $labelText
        $control.AccessibleDescription = $explanation
        if ($name -eq "discovery_scan_prefix") { $control.ReadOnly = $true }
        $row.Controls.Add($control)
        $script:ToolTip.SetToolTip($control, $explanation)
        [void]$flow.Controls.Add($row)
        $script:ControlsByPath[$path] = $control
    }
}

$basicPage = New-Object Windows.Forms.TabPage
$basicPage.Text = (T 'msg_5678a7dd3fa7')
$basicPage.BackColor = [Drawing.Color]::White
[void]$tabs.TabPages.Add($basicPage)
Add-FieldTab (T 'msg_db2f05eefedc') $identityFields
Add-FieldTab (T 'msg_131e39647603') ($scheduleFields | Where-Object { $_ -notin @("pause_until_tomorrow_time", "night_mode", "bedtime") })
$profileFields = @()
foreach ($profile in $script:ConfigObject.light_profiles.PSObject.Properties.Name) {
    foreach ($field in @("kelvin", "brightness")) { $profileFields += "light_profiles.$profile.$field" }
}
$transitionFields = @($advancedFields | Where-Object { $_ -match '^(profile_|power_transition)' })
$externalFields = @($advancedFields | Where-Object { $_ -like 'external_*' })
$networkFields = @($advancedFields | Where-Object { $_ -match '^(network_|miio_|suspend_|retries$|retry_|discovery_)' })
$windowsFields = @($advancedFields | Where-Object { $_ -match '^(display_|unknown_display_|suppress_|ignore_remote_)' })
$diagnosticFields = @($advancedFields | Where-Object { $_ -notin ($transitionFields + $externalFields + $networkFields + $windowsFields) })
Add-FieldTab (T 'msg_b726ba3051b3') ($profileFields + $transitionFields)
Add-FieldTab (T 'msg_44761c55ae76') (@($behaviorFields | Where-Object { $_ -notin @("off_on_session_lock", "respect_session_lock", "respect_user_presence", "service_prelogin_display") }) + $externalFields)
Add-FieldTab (T 'msg_ba19e9c3d5f4') $networkFields
Add-FieldTab (T 'msg_39da161b24f6') $windowsFields
Add-FieldTab (T 'msg_e695eb16e81f') $diagnosticFields
$advancedPages = @($tabs.TabPages | Where-Object { $_ -ne $basicPage })
foreach ($page in $advancedPages) { $tabs.TabPages.Remove($page) }

function Add-BasicLabel([string]$Text, [int]$Y, [string]$Help) {
    $label = New-Object Windows.Forms.Label
    $label.Text = $Text
    $label.SetBounds(20, $Y, 215, 25)
    $basicPage.Controls.Add($label)
    $question = New-Object Windows.Forms.Label
    $question.Text = "?"
    $question.ForeColor = [Drawing.Color]::RoyalBlue
    $question.Font = New-Object Drawing.Font("Segoe UI", 10, [Drawing.FontStyle]::Bold)
    $question.SetBounds(235, $Y, 25, 25)
    $basicPage.Controls.Add($question)
    $script:ToolTip.SetToolTip($question, $Help)
}
Add-BasicLabel (T 'msg_efcbd8e9deb9') 24 (T 'msg_d2a67857c8a1')
$city = New-Object Windows.Forms.TextBox
$city.SetBounds(275, 21, 380, 28)
$city.Text = if ($script:ConfigObject.location_name -ne "Your City") { $script:ConfigObject.location_name } else { "" }
$basicPage.Controls.Add($city)
$findCity = New-Object Windows.Forms.Button
$findCity.Text = (T 'msg_5f55edf90089')
$findCity.SetBounds(665, 20, 105, 31)
$basicPage.Controls.Add($findCity)
$cities = New-Object Windows.Forms.ComboBox
$cities.DropDownStyle = "DropDownList"
$cities.SetBounds(275, 61, 495, 30)
$cities.Visible = $false
$basicPage.Controls.Add($cities)
$locationSummary = New-Object Windows.Forms.Label
$locationSummary.SetBounds(20, 102, 750, 52)
$locationSummary.Text = if ($city.Text) { (T 'msg_2dcdc21ccb0a' -Arguments @(($city.Text))) }
    else { (T 'msg_2d9350e40abd') }
$basicPage.Controls.Add($locationSummary)
$cityProgress = New-Object Windows.Forms.ProgressBar
$cityProgress.Style = "Marquee"
$cityProgress.SetBounds(275, 93, 495, 5)
$cityProgress.Visible = $false
$basicPage.Controls.Add($cityProgress)
Add-BasicLabel (T 'msg_28e81ac6f648') 168 (T 'msg_ba3c8dac3539')
$bed = New-Object Windows.Forms.DateTimePicker
$bed.Format = "Custom"
$bed.CustomFormat = "HH:mm"
$bed.ShowUpDown = $true
$bed.Value = [DateTime]::Today.Add([TimeSpan]::Parse($script:ConfigObject.bedtime))
$bed.SetBounds(275, 162, 130, 30)
$basicPage.Controls.Add($bed)
$autoSchedule = New-Object Windows.Forms.CheckBox
$autoSchedule.Text = (T 'msg_1ba1a53004e7')
$autoSchedule.SetBounds(275, 203, 495, 30)
$autoSchedule.Checked = $Setup -or (
    $script:ConfigObject.wind_down_start -eq $bed.Value.AddHours(-2).ToString("HH:mm") -and
    $script:ConfigObject.pre_sleep_start -eq $bed.Value.AddHours(-1).ToString("HH:mm"))
$basicPage.Controls.Add($autoSchedule)
$script:ToolTip.SetToolTip($autoSchedule, (T 'msg_54882439d146'))
$scheduleSummary = New-Object Windows.Forms.Label
$scheduleSummary.SetBounds(275, 241, 495, 48)
$basicPage.Controls.Add($scheduleSummary)
$updateSchedule = {
    foreach ($field in @("wind_down_start", "pre_sleep_start", "profile_transition_mode", "night_start", "night_end", "night_start_offset_minutes", "night_end_offset_minutes")) {
        $script:ControlsByPath[$field].Enabled = -not $autoSchedule.Checked
    }
    $scheduleSummary.Text = if ($autoSchedule.Checked) {
        (T 'msg_1c7c5cadd4e5' -Arguments @(($bed.Value.AddHours(-2).ToString('HH:mm')), ($bed.Value.AddHours(-1).ToString('HH:mm')), ($bed.Value.ToString('HH:mm'))))
    } else { (T 'msg_077217e04c95') }
}
$bed.Add_ValueChanged($updateSchedule)
$autoSchedule.Add_CheckedChanged($updateSchedule)
& $updateSchedule
Add-BasicLabel (T 'msg_1ba05ecaeed0') 303 (T 'msg_f6f5236238e7')
$period = New-Object Windows.Forms.ComboBox
$period.DropDownStyle = "DropDownList"
[void]$period.Items.Add((T 'msg_31d45fd070dc'))
[void]$period.Items.Add((T 'msg_fc0972decc62'))
$period.SelectedIndex = if ($script:ConfigObject.night_mode) { 0 } else { 1 }
$period.SetBounds(275, 298, 495, 30)
$basicPage.Controls.Add($period)
Add-BasicLabel (T 'msg_6d907df937b2') 354 (T 'msg_85123d22cd4c')
$presence = New-Object Windows.Forms.ComboBox
$presence.DropDownStyle = "DropDownList"
[void]$presence.Items.Add((T 'msg_518acbaf426d'))
[void]$presence.Items.Add((T 'msg_43d34c3cfbe2'))
$presence.SelectedIndex = if ($Setup -or -not $script:ConfigObject.off_on_session_lock) { 0 } else { 1 }
$presence.SetBounds(275, 349, 495, 30)
$basicPage.Controls.Add($presence)
$note = New-Object Windows.Forms.Label
$note.Text = if ($Mode -eq "Portable") { (T 'msg_ce2b6f8b5892') }
    else { (T 'msg_5ab69b000349') }
$note.SetBounds(20, 398, 750, 45)
$basicPage.Controls.Add($note)
$advancedToggle = New-Object Windows.Forms.CheckBox
$advancedToggle.Text = (T 'msg_978cb302a03e')
$advancedToggle.SetBounds(20, 454, 500, 30)
$basicPage.Controls.Add($advancedToggle)
$script:ToolTip.SetToolTip($advancedToggle, (T 'msg_0211aac7e123'))
$advancedToggle.Add_CheckedChanged({
    foreach ($page in $advancedPages) {
        if ($advancedToggle.Checked) { [void]$tabs.TabPages.Add($page) } else { $tabs.TabPages.Remove($page) }
    }
})
$script:Locations = @()
$script:CityBusy = $false
$cities.Add_SelectedIndexChanged({
    if ($cities.SelectedIndex -lt 0) { return }
    $selected = $script:Locations[$cities.SelectedIndex]
    foreach ($name in @("location_name", "latitude", "longitude", "elevation_meters", "timezone")) {
        $script:ControlsByPath[$name].Text = [string]$selected.$name
    }
    $city.Text = $selected.location_name
    $locationSummary.Text = (T 'msg_d97797e588ac' -Arguments @(($selected.location_name)))
})
$searchCityAction = {
    if ($script:CityBusy) { return }
    $script:CityBusy = $true
    $findCity.Enabled = $false
    $cityProgress.Visible = $true
    $save.Enabled = $false
    $process = $null
    try {
        if (Test-Administrator) { throw (T 'msg_58ed66ec52f1') }
        $info = New-Object Diagnostics.ProcessStartInfo
        $info.FileName = Get-ValidatorPython
        $info.Arguments = '-B "' + (Join-Path $Root 'tools\location_search.py') + '"'
        $info.UseShellExecute = $false
        $info.CreateNoWindow = $true
        $info.RedirectStandardInput = $true
        $info.RedirectStandardOutput = $true
        $info.RedirectStandardError = $true
        $process = [Diagnostics.Process]::Start($info)
        $outputTask = $process.StandardOutput.ReadToEndAsync()
        $errorTask = $process.StandardError.ReadToEndAsync()
        $request = @{ query = $city.Text } | ConvertTo-Json -Compress
        $process.StandardInput.WriteLine([Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($request)))
        $process.StandardInput.Close()
        $deadline = [DateTime]::UtcNow.AddSeconds(25)
        while (-not $outputTask.IsCompleted) {
            [Windows.Forms.Application]::DoEvents()
            if ([DateTime]::UtcNow -gt $deadline) { throw (T 'msg_ccdb913ce0f0') }
            Start-Sleep -Milliseconds 60
        }
        $result = $outputTask.Result | ConvertFrom-Json
        if (-not $result -or -not $result.ok) { throw $(if ($result.message) { $result.message } else { (T 'msg_29b9fcf130cf') }) }
        $script:Locations = @($result.locations)
        $cities.Items.Clear()
        foreach ($location in $script:Locations) { [void]$cities.Items.Add($location.location_name) }
        $cities.Visible = $script:Locations.Count -gt 0
        $locationSummary.Text = if ($cities.Visible) { (T 'msg_afde2bf101ed') }
            else { (T 'msg_a4b5f04cc870') }
    } catch {
        if ($SelfTest) { throw }
        [void][Windows.Forms.MessageBox]::Show($_.Exception.Message, (T 'msg_02b703c2747a'), "OK", "Warning")
    } finally {
        if ($process) { if (-not $process.HasExited) { $process.Kill() }; $process.Dispose() }
        $script:CityBusy = $false; $findCity.Enabled = $true; $save.Enabled = $true; $cityProgress.Visible = $false
    }
}
$findCity.Add_Click($searchCityAction)
$script:Form.Add_FormClosing({ param($sender, $eventArgs) if ($script:CityBusy) { $eventArgs.Cancel = $true } })

$footer = New-Object System.Windows.Forms.Panel
$footer.Dock = "Fill"
$layout.Controls.Add($footer, 0, 3)
$pathLabel = New-Object System.Windows.Forms.Label
$pathLabel.Text = T 'language.preference'
$pathLabel.AutoEllipsis = $true
$pathLabel.Left = 14
$pathLabel.Top = 8
$pathLabel.Width = 190
$pathLabel.Height = 22
$footer.Controls.Add($pathLabel)
$settingsLanguage = New-Object Windows.Forms.ComboBox
$settingsLanguage.DropDownStyle = 'DropDownList'
[void]$settingsLanguage.Items.Add('English')
[void]$settingsLanguage.Items.Add('Español')
$settingsLanguage.SetBounds(205, 3, 260, 30)
$settingsLanguage.SelectedIndex = if ($script:MijiaLampLanguage -eq 'es') { 1 } else { 0 }
$footer.Controls.Add($settingsLanguage)
$script:ToolTip.SetToolTip($settingsLanguage, (T 'language.hint'))
$save = New-Object System.Windows.Forms.Button
$save.Text = (T 'msg_03288e2cbdea')
$save.Left = 600
$save.Top = 32
$save.Width = 130
$footer.Controls.Add($save)
$cancel = New-Object System.Windows.Forms.Button
$cancel.Text = (T 'msg_bb9dbb406dcb')
$cancel.Left = 735
$cancel.Top = 32
$cancel.Width = 80
$cancel.Add_Click({ $script:Form.Close() })
$footer.Controls.Add($cancel)

function Get-EditedConfigJson {
    foreach ($path in $script:ControlsByPath.Keys) {
        $control = $script:ControlsByPath[$path]
        $oldValue = Get-ValueAtPath $script:ConfigObject $path
        $schemaType = ""
        if ($path -notlike '*.*') {
            $schemaProperty = $script:Schema.properties.PSObject.Properties[$path]
            if ($schemaProperty) { $schemaType = [string]$schemaProperty.Value.type }
        }
        if ($control -is [System.Windows.Forms.CheckBox]) {
            $value = [bool]$control.Checked
        } elseif ($script:ChoicesByPath.ContainsKey($path)) {
            $value = $script:ChoicesByPath[$path][[string]$control.SelectedItem]
            if (-not $value) { throw (T 'msg_a551eeb0ad84' -Arguments @(($control.AccessibleName))) }
        } elseif ($schemaType -eq "number" -or $oldValue -is [double] -or $oldValue -is [decimal] -or $oldValue -is [float]) {
            $value = [double]::Parse($control.Text.Trim().Replace(',', '.'), [Globalization.NumberStyles]::Float, [Globalization.CultureInfo]::InvariantCulture)
        } elseif ($oldValue -is [int] -or $oldValue -is [long]) {
            $value = [int]::Parse($control.Text.Trim(), [Globalization.NumberStyles]::Integer, [Globalization.CultureInfo]::InvariantCulture)
        } else {
            $value = [string]$control.Text
        }
        Set-ValueAtPath $script:ConfigObject $path $value
    }
    if ($city.Text -ne $script:ControlsByPath["location_name"].Text -and $city.Text.Trim()) {
        throw (T 'msg_fb3f76447bb2')
    }
    if ($script:ConfigObject.location_name -eq "Your City") { throw (T 'msg_39ff1fd7cf5b') }
    $script:ConfigObject.bedtime = $bed.Value.ToString("HH:mm")
    $script:ConfigObject.night_mode = $period.SelectedIndex -eq 0
    $script:ConfigObject.off_on_session_lock = $presence.SelectedIndex -eq 1
    $script:ConfigObject.respect_session_lock = $presence.SelectedIndex -eq 1
    $script:ConfigObject.respect_user_presence = $presence.SelectedIndex -eq 1
    $script:ConfigObject.service_prelogin_display = $Mode -eq "Service" -and $presence.SelectedIndex -eq 0
    if ($autoSchedule.Checked) {
        $script:ConfigObject.wind_down_start = $bed.Value.AddHours(-2).ToString("HH:mm")
        $script:ConfigObject.pre_sleep_start = $bed.Value.AddHours(-1).ToString("HH:mm")
        $script:ConfigObject.profile_transition_mode = "continuous"
        $script:ConfigObject.night_start = "sunset"
        $script:ConfigObject.night_end = "sunrise"
        $script:ConfigObject.night_start_offset_minutes = 0
        $script:ConfigObject.night_end_offset_minutes = 0
    }
    $script:ConfigObject.ui_language = if ($settingsLanguage.SelectedIndex -eq 1) { 'es' } else { 'en' }
    $json = $script:ConfigObject | ConvertTo-Json -Depth 25
    Test-ConfigJson $json
    return $json
}

$save.Add_Click({
    try {
        $json = Get-EditedConfigJson
        if ($Mode -eq "Service" -and $ConfigPath -ieq $InstalledConfig -and -not (Test-Administrator)) {
            $encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($json))
            $engine = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
            $process = Start-Process -FilePath $engine -Verb RunAs -WindowStyle Hidden -PassThru -ArgumentList @(
                "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ('"' + $EditorScript + '"'),
                "-Mode", "Service", "-ConfigPath", ('"' + $ConfigPath + '"'), "-ApplyConfig", $encoded)
            $save.Enabled = $false
            while (-not $process.HasExited) { [Windows.Forms.Application]::DoEvents(); Start-Sleep -Milliseconds 80 }
            $process.WaitForExit()
            if ($process.ExitCode -ne 0) { $process.Dispose(); throw (T 'msg_855fd0705148') }
            $process.Dispose()
            $script:Form.Tag = "saved"
            $script:Form.Close()
            return
        }
        Save-ConfigJson $json
        if ($Mode -eq "Service" -and $ConfigPath -ieq $InstalledConfig) {
            try {
                Restart-Service -Name MijiaLampService -ErrorAction Stop
                $task = Get-ScheduledTask -TaskPath "\MijiaLamp\" -TaskName "Lamp Agent" -ErrorAction SilentlyContinue
                if ($task -and $task.State -ne "Disabled") {
                    Stop-ScheduledTask -InputObject $task -ErrorAction SilentlyContinue
                    Start-ScheduledTask -TaskPath "\MijiaLamp\" -TaskName "Lamp Agent" -ErrorAction Stop
                }
                $message = (T 'msg_92d82f1ad25b')
            } catch {
                $message = (T 'msg_4230bf1ae723' -Arguments @(($_.Exception.Message)))
                [void][System.Windows.Forms.MessageBox]::Show($message, "MijiaLamp", "OK", "Warning")
                $script:Form.Close()
                return
            }
        } elseif ($Mode -eq "Portable") {
            $message = (T 'msg_148bedb3e34e')
        } else {
            $message = (T 'msg_f43ee131ea59')
        }
        if (-not $Setup) { [void][System.Windows.Forms.MessageBox]::Show($message, "MijiaLamp") }
        $script:Form.Tag = "saved"
        $script:Form.Close()
    } catch {
        $save.Enabled = $true
        [void][System.Windows.Forms.MessageBox]::Show($_.Exception.Message, (T 'msg_1634cfd2df7f'), "OK", "Error")
    }
})

if ($SelfTest) {
    Write-Host ('Settings validator Python: ' + (Get-ValidatorPython))
    if ($env:MIJIALAMP_CITY_TEST) {
        $city.Text = "Mendoza, Argentina"
        & $searchCityAction
        if (-not $script:Locations.Count) { throw (T 'msg_bd36eabddabb') }
        $cities.SelectedIndex = 0
        if ($script:ControlsByPath["timezone"].Text -ne "America/Argentina/Mendoza") { throw (T 'msg_5da5ad908518') }
        if ([double]$script:ControlsByPath["latitude"].Text -gt -30) { throw (T 'msg_85f4af8b269a') }
        Write-Host (T 'msg_d05bafda9cc7')
    }
    $script:ControlsByPath["location_name"].Text = "San Martín · Mendoza"
    $city.Text = "San Martín · Mendoza"
    $bed.Value = [DateTime]::Today.AddHours(23).AddMinutes(45)
    $autoSchedule.Checked = $true
    $json = Get-EditedConfigJson
    $edited = $json | ConvertFrom-Json
    if ($edited.ui_language -ne $script:MijiaLampLanguage) { throw "The selected language was not saved." }
    if ($edited.wind_down_start -ne "21:45" -or $edited.pre_sleep_start -ne "22:45" -or
        $edited.night_end -ne "sunrise" -or $edited.bedtime -ne "23:45") { throw (T 'msg_d4b7a0c4929d') }
    Test-ConfigJson $json
    # Exercise the BOM-producing Windows PowerShell setting used by CI,
    # as well as legacy ASCII stdin, with the accented city name above.
    $selfTestEncoding = $OutputEncoding
    try {
        foreach ($encoding in @([Text.UTF8Encoding]::new($true), [Text.Encoding]::ASCII)) {
            $OutputEncoding = $encoding
            Test-ConfigJson $json
            if (-not [object]::ReferenceEquals($OutputEncoding, $encoding)) {
                throw 'Configuration validation did not restore the caller encoding.'
            }
        }
    } finally {
        $OutputEncoding = $selfTestEncoding
    }
    if ($tabs.TabPages.Count -ne 1 -or $tabs.TabPages[0].Text -ne (T 'msg_5678a7dd3fa7')) { throw (T 'msg_1ecb96096b78') }
    $advancedToggle.Checked = $true
    if ($tabs.TabPages.Count -lt 5) { throw (T 'msg_9658e40d645f') }
    foreach ($path in $script:ControlsByPath.Keys) {
        $control = $script:ControlsByPath[$path]
        if (-not $control.AccessibleName -or $script:ToolTip.GetToolTip($control).Length -lt 20) {
            throw (T 'msg_56e53169540a' -Arguments @(($path)))
        }
    }
    $autoSchedule.Checked = $false
    foreach ($path in $script:ChoicesByPath.Keys) {
        foreach ($display in $script:ChoicesByPath[$path].Keys) {
            $script:ControlsByPath[$path].SelectedItem = $display
            $roundTrip = Get-EditedConfigJson | ConvertFrom-Json
            if ((Get-ValueAtPath $roundTrip $path) -ne $script:ChoicesByPath[$path][$display]) {
                throw (T 'msg_f2b64b8237c5' -Arguments @(($path)))
            }
        }
    }
    $autoSchedule.Checked = $true
    $json = Get-EditedConfigJson
    $advancedToggle.Checked = $false
    $originalPath = $ConfigPath
    $testDir = Join-Path ([IO.Path]::GetTempPath()) ("mijialamp-gui-test-" + [Guid]::NewGuid().ToString("N"))
    $ConfigPath = Join-Path $testDir "config.json"
    try {
        Save-ConfigJson $json
        $aclBefore = (Get-Acl -LiteralPath $ConfigPath).Sddl
        Save-ConfigJson $json
        if ((Get-Acl -LiteralPath $ConfigPath).Sddl -ne $aclBefore) {
            throw (T 'msg_ebe04ea4342a')
        }
        $savedConfig = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($savedConfig.version -ne 3 -or $savedConfig.location_name -ne "San Martín · Mendoza") {
            throw (T 'msg_12acd30782ff')
        }
    } finally {
        $ConfigPath = $originalPath
        if (Test-Path -LiteralPath (Join-Path $testDir "config.json")) {
            Remove-Item -LiteralPath (Join-Path $testDir "config.json") -Force
        }
        if (Test-Path -LiteralPath $testDir) { Remove-Item -LiteralPath $testDir }
    }
    Write-Host (T 'msg_56763e6dbf1c' -Arguments @(($script:ControlsByPath.Count)))
    if ($env:MIJIALAMP_CONFIG_PREVIEW) {
        if ($env:MIJIALAMP_CONFIG_ADVANCED) {
            $advancedToggle.Checked = $true
            $tabs.SelectedTab = @($advancedPages | Where-Object { $_.Text -eq $env:MIJIALAMP_CONFIG_ADVANCED })[0]
        }
        $script:Form.Show(); $script:Form.Refresh()
        $bitmap = New-Object Drawing.Bitmap($script:Form.Width, $script:Form.Height)
        $rectangle = New-Object Drawing.Rectangle(0, 0, $script:Form.Width, $script:Form.Height)
        $script:Form.DrawToBitmap($bitmap, $rectangle)
        $bitmap.Save($env:MIJIALAMP_CONFIG_PREVIEW); $bitmap.Dispose()
    }
    $script:Form.Dispose()
    return
}
[void]$script:Form.ShowDialog()
$saved = $script:Form.Tag -eq "saved"
$script:Form.Dispose()
if ($Setup) { return $saved }
