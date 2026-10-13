# Contributing

[English](CONTRIBUTING.md) | [Español](CONTRIBUTING.es.md)

Thank you for contributing to MijiaLamp.

## Before you start

- Do not include tokens, `config.json`, `mi-tokens.json`, runtime state, or private data from an installation.
- Concurrency, power, or security changes should include tests.
- Win32 changes should explain which Windows event/API they use.

## Environment

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

## Before a PR

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
ruff check .
ruff format --check .
mypy mijialamp
python .\scripts\check_repository.py
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-powershell.ps1
```

## Architecture

Keep these boundaries:

- `policy/profiles/solar/state`: domain logic.
- `controller`: orchestration, reconciliation, and concurrency.
- `transport`: physical device contract.
- `miio_client`: python-miio adapter.
- `service_core`: service commands/lifecycle without pywin32.
- `service.py`: SCM adapter.
- `agent.py`: interactive Windows integration.

The Agent must never import or read the token.

## Pull requests

A PR should explain the problem, expected behavior, risks, and tests. Changes to ACLs, Service SID, DPAPI, Pipe, Suspend/Shutdown, discovery, or physical commands require an explicit security/concurrency section.

## Commits and versions

Use short commit messages that describe the change, with a prefix such as `feat:`, `fix:`, `docs:`, `test:`, or `chore:`. For example: `fix: preserve manual overrides across suspend`. Keep each commit focused on one reviewable change.

Versions are published from `main` using annotated `vMAJOR.MINOR.PATCH` tags, after updating `CHANGELOG.md` and passing the checks described in [`docs/github-setup.md`](docs/github-setup.md). Never move a published tag; publish a new version for any correction.
