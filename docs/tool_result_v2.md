# ToolResult v2

## Estados independientes

`ToolResult` conserva los campos heredados `success`, `message`, `data`,
`error_code` y `request_id`, y añade un contrato versionado:

- `execution_status`: `succeeded`, `failed`, `rejected`, `timed_out` o
  `cancelled`;
- `effect_status`: `none`, `not_applied`, `applied`, `partial` o `unknown`;
- `verification_status`: `not_requested`, `verified`, `failed` o `unknown`;
- `rollback_status`: disponibilidad o resultado del rollback;
- `duration_ms`;
- `evidence`: identificadores breves aportados por un verifier.

`to_dict()` y `from_dict()` producen y validan el esquema 2. Estados
contradictorios, versiones desconocidas y duraciones negativas se rechazan.

## Adaptación heredada

Las tools existentes pueden seguir devolviendo texto, booleanos, mappings,
`None` o el `ToolResult` anterior:

- una lectura heredada exitosa se adapta como `succeeded/none`;
- una tool con posible efecto que sólo devuelve éxito textual queda
  `succeeded/unknown`;
- un fallo heredado no inventa que el efecto fue revertido o no aplicado;
- un resultado v2 retornado por el handler conserva efecto, verificación,
  rollback y evidencia;
- el executor completa `request_id` y duración medida.

La compatibilidad `success/message/data/error_code` continúa disponible durante
la migración por lotes de las 37 tools.

## Timeout y errores

Un timeout se representa como `execution_status=timed_out`,
`effect_status=unknown` y `verification_status=unknown`. Esto es deliberado:
`asyncio.wait_for()` deja de esperar, pero un handler síncrono enviado a un
thread puede seguir ejecutándose.

Una solicitud rechazada antes de invocar el handler usa
`rejected/not_applied`. Una excepción durante el handler usa `failed/unknown`.

## Integración

Las rutas normal y especial incluyen metadata v2 en `FunctionResponse` y en el
evento `completed` del audit sink. No se serializa `data` dentro de esa metadata
de respuesta. La Fase 5 añadirá verificadores concretos para que operaciones
piloto puedan afirmar `applied/verified` con evidencia real.
