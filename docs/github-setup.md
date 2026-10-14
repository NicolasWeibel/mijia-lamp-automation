# Recommended GitHub setup

[English](github-setup.md) | [Español](es/github-setup.md)


## First publication

1. Publish only the project source folder as the repository root. `MijiaLamp-Portable-*` and `MijiaLamp-Service-*` folders are local artifacts and must not be uploaded as source code.
2. Create an empty public repository without adding a README, license, or `.gitignore` from GitHub; these files are already in the project.
3. Before the first push, run `python scripts/check_repository.py`, `python scripts/verify_dependency_pins.py`, and `pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/check-powershell.ps1`. Also inspect `git status --short` and `git ls-files` for personal data or secrets.
4. From the `mijia-lamp-automation` folder, add the empty repository as a remote and push only `main`:

   ```powershell
   git remote add origin https://github.com/NicolasWeibel/mijia-lamp-automation.git
   git push -u origin main
   ```

   This has already been done for `NicolasWeibel/mijia-lamp-automation`; do not run `git remote add` again if `origin` exists. Do not use `git push --tags` for the first push.
5. Wait for every CI job to finish. The first release should also wait for a manual Portable and Service test with a real lamp on Windows.
6. Configure `main` branch protection, dependency alerts, secret protection, and `v*` tag rules before publishing the first release.
7. Publish the prepared version only when those checks are green. The workflow builds and verifies the ZIPs before creating the release.

The workflow is ready, but no local ZIP yet has GitHub provenance. That provenance will exist after a release is built and attested from the published repository.

## Repository

Suggested name: `mijia-lamp-automation`

Description:

> Windows-native local automation for Xiaomi/Mijia lamps with a low-privilege service, Win32 session/power events, solar profiles and DPAPI-protected miIO tokens.

Topics:

`xiaomi`, `mijia`, `yeelight`, `python`, `windows-11`, `python-miio`, `home-automation`, `dpapi`, `win32`

## Protect `main`

- Require a pull request.
- Require CI status checks.
- Resolve conversations before merge.
- Block force-push and deletion.
- Require additional approval for changes under `.github/workflows/` if there are other maintainers.

## Security

Enable:

- Dependabot alerts/security updates.
- Secret scanning and push protection when available.
- Private vulnerability reporting.
- Artifact attestations for public releases.

## Versions and releases

The project uses `MAJOR.MINOR.PATCH` semantic versioning. Each release corresponds to one commit on `main` and an annotated `vMAJOR.MINOR.PATCH` tag. Published tags are never moved; corrections use a new version.

To prepare a new version:

1. Change only `__version__` in `mijialamp/__init__.py`. Packaging reads it through setuptools; PowerShell scripts read it as data through `version.ps1`; test fixtures use the same source. `scripts/check_repository.py` rejects duplicate fixed versions and mismatching release tags.
2. Add a dated entry to `CHANGELOG.md` and update documentation or dependency pins as needed.
3. Open a PR, review the changes, and wait for green CI on `main` after merge. Test Portable and Service on Windows with a real lamp for the first release and for changes affecting installation or physical behavior.
4. From an up-to-date, clean `main`, create and push only the version tag:

   ```powershell
   git switch main
   git pull --ff-only origin main
   git status --short
   . .\version.ps1
   $version = Get-MijiaLampVersion
   git tag -a "v$version" -m "MijiaLamp v$version"
   git push origin "v$version"
   ```

   The commands read the version automatically from the current checkout. The workflow rejects lightweight tags, tags that do not point to a commit on `main`, and tags that do not match `pyproject.toml`.

The release workflow audits pins, builds ZIP/checksum/SBOM/dependency manifest, verifies ZIP contents, attests the artifacts, and creates the GitHub Release. Check that the workflow succeeds and verify the downloaded ZIP before installing it.

## License

The project explicitly uses GPL-3.0-only. Do not replace it with a permissive license without first reviewing its interaction with `python-miio` and redistribution obligations.
