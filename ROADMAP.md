# Roadmap incremental de JARVIS Mark LI

## Principios de ejecución

- No reescribir desde cero.
- Un cambio acotado por fase y una frontera técnica a la vez.
- Preservar wake word, interrupción de audio, UI, memoria, visión, recordatorios y herramientas funcionales.
- No retirar legado hasta demostrar equivalencia y rollback.
- No iniciar una migración masiva de herramientas hasta completar una matriz real de las 37 `ToolDefinition`.
- Antes de cada fase: `git status`, baseline, archivos sensibles fuera del diff y tests relevantes.
- No hacer commit o push sin solicitud explícita.

## Prioridad inmediata

El orden del PDF se ajusta a la evidencia del repositorio: antes de introducir trazabilidad general hay que cerrar dos huecos de seguridad observados en el dispatch actual —origen remoto y clasificación de herramientas— mediante tests que fallen primero. Después se puede implementar `RequestContext` y persistencia atómica sin alterar el comportamiento visual ni el protocolo Gemini.

## Fases

### Fase 0 - Línea base reproducible e inventario

- **Estado:** completada e integrada en `main` el 2026-07-28 desde
  `codex/01-baseline-inventory`.
- **Objetivo:** documentar una instalación limpia, distinguir dependencias principales/opcionales/legacy, medir baseline y completar la matriz de 37 herramientas y rutas especiales.
- **Archivos previstos:** `requirements.txt`, `readme.md`, posible `requirements-optional.txt` o extras, `docs/baseline.md`, `docs/tool_migration_matrix.md`, tests de imports.
- **Riesgo:** bajo; una corrección de dependencias puede ser pesada en Python 3.14.
- **Dependencias:** hardware y una instalación limpia separada; no usar credenciales reales.
- **Criterio de aceptación:** entorno nuevo instala; launcher `--help`, imports y UI offscreen funcionan; cada herramienta tiene retorno, risk, policy, preview, verify, rollback, timeout, ruta y tests registrados.
- **Pruebas:** `pip check`, smoke imports, `compileall`, suite completa, prueba de instalación en entorno vacío.
- **Rollback:** revertir sólo documentación/manifest; no tocar runtime.
- **Evidencia:** instalación nueva en Python 3.14.6; `requirements-dev.txt`;
  `scripts/validate_baseline.ps1`; matriz sincronizada por test; `pip check`,
  launcher, imports, UI offscreen, `compileall`, 213 tests y 65 subtests
  aprobados. Las dependencias opcionales continúan explícitamente pendientes.

### Fase 1 - Cerrar origen y clasificación de riesgo

- **Estado:** completada e integrada en `main` el 2026-07-28 desde
  `codex/02-origin-risk`.
- **Objetivo:** impedir que entradas remotas se evalúen como locales y corregir herramientas subclasificadas (`file_processor`, `code_helper`, browser, reminder y escrituras de conectores).
- **Archivos previstos:** `main.py`, `dashboard/server.py`, `core/permissions/models.py`, `core/permissions/policy.py`, `core/tools/builtins.py`, tests de policy/seguridad.
- **Riesgo:** alto; puede añadir confirmaciones a flujos hoy libres.
- **Dependencias:** matriz de herramientas y definición explícita de origen.
- **Criterio de aceptación:** todo comando conserva `local`, `dashboard_text`, `dashboard_audio`, `ui` o `wake`; ninguna acción de escritura/ejecución queda con `READ_ONLY/FREE` por omisión.
- **Pruebas:** integración dashboard -> function call -> policy; tabla parametrizada de mínimos por operación; pruebas negativas sin efectos reales.
- **Rollback:** revertir el mapping de riesgo/origen; conservar los tests como especificación de decisión.
- **Evidencia:** `InputSource` distingue `local`, `ui`, `wake`,
  `dashboard_text` y `dashboard_audio`; los turnos remotos conservan su origen
  hasta policy y confirmación; `save_memory` ya no evita policy; matriz de
  mínimos parametrizada para processor, code, browser, reminder, conectores y
  creación/copia de archivos. Baseline limpio: 226 tests y 102 subtests
  aprobados, inventario de 37 tools, `compileall`, imports, launcher y
  `pip check`; el mismo baseline fue repetido con éxito sobre el merge
  `900c7c7`.

### Fase 2 - `RequestContext` y trazabilidad estructurada

