# Changelog

[English](CHANGELOG.md) | [Español](CHANGELOG.es.md)

All notable changes are documented here. The project uses semantic versioning and follows Keep a Changelog.

## [Unreleased]

## [3.2.0] - 2026-10-13

### Added

- Use `mijialamp/__init__.py` as the single source for the application version across package metadata, PowerShell scripts, test fixtures, and release archives.
- Group temporary pauses under More options → Pause automatic adjustments, with an explanation that pausing does not itself switch the lamp on or off.
- The tray shows the active mode, manual/pause countdowns, and runtime availability; controls use clearer names and wait for Service/Portable readiness.
- Add English and Spanish UI catalogs with language selection before setup and a saved preference for settings, tray, notifications and application errors.
- Make English the default public documentation and link matching Spanish guides.
- Include and verify translation catalogs in release packages and test both interfaces.

- Service can optionally use the console display state to turn on the lamp at night before sign-in. Enable with `service_prelogin_display` after verifying behavior on the PC.
- A Windows graphical wizard installs Portable or Service, configures preferences, and imports the token without commands. The editor also opens from the tray.
- The wizard can authorize a Xiaomi account with a QR code, choose a device, verify its IP/model/DID over the LAN, and prepare a DPAPI-encrypted token for import without copying secrets.
- Setup package with both modes and a console-free launcher. Preparation, import, and selected activation are integrated into installation, with one UAC prompt for Service.
- Simple preferences: worldwide city search with automatic location/time zone, bedtime with calculated dimming, lighting period, and display or unlocked-session tracking. Advanced categories and contextual help are available.
- Installation progress by verified stage, with percentage and description; messages update while work is in progress. Advanced options have specific names, choices, and help in English and Spanish.

### Fixed

- Start Service automatically without the delayed-start setting, reducing startup unavailability for tray controls and pre-sign-in lighting.
- Settings prefer the configured PATH Python over the system launcher when no project runtime exists, keeping validation and city lookup in the environment containing the installed dependencies.
- Settings validation reads Base64 as bytes, strips an optional UTF-8 BOM, and uses strict decoding independently of Python's console encoding. Regression tests cover accented cities, BOM input, UTF-8 mode, and invalid data.
- Returning to automatic mode cancels manual ON/OFF as well as pauses and external overrides, invalidating delayed OFF reassertions.
- First-run Xiaomi onboarding requests and displays the QR before offering device selection; empty caches and malformed device lists cannot create a blank lamp row.
- The Windows wizard uses guided Back/Next pages and displays accented characters correctly in Windows PowerShell 5.1.
- QR authorization accepts Xiaomi account hosts `ak.account.xiaomi.com` and `sgp.lp.account.xiaomi.com` while keeping a closed list of HTTPS destinations.
- Installation keeps the window active and displays incremental output. On completion it shows full progress and prevents repetition or going back; the bar is hidden when continuing. Each retry clears old messages.
- Continuous profiles preserve the same night across midnight and keep the light dim after bedtime. The pause ends at the next sunrise, including that same morning if sunrise has not happened yet.
- The interactive Agent reads configuration without trying to create the Service cache's private lock, allowing the tray to start as a standard user.
- Suspend OFF reuses a recently verified miIO header and avoids `python-miio`'s implicit handshake, whose retries could block for several seconds as Windows cuts the network. Without a prior session, it uses one unicast handshake bounded by the Suspend timeout.
- The Named Pipe listener starts listening again after a disconnect or transient error instead of leaving Portable running without accepting commands.
- `sleepnow --require-lamp-off` requires explicit OFF confirmation and discards suspend requests that reach the runtime after the confirmation deadline.
- The tray's Automatic action re-enables automation as well as removing a pause; previously it could leave automation disabled and screen events in `hold`.
- The `/24` discovery scan honors the configured per-address timeout; implicit miIO handshakes could hold the control lock for over a minute after Resume.
- Service reinstalls disable automation before the first start, even if inherited state had it enabled; `-EnableAutomation` retains explicit activation after `doctor` passes.

### Security

- The private Service runtime now fixes `sys.path` through `pythonXY._pth` and copies pywin32 DLLs into the runtime. Preparation and installation reject imports from user `site-packages`; the installer requires a manifest generated with this isolation.
- The installed city editor searches without Administrator privileges; only validated saving and applying changes is elevated.

## [3.1.3] - 2026-09-30

### Changed

- Full Ruff, formatting, and mypy checks are now required CI and release workflow gates.
- Artifact verification documentation identifies the actual public repository.

### Fixed

- Service installation in Windows PowerShell 5.1 configures LocalService without empty arguments, writes UTF-8 JSON without a BOM, and calculates the integrity manifest after pywin32 prepares the service executable.
- Security verification distinguishes read and write permissions when checking the interactive user.
- Fixed Agent/Tray startup in both modes.
- Fixed manifest path normalization during Service preparation and installation.
- The source manifest no longer includes Python caches excluded from the ZIP.
- Manual builds use a safe SBOM name when a branch contains `/`.

