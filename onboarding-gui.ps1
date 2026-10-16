param(
    [Parameter(Mandatory = $true)][string]$ConfigPath,
    [ValidateSet("Portable", "Service")][string]$Mode = "Portable",
    [object[]]$CachedDevices = @(),
    [switch]$SelfTest
)
. (Join-Path $PSScriptRoot 'i18n.ps1')
Initialize-MijiaLampLanguage -ConfigPath $ConfigPath
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Tool = Join-Path $Root "tools\xiaomi_onboarding.py"
$ConfigPath = [IO.Path]::GetFullPath($ConfigPath)

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[Windows.Forms.Application]::EnableVisualStyles()

function Get-OnboardingPython {
    foreach ($candidate in @(
        (Join-Path $Root "runtime\python.exe"),
        (Join-Path $Root "prepared-runtime\python\python.exe"),
        (Join-Path $Root ".venv\Scripts\python.exe")
    )) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    }
    if ($SelfTest) {
        $python = Get-Command python.exe -ErrorAction SilentlyContinue
        if ($python) { return $python.Source }
    }
    throw (T 'msg_491a1452b845')
}

function Start-OnboardingProcess {
    param([string]$Python, [string]$Action, [string]$Config = "", [string]$SelectedMode = "")
    $info = New-Object Diagnostics.ProcessStartInfo
    $info.FileName = $Python
    $info.Arguments = '-B "' + $Tool + '" ' + $Action
    if ($Config) { $info.Arguments += ' --config "' + $Config + '" --mode ' + $SelectedMode }
    $info.WorkingDirectory = $Root
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    if ($Action -eq "select") { $info.RedirectStandardInput = $true }
    return [Diagnostics.Process]::Start($info)
}

function Read-OnboardingEvent {
    param([Diagnostics.Process]$Process, [Windows.Forms.Form]$Progress, [int]$TimeoutSeconds)
    $lineTask = $Process.StandardOutput.ReadLineAsync()
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while (-not $lineTask.IsCompleted) {
        [Windows.Forms.Application]::DoEvents()
        if ($Progress.IsDisposed -or $Progress.Tag -eq "cancel") {
            throw (T 'msg_d48f94d13f08')
        }
        if ([DateTime]::UtcNow -gt $deadline) { throw (T 'msg_febc19f66f38') }
        Start-Sleep -Milliseconds 80
    }
    $line = $lineTask.Result
    if (-not $line -or $line.Length -gt 2000000) { throw (T 'msg_863e52adc979') }
    try { $event = $line | ConvertFrom-Json }
    catch { throw (T 'msg_863e52adc979') }
    if ($null -eq $event -or $event.type -notin @('qr', 'devices', 'selected', 'error')) {
        throw (T 'msg_863e52adc979')
    }
    if ($event.type -eq "error") { throw [string]$event.message }
    return $event
}

function New-ProgressForm {
    $form = New-Object Windows.Forms.Form
    $form.Text = (T 'msg_951ddfa619bb')
    $form.Size = New-Object Drawing.Size(510, 630)
    $form.MinimumSize = New-Object Drawing.Size(480, 600)
    $form.StartPosition = "CenterScreen"
    $form.Font = New-Object Drawing.Font("Segoe UI", 10)
    $form.Tag = "running"
    $label = New-Object Windows.Forms.Label
    $label.Text = (T 'msg_a58c4aad9d6e')
    $label.SetBounds(20, 18, 460, 56)
    $form.Controls.Add($label)
    $image = New-Object Windows.Forms.PictureBox
    $image.SetBounds(20, 90, 460, 430)
    $image.SizeMode = "Zoom"
    $form.Controls.Add($image)
    $cancel = New-Object Windows.Forms.Button
    $cancel.Text = (T 'msg_bb9dbb406dcb')
    $cancel.SetBounds(370, 535, 105, 38)
    $cancel.Add_Click({ param($sender) $sender.FindForm().Tag = "cancel" })
    $form.Controls.Add($cancel)
    return @{ Form = $form; Label = $label; Image = $image; Auth = $null; Picture = $null }
}