- **Estado:** completada e integrada en `main` el 2026-07-28 desde
  `codex/03-request-context`.
- **Objetivo:** correlación extremo a extremo sin cambiar Gemini Live, audio ni UI visual.
- **Archivos previstos:** nuevo `core/request_context.py`, `core/tools/definitions.py`, `core/tools/executor.py`, `core/permissions/*`, `main.py`, nuevo sink de auditoría sanitizado, `docs/request_lifecycle.md`.
- **Riesgo:** medio-alto; toca el camino central de herramientas.
- **Dependencias:** Fase 1 y contrato de eventos.
- **Criterio de aceptación:** `request_id` único en requested, policy, confirmation, started, completed y response; logs sin tokens, cuerpos, memoria ni argumentos sensibles.
- **Pruebas:** unicidad, propagación, sanitización, fallos del sink, correlación en ruta normal/especial.
- **Rollback:** adapters con context opcional; feature flag para sink.
- **Evidencia:** `RequestContext` único llega a policy, confirmación, executor,
  `ToolResult` y `FunctionResponse`; rutas normal y especial emiten
  `requested`, `policy`, `confirmation`, `started`, `completed` y `response`.
  El sink JSONL usa allowlist, no recibe argumentos, tolera fallos y puede
  desactivarse. Baseline: 236 tests y 102 subtests aprobados antes y después
  del merge `19a2adc`.

### Fase 3 - Persistencia atómica de permisos

- **Estado:** completada e integrada en `main` el 2026-07-28 desde
  `codex/04-atomic-permission-store`.
- **Objetivo:** evitar JSON parcial y fallar cerrado.
- **Archivos previstos:** `core/permissions/store.py`, tests de permisos y fault injection.
- **Riesgo:** medio; afecta preferencias de seguridad.
- **Dependencias:** ninguna de runtime Live.
- **Criterio de aceptación:** temporal en mismo volumen, flush/fsync cuando corresponda, `os.replace`, backup/recuperación y validación antes de publicar.
- **Pruebas:** corte simulado, JSON corrupto, error de escritura, versión desconocida, concurrencia básica.
- **Rollback:** lector compatible con versión anterior y copia del archivo previo.
- **Evidencia:** temporal en el mismo directorio, `flush`/`fsync`, relectura y
  validación antes de `os.replace`; backup sólo de un primario válido y
  recuperación primaria/backup/defaults. Lock compartido por ruta para
  concurrencia entre instancias del proceso. Baseline: 247 tests y 102 subtests
  aprobados antes y después del merge `f4fe895`.

### Fase 4 - `ToolResult` v2 compatible

- **Estado:** completada e integrada en `main` el 2026-07-28 desde
  `codex/05-tool-result-v2`.
- **Objetivo:** separar ejecución, efecto y verificación.
- **Archivos previstos:** `core/tools/definitions.py`, `executor.py`, adapters de normalización, tests; sin migrar las 37 tools.
- **Riesgo:** alto; contrato transversal.
- **Dependencias:** `RequestContext`.
- **Criterio de aceptación:** legacy adapters conservan comportamiento; estados de ejecución/efecto/verificación y latencia no se infieren de texto.
- **Pruebas:** matriz semántica, serialización, timeouts, errores, compatibilidad con retornos legacy.
- **Rollback:** mantener el constructor/adapter v1 hasta finalizar la migración.
- **Evidencia:** enums independientes para ejecución, efecto, verificación y
  rollback; duración y evidencia serializables; adaptadores de texto, bool,
  mapping, `None` y v2. Timeout declara efecto desconocido, rechazo previo
  declara no aplicado y las 37 tools conservan campos legacy. Baseline: 257
  tests y 102 subtests aprobados antes y después del merge `d150a2a`.

### Fase 5 - Piloto de verificación

- **Estado:** completada e integrada en `main` el 2026-07-28 desde
  `codex/06-file-verification-pilot`.