### Security

- Installed file ACLs inherit restricted permissions from their folders; the Windows test checks for no broad grants on child files.
- Locks pin SHA-256 hashes for all Windows x64 runtime wheels and Python 3.10–3.12; Service and Portable use `pip --require-hashes` when downloading/installing dependencies.
- CI validates locks and reuses their unhashed versions for vulnerability auditing and the SBOM.
- The installer requires `install.ps1` in the verified manifest and rejects extra staging files, including root scripts added after runtime preparation.
- Local Service and Portable preparation accepts only binary wheels during dependency installation.
- Service installation and removal reject custom paths outside `ProgramData\MijiaLamp`, preventing staging in user-modifiable locations and accidental administrative deletion.
- Service rollback and uninstall no longer run Python or `service.py` from a previous installation with Administrator privileges; on failure, files are preserved and automation remains stopped until a verified install.
- The Service installer creates staging with private ACLs from the start, validates ownership and permissions before running prepared code, and fails if `icacls` cannot protect a file.
- The backup directory is created or validated before moving the previous installation; the Windows test exercises these ACL checks.
- The workflow verifies ZIP hashes, runtime contents, and code before publishing a release.
- Documented how to verify official release provenance before elevation.
- Publishing audits all runtime pins and creates the wheel manifest from the wheelhouse actually used.
- Windows tests install `tzdata` before using `ZoneInfo`; release tag must match the project version.
- `python-miio` uses one explicit shared pin for preparation, installation, auditing, and SBOM.
- Runtime excludes `python-miio` optional `android_backup` and `micloud` modules: they are not involved in local lamp control and do not provide Windows wheels.

## [3.1.2] - 2026-09-30

### Fixed

- Portable Suspend runs critical OFF directly in the same process, without waiting for a Named Pipe worker.
- Suspend OFF uses the known IP, without discovery, retries, or long waits, and a dedicated short timeout (`suspend_off_timeout_seconds`).
- Suspend no longer removes `manual_day`, `manual_off`, or external overrides: this temporary logical state must survive Sleep/Resume.
- `resume-auto` and `resume-user` increment `intent_revision`, invalidating work started before sleep without inventing Display ON.
- Suspend hints from Agent to Service include a monotonic deadline; an event queued during Sleep is discarded as `suspend-off-missed` rather than issuing a stale OFF after Resume.
- Suspend no longer schedules deferred reassertion, avoiding a late OFF racing a real Display ON after Resume.
- `start-portable.cmd` detects an already active Portable instance and exits cleanly instead of causing `agent.lock`/`PermissionError` in the log.
- Shutdown/Preshutdown keep the stronger previous behavior: clear overrides and retain cancelable reassertion.

### Added

- `suspend_off_timeout_seconds` (default `0.25`) and `suspend_event_deadline_seconds` (default `0.75`).
- Regression tests for synchronous Portable OFF, override preservation, hint expiration, and cancellation of pre-Suspend work.

## [3.1.1] - 2026-09-29

### Fixed

- `tools/migrate_legacy_config.py` now explicitly adds the project root to `sys.path` when run as a direct script. This fixes `ModuleNotFoundError: No module named 'mijialamp'` during `setup-portable.ps1` and the equivalent installer flow.
- Added a regression test that runs the migrator from a working directory outside the repository, reproducing the way PowerShell invokes it in a real installation.

## [3.1.0] - 2026-09-29

### Added

- Official Portable mode without Administrator privileges or Windows Service.
- Portable token encrypted with DPAPI `CurrentUser` and per-user Pipe.
- `setup-portable.ps1`, user autostart, Portable wrappers, and `--mode portable` commands.
- Hardened Service mode with a private Python runtime under `ProgramData`.
- `prepare-service-runtime.ps1` downloads/installs dependencies without elevation, requires binary wheels, tests relocation, and generates a SHA-256 manifest.
- `security-check.ps1` audits the service account, ACL, runtime, privileges, Named Pipe, and absence of TCP listeners.
- Separate `MijiaLamp-Portable-*` and `MijiaLamp-Service-*` releases.
- Official Portable release can include a self-contained Python runtime verified by `runtime-manifest.json`, so it works without installed Python or `pip`.
- Portable accepts `-ConfigPath` and migrates legacy plaintext tokens directly to DPAPI `CurrentUser`.

### Security

- Elevated `install.ps1` no longer downloads packages or runs `pip`.
- Service no longer depends on potentially user-modifiable Python under `%LOCALAPPDATA%`.
- Service `RequiredPrivileges` reduced to `SeChangeNotifyPrivilege`.
- Prepared runtime excludes preexisting `site-packages`/Scripts from source Python and removes installation tools from the final runtime.
- Installer verifies no unmanifested runtime files, rejects reparse points, and rechecks hashes after copying to staging (TOCTOU mitigation).
- Service Named Pipe restricted to the exact user SID + **dedicated Service SID**, with no broad ACE for all `LocalService` processes.
- `integrity-manifest.json` and `security-check.ps1` detect later changes to protected code/runtime.
- Transactional staging + swap + best-effort rollback on failures after replacement.
- DPAPI explicitly distinguishes `current-user` and `local-machine` scopes; legacy v2 blobs remain supported.

