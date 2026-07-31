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
- artefactos generados dentro de `output/`;
- `AGENTS.md`, que contiene instrucciones locales de desarrollo.

Antes de hacer público un fork o una copia, verificá no sólo el árbol actual
sino también todo el historial de Git. Rotá inmediatamente cualquier
credencial que haya sido publicada, incluso si luego eliminaste el commit.

Los archivos `*.example.json` son plantillas sin secretos y sí pueden
versionarse.

## Chequeo preventivo

Ejecutá antes de cada commit:

```powershell
python scripts/check_secrets.py --repo-root .
```

El comando revisa archivos versionados y usa el blob del índice para todo
archivo staged. Falla si encuentra una ruta privada conocida o una credencial
de alta confianza. Su salida no incluye el valor coincidente.

Este control no revisa archivos no versionados ni demuestra que el historial
completo esté limpio. Si una credencial llegó a un commit o remoto, revocala y
rotala; eliminar solamente el archivo no es suficiente.

Los eventos generales de runtime usan `StructuredRuntimeLog`: sólo aceptan
metadata allowlisted, sanitizan mensajes y rotan `logs/runtime.jsonl`. Los
eventos de tools continúan en `RequestAuditSink` y no aceptan argumentos ni
cuerpos. Los logs reales permanecen fuera de Git.

## Lista mínima antes de cambiar la visibilidad

1. Ejecutar el escaneo de secretos sobre el árbol y todo el historial.
2. Confirmar que las plantillas usan únicamente placeholders reconocibles.
3. Revisar ramas y tags, porque también pasan a ser visibles.
4. Verificar que `git status` no incluya artefactos personales por agregar.
5. Confirmar créditos, licencias y avisos de terceros.
6. Recordar que una copia o fork realizado mientras el repositorio es público
   no puede retirarse de equipos ajenos volviendo el repositorio a privado.

## Alcance

JARVIS ejecuta acciones locales y puede conectarse con servicios externos.
Mantené activadas las confirmaciones para operaciones sensibles, aplicá el
principio de mínimo privilegio y revisá cada integración antes de concederle
acceso.