- **Objetivo:** implementar verifier para dos o tres operaciones seguras de `file_controller`.
- **Archivos previstos:** `actions/file_controller.py`, nuevo módulo de verificadores, `core/tools/*`, tests.
- **Riesgo:** medio.
- **Dependencias:** ToolResult v2 y matriz.
- **Criterio de aceptación:** crear/copiar/mover reportan ruta resuelta y evidencia; un efecto no observado no se comunica como verificado.
- **Pruebas:** `tmp_path`, hash/tamaño, destino conflictivo, rollback por papelera/movimiento inverso.
- **Rollback:** desactivar verifier y volver al adapter legacy sin cambiar handlers.
- **Evidencia de rama:** `create_file`, `copy` y `move` sobre archivos regulares
  devuelven `ToolResult` v2 con ruta resuelta, tamaño y SHA-256 observados.
  Los conflictos se rechazan sin sobrescritura; un destino no observable queda
  `verification=failed`; directorios siguen en el adaptador legacy. Pruebas
  focalizadas: 67 tests y 22 subtests aprobados. El baseline posterior al merge
  `fa664e4` aprobó 264 tests y 104 subtests.

### Fase 6 - Cancelación y aislamiento de herramientas

- **Estado:** completada e integrada en `main` el 2026-07-28 desde
  `codex/07-tool-cancellation`.
- **Objetivo:** que timeout no signifique sólo dejar de esperar mientras el thread continúa.
- **Archivos previstos:** `core/tools/executor.py`, contratos de cancelación, pilotos de acciones largas, tests de fault injection.
- **Riesgo:** alto.
- **Dependencias:** ToolResult v2.
- **Criterio de aceptación:** handlers cooperativos reciben señal; procesos hijos se terminan de forma acotada; efectos parciales quedan explícitos.
- **Pruebas:** handler bloqueado, subprocess timeout, cancelación, cleanup y ausencia de threads/procesos huérfanos.
- **Rollback:** mantener executor anterior para herramientas aún no migradas.
- **Evidencia de rama:** `CancellationToken` thread-safe y cancelación por
  `request_id`; el executor espera cleanup durante una gracia acotada y conserva
  efecto/rollback declarados por el handler. El runner de procesos termina y
  recolecta el árbol iniciado por JARVIS. `dev_agent` es el primer piloto:
  incorpora checkpoints y su proceso de proyecto no queda ejecutándose tras
  timeout. El baseline posterior al merge `9e1e97a` aprobó 273 tests y 104
  subtests.

### Fase 7 - Ownership de sesión, audio, visión y lifecycle

- **Estado:** completada e integrada en `main` el 2026-07-28 desde
  `codex/08-session-lifecycle`.
- **Objetivo:** extraer servicios con un único escritor por estado sin cambiar el protocolo Gemini.
- **Archivos previstos:** nuevos `services/session.py`, `audio.py`, `vision.py`, `lifecycle.py`; `main.py`; tests.
- **Riesgo:** muy alto.
- **Dependencias:** trazabilidad, eventos mínimos y baseline de latencia.
- **Criterio de aceptación:** owners documentados; reconexión, interrupción y shutdown mantienen métricas; `main.py` compone en vez de implementar.
- **Pruebas:** fault injection de red/mic/cámara, doble sesión, audio en cola, shutdown y recuperación.
- **Rollback:** facade que delega al comportamiento heredado por servicio.
- **Evidencia de rama:** `RuntimeServices` compone owners separados de sesión,
  audio, visión y lifecycle. Reconexión preserva el checkpoint y reinicia sólo
  transitorios; generaciones evitan liberar una interrupción nueva desde una
  tarea vieja; cámara aplica backpressure; shutdown es idempotente y conserva
  deadline/métricas. `main.py` conserva el transporte y protocolo existentes,
  pero delega esos estados. El baseline posterior al merge `49e0677` aprobó 283
  tests y 104 subtests.

### Fase 8 - Frontera de UI

- **Estado:** completada e integrada en `main`.
- **Objetivo:** todas las mutaciones de widgets en el hilo Qt; UI emite comandos y consume snapshots.
- **Archivos previstos:** `ui.py`, `ui_mk2/*`, presenters/ViewModels y workers.
- **Riesgo:** alto.
- **Dependencias:** servicios y eventos tipados mínimos.
- **Criterio de aceptación:** ningún handler de `ToolExecutor` muta widgets desde `to_thread`; filesystem/red/subprocess salen de la capa visual.
- **Pruebas:** Qt offscreen, afinidad de thread, cierre de cámara, cambios rápidos de panel y Pet/Main.
- **Rollback:** señales/facades compatibles con métodos actuales.
- **Evidencia de rama:** `core/ui_boundary.py` define una fachada mínima para
  handlers; `main.py` deja de entregar `JarvisUI` a las tools; teléfono, Study,
  archivo seleccionado y cámara cruzan el límite mediante señales, snapshots o
  locks. `tests/test_ui_thread_boundary.py` cubre superficie pública, afinidad
  Qt real y regresiones estáticas, junto con las suites Mk II/Mk III. El commit
  de implementación `10000db` se integró mediante `a7370bd`; el baseline previo
  al merge aprobó 290 tests y 104 subtests.

