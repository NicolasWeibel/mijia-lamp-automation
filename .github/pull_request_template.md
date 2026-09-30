## Resumen

<!-- Qué cambia y por qué. -->

## Tipo de cambio

- [ ] Bug fix
- [ ] Feature
- [ ] Refactor
- [ ] Seguridad
- [ ] Documentación / tooling

## Validación

- [ ] `python -m unittest discover -s tests -p "test_*.py" -v`
- [ ] `python scripts/check_repository.py`
- [ ] PowerShell parsea sin errores (si aplica)
- [ ] Probado en Windows con hardware real (si cambia integración Win32/miIO)

## Seguridad y privacidad

- [ ] No incluye tokens, `config.json`, `mi-tokens.json`, logs privados ni datos de una instalación real.
- [ ] Revisé el impacto sobre tareas `SYSTEM`, ACL, DPAPI y discovery (si aplica).
