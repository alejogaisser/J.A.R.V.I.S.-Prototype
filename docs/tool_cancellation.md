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

El primer piloto es el comando de ejecución de proyectos de `dev_agent`. Un
timeout ya no presenta una aplicación larga como posiblemente activa: termina
su árbol y lo informa. La acción también añade checkpoints entre planificación,
escritura, reintentos y ejecución. Si ya creó archivos, declara efecto parcial y
rollback manual disponible.

## Límites

- Los handlers sin parámetro de cancelación mantienen el comportamiento legacy.
- Python no permite detener con seguridad un thread arbitrario; un handler que
  ignore el token puede continuar.
- Las llamadas de modelo, la instalación automática y la apertura del editor de
  `dev_agent` todavía no usan transporte cancelable.
- El rollback de un proyecto parcial se declara, pero no se ejecuta
  automáticamente.
- `cancel(request_id)` requiere una ejecución activa con `RequestContext`.