### Fase 9 - Adaptadores de proveedores

- **Estado:** completada e integrada en `main`.
- **Objetivo:** separar Live, texto, visión y búsqueda; inyectar interfaces en acciones.
- **Archivos previstos:** `core/model_fallback.py`, nuevos adapters, acciones piloto, `main.py`.
- **Riesgo:** medio-alto.
- **Dependencias:** contratos y configuración central.
- **Criterio de aceptación:** la acción piloto no importa `google.genai`, no elige modelos ni lee secretos.
- **Pruebas:** fake providers, timeouts, fallback, error permanente/transitorio y cuota.
- **Rollback:** adapter que envuelve las llamadas actuales.
- **Evidencia de rama:** `core/providers` declara puertos estables para las
  cuatro capacidades y un adaptador Google de búsqueda. `web_search` es el
  piloto: recibe el provider desde `JarvisLive`, conserva DDG como fallback y
  no conoce SDK, clave ni modelos. Las migraciones concretas de Live, texto y
  visión quedan como lotes posteriores sobre los contratos ya definidos. El
  commit `f47954b` se integró mediante `9bffe3e`; el baseline aprobó 301 tests y
  104 subtests.

### Fase 10 - Configuración, observabilidad y calidad continuas

- **Estado:** parcial en `codex/11-settings-bootstrap`: bootstrap de settings
  implementado; logging estructurado, chequeos incrementales y CI pendientes.
- **Objetivo:** configuración validada, logging estructurado, chequeos incrementales y CI.
- **Archivos previstos:** nuevo módulo de settings, acciones migradas por lotes, logging, `pyproject.toml`, CI.
- **Riesgo:** medio.
- **Dependencias:** RequestContext.
- **Criterio de aceptación:** lectura única de secretos/config por proceso; consola + archivo rotativo; lint/type checking sólo sobre superficie migrada; chequeo de secretos.
- **Pruebas:** configuración ausente/malformada, redacción, rotación, import check y CI.
- **Rollback:** adapters de configuración y logging con defaults compatibles.
- **Evidencia de rama:** `config.settings.AppSettings` es inmutable, oculta la
  clave en `repr`, valida tipos/OS y cachea una instancia por archivo.
  `main.py` consume el snapshot y la UI ejecuta una recarga explícita sólo al
  guardar una nueva configuración. Los lectores heredados en actions,
  dashboard y memoria siguen pendientes para lotes de provider/configuración
  posteriores; esta fase no debe marcarse completa todavía.

## Baseline y presupuestos iniciales

Los siguientes valores del PDF son objetivos provisionales, no resultados medidos:

| Métrica | Objetivo inicial | Estado |
| --- | --- | --- |
| Wake -> UI visible | < 500 ms | pendiente hardware |
| ESC -> audio detenido | < 150 ms | pendiente medición |
| Tool local simple | < 300 ms | pendiente benchmark |
| Reconexión recuperable | < 5 s | pendiente fault injection |
| Shutdown limpio | < 3 s | pendiente observación de recursos |

## Quick wins previos al primer sprint

1. Añadir tests que demuestren el origen remoto perdido.
2. Marcar `file_processor` y sus operaciones por riesgo real.
3. Corregir la contradicción de `code_helper write/edit` libre.
4. Crear la matriz automática de las 37 herramientas.
5. Separar dependencias opcionales/legacy y documentarlas.
6. Eliminar sólo el dispatch inalcanzable después de cubrir equivalencia.
7. Convertir `PermissionStore.save()` a reemplazo atómico.

## Siguiente cambio recomendado

Un PR/commit pequeño de seguridad y especificación:

1. tests de integración que conserven `source=dashboard`;
2. inventario parametrizado de riesgo/operación para las 37 tools;
3. corrección de `file_processor` y `code_helper`;
4. sin cambios en audio, wake, UI visual, modelos ni Gemini Live.

La trazabilidad completa debe comenzar inmediatamente después, sobre esa frontera ya correcta.
