# Security v3.1

[English](security.md) | [Español](es/security.md)


## Goals

1. Prevent plaintext secrets.
2. Prevent a service from running code the user can modify.
3. Avoid network access and package managers during elevation.
4. Restrict IPC to the expected machine and user.
5. Keep a Portable option that needs no elevated privileges.

## Portable

The wizard's QR authorization runs as a standard user and only during setup. It queries `account.xiaomi.com`, `ak.account.xiaomi.com`, `sgp.lp.account.xiaomi.com`, `sts.api.io.mi.com`, and Xiaomi regional APIs over HTTPS. The account session stays in memory and is not written to disk. The device list and tokens travel only through a local pipe from the onboarding process to its UI; only the selected device token is saved as a DPAPI blob in the private `%LOCALAPPDATA%\MijiaLamp\onboarding-private` directory. The Import token step rewraps it for Portable or Service and removes the temporary blob after success. The Xiaomi password, token, and session are not placed in process arguments or logs. The elevated Service phase makes no network requests.

The QR integration uses Xiaomi endpoints whose future compatibility is not guaranteed. If they fail, the user can import a selected `mi-tokens.json` file. Lamp control continues to use only the LAN.

The token is encrypted with DPAPI `CurrentUser`. `portable.py`, the controller, and miIO run in the same user session. The Portable Pipe has a different name from the service pipe and a DACL tied to the current SID.

Portable does not aim to survive sign-out or provide SCM Preshutdown. In return, it removes the privilege boundary and needs no administrative installation.

## Hardened Service

### Private runtime

The service does **not** use Python installed under `%LOCALAPPDATA%` or another location the user can modify. `prepare-service-runtime.ps1` copies the base installation, discards `Lib/site-packages` and `Scripts`, installs only the pinned set, and tests relocation.

Local dependency preparation accepts binary wheels only, to avoid running source package builds. The 30 packages are pinned by version, and the locks include SHA-256 hashes for wheels for Windows x64 and Python 3.10–3.12. `pip --require-hashes` checks those hashes both when downloading and installing offline. A wheel with different bytes is rejected; updating a dependency requires reviewing its new wheel and explicitly updating its hash.

This control verifies that the repository-approved bytes are installed; it does not prove those bytes are malware-free or protect against malicious changes to the repository, base Python, or build machine. Other architectures are not covered by these hashes during local preparation.

The resulting runtime is hashed file by file. The elevated installer verifies that no files are missing or unmanifested, every SHA-256 matches, no prepared artifact is a reparse point, and the hashes still match **after copying to staging**, closing the TOCTOU window between verification and copying.

After installation, `integrity-manifest.json` records immutable files and `security-check.ps1` verifies their hashes again.

The staging directory is created with a protected ACL that allows only Administrators and SYSTEM. Before running the prepared Python, the installer checks the owner and ACEs, rejects old directories containing reparse points, and stops if `icacls` fails. The backup destination is validated before the old service is stopped.

The installer requires `install.ps1` in the source manifest and, after copying, rejects any code or script in staging that is not listed. CI tests this by adding a root script at the last moment.

Service mode accepts only the official `ProgramData\MijiaLamp` folder. Installing under a parent the user can modify would break staging isolation; uninstall also restricts the path to avoid accidental deletion with `-DeleteFiles`.

If installation fails after stopping the previous version, rollback preserves its files without running its Python or `service.py` as Administrator. It does not restart Service or Agent: check their state, inspect the files, and repeat installation from a verified release. `uninstall.ps1` removes the service through the Windows service manager and also avoids running the installed runtime with elevated privileges.

The runtime is copied to `C:\ProgramData\MijiaLamp\runtime`, where the user has only `Read & Execute` access.

### Elevation without a package manager

`install.ps1` contains no `pip install`, `pip download`, `Invoke-WebRequest`, or `Invoke-RestMethod`. All package resolution and installation happen before elevation.

### Service

- Account: `NT AUTHORITY\LocalService`.
- Dedicated Service SID enabled.
- `RequiredPrivileges`: `SeChangeNotifyPrivilege`.
- Bounded SCM restarts.
- Preshutdown configured.
- No TCP/HTTP listener.

### ACLs

- Root/code/runtime: user `RX`, Service SID `RX`.
- `config.json`: user `Modify`, service `Read`.
- `data/`: service `Modify`, user `Read`.
- `logs/`: both `Modify`.
- `secrets/`: Service SID/SYSTEM/Administrators only.

`security-check.ps1` audits these invariants after installation.

## DPAPI

Blobs include scope metadata:

- `current-user` for Portable.
- `local-machine` for Service.
- v2 blobs with `dpapi-local-machine-service-owned` are normalized to `local-machine`.

Historical DPAPI entropy is retained to migrate existing secrets without printing them.

## Named Pipes

- Service: `\\.\pipe\MijiaLamp-v3`
- Portable: `\\.\pipe\MijiaLamp-Portable-v3`

Both use bounded JSON messages and `PIPE_REJECT_REMOTE_CLIENTS`. Service authorizes the SID selected during installation **and the exact Service SID for `MijiaLampService`**; it does not grant access to the entire `LocalService` account. Portable uses the current process SID.

## Races and critical OFF

Functional safety matters too: `intent_revision` cancels stale decisions and `critical_off_revision` prioritizes Suspend/Shutdown/Manual OFF. Resume increments the revision without inventing presence, and Suspend hints have a deadline to prevent late OFF commands. A sync waiting on the network cannot send ON after a newer intent.

## Release provenance

The hash manifest protects integrity between preparation and installation, but does not establish the publisher's cryptographic identity. The release workflow is configured to create Windows ZIPs with SHA-256, an SBOM, and GitHub Artifact Attestations. Once the repository is published, prefer these prepared artifacts for Service mode over building the runtime locally. Without Authenticode, an administrator must verify ZIP provenance before elevation.

For an already published official release:

1. Download the Service ZIP from the Releases page of the repository you trust. Keep the ZIP unchanged.
2. Verify its provenance with `gh attestation verify .\MijiaLamp-Service-VERSION.zip -R NicolasWeibel/mijia-lamp-automation`, replacing `VERSION` with the downloaded version. Verification must succeed before extraction or elevation.
3. Extract the ZIP and run `install.ps1` from an elevated PowerShell session. The installer checks runtime and source hashes before and after copying; it uses neither the Internet nor `pip`.
4. After installation, run `security-check.ps1` and `lampctl.py doctor` before enabling automation.

The attestation shows which repository and workflow produced those bytes; it does not prove that the code, dependencies, or runner are free of malware. A local build uses the Python and packages on your machine and provides less provenance assurance. A `.sha256` delivered with a ZIP only protects against accidental corruption unless authenticated through another channel.

After changing code, publish a new version. An attestation for an older version does not authenticate a modified copy, even if its folder name stays the same.
