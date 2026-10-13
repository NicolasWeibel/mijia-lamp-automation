# Development

[English](development.md) | [Español](es/development.md)


## Environment

Supported Python: 3.10–3.12.

Preparing a runtime with verified locks requires Windows x64. To renew hashes after reviewing and changing lock versions, download wheels for all three supported versions:

```powershell
$wheelDir = Join-Path $env:TEMP "mijialamp-reviewed-wheels"
New-Item -ItemType Directory -Force $wheelDir | Out-Null
python scripts/verify_dependency_pins.py --plain-output (Join-Path $env:TEMP "mijialamp-pins.txt")
foreach ($version in @("3.10", "3.11", "3.12")) {
    $abi = "cp" + $version.Replace(".", "")
    python -m pip download --only-binary=:all: --no-deps --platform win_amd64 --python-version $version --implementation cp --abi $abi --dest $wheelDir -r (Join-Path $env:TEMP "mijialamp-pins.txt")
    if ($LASTEXITCODE -ne 0) { throw "Download failed for Python $version" }
}
python scripts/update_dependency_hashes.py $wheelDir
python scripts/verify_dependency_pins.py
```

Use an empty wheel directory, verify package provenance before accepting new hashes, and test `pip --require-hashes` on all three versions. `update_dependency_hashes.py` requires a wheel for each pinned package and rejects additional packages.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

## Tests

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
```

Hardware tests are not part of the normal suite. Test `LampController` using a fake `LampTransport`. Concurrency changes should include a case where an operation is blocked and a new intent arrives.

## Quality

```powershell
ruff check .
ruff format --check .
mypy mijialamp
coverage run -m unittest discover -s tests -p "test_*.py"
coverage report -m
python .\scripts\check_repository.py
pwsh -NoProfile -File .\scripts\check-powershell.ps1
```

The coverage gate measures mainly the core, requires at least **85%**, and omits Win32/miIO adapters that are difficult to run outside Windows.

## Principles

- Policy does not talk to Windows or miIO.
- Controller does not import pywin32.
- `agent.py` never imports `secrets_store` or `miio_client`.
- In Service mode, only `MijiaLampService` physically controls the lamp.
- In Portable mode, `portable.py` hosts the same core within the user process.
- After any wait and before a physical command, revalidate `intent_revision`.
- Never replace critical errors with `except BaseException: pass`.
- The elevated installer does not resolve or download packages.

## Releases

Without a prepared runtime:

```powershell
.\scripts\build-release.ps1
```

To produce a Service release ready for offline installation on Windows:

```powershell
.\prepare-service-runtime.ps1 -Recreate
.\scripts\build-release.ps1 -IncludePreparedRuntime
python .\scripts\verify_release.py .\release --require-runtime
```

The tag workflow performs this preparation on a Windows runner and adds an SBOM, SHA-256 hashes, and attestations.
