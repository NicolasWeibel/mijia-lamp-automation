# Desarrollo

## Entorno

Python soportado: 3.10–3.12.

La preparación de runtime con locks verificados requiere Windows x64. Para renovar los hashes después de revisar y cambiar las versiones de los locks, descargá los wheels para las tres versiones compatibles:

```powershell
$wheelDir = Join-Path $env:TEMP "mijialamp-reviewed-wheels"
New-Item -ItemType Directory -Force $wheelDir | Out-Null
python scripts/verify_dependency_pins.py --plain-output (Join-Path $env:TEMP "mijialamp-pins.txt")
foreach ($version in @("3.10", "3.11", "3.12")) {
    $abi = "cp" + $version.Replace(".", "")
    python -m pip download --only-binary=:all: --no-deps --platform win_amd64 --python-version $version --implementation cp --abi $abi --dest $wheelDir -r (Join-Path $env:TEMP "mijialamp-pins.txt")
    if ($LASTEXITCODE -ne 0) { throw "Falló la descarga para Python $version" }
}
python scripts/update_dependency_hashes.py $wheelDir
python scripts/verify_dependency_pins.py
```

Usá un directorio de wheels vacío, verificá la procedencia de los paquetes antes de aceptar sus nuevos hashes y probá `pip --require-hashes` en las tres versiones. `update_dependency_hashes.py` exige un wheel para cada paquete fijado y rechaza paquetes adicionales.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

## Tests

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
```

Los tests de hardware no forman parte de la suite normal. `LampController` debe testearse mediante `LampTransport` fake. Cambios de concurrencia deben incluir un caso donde una operación queda bloqueada y aparece una intención nueva.

## Calidad

```powershell
ruff check .
ruff format --check .
mypy mijialamp
coverage run -m unittest discover -s tests -p "test_*.py"
coverage report -m
python .\scripts\check_repository.py
pwsh -NoProfile -File .\scripts\check-powershell.ps1
```

El gate de coverage mide principalmente el core, exige al menos **85%** y omite adaptadores Win32/miIO difíciles de ejecutar fuera de Windows.

## Principios

- Policy no habla con Windows ni miIO.
- Controller no importa pywin32.
- `agent.py` nunca importa `secrets_store` ni `miio_client`.
- En Service, sólo `MijiaLampService` controla físicamente la lámpara.
- En Portable, `portable.py` aloja el mismo core dentro del usuario.
- Cualquier espera seguida de un comando físico revalida `intent_revision`.
- Nunca reemplazar errores críticos por `except BaseException: pass`.
- El instalador elevado no resuelve/descarga paquetes.

## Releases

Sin runtime preparado:

```powershell
.\scripts\build-release.ps1
```

Para producir una release Service lista para instalación offline en Windows:

```powershell
.\prepare-service-runtime.ps1 -Recreate
.\scripts\build-release.ps1 -IncludePreparedRuntime
python .\scripts\verify_release.py .\release --require-runtime
```

El workflow de tags hace esta preparación en un runner Windows y agrega SBOM, SHA-256 y attestations.