function Get-OnboardingDevices {
    param([object[]]$Devices)
    foreach ($device in $Devices) {
        if ($null -eq $device) { continue }
        if ($device.did -isnot [string] -or $device.did -notmatch '^\d+$' -or
            $device.model -isnot [string] -or [string]::IsNullOrWhiteSpace($device.model) -or
            $device.token -isnot [string] -or $device.token -notmatch '^[0-9a-fA-F]{32}$') {
            # Never include the malformed row: it can contain a device token.
            throw (T 'onboarding.invalid_devices')
        }
        $device
    }
}

function Get-OnboardingDeviceList {
    param([string]$Python, [object[]]$CachedDevices, [hashtable]$Progress)
    $devices = @(Get-OnboardingDevices -Devices $CachedDevices)
    if ($devices.Count -gt 0) { return ,$devices }

    $Progress.Auth = Start-OnboardingProcess $Python 'qr'
    $first = Read-OnboardingEvent $Progress.Auth $Progress.Form 30
    if ($first.type -ne 'qr') { throw (T 'msg_e157ae0e8a81') }
    $bytes = [Convert]::FromBase64String([string]$first.image_b64)
    $stream = [IO.MemoryStream]::new($bytes)
    try {
        $loaded = [Drawing.Image]::FromStream($stream)
        try { $Progress.Picture = [Drawing.Bitmap]::new($loaded) }
        finally { $loaded.Dispose() }
    } finally { $stream.Dispose() }
    $Progress.Image.Image = $Progress.Picture
    $Progress.Label.Text = (T 'msg_e73e34070aee')
    $Progress.Form.Refresh()
    [Windows.Forms.Application]::DoEvents()

    $second = Read-OnboardingEvent $Progress.Auth $Progress.Form 390
    if ($second.type -ne 'devices') { throw (T 'msg_8ce2082ce30c') }
    $devices = @(Get-OnboardingDevices -Devices $second.devices)
    if ($devices.Count -eq 0) { throw (T 'msg_b6a6a945a1f4') }
    return ,$devices
}

function Select-Lamp {
    param([object[]]$Devices)
    $Devices = @(Get-OnboardingDevices -Devices $Devices)
    if ($Devices.Count -eq 0) { throw (T 'msg_b6a6a945a1f4') }
    $form = New-Object Windows.Forms.Form
    $form.Text = (T 'msg_dd7ebca57008')
    $form.Size = New-Object Drawing.Size(650, 440)
    $form.StartPosition = "CenterScreen"
    $form.Font = New-Object Drawing.Font("Segoe UI", 10)
    $label = New-Object Windows.Forms.Label
    $label.Text = (T 'msg_6ca992225955')
    $label.SetBounds(18, 15, 610, 48)
    $form.Controls.Add($label)
    $list = New-Object Windows.Forms.ListBox
    $list.SetBounds(18, 69, 595, 260)
    $list.Anchor = "Top,Bottom,Left,Right"
    foreach ($device in $Devices) {
        $name = if ([string]::IsNullOrWhiteSpace([string]$device.name)) { $device.model } else { $device.name }
        [void]$list.Items.Add("$name  ·  $($device.model)  ·  DID $($device.did)  ·  $($device.localip)")
    }
    $form.Controls.Add($list)
    $choose = New-Object Windows.Forms.Button
    $choose.Text = T 'onboarding.select'
    $choose.Enabled = $false
    $choose.SetBounds(495, 342, 118, 38)
    $choose.Anchor = "Bottom,Right"
    $list.Add_SelectedIndexChanged({ $choose.Enabled = $list.SelectedIndex -ge 0 })
    $choose.Add_Click({
        if ($list.SelectedIndex -ge 0) {
            $form.Tag = $list.SelectedIndex
            $form.DialogResult = [Windows.Forms.DialogResult]::OK
            $form.Close()
        }
    })
    $form.Controls.Add($choose)
    $form.AcceptButton = $choose
    $cancel = New-Object Windows.Forms.Button
    $cancel.Text = (T 'msg_bb9dbb406dcb')
    $cancel.SetBounds(370, 342, 115, 38)
    $cancel.Anchor = "Bottom,Right"
    $cancel.DialogResult = [Windows.Forms.DialogResult]::Cancel
    $form.Controls.Add($cancel)
    $form.CancelButton = $cancel
    $result = $form.ShowDialog()
    $index = if ($result -eq [Windows.Forms.DialogResult]::OK) { [int]$form.Tag } else { -1 }
    $form.Dispose()
    if ($index -lt 0) { throw (T 'msg_3860cde47ba6') }
    return $Devices[$index]
}

