# Auditoría técnica de JARVIS Mark LI

## Alcance y método

Auditoría realizada el 2026-07-28 sobre el working tree local y contrastada con el PDF de arquitectura v1.1. Se revisaron:

- estructura versionada completa;
- entrypoints, runtime, audio, UI, wake word, herramientas, permisos, memoria, conectores, dashboard y acciones;
- imports y dependencias;
- patrones de excepciones, subprocess, red, configuración y secretos;
- suite, sintaxis, imports y arranque no interactivo.

No se leyeron contenidos de claves, OAuth, certificados, memoria personal o logs. No se ejecutaron acciones reales del sistema, red externa, cuentas, Gemini Live, micrófono, cámara o dashboard LAN.

Fase 10 incorporó un control preventivo reproducible sobre archivos
versionados y blobs staged. El chequeo bloquea rutas sensibles y formas de
credenciales de alta confianza sin mostrar el valor. No sustituye la revisión
del historial remoto, la rotación de una credencial expuesta ni un detector
especializado de entropía.

## Línea base verificada

| Comprobación | Resultado |
| --- | --- |
| Rama dedicada | `codex/audit-architecture-v1-1` |
| Base | `0f60519` |
| Cambios locales previos | 4 archivos de wake/launcher modificados y `output/` sin versionar |
| Python | 3.14.6 |
| `pip check` | sin dependencias rotas instaladas |
| Launcher | `jarvis_launcher.py --help` correcto |
| Smoke imports | launcher, wake, tools, permisos, Live, runtime y memoria correctos |
| Import `main.py` offscreen | correcto; 37 tools |
| `compileall` | correcto |
| Suite | 218 passed, 1 skipped, 28 subtests; 1 warning externo |
| Recuento | 102 Python, 27.876 líneas, 22 tests, 37 tools |
| Deuda estática | 360 `except Exception/BaseException` amplios, 67 con `pass`, 303 `print()` |

## Discrepancias PDF-código

1. **Origen remoto:** la policy sabe elevar fuentes no locales, pero el runtime siempre construye `ExecutionContext(source="local")`.
2. **Policy universal:** `save_memory` se ejecuta antes de registro y policy.
3. **Dispatch central:** existe ToolExecutor, pero las rutas especiales siguen dentro de `main.py` y hay branches heredados inalcanzables.
4. **Matriz de tools:** resuelto en Fase 0 mediante
   `docs/tool_migration_matrix.md` y un test que sincroniza las 37 tools con el
   registro efectivo.
5. **Dependencias:** el runtime principal y pytest se reproducen mediante
   `requirements-dev.txt`; las capacidades opcionales anunciadas todavía no
   tienen extras verificados.
6. **Atomicidad:** memoria y runtime state reemplazan temporales; PermissionStore no.
7. **UI:** `ui_mk2` separa varias piezas, pero acciones registradas pueden tocar Qt desde worker threads.
8. **Observabilidad:** CrashReporter y auditoría de conectores existen; no hay traza estructurada de toda tool call.

## Hallazgos críticos

### C-01 - El origen remoto se degrada a local

- **Estado:** resuelto en Fase 1.
- **Descripción:** todos los tool calls son evaluados como locales, aunque el texto o audio provenga del dashboard.
- **Evidencia:** `main.py:1350-1354` fija `ExecutionContext(source="local")`; `dashboard/server.py:778-784` y `main.py:2126-2143` reinyectan comandos sin conservar origen. La elevación remota sí existe en `core/permissions/policy.py:97-110`.
- **Impacto:** un cliente LAN autenticado puede recibir mínimos más permisivos que los diseñados para una fuente remota.
- **Solución recomendada:** crear `RequestContext/InputSource`, conservarlo desde cada entrada y exigirlo en policy/executor.
- **Esfuerzo:** medio.
- **Prioridad:** P0, antes de ampliar dashboard o tools.
- **Resolución:** `InputSource` tipa las cinco entradas; texto y audio del
  dashboard fijan un origen remoto que no puede degradarse dentro del turno, y
  `_execute_tool()` lo entrega a `PermissionPolicy`.

### C-02 - `file_processor` puede escribir o ejecutar con clasificación de sólo lectura

- **Estado:** resuelto en Fase 1 para la policy central.
- **Descripción:** la herramienta no aparece en `RISK` ni `CONFIRMATION`, por lo que toma defaults `READ_ONLY/NEVER`; sin regla específica, policy queda `FREE`.
- **Evidencia:** `core/tools/builtins.py:11-56`; operaciones `run/test` y escrituras en `actions/file_processor.py:455-510`; extracción a destino en `actions/file_processor.py:713-741`.
- **Impacto:** contenido subido o instrucciones del modelo pueden ejecutar código, escribir resultados o extraer archivos sin confirmación central.
- **Solución recomendada:** clasificar por operación, bloquear ejecución por defecto, validar destino y separar procesamiento consultivo de efectos.
- **Esfuerzo:** medio.
- **Prioridad:** P0.
- **Resolución:** metadata `SENSITIVE` y mínimos por operación: consultas
  libres, transformaciones con confirmación y `run/test` siempre confirmados.

### C-03 - `code_helper write/edit` contradice la confirmación de seguridad

