# Auditoría técnica de JARVIS Mark LI

## Alcance y método

Auditoría realizada el 2026-07-28 sobre el working tree local y contrastada con el PDF de arquitectura v1.1. Se revisaron:

- estructura versionada completa;
- entrypoints, runtime, audio, UI, wake word, herramientas, permisos, memoria, conectores, dashboard y acciones;
- imports y dependencias;
- patrones de excepciones, subprocess, red, configuración y secretos;
- suite, sintaxis, imports y arranque no interactivo.

No se leyeron contenidos de claves, OAuth, certificados, memoria personal o logs. No se ejecutaron acciones reales del sistema, red externa, cuentas, Gemini Live, micrófono, cámara o dashboard LAN.

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
  snapshots protegidos para archivo y micrófono. La conexión del teléfono ya no
  toca el overlay desde el callback del dashboard y el callback de cámara se
  publica/consume bajo el lock de la sesión.

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

- **Descripción:** numerosas acciones crean clientes Gemini, leen la API key y eligen modelos.
- **Evidencia:** imports/calls en `main.py`, `actions/code_helper.py`, `computer_control.py`, `computer_settings.py`, `desktop.py`, `dev_agent.py`, `file_processor.py`, `flight_finder.py`, `screen_processor.py`, `web_search.py` y `youtube_video.py`.
- **Impacto:** retries, timeouts, modelos, secretos y pruebas son inconsistentes.
- **Solución recomendada:** adapters separados Live/Text/Vision/Search y `ModelPolicy`; migrar una action piloto.
- **Esfuerzo:** alto.
- **Prioridad:** P1/P2.

### H-09 - Memoria atómica sólo dentro de un proceso

- **Descripción:** usa `RLock`, temporal y `os.replace`, pero no lock entre procesos ni fsync.
- **Evidencia:** `memory/memory_manager.py:25-36,76-80,102-135`.
- **Impacto:** dos procesos/escritores o un corte pueden perder la última actualización; la privacidad sensible sigue en texto plano.
- **Solución recomendada:** locking interproceso, fsync, recuperación probada y cifrado opcional.
- **Esfuerzo:** medio-alto.
- **Prioridad:** P1.

### H-10 - Ejecución e instalación generada tienen autoridad amplia

- **Descripción:** `dev_agent` instala dependencias decididas por salida de modelo y ejecuta comandos/proyectos; scripts memorizados ejecutan código.
- **Evidencia:** `actions/dev_agent.py:239-272,295-344,519-549`; `memory/script_memory.py:23-34`.
- **Impacto:** supply-chain, ejecución arbitraria, cambios persistentes y salidas sin límite estricto.
- **Solución recomendada:** workspace aislado, allowlist, entorno virtual por proyecto, preview, confirmación siempre, límites de salida y auditoría.
- **Esfuerzo:** alto.
- **Prioridad:** P1 seguridad.

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

- **Descripción:** 303 `print()`; CrashReporter sólo cubre excepciones no manejadas y auditoría de conectores no cubre tools.
- **Evidencia:** recuento AST y `core/diagnostics.py`.
- **Impacto:** sin niveles, sesión, request ID ni latencia uniforme.
- **Solución recomendada:** `logging` estructurado y rotativo, preservando consola de diagnóstico wake.
- **Esfuerzo:** medio.
- **Prioridad:** P1.

### M-05 - Configuración duplicada y fallos ocultos

- **Descripción:** `api_keys.json` se lee desde múltiples módulos; `config.get_config()` captura cualquier excepción y devuelve `{}`.
- **Evidencia:** `config/__init__.py:5-18` y múltiples `_get_api_key()` en acciones.
- **Impacto:** modelos/rutas inconsistentes y errores tardíos poco claros.
- **Solución recomendada:** settings inmutables validados al bootstrap e inyección.
- **Esfuerzo:** medio-alto.
- **Prioridad:** P1/P2.

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
  presentación sin intentar dividir mecánicamente `ui.py`.

### M-07 - Colas y tareas sin política única

- **Descripción:** `audio_in_queue` no tiene máximo; tareas dashboard se crean fuera de un lifecycle común.
- **Evidencia:** `main.py:2184-2214`, `1043-1053`.
- **Impacto:** memoria creciente o tareas huérfanas bajo fallos prolongados.
- **Solución recomendada:** ownership, límites, métricas de profundidad y cierre explícito.
- **Esfuerzo:** medio.
- **Prioridad:** P1 con lifecycle.

### M-08 - Promesas multiplataforma superan la verificación

- **Descripción:** el proyecto anuncia Windows principal con soporte parcial macOS/Linux, pero no hay matriz CI/hardware para esas plataformas.
- **Evidencia:** handlers con ramas por OS y dependencias condicionadas; suite ejecutada sólo en Windows.
- **Impacto:** regresiones silenciosas fuera de Windows.
- **Solución recomendada:** declarar capacidades por plataforma en la matriz y smoke CI donde sea realista.
- **Esfuerzo:** medio.
- **Prioridad:** P2.

## Hallazgos bajos

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
