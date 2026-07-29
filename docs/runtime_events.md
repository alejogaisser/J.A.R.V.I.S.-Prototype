# Eventos tipados de runtime

## Alcance

La Fase 11 implementa el `P2 Event bus` del PDF únicamente para hechos que
cruzan fronteras. `core.events.EventBus` conecta owners de runtime, dashboard,
composition root y logging sin transportar comandos ni sustituir llamadas
locales.

Eventos actuales:

- `SessionStateChanged`: conexión, desconexión y reconexión;
- `AudioInterruptionChanged`: inicio, liberación y reset de una interrupción;
- `VisionAnalysisChanged`: inicio, fin y reset de análisis;
- `ShutdownStateChanged`: solicitud y comienzo efectivo del cierre;
- `DashboardConnected`: conexión por PIN, QR o dispositivo conocido;
- `InputReceived`: presencia de texto/wake remoto, nunca su contenido.

## Invariantes

- Los eventos son dataclasses inmutables con `event_id`, UTC y tiempo
  monotónico.
- `request_id` sólo se incluye cuando ya existe un identificador seguro; visión
  y shutdown conservan el de la tool que originó la transición.
- No se publican texto, prompts, audio, imágenes, tokens, device IDs ni cuerpos.
- Los owners construyen el evento dentro del lock y lo publican después de
  liberarlo.
- Los handlers se copian bajo lock y se ejecutan en orden, sin mantener el lock
  del bus.
- Un handler fallido no impide los siguientes ni revierte la transición.
- La entrega es síncrona: un subscriber debe ser breve o encolar su propio
  trabajo.

## Compatibilidad

El composition root consume `DashboardConnected` en lugar de registrar un
callback directo. `DashboardServer.set_connect_callback()` y
`set_wake_callback()` permanecen como adaptadores heredados para consumidores
externos, pero JARVIS ya no depende de ellos.

`StructuredRuntimeLog.record_runtime_event()` consume la metadata allowlisted
y correlaciona por `event_id`/`request_id`. El logging continúa siendo best
effort y no recibe payload sensible.

## Pruebas

`tests/test_runtime_events.py` cubre:

- orden, desuscripción y reentrancia;
- publicación concurrente;
- aislamiento de excepciones;
- eventos reales de los cuatro owners;
- correlación de visión/shutdown;
- compatibilidad de callbacks del dashboard;
- ausencia de datos de comando/token/device;
- serialización allowlisted;
- composición sin callback directo dashboard→runtime.

## Riesgos y rollback

El bus es local al proceso y no persiste ni reintenta eventos. La entrega
síncrona no es adecuada para IO lento. Los callbacks heredados de wake y cámara
siguen fuera de este piloto.

Rollback: construir `RuntimeServices` sin un bus compartido, retirar la
suscripción del logger y volver temporalmente al setter de conexión del
dashboard. Los owners y sus APIs públicas conservan defaults compatibles.