- **Estado:** resuelto en Fase 1.
- **Descripción:** `confirmation_request()` prepara confirmación para escribir/editar, pero policy declara esas operaciones `FREE`, por lo que el gate nunca se invoca.
- **Evidencia:** `core/permissions/policy.py:63-66`; escritura en `actions/code_helper.py:75-81`, `344` y `425-427`; confirmación esperada en `core/security.py:63-68`.
- **Impacto:** modificación de código local iniciada por modelo sin aprobación efectiva.
- **Solución recomendada:** `explain=FREE`; `write/edit=CONFIRM_ONCE` o `ALWAYS`; `run/build/auto=CONFIRM_ALWAYS`; tests de integración policy -> gate.
- **Esfuerzo:** bajo.
- **Prioridad:** P0.
- **Resolución:** `explain=FREE`, `write/edit/optimize=CONFIRM_ONCE` y el resto,
  incluida ejecución, `CONFIRM_ALWAYS`.

## Hallazgos altos

### H-01 - Timeout no cancela handlers síncronos

- **Estado:** mitigado en Fase 6 para handlers cooperativos y el proceso de
  ejecución de `dev_agent`; abierto para handlers legacy y transportes que no
  aceptan señal.
- **Descripción:** `asyncio.wait_for()` deja de esperar, pero el trabajo iniciado con `asyncio.to_thread()` puede continuar.
- **Evidencia:** `core/tools/executor.py:88-102`.
- **Impacto:** una tool puede seguir escribiendo, automatizando o ejecutando después de reportar timeout.
- **Solución recomendada:** token cooperativo, subprocess groups, cleanup y estado `TIMED_OUT_EFFECT_UNKNOWN`.
- **Esfuerzo:** alto.
- **Prioridad:** P0/P1.
- **Resolución parcial:** el executor registra tokens por `request_id`, señala
  timeout/cancelación y espera cleanup acotado. El handler puede declarar efecto
  parcial y rollback mediante `ToolCancelled`; si no reconoce la señal se
  conserva `effect=unknown`. El runner piloto termina y recolecta el árbol de
  procesos de `dev_agent`, sin asumir que llamadas de modelo o instalación ya
  sean cancelables.

### H-02 - `PermissionStore.save()` no es atómico

- **Estado:** resuelto en Fase 3 para atomicidad, recuperación y concurrencia
  intra-proceso.
- **Descripción original:** escribía el JSON final directamente.
- **Evidencia original:** `PermissionStore.save()` usaba `Path.write_text()`
  sobre el destino definitivo.
- **Impacto:** corte o crash puede dejar preferencias parciales; la carga vuelve a defaults y puede alterar el endurecimiento del usuario.
- **Solución recomendada:** temporal en el mismo directorio, flush/fsync, `os.replace`, backup validado y fault injection.
- **Esfuerzo:** bajo-medio.
- **Prioridad:** P0.
- **Resolución:** serialización y validación ocurren antes de publicar; el
  temporal durable vive en el mismo directorio y se reemplaza con `os.replace`.
  Sólo un primario válido actualiza `.bak`; `load()` intenta
  primario → backup → defaults seguros. Sigue fuera de alcance el locking
  interproceso.

### H-03 - Mutaciones Qt pueden ejecutarse desde threads de herramientas

- **Estado:** resuelto en Fase 8 para handlers de `ToolExecutor` y notificaciones
  de runtime; cámara y workspaces conservan señales Qt y locks explícitos.
- **Descripción:** ToolExecutor envía handlers síncronos a un worker; varios handlers registrados llaman directamente a métodos de UI.
- **Evidencia:** `core/tools/executor.py:88-91`; handlers de UI en `main.py:930-943`; registro/ejecución en `main.py:897-948`.
- **Impacto:** carreras, crashes nativos, estados visuales intermitentes y cierres difíciles de reproducir.
- **Solución recomendada:** command bus/señales Qt con respuesta futura; toda mutación de widget en el hilo gráfico.
- **Esfuerzo:** medio-alto.
- **Prioridad:** P1.
- **Resolución:** `UiCommandFacade` limita lo que un handler puede pedir a la
  presentación; `JarvisUI` traduce esas órdenes a señales y sólo expone
  snapshots protegidos para archivo y micrófono. Fase 11 reemplaza el callback
  dashboard→runtime por `DashboardConnected`; la UI mantiene su señal Qt. El
  callback de cámara se publica/consume bajo el lock de la sesión.

### H-04 - Trazabilidad común y verificación obligatoria

- **Estado:** trazabilidad resuelta en Fase 2, contrato de estados resuelto en
  Fase 4 y primer verifier de archivos implementado en Fase 5; la migración del
  resto de familias continúa pendiente.
- **Descripción:** `ToolResult` sólo tiene success/message/data/error; no hay request ID, efecto, evidencia, rollback o latencia.
- **Evidencia:** `core/tools/definitions.py:50-55`; consola en `main.py:1297,1355-1358,1628`; auditoría limitada a conectores en `connectors/audit.py`.
- **Impacto:** no se puede reconstruir una acción ni distinguir ejecución exitosa de efecto aplicado.
- **Solución recomendada:** `RequestContext`, `ToolResult v2`, eventos JSONL sanitizados y verificadores por familia.
- **Esfuerzo:** alto.
- **Prioridad:** P0/P1.
- **Resolución parcial:** `RequestContext` correlaciona policy, confirmación,
  ejecución y respuesta; el sink JSONL sólo admite metadata enumerada y
  `ToolResult` v2 separa ejecución, efecto, verificación, rollback, duración y
  evidencia. `file_controller` ya observa ruta resuelta, tamaño y SHA-256 para
  crear, copiar y mover archivos regulares, rechaza destinos conflictivos y no
  afirma verificación si el efecto no puede observarse. Directorios y las demás
  familias siguen en el adaptador heredado.

