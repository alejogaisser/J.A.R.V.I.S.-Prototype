# Logging estructurado de runtime

## Alcance

`core.structured_logging.StructuredRuntimeLog` es el owner de logs generales
del proceso principal. Complementa, sin reemplazar:

- `RequestAuditSink`, que conserva las fases sanitizadas de cada tool call;
- `CrashReporter` y `faulthandler`, que preservan diagnóstico de fallos fatales;
- la consola específica de wake word, necesaria para soporte de audio.

Este incremento no convierte masivamente los `print()` heredados.

## Salidas

Por defecto cada evento se publica como una línea JSON en:

- la consola de diagnóstico;
- `logs/runtime.jsonl`.

El archivo usa `RotatingFileHandler`, un máximo de 1 MiB y tres backups. La
carpeta `logs/` continúa ignorada por Git.

## Contrato

Campos base:

- `timestamp` UTC;
- `level`;
- `event`;
- `component`;
- `message` sanitizado y acotado, cuando existe.

Si el productor entrega un `RequestContext`, se agregan `request_id`, `source`
y `tool_call_id`. La metadata adicional se restringe a una allowlist de
estado, operación, duración, código de error, superficie y motivo. Cuerpos,
argumentos, prompts y campos desconocidos se descartan.

`main.py`, como composition root temporal, configura el owner y registra:

- `application_started`;
- `runner_failed`;
- `application_stopped`.

## Sanitización

`redact_diagnostic_text()` cubre asignaciones sensibles y parámetros de URL,
además de formatos de alta confianza de Google, GitHub, OpenAI, AWS y Slack y
encabezados de claves privadas. El valor coincidente nunca debe llegar al
archivo ni a la consola.

## Degradación y concurrencia

Los handlers estándar de `logging` serializan escrituras entre threads. Si el
archivo no puede abrirse, la consola permanece activa. Si ninguna salida puede
configurarse, `record()` devuelve `False`; el arranque continúa.

## Límites

- Los `print()` heredados todavía no llevan nivel ni correlación.
- `RequestAuditSink` conserva su archivo separado y todavía no rota.
- `CrashReporter` conserva su formato de traceback y archivo separado.
- No se midió hardware ni se inició Gemini, wake, cámara o micrófono.

## Medición local

En el entorno limpio de validación, 1.000 eventos secuenciales con archivo
JSONL, consola desactivada y límite de 1 MiB tomaron 64,829 ms en total
(0,064829 ms por evento). Es una microprueba de overhead del writer, no una
medición de latencia de JARVIS ni de hardware interactivo.

## Rollback

Retirar la construcción y las tres llamadas de `main.py` restaura el
comportamiento previo sin afectar `RequestAuditSink`, crash reports ni runtime.
El módulo puede permanecer sin consumidores hasta corregir el problema que
motivó el rollback.
