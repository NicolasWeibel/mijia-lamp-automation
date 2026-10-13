# Security Policy

[English](SECURITY.md) | [Español](SECURITY.es.md)

## Supported versions

| Version | Support |
|---|---|
| 3.1.x | Yes |
| 3.0.x | Migration to 3.1 recommended |
| 2.x | Migration only |

## Two execution models

### Portable

- No Administrator privileges.
- No Windows Service.
- DPAPI `CurrentUser` token.
- Data and runtime belong to the user running the application.

### Hardened Service

- Runs under `LocalService`, never `LocalSystem`.
- Dedicated Service SID and ACLs.
- DPAPI `LocalMachine` token, but the file is accessible only to SYSTEM/Administrators/Service SID.
- Private Python runtime, not writable by the interactive user.
- Local Named Pipe with user SID + dedicated Service SID ACL and rejection of remote clients.
- Elevated installer runs offline and does not run `pip`.

## Sensitive data

Never publish:

- miIO token;
- `mi-tokens.json`;
- `secrets/token.dpapi.json`;
- unreviewed full logs;
- network/location data you want to keep private.

## Supply chain

`prepare-service-runtime.ps1` runs without elevation and:

1. Downloads only binary wheels with pinned versions.
2. Builds a private CPython copy without preexisting `site-packages`.
3. Installs dependencies without Administrator privileges.
4. Removes package installation tools from the final runtime.
5. Generates SHA-256 for every file.

`install.ps1` does not download or install packages: it verifies the manifest, rejects reparse points, creates staging with an ACL limited to Administrators/SYSTEM before copying or running files, and verifies hashes again after copying. ACL failures stop installation. It then creates `integrity-manifest.json`, which `security-check.ps1` can verify again.

For maximum security, use the official Service release built by GitHub Actions: it includes a prepared runtime, SHA-256, SBOM, and Artifact Attestations. A runtime prepared locally keeps privilege separation, but by itself does not provide cryptographic publisher identity.

An official release may also attach GitHub Artifact Attestations/SBOM. Authenticode signing is not included unless the maintainer configures a certificate.

## Threat model limits

A local Administrator already controls the computer and can take ownership of files/processes. MijiaLamp does not attempt to protect secrets from a compromised administrator.

In Portable mode, malware running as the same user can act with that user's permissions. In Service mode, the authorized user can request lamp operations over IPC, but cannot read the token or modify code run by `LocalService`.

## Report vulnerabilities

Use GitHub Private Vulnerability Reporting when available. Do not publish valid tokens or exploits before coordinating a fix.