if ($SelfTest) {
    function Test-OnboardingQrFlow {
        param([object[]]$InputDevices, [object[]]$CloudDevices, [int]$ExpectedQrStarts, [int]$ExpectedCount = 1)
        $testProgress = New-ProgressForm
        $flow = @{ Starts = 0; Reads = 0 }
        $bitmap = [Drawing.Bitmap]::new(2, 2)
        $stream = [IO.MemoryStream]::new()
        try {
            $bitmap.Save($stream, [Drawing.Imaging.ImageFormat]::Png)
            $image = [Convert]::ToBase64String($stream.ToArray())
        } finally { $bitmap.Dispose(); $stream.Dispose() }

        # Replace cloud/process I/O only in this test scope. Exercise the same
        # first-run flow and QR rendering used by the real installer.
        function Start-OnboardingProcess {
            param($Python, $Action)
            if ($Action -ne 'qr') { throw 'First-run onboarding must request a QR.' }
            $flow.Starts++
            return [pscustomobject]@{ TestProcess = $true }
        }
        function Read-OnboardingEvent {
            param($Process, $Progress, $TimeoutSeconds)
            $flow.Reads++
            if ($flow.Reads -eq 1) { return [pscustomobject]@{ type = 'qr'; image_b64 = $image } }
            if ($flow.Reads -ne 2 -or $testProgress.Image.Image -isnot [Drawing.Bitmap] -or
                $testProgress.Label.Text -ne (T 'msg_e73e34070aee')) {
                throw 'The QR must be rendered before waiting for authorization and devices.'
            }
            return [pscustomobject]@{ type = 'devices'; devices = $CloudDevices }
        }
        try {
            $found = Get-OnboardingDeviceList -Python 'test-only' -CachedDevices $InputDevices -Progress $testProgress
            if ($flow.Starts -ne $ExpectedQrStarts -or $found.Count -ne $ExpectedCount -or $found[0].did -ne '123') {
                throw 'Onboarding did not preserve first-run or cached-device behavior.'
            }
        } finally {
            $testProgress.Image.Image = $null
            if ($testProgress.Picture) { $testProgress.Picture.Dispose() }
            $testProgress.Form.Dispose()
        }
    }
    $validDevice = [pscustomobject]@{ name = 'Test lamp'; did = '123'; model = 'yeelink.light.lamp22'; token = ('a' * 32) }
    foreach ($case in @(@{ Value = $null }, @{ Value = @() }, @{ Value = @($null) })) {
        Test-OnboardingQrFlow -InputDevices $case.Value -CloudDevices @($validDevice) -ExpectedQrStarts 1
    }
    Test-OnboardingQrFlow -InputDevices @($validDevice) -CloudDevices @() -ExpectedQrStarts 0
    $secondDevice = [pscustomobject]@{ did = '456'; model = 'yeelink.light.lamp22'; token = ('b' * 32) }
    Test-OnboardingQrFlow -InputDevices @() -CloudDevices @($validDevice, $secondDevice) -ExpectedQrStarts 1 -ExpectedCount 2
    Test-OnboardingQrFlow -InputDevices @($validDevice, $secondDevice) -CloudDevices @() -ExpectedQrStarts 0 -ExpectedCount 2
    foreach ($rows in @(@{ Value = @() }, @{ Value = @($null) }, @{ Value = @([pscustomobject]@{}) })) {
        $rejected = $false
        try { Test-OnboardingQrFlow -InputDevices @() -CloudDevices $rows.Value -ExpectedQrStarts 1 }
        catch {
            $rejected = $_.Exception.Message -in @((T 'msg_b6a6a945a1f4'), (T 'onboarding.invalid_devices'))
        }
        if (-not $rejected) { throw 'Empty or malformed cloud results must never reach the lamp picker.' }
    }
    $rejected = $false
    try { [void](Select-Lamp -Devices @($null)) }
    catch { $rejected = $_.Exception.Message -eq (T 'msg_b6a6a945a1f4') }
    if (-not $rejected) { throw 'The lamp picker must reject an empty list.' }

    if (-not (Test-Path -LiteralPath $Tool -PathType Leaf)) { throw (T 'msg_638c9fa1545d') }
    $python = Get-OnboardingPython
    $previousInputEncoding = [Console]::InputEncoding
    try {
        foreach ($withBom in @($false, $true)) {
            # Process.StandardInput uses the console input encoding on .NET Framework.
            # Exercise the real writer with and without its UTF-8 preamble.
            [Console]::InputEncoding = New-Object Text.UTF8Encoding($withBom)
            $probe = Start-OnboardingProcess $python "select" $ConfigPath $Mode
            $form = New-ProgressForm
            try {
                $probe.StandardInput.WriteLine("e30=") # Base64 of {}, without a token or network access.
                $probe.StandardInput.Close()
                try {
                    [void](Read-OnboardingEvent $probe $form.Form 10)
                    throw (T 'msg_1b9d048e884c')
                } catch {
                    if ($_.Exception.Message -notmatch [regex]::Escape((T 'msg_70311df10079'))) { throw }
                }
            } finally {
                if (-not $probe.HasExited) { $probe.Kill() }
                $probe.Dispose()
                $form.Form.Dispose()
            }
        }
    } finally {
        [Console]::InputEncoding = $previousInputEncoding
    }
    Write-Host (T 'msg_3d1114a6b1a8')
    return
}

