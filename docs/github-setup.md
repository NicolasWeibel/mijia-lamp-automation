# Configuración recomendada de GitHub

## Primera publicación

1. Publicá solamente la carpeta fuente del proyecto como raíz del repositorio. Las carpetas `MijiaLamp-Portable-*` y `MijiaLamp-Service-*` son artefactos locales y no deben subirse como código fuente.
2. Creá un repositorio público vacío, sin agregar README, licencia o `.gitignore` desde GitHub: esos archivos ya están en el proyecto.
3. Antes del primer push, ejecutá `python scripts/check_repository.py`, `python scripts/verify_dependency_pins.py` y `pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/check-powershell.ps1`. Revisá además `git status --short` y `git ls-files` para detectar cualquier dato personal o secreto.
4. Desde la carpeta `mijia-lamp-automation`, agregá el remoto del repositorio vacío y subí solamente `main`:

   ```powershell
   git remote add origin https://github.com/OWNER/mijia-lamp-automation.git
   git push -u origin main
   ```

   Reemplazá `OWNER` por tu usuario u organización. No uses `git push --tags` en la primera subida.
5. Esperá a que terminen todos los jobs de CI. La primera release debe esperar también una prueba manual de Portable y Service con una lámpara real en Windows.
6. Configurá protección de `main`, alertas de dependencias, protección contra secretos y reglas para tags `v*` antes de publicar la primera release.
7. Publicá `v3.1.3` sólo cuando esas comprobaciones estén verdes. El workflow generará y verificará los ZIPs antes de crear la release.

El workflow está preparado, pero ningún ZIP local tiene todavía procedencia de GitHub. Esa procedencia existirá después de que una release se construya y se atestigüe desde el repositorio publicado.

## Repositorio

Nombre sugerido: `mijia-lamp-automation`

Descripción:

> Windows-native local automation for Xiaomi/Mijia lamps with a low-privilege service, Win32 session/power events, solar profiles and DPAPI-protected miIO tokens.

Topics:

`xiaomi`, `mijia`, `yeelight`, `python`, `windows-11`, `python-miio`, `home-automation`, `dpapi`, `win32`

## Protección de `main`

- Pull Request requerido.
- Status checks de CI requeridos.
- Conversaciones resueltas antes de merge.
- Bloquear force-push/delete.
- Requerir aprobación adicional para cambios bajo `.github/workflows/` si hay más mantenedores.

## Security

Habilitar:

- Dependabot alerts/security updates.
- Secret scanning y push protection cuando estén disponibles.
- Private vulnerability reporting.
- Artifact attestations para releases públicas.

## Versiones y releases

El proyecto usa versionado semántico `MAJOR.MINOR.PATCH`. Cada release corresponde a un único commit de `main` y a un tag anotado `vMAJOR.MINOR.PATCH`. Los tags publicados no se mueven; una corrección posterior usa una nueva versión.

Para preparar una versión nueva:

1. Actualizá `pyproject.toml`, `mijialamp/__init__.py`, `install.ps1`, `prepare-service-runtime.ps1`, `setup-portable.ps1` y `scripts/build-dependency-manifest.ps1`. Actualizá también las pruebas que incluyen la versión en fixtures. `scripts/check_repository.py` comprueba que los scripts de instalación coincidan con la versión del proyecto.
2. Agregá una entrada fechada en `CHANGELOG.md` y actualizá documentación o pins de dependencias si corresponde.
3. Abrí un PR, revisá los cambios y esperá CI verde en `main` tras el merge. Probá Portable y Service en Windows con una lámpara real para la primera release y para cambios que afecten instalación o comportamiento físico.
4. Desde `main` actualizado y limpio, creá y subí sólo el tag de esa versión:

   ```powershell
   git switch main
   git pull --ff-only origin main
   git status --short
   git tag -a v3.1.3 -m "MijiaLamp v3.1.3"
   git push origin v3.1.3
   ```

   Reemplazá `3.1.3` por la versión preparada. El workflow rechaza tags ligeros, tags que no apunten a un commit de `main` y tags que no coincidan con `pyproject.toml`.

El workflow de release audita los pins, construye ZIP/checksum/SBOM/manifest de dependencias, verifica el contenido de los ZIPs, atestigua los artefactos y crea GitHub Release. Revisá que el workflow termine correctamente y verificá el ZIP descargado antes de instalarlo.

## Licencia

El proyecto incluye GPL-3.0-only explícita. No reemplazarla por una licencia permisiva sin revisar primero la interacción con `python-miio` y las obligaciones de redistribución.