### Changed

- Portable is now the recommended way to start; Service is the maximum-reliability option.
- Installed scripts use `runtime\python.exe`; `.venv` is reserved for Portable/development.
- Windows GitHub Releases build prepared Service and Portable runtimes from the same pinned dependency set.
- Suite expanded to 91 tests and core coverage gate raised to 85%.

## [3.0.0] - 2026-09-29

- `enable-automation.ps1` and `disable-automation.ps1` now require explicit elevation, validate IPC/Doctor, and fail safely when tasks or service state are inconsistent.

### Security

- Token and miIO access moved to a Windows Service running as `LocalService`; interactive Agent can no longer read the secret.
- Local Named Pipe ACL limited to the authorized user, dedicated Service SID, SYSTEM, and Administrators.
- Concurrent Named Pipe with bounded workers and one-way notifications for Windows events.
- Dedicated Service SID and hardened ACLs for code, config, data, logs, and secrets.
- Automatic migration of legacy plaintext tokens to DPAPI without printing them.
- GitHub Actions pinned by SHA; release includes SBOM, hashes, and attestations.

### Fixed

- Removed race that allowed an old sync to send ON after a newer Suspend/OFF through `intent_revision` and validation before every physical action.
- Critical OFF uses cancelable reassertion; a newer intent prevents an old reassert from incorrectly changing power.
- Suspend/Shutdown/Preshutdown no longer depend on a Scheduled Task starting late during shutdown.
- `PBT_APMRESUMEAUTOMATIC` does not invent presence or display ON.
- Service restart invalidates interactive state instead of assuming the display is active.
- `SetSuspendState` explicitly enables `SeShutdownPrivilege` with safe Win32 prototypes for x64.
- `Sleep Now` uses bounded one-way OFF by default; `--require-lamp-off` has a bounded total wait and cannot block suspension indefinitely.
- Agent/CLI no longer try to create/touch Service `secrets/` or `data/` after ACL hardening.
- Corrupt `device_cache.json` is quarantined and does not prevent startup.
- Discovery adds cooldown/exponential backoff to prevent repeated scans.
- Heartbeat refreshes Display/WTS/Presence timestamps even when values do not change, preventing false stale state during long sessions.
- Explicit `ctypes` prototypes prevent HWND/HANDLE truncation on Windows x64.
- `GUID_SESSION_USER_PRESENCE` is optional: its absence does not crash Agent.

### Added

- Windows Service support for Preshutdown/Shutdown/Power events.
- Interactive Agent for Display, WTS Lock/Unlock, User Presence, and tray.
- Agent → Service heartbeat to recover context after restarts.
- MAC discovery through Windows Neighbor before mDNS and `/24`; importer can cache the MAC observed from `mihome-ctl`.
- Network-change watcher invalidates discovery throttles and reconciles when appropriate.
- Strict v3 config and `config.schema.json`.
- Policy for respecting external changes (`enforce`, `respect_for_minutes`, `respect_until_next_profile`).
- Continuous nighttime profiles with optional interpolation.
- Tray with ON/OFF/Auto/Pause/Sync and persistent-failure notifications.
- Event Viewer support in addition to rotating logs.
- `LampTransport` interface to decouple `python-miio` and support future tests/migrations.
- Packaged `mijialamp` CLI.
- Ruff, mypy, core coverage, PSScriptAnalyzer, `pip-audit`, and Python 3.10–3.12 matrix.
- Explicit GPL-3.0-only license.

### Changed

- Removed Startup Sync that assumed display ON before sign-in.
- Removed privileged Boot/Shutdown Scheduled Tasks; only `Lamp Agent` at logon remains.
- Automation remains disabled after installation until `doctor` passes.
- Installer requires a real `service-status` smoke test of service/ACL/Named Pipe before finishing.
- v3 config rejects unknown keys and the migrator converts/removes legacy operational fields.
- Migration backups that may contain sensitive material are stored outside the runtime with ACLs limited to SYSTEM/Administrators; known legacy artifacts are cleaned.

## [2.1.0] - 2026-09-28

### Added

- Structure prepared for a public GitHub repository.
- `config.example.json` and exclusion of `config.json` from version control.
- GitHub Actions, Dependabot, templates, documentation, and release packaging.

### Changed

- Installer preserves local configuration and `import-token.ps1` no longer contains installation-specific data.

## [2.0.0] - 2026-09-28

### Added

- Single agent for Display/Resume/Suspend and periodic synchronization.
- Locks, atomic writes, physical reconciliation, bounded discovery, DPAPI, and rotating logs.
