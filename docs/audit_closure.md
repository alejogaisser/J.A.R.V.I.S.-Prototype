# Cierre metodológico de la auditoría

Este documento cierra la secuencia operativa de las secciones 15, 16 y 17 del
PDF rector. Cerrar la secuencia no equivale a declarar que toda la arquitectura
objetivo está terminada.

## Fuentes verificadas

`docs/audit_closure.json` conserva los ocho grupos de fuentes de la sección
17.1: entrada/runtime, arquitectura central, seguridad, presentación, memoria,
integraciones, actions y documentación/pruebas. El gate resuelve cada ruta y
falla si falta, es absoluta o escapa del repositorio.

## Límites conservados

Los cinco límites de la sección 17.2 permanecen explícitos:

- no hubo benchmark acústico real;
- no se abrieron sesiones reales de Gemini, Google, Microsoft ni dashboard
  móvil;
- no se ejecutaron efectos destructivos o externos;
- los umbrales de rendimiento necesitan calibración en el equipo objetivo;
- la matriz de 37 herramientas se comprueba desde código.

No se reinterpretan mocks como hardware ni un baseline local como prueba de
cuentas, red o efectos reales.

## Estado de cierre

El estado es `closed_with_open_risks`. El gate cruza este documento con
`docs/global_acceptance.json`: mientras haya criterios parciales, manuales o
bloqueados, rechaza `verified_complete`.

Al inicio de esta fase la matriz global contiene:

- 19 criterios totales;
- 6 verificados;
- 11 parciales;
- 2 manuales;
- 0 bloqueados.

Por eso quedan 13 criterios globales abiertos. Las fases 15-17 completan los
controles de cierre del PDF, no las migraciones ni verificaciones de hardware
que esos controles señalan.

## Uso

```powershell
python scripts/check_audit_closure.py --repo-root .
```

El baseline ejecuta el gate junto con aceptación global y control operativo.
Si cambian fuentes, límites o estados de aceptación, el manifiesto debe
actualizarse con evidencia real.

## Rollback

Retirar la llamada del baseline y revertir manifiesto, script y prueba elimina
este control sin cambiar runtime. No hay migración de datos, herramientas,
Gemini, audio ni UI en esta fase.
