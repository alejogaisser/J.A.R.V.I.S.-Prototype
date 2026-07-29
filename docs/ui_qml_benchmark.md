# Decisión Widgets vs QML

## Decisión

JARVIS conserva PyQt Widgets. La Fase 14 no autoriza una migración a QML.

El prototipo QML mostró una mejora medible de pacing, pero no una ventaja neta:
el arranque frío y la memoria empeoraron ampliamente los guardrails. La UI
productiva, `ui.py` y `ui_mk2/*` no fueron modificados.

## Método

`benchmarks/ui_qml_decision.py` ejecuta cada variante en un proceso nuevo para
que imports, memoria y cachés no se compartan. Ambos prototipos tienen una
superficie equivalente de 800x600 con:

- cabecera de estado;
- progreso animado;
- doce métricas;
- un control interactivo;
- actualizaciones cercanas a 60 Hz.

La corrida oficial usó cinco procesos por variante y 45 frames por proceso:

```powershell
python benchmarks\ui_qml_decision.py --runs 5 --frames 45
```

Entorno observado:

- Windows 11 `10.0.26200`;
- Python 3.14.6;
- PyQt/Qt 6.11.0;
- `QT_QPA_PLATFORM=offscreen`;
- Qt Quick y Qt Quick Controls cargados con backend software.

Los agregados son medianas. Startup incluye import, construcción y primer frame
frío. Interacción es p95 de 120 actualizaciones. Pacing es p95 del intervalo
entre frames observados; jank significa un intervalo mayor a 25 ms.

## Resultados

| Métrica | Widgets | QML | Lectura |
| --- | ---: | ---: | --- |
| Startup frío | 63,93 ms | 217,07 ms | QML +239,6% |
| Primer frame | 7,78 ms | 84,27 ms | QML más lento |
| RSS incremental | 20,62 MiB | 32,74 MiB | QML +58,8% |
| Interacción p95 | 0,183 ms | 0,175 ms | diferencia no material |
| Intervalo de frame p95 | 16,14 ms | 13,52 ms | QML mejora 16,3% |
| Frames con jank | 0% | 0% | ambos dentro del proxy |

Los umbrales se fijan antes de decidir:

- ventaja significativa: al menos 15% en startup o pacing;
- regresión máxima tolerable: 10% en cualquier métrica;
- jank QML máximo: 5%.

QML supera el umbral de pacing, pero falla los guardrails de startup y memoria.
El resultado automático es `defer`.

## Límites

Este benchmark es un proxy reproducible y no una prueba visual de producción:

- usa rendering software offscreen, no la GPU/controladores del usuario;
- no carga `JarvisLive`, WebEngine, cámara ni workspaces reales;
- no mide fidelidad visual, accesibilidad, DPI múltiple ni input humano;
- confirmó imports QML desde el árbol fuente, no un ejecutable congelado;
- el callback de rendering offscreen puede comportarse distinto al compositor
  real.

Por estos límites, incluso un resultado `candidate` habría requerido otro
benchmark representativo antes de migrar.

## Condiciones para reabrir la decisión

Reconsiderar QML sólo si existe un prototipo de una pantalla real que:

1. conserve contratos, señales Qt y capacidades actuales;
2. se mida con GPU visible en el hardware objetivo;
3. incluya startup, RSS, frame pacing, DPI, accesibilidad e interacción;
4. produzca un instalable congelado verificado;
5. consiga una ventaja de al menos 15% sin regresiones mayores al 10%.

## Rollback

El prototipo no está conectado al runtime. Para retirarlo basta eliminar
`benchmarks/ui_qml_decision.py`, sus tests y este documento; no se revierte
ningún archivo de UI productiva.
