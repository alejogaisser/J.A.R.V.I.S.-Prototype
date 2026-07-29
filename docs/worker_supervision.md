# Supervisión y health de workers

## Alcance

La Fase 12 implementa el `P2 Workers` del documento rector. El nuevo
`services.workers.WorkerSupervisor` administra workers existentes mediante
callbacks tipados de `start`, `stop` y `health`; no reemplaza su trabajo ni
introduce un segundo runtime.

Los pilotos son:

- sesiones Playwright de `actions.browser_control`;
- sesión Live heredada de `actions.screen_processor`.

No se modifican Gemini Live principal, PCM, cámara física, UI visual, wake word
ni providers.

## Contrato

Cada `WorkerSpec` declara un nombre seguro, callbacks, presupuesto de reinicios
y backoff. El supervisor expone snapshots inmutables con:

- fase (`stopped`, `starting`, `running`, `degraded`, `restarting`,
  `stopping` o `failed`);
- intención de ejecución;
- health actual;
- starts, restarts y failures;
- último error sanitizado y tiempo monotónico de transición.

`start()`, `cancel()` y `close()` son idempotentes. Un monitor local realiza
health checks acotados y publica `WorkerStateChanged` sin payloads. Los eventos
sólo contienen nombre, fase y contadores allowlisted.

## Regla anti-duplicación

Un worker muerto o no responsivo se detiene antes de consumir presupuesto de
restart. El supervisor sólo reinicia si el adaptador demuestra que el recurso
anterior dejó de estar healthy y `stop()` no informó error.

Si cleanup falla o el worker sigue vivo:

1. la fase pasa a `failed`;
2. se desactiva la intención de ejecución;
3. no se inicia otro worker;
4. el fallo queda disponible en health y logging.

Esta regla prefiere degradación visible sobre threads, loops o procesos
duplicados.

## Piloto de navegador

`_BrowserSession.stop()` ahora cierra contexto y Playwright, detiene el event
loop y hace `join` del thread. `start()` limpia estado anterior y puede crear un
thread nuevo. Health envía un callback al loop y exige respuesta dentro del
timeout; `thread.is_alive()` por sí solo no se considera evidencia suficiente.

`_SessionRegistry` registra cada navegador con el supervisor, desregistra al
cerrar y ofrece snapshots. El composition root ejecuta el cleanup global al
salir.

## Piloto de visión

`_VisionSession` conserva la tarea raíz de su event loop. `stop()` la cancela,
espera el thread y deja que los `finally` existentes cierren el stream de audio.
El loop también responde a un ping de health. La conexión, modelos, blobs y
reintentos internos de Gemini permanecen heredados.

## Pruebas

`tests/test_worker_supervisor.py` usa fakes y loops sin hardware para cubrir:

- doble start/cancel/close;
- concurrencia de start;
- worker muerto y no responsivo;
- backoff y presupuesto agotado;
- fallo de startup y cleanup;
- bloqueo de restart cuando habría duplicación;
- orden y sanitización de eventos;
- logging allowlisted;
- restart/cierre real de loops browser y visión sin Playwright, cámara, audio,
  red ni Gemini;
- cleanup configurado en `main.py`.

El baseline local de la fase aprobó 369 tests y 104 subtests.

## Riesgos y rollback

Los callbacks de health deben ser breves. El supervisor no puede terminar por
fuerza un thread Python arbitrario: esa responsabilidad queda en el adaptador.
Los pilotos usan cancelación del loop y join acotado; un fallo queda `failed` y
no se reinicia.

Rollback: retirar la configuración/cleanup del composition root y volver a
invocar `start()`/`close()` directamente en los dos adaptadores. El supervisor
no altera sus payloads ni APIs funcionales.