### H-05 - Rutas especiales evitan partes del contrato común

- **Estado:** mitigado en Fase 1 para `save_memory`; las demás rutas especiales
  siguen abiertas.
- **Descripción:** `save_memory` retorna antes de validación y policy; siete herramientas se implementan mediante branches específicos.
- **Evidencia:** `main.py:1315-1334`; `core/tools/builtins.py:10-13`; `main.py:1482-1605`.
- **Impacto:** cobertura desigual de permisos, auditoría, timeout, cancelación y resultado.
- **Solución recomendada:** `SpecialToolHandler` con el mismo envelope de policy/context/result; migración de una ruta por vez.
- **Esfuerzo:** alto.
- **Prioridad:** P1.

### H-06 - Browser, recordatorios y conectores tienen mínimos demasiado amplios

- **Estado:** resuelto en Fase 1 para browser, reminder y account connector.
- **Descripción:** `browser_control`, `reminder` y otras tools están en `_FREE_TOOLS`; `account_connector` es siempre `FREE`, incluso para creación en Drive.
- **Evidencia:** `core/permissions/policy.py:20-25,47-50`; declaración de operaciones en `main.py:389-415,228-238,793-813`.
- **Impacto:** clicks, formularios, tareas persistentes o escrituras externas pueden no reflejar el riesgo real de la operación.
- **Solución recomendada:** policy por operación y origen; lectura libre, cambios/submit/create con confirmación y verificación.
- **Esfuerzo:** medio.
- **Prioridad:** P0/P1.
- **Resolución:** navegación/lectura se separan de interacción y escritura;
  recordatorios exigen confirmación; creación/desconexión del conector exige
  confirmación permanente.

### H-07 - Dependencias instalables no reproducen capacidades anunciadas

- **Estado:** mitigado parcialmente en Fase 0; sigue abierto para extras.
- **Descripción:** una instalación limpia del runtime principal y tests ya es
  reproducible, pero faltan extras verificados para PDF, Word, Excel, audio y
  módulos TTS/STT.
- **Evidencia:** `requirements-dev.txt` declara pytest y fue instalado en un
  entorno vacío con Python 3.14.6; imports opcionales en
  `actions/file_processor.py` y `core/stt.py`/`core/tts.py` todavía incluyen
  `python-docx`, `pandas`, `openpyxl`, `PyPDF2`, `pdfplumber`, `pydub`,
  `faster-whisper`, `kokoro`, `miniaudio` y `torch`.
- **Impacto:** una instalación limpia no cumple todo lo prometido en README; fallos aparecen sólo al usar la función.
- **Solución recomendada:** definir core vs extras; tests de import; documentar funciones opcionales; retirar dependencias legacy no conectadas.
- **Esfuerzo:** medio.
- **Prioridad:** P0 reproducibilidad.

### H-08 - Proveedores y modelos están distribuidos

- **Estado:** mitigado en Fase 9 con contratos Live/Text/Vision/Search y
  migración completa de `web_search`; las demás acciones continúan pendientes.
- **Descripción:** numerosas acciones crean clientes Gemini, leen la API key y eligen modelos.
- **Evidencia:** imports/calls en `main.py`, `actions/code_helper.py`, `computer_control.py`, `computer_settings.py`, `desktop.py`, `dev_agent.py`, `file_processor.py`, `flight_finder.py`, `screen_processor.py`, `web_search.py` y `youtube_video.py`.
- **Impacto:** retries, timeouts, modelos, secretos y pruebas son inconsistentes.
- **Solución recomendada:** adapters separados Live/Text/Vision/Search y `ModelPolicy`; migrar una action piloto.
- **Esfuerzo:** alto.
- **Prioridad:** P1/P2.
- **Resolución parcial:** `web_search` recibe `GroundedSearchProvider` y ya no
  importa el SDK, lee secretos ni selecciona modelos. El adaptador Google
  contiene deadline HTTP, búsqueda grounded, fallback de modelo sólo para
  fallos transitorios y errores tipados para timeout, cuota y rechazo
  permanente. DDG permanece como fallback del caso de uso.

### H-09 - Memoria atómica sólo dentro de un proceso

- **Estado:** mitigado en Fase 15 para durabilidad, validación, backup y
  recuperación; locking interproceso y cifrado opcional siguen pendientes.
- **Descripción original:** usaba `RLock`, temporal y `os.replace`, pero no
  lock entre procesos ni `fsync`.
- **Evidencia:** `memory/memory_manager.py:25-36,76-80,102-135`.
- **Impacto:** dos procesos/escritores o un corte pueden perder la última actualización; la privacidad sensible sigue en texto plano.
- **Solución recomendada:** locking interproceso, fsync, recuperación probada y cifrado opcional.
- **Esfuerzo:** medio-alto.
- **Prioridad:** P1.
- **Resolución parcial:** el temporal vive en el mismo directorio, se valida
  antes de publicar, usa `flush`/`fsync` y `os.replace`, y se limpia ante
  fallos. Sólo un primario validado reemplaza el backup; un primario corrupto
  recupera el último backup válido. Las pruebas inyectan fallos de escritura y
  publicación. El riesgo restante es actualización perdida entre procesos y
  almacenamiento sensible sin cifrado.

