# Decision Widgets vs QML

## Decision

JARVIS retains PyQt Widgets. Phase 14 does not authorize a migration to QML.

The QML prototype showed measurable improvement in packaging, but not a net advantage:
The cold start and memory greatly worsened the Guardrails.
`ui.py` and `ui_mk2/*` were not modified.

## Method

`benchmarks/ui_qml_decision.py` runs each variant in a new process for
that you import, memory and caches are not shared. Both prototypes have a
equivalent area of 800x600 with:

- status header;
- encouraging progress;
- 12 metrics;
- an interactive control;
- updates close to 60 Hz.

The official run used five processes per variant and 45 frames per process:

```powershell
python benchmarks\ui_qml_decision.py --runs 5 --frames 45
```

Observed environment:

- Windows 11 `10.0.26200`;
- Python 3.14.6;
- PyQt/Qt 6.11.0;
- `QT_QPA_PLATFORM=offscreen`;
- Qt Quick and Qt Quick Controls loaded with backend software.

The aggregates are medium. Startup includes import, construction and first frame
interaction is p95 of 120 updates. Pacing is p95 of the interval
between observed frames; Jank means an interval greater than 25 ms.

## Results

| Metric | Widgets | QML | Reading |
| --- | ---: | ---: | --- |
| Cold Startup | 63.93 ms | 217.07 ms | QML +239.6% |
| First frame | 7.78 ms | 84.27 ms | QML slower |
| Incremental RSS | 20.62 MiB | 32.74 MiB | QML +58.8% |
| Interaction p95 | 0.183 ms | 0.175 ms | non-material difference |
| Frame interval p95 | 16,14 ms | 13,52 ms | QML improves 16.3% |
| Frames with jank | 0% | 0% | both inside the proxy |

The thresholds are set before deciding:

- significant advantage: at least 15% in startup or packing;
- maximum tolerable regression: 10% in any metric;
- maximum Jank QML: 5%.

QML exceeds the pacing threshold, but the startup and memory guardrails fail.
The automatic result is `defer`.

## Limits

This benchmark is a reproducible proxy and not a visual production test:

- uses rendering software offscreen, not the user's GPU/controllers;
- does not load `JarvisLive`, WebEngine, real camera or workspaces;
- does not measure visual fidelity, accessibility, multiple IPR or human input;
- confirmed QML imports from the source tree, not a frozen executable;
- the rendering offscreen callback may behave different to the composer
real.

By these limits, even one result `candidate` would have required another
representative benchmark before migrating.

## Conditions for reopening the decision

Reconsider QML only if there is a prototype of a real screen that:

1. Keep current contracts, Qt signals and capabilities;
2. is measured with GPU visible on the target hardware;
3. include startup, RSS, framework packaging, DPI, accessibility and interaction;
4. produce a verified frozen installable;
5. get an advantage of at least 15% without regressions greater than 10%.

## Rollback

The prototype is not connected to the runtime. To remove it just delete
`benchmarks/ui_qml_decision.py`, its tests and this document; not reversed
no productive UI file.
