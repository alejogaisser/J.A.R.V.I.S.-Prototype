# Calidad incremental y CI

## Objetivo

Incorporar controles reproducibles sin exigir que toda la deuda histórica se
resuelva en una sola etapa. La superficie sólo crece cuando otro módulo obtiene
contratos y tipos suficientes.

## Herramientas

`requirements-dev.txt` declara:

- Ruff para imports, errores de sintaxis, nombres indefinidos y patrones de bug;
- mypy para contratos tipados;
- pytest para comportamiento.

`pyproject.toml` mantiene la configuración. No se habilitan reglas de
modernización que fuercen refactors ajenos.

## Superficie

`scripts/validate_quality.ps1` entrega a Ruff una lista explícita de módulos
migrados y sus pruebas. Mypy usaba inicialmente seis módulos productivos;
Fase 11 amplía la lista a doce con `core.events` y los cinco módulos de owners;
Fase 12 añade `services.workers` como módulo productivo número trece y Fase 13
incorpora `services.agents` como contrato productivo número catorce. No se
inspeccionan `main.py`, `ui.py`, hardware de audio ni actions heredadas hasta
migrarlas por frontera.

El benchmark aislado de Fase 14 y sus tests también pasan por Ruff. No se añade
a mypy porque es instrumentación reproducible, no un contrato productivo. El
baseline incluye `benchmarks/` en `compileall`.

Fase 15 incorpora `scripts/check_global_acceptance.py` a Ruff y mypy, y su
prueba a Ruff. El baseline ejecuta el gate en modo integridad: exige los 19
criterios del PDF y evidencia local válida, sin confundir ese control con el
cierre estricto de brechas manuales o parciales.

Fase 16 añade `scripts/check_operational_change_control.py` a Ruff/mypy y su
prueba a Ruff. El baseline exige los 19 controles operativos y un registro
estructurado por fase completada desde la 15.

Fase 17 añade `scripts/check_audit_closure.py` a Ruff/mypy y su prueba a Ruff.
El baseline conserva los ocho grupos de fuentes, cinco límites y el estado de
riesgos abiertos sincronizado con aceptación global.

Ejecución:

```powershell
.\scripts\validate_quality.ps1 -Python python
```

`scripts/validate_baseline.ps1` incorpora el mismo gate antes del escaneo de
secretos y la suite.

## CI

`.github/workflows/quality.yml` se activa para pushes a `main`,
`codex/**` y pull requests. Usa:

- Windows, la plataforma principal verificada;
- Python 3.12;
- dependencias versionadas;
- permisos `contents: read`;
- timeout de 30 minutos;
- el baseline reproducible completo.

No recibe credenciales, no inicia modos direct/wake y no accede a hardware,
Gemini ni cuentas.

## Expansión

Para agregar un módulo:

1. corregirlo y agregar pruebas dentro de una etapa propia;
2. añadirlo a `$QualityFiles`;
3. añadirlo a `tool.mypy.files` sólo si su contrato productivo está tipado;
4. ejecutar el baseline completo;
5. documentar cualquier regla omitida.

## Rollback

Retirar temporalmente la llamada del baseline o el workflow no cambia runtime,
pero elimina una barrera de regresión. Ruff/mypy pueden revertirse quitando sus
entradas de `requirements-dev.txt`; no generaron formato masivo ni cambios de
interfaces.