### H-10 - Ejecución e instalación generada tienen autoridad amplia

- **Estado:** resuelto en Fase 13 para `dev_agent` y rutinas crudas heredadas.
- **Descripción:** `dev_agent` instala dependencias decididas por salida de modelo y ejecuta comandos/proyectos; scripts memorizados ejecutan código.
- **Evidencia:** `actions/dev_agent.py:239-272,295-344,519-549`; `memory/script_memory.py:23-34`.
- **Impacto:** supply-chain, ejecución arbitraria, cambios persistentes y salidas sin límite estricto.
- **Solución recomendada:** workspace aislado, allowlist, entorno virtual por proyecto, preview, confirmación siempre, límites de salida y auditoría.
- **Esfuerzo:** alto.
- **Prioridad:** P1 seguridad.
- **Resolución:** el agente sólo crea previews en un proyecto nuevo contenido
  por rutas canónicas, budgets tipados y rollback de archivos propios. Todo
  `run_command` o dependencia propuesto por el modelo se rechaza antes de
  escribir; se retiraron instalación, ejecución y apertura de IDE del handler.
  `script_memory.run_script()` ya no interpreta código almacenado y la policy
  dejó de conceder `FREE` a una rutina por estar registrada. La ejecución de
  previews seguirá bloqueada hasta disponer de sandbox real y una segunda
  confirmación explícita.

## Hallazgos medios

### M-01 - Dispatch heredado inalcanzable

- **Descripción:** después de `if name not in SPECIAL_TOOLS`, aparecen `elif` para tools que no son especiales.
- **Evidencia:** `main.py:1419-1480` y `1546-1594`.
- **Impacto:** duplicación, falsa impresión de cobertura y riesgo de divergencia.
- **Solución recomendada:** tests de equivalencia y eliminación acotada del branch muerto.
- **Esfuerzo:** bajo.
- **Prioridad:** P1.

### M-02 - Validación de argumentos es un subconjunto de JSON Schema

- **Descripción:** sólo valida required y tipos básicos; no controla enum, rangos, items, adicionales ni formatos.
- **Evidencia:** `core/tools/registry.py:57-83`.
- **Impacto:** valores peligrosos o inválidos llegan a handlers.
- **Solución recomendada:** validador compatible o validadores por tool sin dependencia pesada.
- **Esfuerzo:** medio.
- **Prioridad:** P1.

### M-03 - Excepciones amplias y errores silenciosos

- **Descripción:** 360 handlers amplios, 67 con `pass`.
- **Evidencia:** máximos en `file_processor.py`, `ui.py`, `game_updater.py`, `browser_control.py`, `dashboard/server.py` y `main.py`.
- **Impacto:** diagnósticos incompletos y estados falsamente normales.
- **Solución recomendada:** migración gradual a excepciones específicas y logging con traceback/código estable.
- **Esfuerzo:** alto y gradual.
- **Prioridad:** P1/P2.

### M-04 - Logging fragmentado

- **Estado:** mitigado parcialmente en Fase 10 con un owner estructurado y
  rotativo para runtime; la migración de `print()` heredados sigue pendiente.
- **Descripción:** 303 `print()`; CrashReporter sólo cubre excepciones no manejadas y auditoría de conectores no cubre tools.
- **Evidencia:** recuento AST y `core/diagnostics.py`.
- **Impacto:** sin niveles, sesión, request ID ni latencia uniforme.
- **Solución recomendada:** `logging` estructurado y rotativo, preservando consola de diagnóstico wake.
- **Esfuerzo:** medio.
- **Prioridad:** P1.
- **Resolución parcial:** `StructuredRuntimeLog` emite JSON allowlisted a
  consola y `RotatingFileHandler`, soporta correlación con `RequestContext` y
  falla sin impedir el arranque. `main.py` registra los límites de inicio,
  error fatal y cierre. El sanitizador común ahora cubre formas de credenciales
  Google, GitHub, OpenAI, AWS y Slack, además de claves privadas. La auditoría
  estructurada de tools continúa en `RequestAuditSink`.

### M-05 - Configuración duplicada y fallos ocultos

- **Estado:** resuelto en Fase 10 para la lectura y escritura del documento de
  configuración local.
- **Descripción:** `api_keys.json` se lee desde múltiples módulos; `config.get_config()` captura cualquier excepción y devuelve `{}`.
- **Evidencia:** `config/__init__.py:5-18` y múltiples `_get_api_key()` en acciones.
- **Impacto:** modelos/rutas inconsistentes y errores tardíos poco claros.
- **Solución recomendada:** settings inmutables validados al bootstrap e inyección.
- **Esfuerzo:** medio-alto.
- **Prioridad:** P1/P2.
- **Resolución:** `AppSettings` valida JSON y tipos, normaliza OS, mantiene
  extras compatibles y falla con `SettingsError` estable. El snapshot se cachea
  por ruta y todas las fronteras productivas lo consumen sin abrir el archivo
  directamente. `update_settings()` valida el documento completo antes de
  publicarlo atómicamente con temporal, `fsync` y `os.replace`, y actualiza el
  cache bajo el mismo lock. La clave queda excluida de `repr`; una prueba
  estática bloquea nuevos lectores paralelos.

