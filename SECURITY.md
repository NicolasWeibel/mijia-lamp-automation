# Security Policy

## Versiones soportadas

| Versión | Soporte |
|---|---|
| 3.1.x | Sí |
| 3.0.x | Migración recomendada a 3.1 |
| 2.x | Sólo migración |

## Dos modelos de ejecución

### Portable

- sin privilegios administrativos;
- sin Windows Service;
- token DPAPI `CurrentUser`;
- datos y runtime pertenecen al usuario que ejecuta la aplicación.

### Hardened Service

- servicio bajo `LocalService`, nunca `LocalSystem`;
- Service SID y ACLs específicas;
- token DPAPI `LocalMachine`, pero el archivo sólo es accesible por SYSTEM/Administradores/Service SID;
- runtime Python privado e inmutable para el usuario interactivo;
- Named Pipe local con ACL por SID de usuario + Service SID específico y rechazo de clientes remotos;
- instalador elevado offline y sin ejecución de `pip`.

## Datos sensibles

Nunca publicar:

- token miIO;
- `mi-tokens.json`;
- `secrets/token.dpapi.json`;
- logs completos sin revisar;
- datos de red/ubicación que quieras mantener privados.

## Supply chain

`prepare-service-runtime.ps1` se ejecuta sin elevación y:

1. descarga sólo wheels binarios con versiones fijadas;
2. construye una copia privada de CPython sin `site-packages` preexistentes;
3. instala dependencias sin Admin;
4. elimina herramientas de instalación del runtime final;
5. genera SHA-256 de cada archivo.

`install.ps1` no descarga ni instala paquetes: verifica el manifest, rechaza reparse points, crea staging con ACL exclusiva de Administradores/SYSTEM antes de copiar o ejecutar archivos y vuelve a verificar hashes tras la copia. Los fallos al aplicar ACL detienen la instalación. Después genera `integrity-manifest.json`, que `security-check.ps1` puede revalidar.

Para máxima seguridad, usá la release Service oficial generada por GitHub Actions: incluye el runtime ya preparado, SHA-256, SBOM y Artifact Attestations. Un runtime preparado localmente conserva la separación de privilegios, pero no aporta por sí solo una identidad criptográfica del publicador.

Una release oficial puede adjuntar además GitHub Artifact Attestations/SBOM. La firma Authenticode no está incluida salvo que el mantenedor configure un certificado propio.

## Límite del modelo de amenaza

Un Administrador local ya controla el equipo y puede tomar propiedad de archivos/procesos. MijiaLamp no intenta proteger secretos frente a un administrador comprometido.

En Portable, malware ejecutándose como el mismo usuario puede actuar con los permisos de ese usuario. En Service, el usuario autorizado puede solicitar operaciones de lámpara por IPC, pero no leer el token ni modificar el código que ejecuta `LocalService`.

## Reportar vulnerabilidades

Usá GitHub Private Vulnerability Reporting cuando esté disponible. No publiques tokens válidos ni exploits antes de coordinar una corrección.
