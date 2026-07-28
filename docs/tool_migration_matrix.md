# Matriz de migración de herramientas

## Contrato

Snapshot del registro de 37 `ToolDefinition` al 2026-07-28. La tabla describe
el comportamiento actual, no el nivel deseado. `Sin contrato` significa que
el runtime todavía no dispone de evidencia/verificación o rollback tipados.

Desde la Fase 8 todos los handlers `executor` reciben `UiCommandFacade`, no
`JarvisUI`. Esto cierra el acceso directo a widgets pero no convierte por sí
solo sus retornos legacy en resultados verificables.

El test `tests/test_tool_inventory.py` compara nombres, riesgo, ruta y timeout
contra `main.py` y `core/tools/builtins.py`. Una tool nueva no puede incorporarse
sin añadir una fila y declarar sus límites.

| Tool | Risk | Policy actual | Preview | Retorno actual | Verificación | Rollback | Timeout s | Route | Cobertura | Migración pendiente |
| --- | --- | --- | --- | --- | --- | --- | ---: | --- | --- | --- |
| `open_app` | local_change | FREE | No | Texto legacy | Sin contrato | Cierre manual | 30 | executor | Seguridad estática | Evidencia de proceso/ventana |
| `web_search` | read_only | FREE | No | Texto legacy | Fuentes en texto | No aplica | 30 | executor | Clock parcial | Provider + citas tipadas |
| `system_status` | read_only | FREE | No | Texto legacy | Lectura puntual | No aplica | 30 | executor | Policy | Resultado estructurado |
| `weather_report` | read_only | FREE | No | Texto legacy | Fuente en texto | No aplica | 30 | executor | Indirecta | Provider inyectable |
| `send_message` | external_effect | CONFIRM_ALWAYS | Sí | Texto legacy | Sin contrato | No disponible | 30 | executor | Policy/preview | ID remoto + estado de entrega |
| `reminder` | external_effect | CONFIRM_ONCE | No | Texto legacy | Sin contrato | Manual | 30 | executor | Policy parametrizada | Verificar persistencia |
| `youtube_video` | read_only | FREE | No | Texto legacy | Sin contrato | Cerrar navegador | 30 | executor | Sin prueba directa | Resultado y destino tipados |
| `screen_process` | read_only | FREE | No | Ruta especial | Captura parcial + owner de cooldown | No aplica | 30 | special | Seguridad + runtime owner | Envelope común + latencia |
| `close_camera` | read_only | FREE | No | Ruta especial | Owner libera frame pendiente; UI implícita | Reabrir cámara | 30 | special | Seguridad + runtime owner | Evento/verificación de cámara |
| `camera_control` | read_only | FREE | No | Ruta especial | Owner de backpressure; estado UI implícito | Acción inversa | 30 | special | Cámara + runtime owner | Riesgo por operación + evento |
| `pet_mode` | local_change | FREE | No | Texto legacy | Señal Qt encolada | Salir de Pet | 30 | executor | UI + afinidad Qt | Resultado tipado |
| `interface_control` | local_change | FREE | No | Texto legacy | Confirmación del slot Qt | Acción inversa | 30 | executor | Interfaz + afinidad Qt | Resultado tipado |
| `visual_mouse` | read_only | FREE | No | Ruta especial | UIA/imagen parcial | No disponible | 30 | special | Seguridad estática | Riesgo real + envelope común |
| `computer_settings` | sensitive | FREE; power CONFIRM_ALWAYS | No | Texto legacy | Sin contrato | Según operación | 30 | executor | Policy/seguridad | Matriz por operación |
| `browser_control` | sensitive | Lectura/navegación FREE; interacción ONCE; desconocida ALWAYS | No | Texto legacy | Sin contrato | Según operación | 30 | executor | Policy parametrizada | Preview y verificación de submit |
| `file_controller` | sensitive | Por acción | Sí | `ToolResult` v2 en create/copy/move de archivos; resto legacy | Ruta, tamaño y SHA-256; ausencia de origen en move | Papelera para create/copy; movimiento inverso para move | 30 | executor | Seguridad + verifier piloto | Verificación recursiva y migrar operaciones restantes |
| `desktop_control` | sensitive | CONFIRM_ONCE | No | Texto legacy | Sin contrato | Según operación | 30 | executor | Sin prueba directa | Clasificación por operación |
| `code_helper` | sensitive | explain FREE; write/edit/optimize ONCE; resto ALWAYS | No | Texto legacy | Sin contrato | VCS/manual | 120 | executor | Policy/scripts | Sandbox y evidencia |
| `dev_agent` | sensitive | CONFIRM_ONCE | No | Texto legacy; cancelación v2 en executor | Checkpoints y proceso terminado; efecto parcial tipado | Proyecto/VCS manual declarado disponible | 120 | executor | Policy + cancelación/proceso | Cancelar provider/instalación; límite de workspace + evidencia |
| `computer_control` | sensitive | Acciones comunes FREE; resto ONCE | No | Texto legacy | UIA/imagen parcial | No disponible | 30 | executor | Seguridad parcial | Riesgo por acción + límites |
| `game_updater` | external_effect | CONFIRM_ONCE | No | Texto legacy | Sin contrato | Gestor externo | 120 | executor | Seguridad estática | Estado de instalación verificable |
| `flight_finder` | read_only | FREE | No | Texto legacy | Fuentes en texto | No aplica | 30 | executor | Sin prueba directa | Provider + esquema de resultados |
| `shutdown_jarvis` | sensitive | FREE | No | Ruta especial | State machine idempotente con deadline | Reinicio manual | 30 | special | Policy + lifecycle owner | Policy sensible + envelope común |
| `file_processor` | sensitive | Lectura FREE; escritura ONCE; ejecución ALWAYS | No | Texto/archivo legacy | Sin contrato | Según operación | 30 | executor | Policy parametrizada | Verificación de artefactos |
| `save_memory` | local_change | Bypass de policy | No | Ruta especial | Lectura posterior no contractual | Forget/manual | 30 | special | Memoria indirecta | Pasar por policy y executor |
| `memory_list` | read_only | FREE | No | Lista/dict legacy | Datos cargados | No aplica | 30 | executor | Memoria | Resultado paginado/tipado |
| `memory_search` | read_only | FREE | No | Lista/dict legacy | Datos cargados | No aplica | 30 | executor | Memoria | Resultado paginado/tipado |
| `memory_update` | local_change | CONFIRM_ONCE | No | Bool/dict legacy | Persistencia parcial | Historial | 30 | executor | Policy/memoria | Evidencia + versión |
| `memory_forget` | sensitive | CONFIRM_ALWAYS | No | Bool/dict legacy | Persistencia parcial | `memory_restore` | 30 | executor | Policy/memoria | Evidencia + versión |
| `memory_restore` | local_change | CONFIRM_ONCE | No | Bool/dict legacy | Persistencia parcial | `memory_forget` | 30 | executor | Policy/memoria | Evidencia + versión |
| `memory_graph` | read_only | FREE | No | Texto legacy | Reindexado implícito vía señal Qt | No aplica | 30 | executor | Grafo/UI + afinidad Qt | Métricas |
| `geo_map` | read_only | FREE | No | Dict/texto legacy | Respuesta del provider; presentación encolada | No aplica | 30 | executor | GEO + afinidad Qt | Provider tipado |
| `math_engine` | read_only | FREE | No | Texto/archivo legacy | Cálculo local parcial | No aplica | 30 | executor | Math/seguridad | Resultado/artefacto tipado |
| `study_engine` | local_change | FREE | No | Texto/archivo legacy | Parcial por operación | Según artefacto | 30 | executor | Study | Riesgo y provider por operación |
| `account_connector` | external_effect | Lectura FREE; connect/download ONCE; create/disconnect ALWAYS | No | Texto/JSON legacy | Provider parcial | Según operación | 30 | executor | Conectores/policy | Preview y verificación externa |
| `obsidian_connector` | sensitive | Lectura FREE; escritura ONCE; resto ALWAYS | No | Texto/JSON legacy | Filesystem parcial | Historial/manual | 30 | executor | Obsidian/policy | Preview + evidencia de nota |
| `permission_manager` | sensitive | Lectura FREE; cambios ALWAYS | No | Ruta especial | Store recargado | Restaurar preferencia | 30 | special | Policy/seguridad | Store atómico + envelope común |

## Rutas especiales

Siete herramientas evitan el handler normal del `ToolExecutor`:
`screen_process`, `close_camera`, `camera_control`, `visual_mouse`,
`shutdown_jarvis`, `save_memory` y `permission_manager`. Deben migrarse por
lotes pequeños al mismo envelope de validación, policy, ejecución, auditoría y
resultado, conservando sus requisitos de UI/lifecycle.

## Prioridad derivada

1. Propagar el origen remoto y añadir tests de dashboard.
2. Corregir `file_processor`, `code_helper`, browser, reminder y escrituras de
   conectores.
3. Incorporar `RequestContext` antes de migrar rutas especiales.
4. Extender por lotes el piloto ya activo de verificación de archivos sin
   inferir efectos de los retornos legacy.
