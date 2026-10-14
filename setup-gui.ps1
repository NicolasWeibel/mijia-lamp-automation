param([switch]$SelfTest, [ValidateSet('en', 'es')][string]$Language = '')
. (Join-Path $PSScriptRoot 'i18n.ps1')
. (Join-Path $PSScriptRoot 'version.ps1')
Initialize-MijiaLampLanguage -Language $Language
$ErrorActionPreference = 'Stop'
trap {
    Add-Type -AssemblyName System.Windows.Forms
    [void][Windows.Forms.MessageBox]::Show(
        (T 'msg_0958486400e2') + $_.Exception.Message,
        'MijiaLamp', 'OK', 'Error'
    )
    exit 1
}
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Engine = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$InstalledRoot = Join-Path ([Environment]::GetFolderPath('CommonApplicationData')) 'MijiaLamp'
$ConfigPath = Join-Path $env:LOCALAPPDATA 'MijiaLamp\setup-config.json'
Initialize-MijiaLampLanguage -Language $Language -ConfigPath $ConfigPath
$PreviousLanguageEnvironment = $env:MIJIALAMP_LANGUAGE
$env:MIJIALAMP_LANGUAGE = $script:MijiaLampLanguage
$StagedToken = Join-Path $env:LOCALAPPDATA 'MijiaLamp\onboarding-private\token.dpapi.json'
$PortableAvailable = Test-Path -LiteralPath (Join-Path $Root 'setup-portable.ps1')
$ServiceAvailable = Test-Path -LiteralPath (Join-Path $Root 'install.ps1')
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $SelfTest -and $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw (T 'msg_a2fe89a578e5')
}
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[Windows.Forms.Application]::EnableVisualStyles()
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class MijiaLampSetupWindow {
    [DllImport("user32.dll")]
    public static extern bool ShowWindow(IntPtr window, int command);
}
'@
$script:Busy = $false
$script:Installed = $false
$script:Finished = $false
$script:RuntimeReady = $false
$script:Reviewed = $false
$script:Lamp = $null
$script:Devices = @()
$script:Page = -1
$script:OperationKind = ''
$script:ProgressValue = 0
$script:OutputPending = ''
function Get-WizardPages { @((T 'language.title'), (T 'msg_6efe5e3c0bcc'), (T 'msg_f016ad2c1af4'), (T 'msg_bb507137e363'), (T 'msg_8e8a1dd48676'), (T 'msg_b5fa51d564a9')) }
$pages = Get-WizardPages
$navy = [Drawing.ColorTranslator]::FromHtml('#15304B')
$blue = [Drawing.ColorTranslator]::FromHtml('#1761A0')
$light = [Drawing.ColorTranslator]::FromHtml('#F3F7FB')
$muted = [Drawing.ColorTranslator]::FromHtml('#536579')
$form = New-Object Windows.Forms.Form
$form.Text = (T 'msg_b7e49090fb29')
$form.ClientSize = New-Object Drawing.Size(860, 650)
$form.MinimumSize = New-Object Drawing.Size(860, 680)
$form.StartPosition = 'CenterScreen'
$form.Font = New-Object Drawing.Font('Segoe UI', 10)
$form.AutoScaleMode = 'Dpi'
$form.BackColor = [Drawing.Color]::White
# The hidden launcher also sets the first GUI window's startup visibility.
# Explicitly show the form after that first show, keeping the console hidden.
$form.Add_Shown({
    [void][MijiaLampSetupWindow]::ShowWindow($form.Handle, 5)
    $form.Activate()
})
function New-Label($Parent, $Text, $X, $Y, $Width, $Height) {
    $item = New-Object Windows.Forms.Label
    $item.Text = $Text
    $item.SetBounds($X, $Y, $Width, $Height)
    $Parent.Controls.Add($item)
    return $item
}
function New-Button($Parent, $Text, $X, $Y, $Width) {
    $item = New-Object Windows.Forms.Button
    $item.Text = $Text
    $item.SetBounds($X, $Y, $Width, 38)
    $Parent.Controls.Add($item)
    return $item
}
$header = New-Object Windows.Forms.Panel
$header.BackColor = $navy
$header.SetBounds(0, 0, 860, 82)
$header.Anchor = 'Top,Left,Right'
$form.Controls.Add($header)
$brand = New-Label $header (T 'msg_1d4498d26bce') 26 23 800 36
$brand.Font = New-Object Drawing.Font('Segoe UI Semibold', 15)
$brand.ForeColor = [Drawing.Color]::White
$sidebar = New-Object Windows.Forms.Panel
$sidebar.SetBounds(0, 82, 200, 470)
$sidebar.Anchor = 'Top,Bottom,Left'
$sidebar.BackColor = $light
$form.Controls.Add($sidebar)
$stepsHeading = New-Label $sidebar (T 'msg_2d63c8266459') 25 30 160 28
$stepLabels = @()
for ($i = 0; $i -lt $pages.Count; $i++) {
    $stepLabels += New-Label $sidebar (('{0}. {1}' -f ($i + 1), $pages[$i])) 25 (78 + $i * 49) 160 34
}
$content = New-Object Windows.Forms.Panel
$content.SetBounds(200, 82, 660, 470)
$content.Anchor = 'Top,Bottom,Left,Right'
$form.Controls.Add($content)
$heading = New-Label $content '' 30 25 590 45
$heading.Font = New-Object Drawing.Font('Segoe UI Semibold', 20)
$heading.ForeColor = $navy
$hint = New-Label $content '' 32 83 580 65
$hint.ForeColor = $muted
$languageLabel = New-Label $content (T 'language.label') 32 162 580 30
$languageChoice = New-Object Windows.Forms.ComboBox
$languageChoice.DropDownStyle = 'DropDownList'
[void]$languageChoice.Items.Add('English')
[void]$languageChoice.Items.Add('Español')
$languageChoice.SetBounds(32, 205, 350, 34)
$languageChoice.SelectedIndex = if ($script:MijiaLampLanguage -eq 'es') { 1 } else { 0 }
$content.Controls.Add($languageChoice)
$portable = New-Object Windows.Forms.RadioButton
$portable.Text = (T 'msg_dcd6dbcfc7d5')
$portable.SetBounds(32, 158, 580, 30)
$portable.Checked = $PortableAvailable
$content.Controls.Add($portable)
$portableInfo = New-Label $content (T 'msg_77309cc1a35e') 53 193 550 45
$service = New-Object Windows.Forms.RadioButton
$service.Text = (T 'msg_571f6b3c0c66')
$service.SetBounds(32, 255, 580, 30)
$service.Checked = -not $PortableAvailable
$content.Controls.Add($service)
$serviceInfo = New-Label $content (T 'msg_eeb2d80c6635') 53 291 550 50
$modeWarning = New-Label $content '' 32 355 575 55
$lampSummary = New-Label $content '' 32 155 580 88
$lampSummary.Font = New-Object Drawing.Font('Segoe UI Semibold', 11)
$search = New-Button $content (T 'msg_3567076d2aba') 32 256 260
$reconnect = New-Button $content (T 'msg_3c02076197a2') 304 256 280
$edit = New-Button $content (T 'msg_fea87018b8fc') 32 161 280
$configSummary = New-Label $content '' 32 215 580 90
$auto = New-Object Windows.Forms.CheckBox
$auto.Text = (T 'msg_fd7f1f99bbd5')
$auto.Checked = $true
$auto.SetBounds(32, 312, 560, 30)
$content.Controls.Add($auto)
$autostart = New-Object Windows.Forms.CheckBox
$autostart.Text = (T 'msg_26a0e85a1bd9')
$autostart.SetBounds(32, 352, 580, 30)
$content.Controls.Add($autostart)
$install = New-Button $content (T 'msg_8e8a1dd48676') 32 154 240
$status = New-Object Windows.Forms.TextBox
$status.Multiline = $true
$status.ReadOnly = $true
$status.ScrollBars = 'Vertical'
$status.BackColor = $light
$status.BorderStyle = 'None'
$status.SetBounds(32, 211, 590, 226)
$status.Anchor = 'Top,Bottom,Left,Right'
$content.Controls.Add($status)
$done = New-Label $content '' 32 155 580 260
$footer = New-Object Windows.Forms.Panel
$footer.SetBounds(0, 552, 860, 98)
$footer.Anchor = 'Bottom,Left,Right'
$footer.BackColor = $light
$form.Controls.Add($footer)
$progress = New-Object Windows.Forms.ProgressBar
$progress.SetBounds(25, 33, 810, 12)
$progress.Anchor = 'Top,Left,Right'
$progress.Style = 'Marquee'
$progress.MarqueeAnimationSpeed = 25
$progress.Visible = $false
$footer.Controls.Add($progress)
$progressLabel = New-Label $footer '' 25 6 810 24
$progressLabel.Anchor = 'Top,Left,Right'
$progressLabel.ForeColor = $muted
$progressLabel.Visible = $false
$cancel = New-Button $footer (T 'msg_bb9dbb406dcb') 25 51 112
$back = New-Button $footer (T 'msg_f9618693ab0e') 584 51 112
$back.Anchor = 'Top,Right'
$next = New-Button $footer (T 'msg_49683b71c6ac') 710 51 125
$next.Anchor = 'Top,Right'
$next.BackColor = $blue
$next.ForeColor = [Drawing.Color]::White
$next.FlatStyle = 'Flat'
$form.AcceptButton = $next
$tooltip = New-Object Windows.Forms.ToolTip
$tooltip.SetToolTip($auto, (T 'msg_0ba9a5cc119d'))
function Get-Mode { if ($service.Checked) { return 'Service' }; return 'Portable' }
function Get-ModeName { if ($service.Checked) { return (T 'msg_d883fd467448') }; return (T 'msg_6d06f4959dbf') }
function Set-OperationProgress([int]$Percent, [string]$Stage) {
    if ($script:OperationKind -ne 'Install') { return }
    $script:ProgressValue = [Math]::Max($script:ProgressValue, [Math]::Min(100, [Math]::Max(0, $Percent)))
    $progress.Style = 'Continuous'
    $progress.Value = $script:ProgressValue
    $progressLabel.Text = "$($script:ProgressValue)% · $Stage"
    $progressLabel.AccessibleName = $progressLabel.Text
    [Windows.Forms.Application]::DoEvents()
}
function Add-Status([string]$Text) {
    $status.AppendText($Text + "`r`n")
    $status.SelectionStart = $status.TextLength
    $status.ScrollToCaret()
}
function Update-Navigation {
    $back.Enabled = -not $script:Busy -and -not $script:Installed -and $script:Page -gt -1
    $cancel.Enabled = -not $script:Busy
    $next.Text = if ($script:Page -eq 4) { (T 'msg_aeccae342e4b') } else { (T 'msg_49683b71c6ac') }
    $next.Enabled = -not $script:Busy -and $(switch ($script:Page) {
        1 { $null -ne $script:Lamp }
        2 { $script:Reviewed }
        3 { $script:Finished }
        default { $true }
    })
    $install.Enabled = -not $script:Busy -and -not $script:Finished
    foreach ($button in @($search, $reconnect, $edit)) { $button.Enabled = -not $script:Busy }
    $portable.Enabled = $PortableAvailable -and -not $script:Busy -and -not $script:Installed
    $service.Enabled = $ServiceAvailable -and -not $script:Busy -and -not $script:Installed
    $progress.Visible = $script:Busy -or ($script:Page -eq 3 -and $script:Finished)
    $progressLabel.Visible = $progress.Visible
}
function Show-Page([int]$Index) {
    $script:Page = $Index
    $cancel.Visible = -not $script:Finished
    $back.Visible = -not $script:Finished
    foreach ($control in @($languageLabel, $languageChoice, $portable, $portableInfo, $service, $serviceInfo, $modeWarning, $lampSummary,
        $search, $reconnect, $edit, $configSummary, $auto, $autostart, $install, $status, $done)) { $control.Visible = $false }
    $pages = Get-WizardPages
    $heading.Text = $pages[$Index + 1]
    for ($i = 0; $i -lt $pages.Count; $i++) {
        $stepLabels[$i].Text = ('{0}. {1}' -f ($i + 1), $pages[$i])
        $stepLabels[$i].ForeColor = if ($i -eq ($Index + 1)) { $blue } else { $muted }
        $stepLabels[$i].Font = New-Object Drawing.Font('Segoe UI', 10,
            $(if ($i -eq ($Index + 1)) { [Drawing.FontStyle]::Bold } else { [Drawing.FontStyle]::Regular }))
    }
    switch ($Index) {
        -1 {
            $hint.Text = T 'language.hint'
            $languageLabel.Visible = $true
            $languageChoice.Visible = $true
        }
        0 {
            $hint.Text = (T 'msg_081f206f22d8')
            foreach ($control in @($portable, $portableInfo, $service, $serviceInfo)) { $control.Visible = $true }
            if (-not $PortableAvailable -or -not $ServiceAvailable) {
                $modeWarning.Text = (T 'msg_f9a4c3f45a7b')
                $modeWarning.Visible = $true
            }
        }
        1 {
            $hint.Text = (T 'msg_420d0e9fb346')
            $lampSummary.Visible = $true
            $search.Visible = $true
            $search.Text = if ($script:Lamp) { (T 'msg_c74801943bc3') } else { (T 'msg_3567076d2aba') }
            $reconnect.Visible = $script:Devices.Count -gt 0
            $lampSummary.Text = if ($script:Lamp) {
                (T 'msg_3820013178b1' -Arguments @(($script:Lamp.Selected.name), ($script:Lamp.Result.model), ($script:Lamp.Result.ip)))
            } else { (T 'msg_34a2b532d093') }
        }
        2 {
            $configSummary.SetBounds(32, 215, 580, 90)
            $hint.Text = (T 'msg_358a2513e0e3')
            foreach ($control in @($edit, $configSummary, $auto)) { $control.Visible = $true }
            $autostart.Visible = $portable.Checked
            $configSummary.Text = (T 'msg_382dc6e893cc')
            if ($script:Reviewed) {
                $cfg = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
                $transition = if ($cfg.profile_transition_mode -eq 'continuous') { (T 'msg_5177de817fcd') } else { (T 'msg_2043e1156fb3') }
                $configSummary.Text = (T 'msg_8cf28963ef5a' -Arguments @(($cfg.location_name), ($cfg.bedtime), ($transition)))
            }
        }
        3 {
            $status.SetBounds(32, 211, 590, 226)
            $hint.Text = if ($script:Finished) { (T 'msg_a8fb1770ec2b') }
                elseif ($script:Installed) { (T 'msg_f2caeaef94b2') }
                elseif ($service.Checked) { (T 'msg_38a74a279c38') }
                else { (T 'msg_3777e19a5842') }
            $install.Text = if ($script:Installed) { (T 'msg_43daa61e6c51') } else { (T 'msg_e1149f7bd26d' -Arguments @(((Get-ModeName)))) }
            $install.Visible = -not $script:Finished
            $status.Visible = $true
            if ($script:Reviewed -and -not $script:Busy -and -not $script:Finished) {
                $cfg = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
                $configSummary.Text = (T 'msg_9f5f340f358a' -Arguments @(($script:Lamp.Selected.name), ($cfg.location_name), ($cfg.bedtime))) + $(if ($auto.Checked) { 'activada' } else { 'desactivada' })
                $configSummary.Visible = $true
                $configSummary.SetBounds(32, 199, 580, 62)
                $status.SetBounds(32, 270, 590, 167)
            }
        }
        4 {
            $hint.Text = (T 'msg_60a4ac9bae54')
            $done.Text = (T 'msg_b5cb28df4564' -Arguments @(((Get-ModeName)), ($script:Lamp.Selected.name))) +
                $(if ($auto.Checked) { (T 'msg_8bf41f2ff5c8') }
                else { (T 'msg_e1cc524632ac') }) +
                (T 'msg_dd0ffbf27f95')
            $done.Visible = $true
            $cancel.Visible = $false
        }
    }
    Update-Navigation
}
function Invoke-Action([scriptblock]$Action, [switch]$Installation) {
    if ($script:Busy) { return $false }
    $script:Busy = $true
    $script:OperationKind = if ($Installation) { 'Install' } else { '' }
    if ($Installation) {
        $status.Clear()
        $script:ProgressValue = 0
        Set-OperationProgress 0 (T 'msg_bd1e3515ef8a')
    } else {
        $progress.Style = 'Marquee'
        $progressLabel.Text = T 'setup.processing'
    }
    Update-Navigation
    [Windows.Forms.Application]::DoEvents()
    try { & $Action | Out-Null; return $true }
    catch {
        $progress.Visible = $false; $progressLabel.Visible = $false
        Add-Status "ERROR: $($_.Exception.Message)"
        [void][Windows.Forms.MessageBox]::Show($form, $_.Exception.Message, (T 'msg_2df446caf289'), 'OK', 'Error')
        return $false
    } finally { $script:Busy = $false; Update-Navigation }
}
function Receive-SetupOutput([string]$Text, [int]$ProgressStart, [int]$ProgressEnd, [switch]$Flush) {
    $script:OutputPending += $Text
    if ($Flush -and $script:OutputPending -and -not $script:OutputPending.EndsWith("`n")) { $script:OutputPending += "`n" }
    while (($break = $script:OutputPending.IndexOf("`n")) -ge 0) {
        $line = $script:OutputPending.Substring(0, $break).TrimEnd("`r")
        $script:OutputPending = $script:OutputPending.Substring($break + 1)
        if ($line -match '^\[MijiaLamp:progress:(\d{1,3})\] (.+)$' -and [int]$Matches[1] -le 100) {
            $percent = $ProgressStart + [int](($ProgressEnd - $ProgressStart) * [int]$Matches[1] / 100)
            Set-OperationProgress $percent $Matches[2]
        } else { $status.AppendText($line + "`r`n") }
    }
    $status.SelectionStart = $status.TextLength; $status.ScrollToCaret()
}
function Quote-Literal([string]$Value) { return "'" + $Value.Replace("'", "''") + "'" }
function Read-SharedLog([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return '' }
    $stream = [IO.File]::Open($Path, 'Open', 'Read', 'ReadWrite')
    $reader = New-Object IO.StreamReader($stream, [Text.Encoding]::UTF8)
    try { return $reader.ReadToEnd() } finally { $reader.Dispose() }
}
function Invoke-SetupScript([string]$Path, [string[]]$Arguments = @(), [switch]$Elevated,
    [int]$ProgressStart = 0, [int]$ProgressEnd = 100) {
    $logDir = Join-Path $env:LOCALAPPDATA 'MijiaLamp\setup-logs'
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    $logPath = Join-Path $logDir ([Guid]::NewGuid().ToString('N') + '.log')
    $invocation = '& ' + (Quote-Literal $Path)
    foreach ($argument in $Arguments) {
        $invocation += ' ' + $(if ($argument -match '^-[A-Za-z][A-Za-z0-9]*$') { $argument } else { Quote-Literal $argument })
    }
    $body = @"
`$ErrorActionPreference = 'Stop'
`$env:MIJIALAMP_LANGUAGE = $(Quote-Literal $script:MijiaLampLanguage)
`$global:LASTEXITCODE = 0
`$stream = [IO.File]::Open($(Quote-Literal $logPath), 'CreateNew', 'Write', 'Read')
`$writer = [IO.StreamWriter]::new(`$stream, [Text.UTF8Encoding]::new(`$false))
`$writer.AutoFlush = `$true
try {
    $invocation *>&1 | ForEach-Object { `$writer.WriteLine((`$_ | Out-String).TrimEnd()) }
    if (`$LASTEXITCODE -ne 0) { exit `$LASTEXITCODE }
} catch { `$writer.WriteLine((`$_ | Out-String)); exit 1 }
finally { `$writer.Dispose() }
"@
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($body))
    $start = @{ FilePath = $Engine; WorkingDirectory = (Split-Path -Parent $Path); WindowStyle = 'Hidden'
        ArgumentList = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-EncodedCommand', $encoded); PassThru = $true }
    if ($Elevated) { $start.Verb = 'RunAs' }
    $process = Start-Process @start
    $seen = 0
    $script:OutputPending = ''
    try {
        do {
            $text = Read-SharedLog $logPath
            if ($text.Length -gt $seen) {
                Receive-SetupOutput $text.Substring($seen) $ProgressStart $ProgressEnd
                $seen = $text.Length
            }
            [Windows.Forms.Application]::DoEvents()
            if (-not $process.HasExited) { Start-Sleep -Milliseconds 80 }
        } while (-not $process.HasExited)
        $process.WaitForExit()
        $text = Read-SharedLog $logPath
        Receive-SetupOutput $text.Substring($seen) $ProgressStart $ProgressEnd -Flush
        if ($process.ExitCode -ne 0) { throw (T 'msg_d5d8cb0ce56a' -Arguments @(($text))) }
        return $text
    } finally { $process.Dispose() }
}
function Ensure-Runtime {
    if ($script:RuntimeReady) { return }
    $runtime = Join-Path $Root 'prepared-runtime\python'
    $manifest = Join-Path $Root 'prepared-runtime\manifest.json'
    if ((Test-Path -LiteralPath (Join-Path $Root 'runtime-manifest.json')) -and
        (Test-Path -LiteralPath (Join-Path $Root 'runtime\python.exe') -PathType Leaf)) {
        $runtime = Join-Path $Root 'runtime'; $manifest = Join-Path $Root 'runtime-manifest.json'
    }
    if (-not (Test-Path -LiteralPath $manifest)) {
        if ((Test-Path -LiteralPath (Join-Path $Root 'runtime-manifest.json')) -and
            (Test-Path -LiteralPath (Join-Path $Root 'runtime\python.exe') -PathType Leaf)) {
            $runtime = Join-Path $Root 'runtime'; $manifest = Join-Path $Root 'runtime-manifest.json'
        } elseif ($ServiceAvailable) {
            Invoke-SetupScript (Join-Path $Root 'prepare-service-runtime.ps1') @('-Recreate') | Out-Null
        } else {
            Invoke-SetupScript (Join-Path $Root 'setup-portable.ps1') | Out-Null
            $script:RuntimeReady = $true; return
        }
    }
    Add-Status (T 'msg_e77bb8ec09d8')
    $data = Get-Content -LiteralPath $manifest -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($data.schema -ne 1 -or $data.project_version -ne (Get-MijiaLampVersion) -or -not $data.runtime_files) { throw (T 'msg_ce7e72ab9d87') }
    $items = @(Get-Item -LiteralPath $runtime -Force) + @(Get-ChildItem -LiteralPath $runtime -Recurse -Force)
    if (@($items | Where-Object { ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 }).Count) {
        throw (T 'msg_854071a64443')
    }
    $base = [IO.Path]::GetFullPath($runtime).TrimEnd('\')
    $expected = @{}
    $verifiedCount = 0
    foreach ($entry in $data.runtime_files) {
        $path = [IO.Path]::GetFullPath((Join-Path $runtime ([string]$entry.path)))
        if (-not $path.StartsWith($base + '\', [StringComparison]::OrdinalIgnoreCase) -or
            -not (Test-Path -LiteralPath $path -PathType Leaf)) { throw (T 'msg_c116d4d32c44') }
        $stream = [IO.File]::OpenRead($path)
        $sha256 = [Security.Cryptography.SHA256]::Create()
        try {
            $hash = [BitConverter]::ToString($sha256.ComputeHash($stream)).Replace('-', '')
        } finally { $sha256.Dispose(); $stream.Dispose() }
        if ($hash -ine [string]$entry.sha256) { throw "El runtime fue modificado: $($entry.path)" }
        $expected[$path.ToLowerInvariant()] = $true
        $verifiedCount++
        if ($verifiedCount % 100 -eq 0 -or $verifiedCount -eq $data.runtime_files.Count) {
            Set-OperationProgress ([int](15 * $verifiedCount / $data.runtime_files.Count)) (T 'msg_d0eb49810648')
        }
        [Windows.Forms.Application]::DoEvents()
    }
    foreach ($file in Get-ChildItem -LiteralPath $runtime -Recurse -File -Force) {
        if (-not $expected.ContainsKey($file.FullName.ToLowerInvariant())) {
            $relative = $file.FullName.Substring($base.Length + 1).Replace('\', '/')
            if ($relative -match '(^|/)__pycache__/.*\.(pyc|pyo)$') {
                Remove-Item -LiteralPath $file.FullName -Force
            } else { throw (T 'msg_8ed90ac7f01d' -Arguments @(($file.Name))) }
        }
    }
    $script:RuntimeReady = $true
}
function Get-WizardCachedDevices([switch]$Refresh) {
    # Preserve an empty array across the script parameter boundary. An empty
    # pipeline assigned from an if expression would become a single null row.
    if ($Refresh) { return ,@() }
    return ,@($script:Devices | Where-Object { $null -ne $_ })
}
function Select-WizardLamp([switch]$Refresh) {
    $script:Lamp = $null; $script:Reviewed = $false
    Ensure-Runtime
    $cached = Get-WizardCachedDevices -Refresh:$Refresh
    $result = & (Join-Path $Root 'onboarding-gui.ps1') -ConfigPath $ConfigPath -Mode (Get-Mode) -CachedDevices $cached
    if (-not $result.Result.token_staged) { throw (T 'msg_ee5fd41c5488') }
    $cfg = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $cfg | Add-Member -NotePropertyName ui_language -NotePropertyValue $script:MijiaLampLanguage -Force
    [IO.File]::WriteAllText($ConfigPath, ($cfg | ConvertTo-Json -Depth 25), [Text.UTF8Encoding]::new($false))
    $script:Lamp = $result; $script:Devices = @($result.Devices); $script:Reviewed = $false
}
$search.Add_Click({ [void](Invoke-Action { Select-WizardLamp }); Show-Page 1 })
$reconnect.Add_Click({ [void](Invoke-Action { Select-WizardLamp -Refresh }); Show-Page 1 })
$edit.Add_Click({
    if (Invoke-Action {
        Ensure-Runtime
        $progress.Visible = $false
        $progressLabel.Visible = $false
        $saved = & (Join-Path $Root 'config-gui.ps1') -ConfigPath $ConfigPath -Mode (Get-Mode) -Setup -Language $script:MijiaLampLanguage
        if ($saved) {
            $script:Reviewed = $true
            $editedConfig = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
            $languageChoice.SelectedIndex = if ($editedConfig.ui_language -eq "es") { 1 } else { 0 }
        }
    }) { Show-Page 2 }
})
$install.Add_Click({
    [void](Invoke-Action -Installation {
        if (-not $script:Reviewed -or -not $script:Lamp) { throw (T 'msg_d94df8de196d') }
        Ensure-Runtime
        Set-OperationProgress 15 (T 'msg_9e2bf4b66840')
        if (-not $script:Installed) {
            $otherPortable = @(Get-CimInstance Win32_Process -Filter "name = 'pythonw.exe'" -ErrorAction SilentlyContinue |
                Where-Object { $_.CommandLine -match 'portable\.py' })
            if ($otherPortable.Count) { throw (T 'msg_74d70c1e3898') }
            if ($portable.Checked) {
                $existingService = Get-Service -Name MijiaLampService -ErrorAction SilentlyContinue
                if ($existingService -and $existingService.Status -eq 'Running') {
                    throw (T 'msg_207526bf7a62')
                }
            }
            if ($service.Checked) {
                # Only a developer checkout may update its source manifest.
                if (Test-Path -LiteralPath (Join-Path $Root '.git')) {
                    Invoke-SetupScript (Join-Path $Root 'prepare-service-runtime.ps1') @('-RefreshSourceOnly') | Out-Null
                }
                Add-Status (T 'msg_06716c98907c')
                $arguments = @('-ConfigPath', $ConfigPath, '-EncryptedTokenSource', $StagedToken, '-ShowTray', '-GuiProgress')
                if ($auto.Checked) { $arguments += '-EnableAutomation' }
                Set-OperationProgress 20 (T 'msg_0f74cb400435')
                Invoke-SetupScript (Join-Path $Root 'install.ps1') $arguments -Elevated -ProgressStart 20 -ProgressEnd 96 | Out-Null
                Remove-Item -LiteralPath $StagedToken -Force
            } else {
                Invoke-SetupScript (Join-Path $Root 'setup-portable.ps1') @('-ConfigPath', $ConfigPath, '-GuiProgress') -ProgressStart 20 -ProgressEnd 72 | Out-Null
            }
            $script:Installed = $true; Update-Navigation
        }
        $target = if ($service.Checked) { $InstalledRoot } else { $Root }
        if (Test-Path -LiteralPath $StagedToken) {
            Set-OperationProgress 75 (T 'msg_4a273f9df305')
            Add-Status (T 'msg_6bcbd4e1dea9')
            Invoke-SetupScript (Join-Path $target 'import-token.ps1') @('-Mode', (Get-Mode), '-EncryptedSource', $StagedToken) -Elevated:$service.Checked | Out-Null
            Remove-Item -LiteralPath $StagedToken -Force
        }
        if (-not $service.Checked) {
            Set-OperationProgress 85 (T 'msg_b0d7cae6815a')
            Start-Process -FilePath (Join-Path $Root 'start-portable.cmd') -WorkingDirectory $Root -WindowStyle Hidden -Wait | Out-Null
            if ($auto.Checked) { Invoke-SetupScript (Join-Path $Root 'enable-portable-automation.ps1') | Out-Null }
            else { Invoke-SetupScript (Join-Path $Root 'disable-portable-automation.ps1') | Out-Null }
            if ($autostart.Checked) { Invoke-SetupScript (Join-Path $Root 'enable-portable-autostart.ps1') | Out-Null }
        }
        $script:Finished = $true
        Set-OperationProgress 100 (T 'msg_efdfaf8d1f10')
        Add-Status (T 'msg_c2f6115cddcd')
    })
    Show-Page 3
})
$back.Add_Click({ if (-not $script:Installed -and -not $script:Busy) { Show-Page ($script:Page - 1) } })
$next.Add_Click({
    if ($script:Busy -or -not $next.Enabled) { return }
    if ($script:Page -eq 4) { $form.Close(); return }
    Show-Page ($script:Page + 1)
})
$modeChanged = { $script:Lamp = $null; $script:Reviewed = $false }
$portable.Add_CheckedChanged($modeChanged)
$service.Add_CheckedChanged($modeChanged)
$cancel.Add_Click({ if (-not $script:Busy) { $form.Close() } })
$form.Add_FormClosing({ param($sender, $eventArgs) if ($script:Busy) { $eventArgs.Cancel = $true } })
$form.Add_FormClosed({ $script:Devices = @(); $script:Lamp = $null })
$languageChoice.Add_SelectedIndexChanged({
    $selectedLanguage = if ($languageChoice.SelectedIndex -eq 1) { 'es' } else { 'en' }
    Initialize-MijiaLampLanguage -Language $selectedLanguage
    $env:MIJIALAMP_LANGUAGE = $selectedLanguage
    if ($script:Lamp -and (Test-Path -LiteralPath $ConfigPath)) {
        $cfg = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $cfg | Add-Member -NotePropertyName ui_language -NotePropertyValue $selectedLanguage -Force
        [IO.File]::WriteAllText($ConfigPath, ($cfg | ConvertTo-Json -Depth 25), [Text.UTF8Encoding]::new($false))
    }
    Update-MijiaLampWindowLanguage $form $tooltip
    Show-Page $script:Page
})
Show-Page -1
if ($SelfTest) {
    $initialCache = Get-WizardCachedDevices
    if ($initialCache -isnot [array] -or $initialCache.Count -ne 0) { throw 'First-run device cache must be an empty array.' }
    $script:Devices = @([pscustomobject]@{ did = '123' })
    if ((Get-WizardCachedDevices).Count -ne 1 -or (Get-WizardCachedDevices -Refresh).Count -ne 0) {
        throw 'Changing lamps must reuse the device list; refreshing must request a new QR.'
    }
    $script:Devices = @()
    foreach ($code in @('en', 'es')) {
        $languageChoice.SelectedIndex = if ($code -eq 'es') { 1 } else { 0 }
        Show-Page -1
        if ($heading.Text -ne (T 'language.title') -or $back.Enabled -or -not $next.Enabled) { throw 'Invalid language step navigation.' }
        if ($pages.Count -ne 6) { throw 'The installer must include the language step.' }
    }
    $languageChoice.SelectedIndex = if ($Language -eq 'es') { 1 } else { 0 }
    $testPath = Join-Path ([IO.Path]::GetTempPath()) ([Guid]::NewGuid().ToString('N') + '.ps1')
    try {
        [IO.File]::WriteAllText($testPath, "Write-Output '[MijiaLamp:progress:25] Comprobando'; Write-Output 'first'; Start-Sleep -Milliseconds 600; Write-Output '[MijiaLamp:progress:100] Comprobado'; Write-Output 'last'", [Text.UTF8Encoding]::new($false))
        $script:OperationKind = 'Install'; $script:ProgressValue = 0
        $status.Clear()
        $script:ObservedLiveOutput = $false
        $timer = New-Object Windows.Forms.Timer
        $timer.Interval = 30
        $timer.Add_Tick({
            if ($status.Text -match 'first' -and $status.Text -notmatch 'last' -and $progress.Value -eq 40) { $script:ObservedLiveOutput = $true }
        })
        $timer.Start()
        $result = Invoke-SetupScript $testPath -ProgressStart 20 -ProgressEnd 100
        $timer.Stop(); $timer.Dispose()
        if ($result -notmatch 'first' -or $result -notmatch 'last') { throw (T 'msg_90bea8ca8157') }
        if (-not $script:ObservedLiveOutput) { throw (T 'msg_1ee02d1f1c1c') }
        if ($progress.Value -ne 100 -or $status.Text -match 'MijiaLamp:progress') { throw (T 'msg_bf5a47778688') }
        $script:ProgressValue = 0; $status.Clear()
        Receive-SetupOutput '[MijiaLamp:pro' 0 100
        Receive-SetupOutput "gress:55] Copiando`r`n[MijiaLamp:progress:20] Etapa anterior`n" 0 100
        if ($progress.Value -ne 55) { throw (T 'msg_c773629d5d8a') }
        Receive-SetupOutput (T 'msg_be24c4285175') 0 100 -Flush
        if ($status.Text -notmatch (T 'msg_be24c4285175')) { throw (T 'msg_9ee0dd66d102') }
        [IO.File]::WriteAllText($testPath, "Write-Output '[MijiaLamp:progress:60] Etapa incompleta'; exit 2", [Text.UTF8Encoding]::new($false))
        $script:ProgressValue = 0; $failed = $false
        try { Invoke-SetupScript $testPath | Out-Null } catch { $failed = $true }
        if (-not $failed -or $progress.Value -ge 100 -or $script:Finished) { throw (T 'msg_6b55520595a2') }
        Show-Page 1
        if ($next.Enabled) { throw (T 'msg_d709d4f4d70f') }
        Show-Page 3
        if ($next.Enabled) { throw (T 'msg_460b82c6939f') }
        $script:Installed = $true; $script:Finished = $true; Update-Navigation
        if ($back.Enabled -or $install.Enabled -or -not $next.Enabled) { throw (T 'msg_65a5dd87072b') }
        $script:Busy = $true; Update-Navigation
        if ($next.Enabled -or $cancel.Enabled) { throw (T 'msg_552d039b7aca') }
        $script:Busy = $false; $script:Installed = $false; $script:Finished = $false
        Show-Page 0
        if ($env:MIJIALAMP_GUI_PREVIEW) {
            $previewPage = 3
            if ($env:MIJIALAMP_GUI_PREVIEW_PAGE -and
                [int]::TryParse($env:MIJIALAMP_GUI_PREVIEW_PAGE, [ref]$previewPage) -and
                $previewPage -ge -1 -and $previewPage -le 4) { Show-Page $previewPage }
            else { Show-Page 3 }
            $form.Show()
            if ($script:Page -eq 3) {
                $script:Busy = $true; Update-Navigation
                $script:ProgressValue = 0; Set-OperationProgress 55 (T 'msg_a1cf65d799c5')
                $status.Text = (T 'msg_0bc921b568ba')
            }
            $status.SelectionStart = $status.TextLength; $status.SelectionLength = 0
            Start-Sleep -Milliseconds 400
            [Windows.Forms.Application]::DoEvents(); $form.Refresh()
            $bitmap = New-Object Drawing.Bitmap($form.Width, $form.Height)
            $rectangle = New-Object Drawing.Rectangle(0, 0, $form.Width, $form.Height)
            $form.DrawToBitmap($bitmap, $rectangle)
            $bitmap.Save($env:MIJIALAMP_GUI_PREVIEW); $bitmap.Dispose()
        }
        Write-Host (T 'msg_20bb221cb708')
    } finally { Remove-Item -LiteralPath $testPath -Force -ErrorAction SilentlyContinue; $form.Dispose(); $env:MIJIALAMP_LANGUAGE = $PreviousLanguageEnvironment }
    return
}
try { [void]$form.ShowDialog() } finally { $form.Dispose(); $env:MIJIALAMP_LANGUAGE = $PreviousLanguageEnvironment }
