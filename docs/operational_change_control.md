# Control operativo de cambios

Este gate convierte la sección 16 del PDF rector en un contrato comprobable
para fases arquitectónicas. No reemplaza el juicio técnico ni demuestra actos
externos: obliga a registrar la evidencia y falla si un cierre queda
incompleto o incoherente.

## Alcance

`docs/operational_change_control.json` contiene:

- los 11 mandatos operativos `OP-01` a `OP-11`;
- las 8 preguntas previas a refactorizar `REF-01` a `REF-08`;
- un registro por fase completada desde la fase 15.

Cada registro consigna motivo, objetivo, archivos, riesgos, pruebas, métricas,
rollback, owner, paso por policy, verificación del efecto, comportamiento ante
cancelación/timeout/reconexión, compatibilidad, beneficio de abstracciones,
límites de evidencia y estado de la nota Obsidian.

El gate comprueba:

- inventario exacto y sin duplicados;
- evidencia y archivos existentes, relativos y contenidos en el repositorio;
- ausencia de rutas sensibles en los registros;
- fases secuenciales y un único registro por fase;
- resultados aprobados y nota Obsidian actualizada antes de aceptar una fase
  marcada como completada en `ROADMAP.md`;
- confirmación y preview obligatorios cuando un cambio se declara destructivo;
- beneficio explícito para cualquier abstracción.

## Uso

```powershell
python scripts/check_operational_change_control.py --repo-root .
```

El baseline ejecuta este comando antes de pytest. Para una fase nueva:

1. crear el registro con tests y Obsidian en `pending`;
2. implementar y ejecutar pruebas dirigidas;
3. registrar resultados y métricas reales, distinguiendo mocks de hardware;
4. actualizar la nota Obsidian;
5. cambiar esos estados a `passed`/`updated`;
6. recién entonces marcar la fase completada en `ROADMAP.md`.

## Límites manuales

CI no puede demostrar que un operador leyó `AGENTS.md`, observó `git status` o
actualizó un archivo externo de Obsidian. El contrato conserva esas
obligaciones y exige declararlas, pero la evidencia final debe revisarse en el
handoff. Tampoco transforma una prueba mockeada en verificación de hardware.

## Rollback

Retirar la llamada de `scripts/validate_baseline.ps1` desactiva el gate sin
cambiar runtime. Revertir todos los archivos de esta fase restaura el baseline
anterior; no hay migración de datos ni adaptador productivo involucrado.
