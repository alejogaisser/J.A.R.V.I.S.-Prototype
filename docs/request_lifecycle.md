# Ciclo de vida y auditoría de solicitudes

## Contrato

Cada function call crea un `RequestContext` inmutable con:

- `request_id`: UUID local, independiente del ID del proveedor;
- `source`: `local`, `ui`, `wake`, `dashboard_text` o `dashboard_audio`;
- `tool_call_id`: identificador opaco de la function call;
- `created_at`: timestamp UTC.

El mismo contexto atraviesa validación, policy, confirmación, ejecución y
respuesta. Una acción pendiente reutiliza su contexto al ser aprobada; no crea
otro `request_id`. Los callers de `ToolExecutor` que todavía no entregan
contexto conservan el comportamiento anterior.

## Eventos

`logs/request_audit.jsonl` recibe, en orden, eventos de metadata:

1. `requested`;
2. `policy`;
3. `confirmation`;
4. `started`;
5. `completed`;
6. `response`.

Una solicitud bloqueada o inválida puede terminar antes de `started`. Una
confirmación pendiente emite una respuesta provisional y continúa con el mismo
ID después de la aprobación. La denegación cierra el request como `denied`.

## Privacidad

El sink acepta únicamente campos enumerados: IDs, evento, tool, source,
resultado categórico, operación normalizada, policy, código de error y duración.
No acepta ni serializa argumentos, prompts, cuerpos, mensajes, memoria, rutas,
consultas, direcciones, tokens o resultados de herramientas. Etiquetas no
estructuradas se reemplazan por `unknown` o `custom`.

Los fallos de directorio, apertura, encoding o serialización devuelven `False` y
no interrumpen policy, ejecución ni respuesta. La escritura puede desactivarse
con `JARVIS_REQUEST_AUDIT=0`; el archivo está dentro de `logs/`, excluido de Git.

## Límites deliberados

Esta fase añade correlación y duración de ejecución, pero no afirma que un
efecto externo haya sido observado. Evidencia, verificación, rollback y estados
de efecto pertenecen a `ToolResult v2` y a los verificadores de fases
posteriores.
