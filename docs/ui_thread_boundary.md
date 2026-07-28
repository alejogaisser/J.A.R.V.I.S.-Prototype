# Frontera de hilo de UI

## Invariante

Sólo el hilo propietario de Qt puede leer o mutar widgets. Los workers de
`ToolExecutor`, el loop asyncio y los callbacks del dashboard pueden:

1. emitir un comando de presentación;
2. esperar una respuesta explícita cuando el comando la requiere;
3. consumir un snapshot inmutable protegido por lock.

No pueden recibir `MainWindow`, `JarvisUI._win` ni widgets concretos.

## Contrato

`core.ui_boundary.UiCommandFacade` es el puerto que `main.py` entrega a los
handlers. Su superficie se limita a:

- log y resultados de Study;
- contenido, Memory y GEO;
- transición a Pet e instrucciones de interfaz;
- snapshots de archivo seleccionado y micrófono.

La fachada delega en `JarvisUI`, cuyos métodos públicos emiten señales. Los
slots de `MainWindow` realizan la mutación y, para Study e
`interface_control`, completan un `threading.Event` con resultado o error.

## Snapshots

`MainWindow.tool_snapshot()` copia bajo `_tool_state_lock`:

- `current_file`;
- `listen_mode`;
- `microphone_enabled`;
- `muted`.

El snapshot evita consultar `DropZone` o cualquier otro QWidget desde el
runtime. El modo de superficie Main/Pet usa un lock separado porque pertenece
al coordinador `JarvisUI`.

## Cámara y cierre

El inicio y cierre siguen entrando por `_camera_request_sig`. La generación de
sesión impide que una cámara anterior cierre una nueva. El callback de análisis
se copia bajo `_cam_lock` y se ejecuta fuera del lock; cierre y reemplazo usan
el mismo lock.

## Verificación

`tests/test_ui_thread_boundary.py` comprueba la superficie exacta de la
fachada, que los handlers no reciben el dueño de widgets, la señal del teléfono,
los snapshots y la sincronización de cámara. También emite una señal desde un
thread real y confirma que el slot se ejecuta en el hilo de
`QCoreApplication`. Las regresiones de cámara, paneles rápidos y Pet/Main
permanecen en `tests/test_ui_mk2.py` y `tests/test_ui_v3.py`.

## Rollback

La fachada delega en los métodos existentes de `JarvisUI`; puede retirarse
reinyectando temporalmente ese adaptador sin cambiar firmas de acciones. Las
señales y snapshots deben conservarse mientras existan callbacks fuera del
hilo Qt.