### M-06 - `ui.py` y `main.py` siguen concentrando responsabilidades

- **Estado:** mitigado parcialmente en Fase 7 para estado de sesión, audio,
  visión y shutdown, y en Fase 8 para la frontera de comandos UI; transporte,
  IO y casos de uso siguen en `main.py`.
- **Descripción:** 4.535 y 2.331 líneas respectivamente, con estado, IO y lifecycle mezclados.
- **Evidencia:** recuento directo y outlines de clases/métodos.
- **Impacto:** cambios de UI/audio tienen amplio radio de regresión.
- **Solución recomendada:** extraer servicios/presenters por ownership, no por traslado mecánico.
- **Esfuerzo:** muy alto.
- **Prioridad:** P2 tras P0/P1.
- **Resolución parcial:** `RuntimeServices` compone cuatro owners con
  transiciones explícitas, locks donde cruzan threads, snapshots inmutables y
  métricas. Se eliminaron flags duplicados de `JarvisLive` sin cambiar el
  protocolo Gemini ni mover UI/hardware. Colas, streams y providers continúan
  pendientes. `UiCommandFacade` reduce el acceso de handlers al contrato de
  presentación sin intentar dividir mecánicamente `ui.py`. Fase 11 añade un
  `EventBus` tipado para hechos de sesión, interrupción, visión, shutdown y
  dashboard; los observers corren fuera del lock del owner y sus fallos quedan
  aislados. No reemplaza colas, comandos ni lifecycle de workers.

### M-07 - Colas y tareas sin política única

- **Estado:** mitigado parcialmente en Fase 12.
- **Descripción:** `audio_in_queue` no tiene máximo; tareas dashboard se crean fuera de un lifecycle común.
- **Evidencia:** `main.py:2184-2214`, `1043-1053`.
- **Impacto:** memoria creciente o tareas huérfanas bajo fallos prolongados.
- **Solución recomendada:** ownership, límites, métricas de profundidad y cierre explícito.
- **Esfuerzo:** medio.
- **Prioridad:** P1 con lifecycle.
- **Resolución parcial:** `WorkerSupervisor` aporta start/cancel/close
  idempotentes, health activo, backoff y restart limitado. Browser y visión son
  pilotos: cierran loop/thread y fallan cerrado si cleanup no demuestra que el
  worker anterior terminó. Colas Live, dashboard, monitor, proactividad y
  workers restantes conservan lifecycle heredado.

### M-08 - Promesas multiplataforma superan la verificación

- **Estado:** mitigado parcialmente en Fase 10 con CI reproducible sobre
  Windows/Python 3.12; macOS/Linux y hardware continúan sin verificar.
- **Descripción:** el proyecto anuncia Windows principal con soporte parcial macOS/Linux, pero no hay matriz CI/hardware para esas plataformas.
- **Evidencia:** handlers con ramas por OS y dependencias condicionadas; suite ejecutada sólo en Windows.
- **Impacto:** regresiones silenciosas fuera de Windows.
- **Solución recomendada:** declarar capacidades por plataforma en la matriz y smoke CI donde sea realista.
- **Esfuerzo:** medio.
- **Prioridad:** P2.
- **Resolución parcial:** `.github/workflows/quality.yml` instala manifests
  versionados y ejecuta el baseline completo con timeout y permisos de sólo
  lectura. Ruff/mypy se restringen a módulos migrados para no convertir deuda
  histórica en falsos bloqueos.

### M-09 - Comparación no canónica de rutas en el conector Obsidian

- **Estado:** resuelto tras Fase 11.
- **Descripción:** el destino de una nota se resolvía, pero podía compararse
  contra una representación no normalizada de la raíz del vault.
- **Impacto:** Windows CI rechazaba notas válidas; una comparación futura por
  prefijo también habría sido vulnerable a vaults con nombres engañosos.
- **Resolución:** resolver primero la raíz, aceptar sólo entradas relativas,
  resolver el destino y usar `Path.relative_to()` para probar descendencia real.
  La misma validación protege backups y bloquea traversal, rutas absolutas,
  carpetas internas y symlinks que escapan.
- **Pruebas:** lectura con/sin `.md`, escritura con backup, raíz no normalizada,
  `..`, ruta absoluta, prefijo engañoso y symlink cuando Windows lo permite.

### M-10 - QML no demuestra una ventaja neta para la UI actual

- **Estado:** decisión cerrada en Fase 14; conservar PyQt Widgets.
- **Descripción:** el PDF permite considerar QML sólo mediante un prototipo
  aislado y una ventaja medible, no como reescritura asumida.
- **Evidencia:** cinco procesos por variante, 45 frames por proceso,
  Windows/Python 3.14.6/Qt 6.11 offscreen con backend software. QML mejoró
  pacing p95 16,3%, pero empeoró startup frío 239,6% y RSS incremental 58,8%.
- **Impacto:** migrar ahora agregaría costo y riesgo de paridad sin evidencia
  de mejora global.
- **Resolución:** mantener `ui.py`/`ui_mk2` en Widgets. Reabrir sólo con pantalla
  real, GPU visible, paridad funcional/visual/accesible y packaging congelado
  que cumpla el umbral de 15% sin regresiones mayores al 10%.
