# Test Service from local source without a PR

[English](local-service-test.md) | [Español](es/local-service-test.md)


This procedure installs the local copy to `C:\ProgramData\MijiaLamp`. It does not upload code to GitHub or require a commit. Unit tests and packaging alone cannot show that the login screen in Session 0 produces the expected events; verify that by restarting Windows.

## 1. Prepare a separate configuration

In a normal PowerShell 7 session from the repository root:

```powershell
$cfg = Get-Content ..\MijiaLamp-Portable-Dev\config.json -Raw | ConvertFrom-Json
if ($cfg.PSObject.Properties.Name -contains 'token') { throw 'Do not copy a plaintext token' }
$cfg | Add-Member -NotePropertyName service_prelogin_display -NotePropertyValue $true -Force
$cfg | Add-Member -NotePropertyName off_on_session_lock -NotePropertyValue $false -Force
$cfg | Add-Member -NotePropertyName respect_user_presence -NotePropertyValue $false -Force
$cfg | ConvertTo-Json -Depth 20 | Set-Content ..\MijiaLamp-Service-Test-config.json -Encoding utf8
```

The file stays outside the repository and does not include the Portable DPAPI token. Service imports its own LocalMachine-scoped token after installation.

## 2. Verify and prepare local code

Still in normal PowerShell:

```powershell
& ..\MijiaLamp-Portable-Dev\runtime\python.exe -m unittest discover -s tests -q
& ..\MijiaLamp-Portable-Dev\runtime\python.exe -c "from pathlib import Path; from mijialamp.config import load_config; load_config(Path('../MijiaLamp-Service-Test-config.json')); print('config OK')"
.\prepare-service-runtime.ps1 -Recreate
```

The first preparation downloads wheels with pinned hashes and creates `prepared-runtime` without Administrator privileges. It may take time and use disk space. After each code change, if the runtime already exists, update only the source manifest without rebuilding Python:

```powershell
.\prepare-service-runtime.ps1 -RefreshSourceOnly
```

The installer verifies all hashes again before copying and running elevated files. Do not modify repository files after preparing or refreshing the manifest; if you do, run `-RefreshSourceOnly` again.

## 3. Stop Portable

Close `MijiaLamp-Portable-Dev` from its tray icon. Confirm that its process is gone:

```powershell
Get-Process pythonw -ErrorAction SilentlyContinue | Where-Object {
    $_.Path -like '*\MijiaLamp-Portable-Dev\runtime\pythonw.exe'
} | Select-Object Id, Path
```

The query should return nothing. If Portable autostart is enabled, run `..\MijiaLamp-Portable-Dev\disable-portable-autostart.ps1` before restarting. Do not let Portable and Service control the same lamp at once.

## 4. Install Service

Open **PowerShell as Administrator**, change to the repository root, and run:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\install.ps1 -ConfigPath ..\MijiaLamp-Service-Test-config.json
```

Do not use `-EnableAutomation` for the first test installation. Installation keeps a backup of any previous installation and leaves automation disabled. The elevated phase does not download packages.

## 5. Import the token and check manual control

In the same elevated PowerShell session:

```powershell
cd C:\ProgramData\MijiaLamp
.\import-token.ps1 -Mode Service
& .\runtime\python.exe .\lampctl.py service-status
& .\runtime\python.exe .\lampctl.py doctor
.\security-check.ps1
```

If `mi-tokens.json` is not found, repeat the import with `-Source` pointing to the `mihome-ctl` file. The token is never displayed. `doctor` should confirm the model, DID, IP, and physical state.

## 6. Enable and test

In elevated PowerShell:

```powershell
.\enable-automation.ps1
& .\runtime\python.exe .\lampctl.py status
```

For the automated test, `automation_enabled` must be `true`, `manual_off_active` must be `false`, and `last_error` must be `null`. At night, check this sequence:

1. While signed in with the display on, the lamp follows the night profile.
2. Lock with `Win+L`: it stays on while the display is on and turns off when Windows turns the display off.
3. Move the mouse: when the display returns, the lamp turns on without unlocking.
4. Restart. **Before signing in**, wait for Windows to connect to the local network: with the login screen visible, the lamp should turn on; when the display turns off, the lamp should also turn off. After sign-in, check `status` and `C:\ProgramData\MijiaLamp\logs\service.log` for `Console display: on/off` events.

The first turn-on may be delayed until the network and lamp respond. If no console display event appears before sign-in, this feature is not yet verified for Session 0 on this PC; leave `service_prelogin_display` disabled and keep the logs for investigation.

## 7. Repeat or return to Portable

To test another local change, repeat the tests, `-RefreshSourceOnly`, and `install.ps1 -ConfigPath ...`; the installer replaces the installation and leaves it disabled so you can rerun `doctor` and `enable-automation.ps1`.

To stop automation and turn off the lamp, from `C:\ProgramData\MijiaLamp` in elevated PowerShell:

```powershell
.\disable-automation.ps1 -TurnOffLamp
```

To remove Service and its task without deleting configuration or the encrypted token:

```powershell
.\uninstall.ps1
```

You can then start Portable again from its Dev folder. Do not manually delete `C:\ProgramData\MijiaLamp` or its backups during testing.
