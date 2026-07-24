# Seguridad

## Reportar una vulnerabilidad

No publiques credenciales ni detalles explotables en un issue. Si el
repositorio está alojado en GitHub, utilizá **Security → Report a
vulnerability** para enviar un reporte privado al mantenedor.

## Datos que nunca deben publicarse

El repositorio excluye deliberadamente:

- `config/api_keys.json`, archivos `.env` y certificados;
- clientes OAuth y tokens de servicios externos;
- configuraciones personales y auditorías de conectores;
- `memory/long_term.json` y demás memoria personal;
- logs, capturas, workspaces locales y entornos virtuales;
- `AGENTS.md`, que contiene instrucciones locales de desarrollo.

Antes de hacer público un fork o una copia, verificá no sólo el árbol actual
sino también todo el historial de Git. Rotá inmediatamente cualquier
credencial que haya sido publicada, incluso si luego eliminaste el commit.

Los archivos `*.example.json` son plantillas sin secretos y sí pueden
versionarse.

## Alcance

JARVIS ejecuta acciones locales y puede conectarse con servicios externos.
Mantené activadas las confirmaciones para operaciones sensibles, aplicá el
principio de mínimo privilegio y revisá cada integración antes de concederle
acceso.