- **Rollback:** el benchmark es independiente; retirarlo no cambia runtime.

## Hallazgos bajos

### L-00A - Límites del snapshot no estaban sincronizados con el cierre

- **Estado:** resuelto en Fase 17 como cierre con riesgos abiertos.
- **Descripción:** las fuentes y límites de la sección 17 eran texto estático;
  podían quedar obsoletos o coexistir con una afirmación falsa de aceptación
  completa.
- **Impacto:** pérdida de trazabilidad del alcance y confusión entre baseline
  mockeado, hardware real y arquitectura totalmente verificada.
- **Resolución:** manifiesto exacto de 8 fuentes/5 límites, paths contenidos y
  cruce automático con la matriz global. Con 13 criterios abiertos,
  `verified_complete` falla.
- **Límite:** existencia de un archivo no demuestra revisión semántica
  exhaustiva; los pendientes permanecen en aceptación global.
- **Rollback:** retirar gate/manifiesto no cambia runtime.

### L-00 - Instrucciones operativas sin gate estructurado

- **Estado:** resuelto en Fase 16 desde la fase de enforcement 15.
- **Descripción:** la sección 16 y `AGENTS.md` exigían motivo, archivos,
  riesgos, pruebas, métricas, rollback y preguntas arquitectónicas, pero su
  cumplimiento dependía sólo de texto libre.
- **Impacto:** una fase podía declararse completa omitiendo evidencia o
  confundiendo mocks con comportamiento real.
- **Resolución:** contrato de 19 controles y un registro secuencial por fase;
  validación de evidencia contenida, rutas sensibles, resultados, Obsidian,
  destructividad y beneficio de abstracciones.
- **Límite:** CI no puede demostrar acciones humanas ni leer de forma portable
  la nota Obsidian externa. Esos puntos siguen documentados para revisión de
  handoff y no se marcan como automatizados.
- **Rollback:** retirar el gate del baseline y revertir sus artefactos no cambia
  runtime.

### L-01 - Dependencia declarada sin uso de runtime observado

- **Descripción:** `beautifulsoup4` sólo figura en el instalador y requirements; no hay import/uso en código funcional.
- **Evidencia:** `requirements.txt`; `core/installer.py:24`.
- **Impacto:** instalación innecesaria y superficie mayor.
- **Solución recomendada:** confirmar intención y retirar o usar.
- **Esfuerzo:** bajo.
- **Prioridad:** P3.

### L-02 - Ruta de la nota Obsidian en `AGENTS.md` quedó obsoleta

- **Descripción:** el archivo indicado sin sufijo no existe; la nota real encontrada se llama `Jarvis Futuras implementaciones - General.md`.
- **Evidencia:** búsqueda por nombre en OneDrive.
- **Impacto:** agentes futuros no pueden cumplir el registro obligatorio.
- **Solución recomendada:** actualizar la ruta manteniendo el mismo vault.
- **Esfuerzo:** bajo.
- **Prioridad:** P0 documental.

### L-03 - No se confirmó un ciclo de imports estático

- **Descripción:** no apareció un ciclo directo en los núcleos inspeccionados ni en smoke imports, pero los imports locales y diferidos complican un dictamen exhaustivo.
- **Evidencia:** imports correctos del runtime base y carga diferida en `main._load_action_dependencies()`.
- **Impacto:** bajo inmediato; riesgo al extraer servicios.
- **Solución recomendada:** añadir análisis de grafo de imports en Fase 0.
- **Esfuerzo:** bajo.
- **Prioridad:** P2.

## Principales diez riesgos

1. Fuente remota tratada como local.
2. `file_processor` libre con escritura/ejecución.
3. `code_helper write/edit` libre.
4. Timeout que no cancela el efecto.
5. Tool calls sin request ID, evidencia ni verificación.
6. UI Qt tocada desde workers.
7. PermissionStore no atómico.
8. Tools especiales fuera del contrato común.
9. Instalación limpia incompleta para capacidades anunciadas.
10. Autoridad amplia de agentes/scripts y proveedores distribuidos.

## Quick wins

- Tests de origen remoto y clasificación de riesgo.
- Corregir `file_processor`/`code_helper`.
- Atomicidad de PermissionStore.
- Matriz de 37 tools generada desde código.
- Dependencias core/opcionales separadas.
- Eliminar dispatch muerto tras pruebas.
- Sink estructurado sanitizado con request ID.

## Recomendación

No iniciar todavía la extracción de audio, sesión o UI. El siguiente cambio debe ser pequeño, reversible y centrado en tests de origen/riesgo y la matriz de herramientas; después, `RequestContext` y PermissionStore atómico.

## Cambio verificado - 2026-07-30 - Google Workspace nativo

### Alcance

- `GoogleDriveConnector` continúa siendo el owner único de OAuth, Drive y
  archivos Workspace.
- `connectors/google_workspace.py` encapsula las APIs nativas de Docs, Sheets
  y Slides con el mismo token, builder inyectado, límites y errores
  específicos.
- `account_connector` incorporó lectura nativa; creación y append de Docs;
  creación, escritura y append de Sheets; y creación/append de Slides.
- `main.py` sigue siendo el composition root y registra la misma herramienta;
  no cambiaron audio, visión, UI, dashboard ni Gemini Live.

### Seguridad y evidencia

