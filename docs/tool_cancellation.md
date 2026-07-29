# Cancelación e aislamiento de herramientas

## Contrato cooperativo

`ToolExecutor` crea un `CancellationToken` por ejecución. Sólo lo entrega a un
handler marcado como cancelable cuya firma acepte explícitamente
`cancellation_token`; los handlers heredados continúan recibiendo únicamente
sus argumentos.

Una ejecución con `RequestContext` puede señalarse mediante
`ToolExecutor.cancel(request_id)`. El timeout usa la misma señal. El executor
espera una gracia acotada para que el handler limpie recursos y declare su
estado:

- `ToolCancelled` transporta efecto, verificación, rollback y evidencia;
- una respuesta estructurada producida después de la señal conserva sus estados;
- falta de reconocimiento queda `cancellation_unacknowledged` y
  `effect=unknown`.

El token es thread-safe, de un solo uso y admite callbacks. No interrumpe
threads por la fuerza.

## Procesos

`run_cancellable_process()` inicia un proceso sin `shell`, consulta el token y
el timeout, y antes de retornar termina y recolecta el árbol creado. El cleanup
usa el PID exacto de `Popen` y sus descendientes mediante `psutil`; nunca busca
procesos por nombre.

El primer piloto fue el comando de ejecución de proyectos de `dev_agent`. En
Fase 13 esa ejecución automática se retiró: el agente conserva checkpoints
entre planificación y escrituras contenidas, y `AgentSupervisor` elimina los
archivos creados por la tarea si falla o se cancela. El runner sigue disponible
para tools explícitas que ejecuten procesos confiables y allowlisted.

## Límites

- Los handlers sin parámetro de cancelación mantienen el comportamiento legacy.
- Python no permite detener con seguridad un thread arbitrario; un handler que
  ignore el token puede continuar.
- Las llamadas bloqueantes de modelo todavía dependen del timeout externo del
  ToolExecutor; Python no puede terminar su thread por fuerza.
- `dev_agent` ya no instala, abre editor ni ejecuta el preview. Habilitarlo
  requerirá un sandbox de sistema operativo y otra confirmación, no sólo `cwd`.
- El rollback automático cubre únicamente archivos nuevos propiedad de la
  tarea; proyectos existentes se rechazan antes de escribir.
- `cancel(request_id)` requiere una ejecución activa con `RequestContext`.