$python = Get-OnboardingPython
$progress = New-ProgressForm
$select = $null
$progress.Form.Show()
try {
    $devices = Get-OnboardingDeviceList -Python $python -CachedDevices $CachedDevices -Progress $progress
    $progress.Form.Hide()
    $selected = Select-Lamp $devices
    $progress.Form.Show()
    $progress.Label.Text = (T 'msg_3a67411f1e7f')
    $progress.Image.Image = $null
    if ($progress.Picture) { $progress.Picture.Dispose() }
    $progress.Picture = $null

    $select = Start-OnboardingProcess $python "select" $ConfigPath $Mode
    $json = $selected | ConvertTo-Json -Compress -Depth 5
    $encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($json))
    $select.StandardInput.WriteLine($encoded)
    $select.StandardInput.Close()
    $result = Read-OnboardingEvent $select $progress.Form 75
    if ($result.type -ne "selected") { throw (T 'msg_2aaf38c547ee') }
    # Keep account devices (including tokens) in memory only. The caller must not
    # send this object to a log or pipeline intended for display.
    return [pscustomobject]@{ Devices = $devices; Selected = $selected; Result = $result }
} finally {
    foreach ($process in @($progress.Auth, $select)) {
        if ($process) {
            if (-not $process.HasExited) { $process.Kill() }
            $process.Dispose()
        }
    }
    if ($progress.Picture) { $progress.Picture.Dispose() }
    $progress.Form.Close()
    $progress.Form.Dispose()
}