- Leer, buscar y descargar continúa libre tras OAuth.
- Toda creación o edición remota requiere al menos `confirm_once`;
  `disconnect` requiere `confirm_always`.
- Las lecturas tienen límites de texto/celdas y las escrituras validan
  contenido, matriz y tamaño.
- Docs se verifica por contenido final; Sheets por rango/celdas y lectura
  posterior; Slides por ID de página y texto observado.
- La auditoría registra sólo proveedor, operación y conteo. No registra
  cuerpos, valores, consultas, IDs ni tokens.

### Discrepancias y riesgos

- **Discrepancia resuelta parcialmente con H-06:** las escrituras de
  `account_connector` ya no son `FREE`. La clasificación de browser,
  recordatorios y otros conectores sigue pendiente.
- Las APIs de Google Workspace fueron habilitadas manualmente en el proyecto
  Google Cloud. Se probó la cuenta real mediante el token protegido existente,
  sin leer ni mostrar configuración OAuth, identidad, archivos previos o
  contenido ajeno al smoke test.
- Crear un archivo y poblar su contenido son dos efectos remotos: si falla el
  segundo, el error informa que el archivo vacío ya fue creado y no intenta
  borrarlo silenciosamente.
- La verificación es local al conector; `ToolResult v2` y `request_id` siguen
  pendientes según las Fases 2 y 4.

### Verificación y rollback

- Suite completa: `226 passed, 1 skipped, 41 subtests passed`; una advertencia
  externa de deprecación futura en `google.genai`.
- `pip check`, `compileall`, `jarvis_launcher.py --help` y `git diff --check`:
  correctos con el Python del entorno virtual.
- Smoke real de Google Workspace: Docs, Sheets y Slides completaron
  `create -> write -> readback`; los tres artefactos temporales se movieron a
  la papelera y `trashed=true` se verificó nuevamente mediante Drive API.
- No se ejecutaron navegador visual, Gemini, micrófono, cámara ni dashboard.
- Rollback: retirar las acciones nativas y `GoogleWorkspaceService`, restaurar
  la matriz de capabilities/policy y conservar el conector Drive previo. No
  requiere migración de datos locales ni tokens.

## Cambio verificado - 2026-07-30 - Wake rápido y superficie base fullscreen

### Causa y alcance

- El arranque por wake ejecutaba `main.py --pet`, mientras el inicio directo
  ya abría `JarvisUI` fullscreen. Se eliminó esa divergencia: ambas rutas
  inician la superficie base y Pet Mode sigue disponible sólo por transición
  explícita.
- Con OpenWakeWord disponible, `wake_word.main()` cargaba Vosk de forma
  síncrona antes de abrir el stream. La medición local fue ~439 ms para
  OpenWakeWord y ~1.498 ms adicionales para Vosk.
- El fallback híbrido esperaba un resultado final `hey`, pero la gramática no
  incluía `hey` como entrada independiente. Además, un final vacío podía
  desarmar la ventana antes de recibir el segundo término.
- `AsyncVoskFallback` carga el modelo pesado en un thread daemon; OpenWakeWord
  escucha inmediatamente y el recognizer Vosk se conecta cuando está listo.
  La gramática incluye `hey` y los finales vacíos ya no alteran la secuencia.

### Ownership, compatibilidad y recuperación

- `wake_word.py` conserva ownership de detector, stream, fallback y proceso
  lanzado. `JarvisUI` conserva ownership de fullscreen y App/Pet.
- No cambiaron Gemini Live, audio de conversación, cámara, dashboard, policy
  ni las señales Qt de Pet Mode.
- Un stream sin callbacks se considera trabado a los 2 s y reintenta después
  de 1 s; antes eran 5 s y 3 s. El reset conserva limpieza de cola y estado
  neural antes de reabrir.
- Rollback: volver a carga Vosk síncrona, timeout 5/3 y argumento `--pet`; no
  hay migración de configuración ni datos.

### Evidencia y límites

- Tests dirigidos de launcher/wake/UI: `72 passed`.
- Suite completa: `229 passed, 1 skipped, 41 subtests passed`.
- `pip check`, `compileall`, launcher `--help` y `git diff --check`: correctos.
- Medición repetida: OpenWakeWord listo en ~160 ms; Vosk listo en background
  a ~1.190 ms. Son tiempos locales de carga, no Wake -> UI.
- Se reiniciaron únicamente supervisor y detector; ambos quedaron activos,
  OpenWakeWord informó estado de escucha y no aparecieron errores nuevos.
- No se grabó audio ni se verificó acústicamente la frase. La detección hablada,
  Wake -> UI visible y el foco fullscreen real requieren prueba manual.

## Corrección verificada - 2026-07-31 - Primer frame, restauración y saludo

### Evidencia posterior y causa

- La prueba manual del 31 de julio confirmó tres brechas del cambio anterior:
  apertura lenta, ventana sólo presente en la barra de tareas y saludo emitido
  recién después de pasar a Pet Mode.
- `main.py` importaba `google.genai` antes de construir la UI. El perfil local
  atribuyó ~1.871 ms acumulados al SDK y midió ~2.241 ms para importar `main`.
- Los dos intentos de foco usaban `SW_SHOW`, que no restaura un HWND minimizado.
- `_briefing_sent` se marcaba al programar el saludo, no después de reproducirlo.
  Una falla o desconexión inicial impedía reintentarlo; además, el vaciado de
  audio podía liberar la espera sin distinguir audio descartado de reproducido.

