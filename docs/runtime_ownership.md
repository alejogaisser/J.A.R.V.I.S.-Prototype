# Ownership de sesión, audio, visión y lifecycle

## Frontera

`JarvisLive` sigue siendo el composition root y mantiene el transporte Gemini,
las colas y las tareas existentes. `RuntimeServices` concentra el estado mutable
que antes estaba distribuido en flags:

- `SessionService`: identidad del transporte observado, generación, conexiones,
  reconexiones y `LiveSessionState`;
- `AudioService`: interrupción explícita, generación anti-stale, watchdog,
  heartbeat y recuperaciones de micrófono;
- `VisionService`: análisis en vuelo, cooldown y backpressure de frames;
- `LifecycleService`: solicitud de cierre, audio de despedida, drenaje,
  deadline de respaldo e inicio de shutdown exactamente una vez.

Cada servicio expone transiciones, no requiere UI ni importa Gemini. Sus
snapshots son dataclasses inmutables y contienen sólo contadores/estados.

## Reglas

1. Sólo `SessionService.bind()` y `unbind()` cambian la identidad observada del
   transporte. Un segundo transporte simultáneo se rechaza y un disconnect
   atrasado no puede limpiar el actual.
2. Una reconexión preserva el checkpoint resumible y contadores, pero reinicia
   interrupción, watchdog, análisis en vuelo y frame pendiente.
3. Cada ESC crea una generación. Una tarea de recuperación vieja no puede
   liberar una interrupción posterior.
4. Visión y cámara usan `try/finally`: el owner libera busy/frame incluso ante
   excepción. Los frames concurrentes se descartan y contabilizan.
5. Shutdown sólo avanza después de despedida+drenaje o del deadline. El inicio
   final es idempotente.

## Compatibilidad y rollback

No cambian el modelo Live, `send_realtime_input`, `session.receive()`, formatos
PCM, blobs de cámara ni señales de UI. El rollback consiste en volver a los
flags de `JarvisLive`; `core/live_session.py` conserva sus tipos públicos.

## Límites pendientes

- `session` aún es una referencia de composición usada por IO en `main.py`.
- `_phone_active`, `audio_in_queue`, `out_queue` y streams físicos no fueron
  extraídos.
- No se ejecutaron micrófono, cámara ni una sesión Gemini real.
- El lifecycle general de UI, dashboard, monitor y tareas proactivas continúa
  distribuido.
- Las métricas están disponibles en snapshots, pero todavía no se exportan a
  telemetría o UI.
