# Contributing

Gracias por contribuir a MijiaLamp.

## Antes de empezar

- No incluyas tokens, `config.json`, `mi-tokens.json`, runtime state o datos privados de una instalación.
- Cambios de concurrency/power/security deben incluir tests.
- Cambios Win32 deben explicar qué evento/API de Windows utilizan.

## Entorno

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

## Antes de un PR

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
ruff check .
ruff format --check .
mypy mijialamp
python .\scripts\check_repository.py
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-powershell.ps1
```

## Arquitectura

Mantené las fronteras:

- `policy/profiles/solar/state`: lógica de dominio.
- `controller`: orquestación, reconciliación y concurrency.
- `transport`: contrato físico.
- `miio_client`: adapter de python-miio.
- `service_core`: comandos/lifecycle del servicio sin pywin32.
- `service.py`: adapter SCM.
- `agent.py`: integración interactiva Windows.

El Agent nunca debe importar/leer el token.

## Pull requests

Un PR debe explicar problema, comportamiento esperado, riesgos y tests. Cambios en ACL, Service SID, DPAPI, Pipe, Suspend/Shutdown, discovery o comandos físicos requieren una sección explícita de seguridad/concurrencia.

## Commits y versiones

Usá mensajes breves que describan el cambio, con un prefijo como `feat:`, `fix:`, `docs:`, `test:` o `chore:`. Por ejemplo: `fix: preserve manual overrides across suspend`. Mantené cada commit enfocado en un cambio revisable.

Las versiones se publican desde `main` con tags anotados `vMAJOR.MINOR.PATCH`, después de actualizar `CHANGELOG.md` y pasar los controles descritos en [`docs/github-setup.md`](docs/github-setup.md). No muevas un tag ya publicado; publicá una nueva versión para cualquier corrección.