### Implementación y ownership

- Gemini se importa de forma diferida y thread-safe dentro del owner
  `JarvisLive`; Qt construye, muestra y pinta la superficie base antes de
  iniciar el thread `jarvis-core`.
- `JarvisUI` mantiene ownership del estado visual. En Windows restaura con
  `SW_RESTORE`, elimina `WindowMinimized`, aplica `WindowFullScreen` y reintenta
  foco de manera acotada. Los callbacks tardíos no revierten una transición
  explícita a Pet Mode.
- El saludo conserva estados separados `inflight`, `played` y `sent`.
  Sólo queda completado tras drenar su audio; una desconexión libera la tarea
  sin declarar éxito y permite reintentar en la siguiente sesión.
- No cambiaron las señales App/Pet, policy, herramientas, cámara, dashboard ni
  los adaptadores de cuentas.

### Evidencia, riesgos y rollback

- Prueba Qt offscreen desde estado minimizado: ventana visible, fullscreen,
  no minimizada y superficie `main`.
- En el mismo entorno, el import de `main` bajó de ~2.241 ms a ~509 ms
  (aprox. 77%); la construcción UI medida fue ~492 ms. Esto mide carga local,
  no Wake -> UI sobre hardware.
- Tests dirigidos: `124 passed, 20 subtests passed`. Suite completa:
  `231 passed, 1 skipped, 41 subtests passed`; `pip check`, `compileall` y
  `git diff --check` correctos.
- Se reiniciaron únicamente el supervisor y el detector wake residentes; ambos
  quedaron activos y habilitados con el código actualizado.
- Riesgo pendiente: repetir “Hey Jarvis” en el equipo real y comprobar foco,
  fullscreen, saludo audible y latencia extremo a extremo. No se iniciaron
  la app principal, Gemini, cámara, dashboard ni cuentas; la suite automatizada
  mantuvo micrófono y demás hardware mockeados.
- Rollback: restaurar imports eager, arranque inmediato del runner, `SW_SHOW`
  y el booleano previo del briefing. No hay migración de datos/configuración.

## Preparación verificada - 2026-07-31 - Publicación no comercial

### Alcance y procedencia

- No se cambió la visibilidad del repositorio, no se hizo commit/push y no se
  modificó lógica productiva.
- La procedencia ahora enlaza el commit público `d178f6b` de Mark XLVIII,
  creado por FatihMakes y publicado bajo CC BY-NC 4.0.
- `NOTICE.md` separa explícitamente material original, modificaciones de Mark LI
  y componentes de terceros. `LICENSE.md` limita el copyright reclamado a las
  contribuciones propias y describe el repositorio como código fuente público
  para uso personal y no comercial.
- Se agregó un aviso de no afiliación con Marvel Entertainment, Marvel Studios
  y The Walt Disney Company; no se reclaman sus marcas o personajes.

### Higiene y prevención de regresiones

- `config/google_oauth_client.example.json` usa únicamente placeholders
  inequívocos. El archivo OAuth real permaneció ignorado; su contenido no se
  mostró ni se modificó.
- `/output/` quedó en `.gitignore` para impedir que PDFs y otros artefactos
  generados entren por accidente en una publicación.
- `SECURITY.md` incluye una checklist previa a visibilidad pública.
- `tests/test_public_release.py` verifica placeholders, ignore, atribución,
  disclaimer y licencias de los modelos wake.

### Verificación, riesgo pendiente y rollback

- Pruebas dirigidas: `5 passed, 7 subtests passed`.
- Suite completa: `236 passed, 1 skipped, 48 subtests passed`.
- `pip check`, `compileall`, escaneo de secretos y `git diff --check`:
  correctos.
- PyQt6 no fue migrado ni relicenciado. Su compatibilidad GPLv3/comercial con
  el esquema no comercial permanece como decisión pendiente antes de declarar
  el repositorio listo jurídicamente.
- El historial conserva una antigua cadena ficticia de aspecto aleatorio en la
  plantilla OAuth; no coincide con la credencial local actual. No se reescribió
  historial ni se forzó ninguna rama para evitar una operación destructiva.
- Rollback: retirar `NOTICE.md` y el test, restaurar los textos previos, la
  plantilla de ejemplo y la entrada `/output/`. No hay migración de runtime,
  credenciales ni datos.

### Integración sobre el main moderno

- Los cambios se guardaron primero en dos commits recuperables y después se
  portaron a una rama nacida del `main` moderno, que estaba 55 commits por
  delante. No se sobrescribieron ni eliminaron las fases arquitectónicas.
- Los conflictos se resolvieron conservando inyección de proveedores, eventos,
  trazabilidad y mínimos de policy del main moderno. `read_workspace_file`
  queda libre; `connect`/`download` requieren confirmación única y toda
  escritura remota o desconexión requiere confirmación siempre.
- La carga diferida del SDK mantiene `_function_response` autosuficiente para
  adaptadores y tests que construyen `JarvisLive` sin ejecutar `__init__`.
- Verificación sobre el árbol integrado: `434 passed, 3 skipped,
  131 subtests passed`; dependencias, compilación y escaneo de secretos
  correctos.
- El puntero local de `main` se avanzó mediante fast-forward al árbol
  verificado. No hubo push ni cambio de visibilidad; PyQt6 permanece sin
  cambios.
