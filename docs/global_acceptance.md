# Gate de aceptación global

Este gate traduce los 19 criterios de la sección 15 del PDF rector a un
inventario versionado y comprobable. La fuente de datos es
`docs/global_acceptance.json`; `scripts/check_global_acceptance.py` valida que
no falte ningún criterio, que los estados sean explícitos y que toda evidencia
permanezca dentro del repositorio y exista.

Estados:

- `verified`: la evidencia automatizada disponible satisface el criterio;
- `partial`: existe implementación real, pero la cobertura no alcanza toda la
  superficie declarada;
- `manual`: hace falta hardware, packaging, observación visual o una medición
  real que los mocks no pueden demostrar;
- `blocked`: no puede avanzarse sin una dependencia o decisión externa.

La validación básica ejecuta el modo de integridad:

```powershell
python scripts/check_global_acceptance.py --repo-root .
```

Ese modo falla ante inventario incompleto, evidencia inexistente, paths
externos o un estado incoherente, pero permite estados pendientes. El cierre
global estricto se consulta por separado:

```powershell
python scripts/check_global_acceptance.py --repo-root . --require-complete
```

Mientras exista un criterio distinto de `verified`, el segundo comando termina
con código 2. Por diseño, la etapa 15 puede entregar un gate confiable sin
afirmar que las brechas históricas ya están resueltas.

## Resultado inicial

La persistencia de memoria y `runtime_state` se endureció en esta etapa:
temporal en el mismo directorio, `flush`/`fsync`, validación antes de publicar,
`os.replace`, limpieza ante fallos y preservación del último primario válido.
Memoria recupera desde backup validado; el estado de runtime, por ser
telemetría de mejor esfuerzo, conserva el último documento completo y nunca
impide el arranque.

Los pendientes principales siguen siendo:

- envelope central para rutas especiales y migración de tools legacy;
- ownership completo de dashboard/shutdown y supervisión del resto de workers;
- propagación/auditoría universal fuera del camino central de tools;
- migración de proveedores de texto, Live y visión;
- métricas reales de wake, audio, reconexión y shutdown.

## Rollback

Revertir el commit de la etapa restaura los escritores anteriores. Si una
regresión de memoria obliga a rollback manual, conservar `long_term.json` y
`long_term.json.bak`, validar ambos como JSON de esquema 2 y restaurar sólo la
copia válida más reciente con JARVIS detenido.
