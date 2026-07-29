"""Reproducible, isolated PyQt Widgets versus QML decision benchmark."""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import statistics
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import psutil

SCHEMA_VERSION = 1
TARGET_FRAME_MS = 1000.0 / 60.0
JANK_THRESHOLD_MS = 25.0
MEANINGFUL_ADVANTAGE_PCT = 15.0
MAX_REGRESSION_PCT = 10.0


@dataclass(frozen=True, slots=True)
class VariantMetrics:
    variant: str
    supported: bool
    import_ms: float
    construction_ms: float
    first_frame_ms: float | None
    rss_delta_mb: float
    interaction_p95_ms: float
    frame_interval_p95_ms: float | None
    frame_jank_pct: float | None
    frames_observed: int
    error: str | None = None


@dataclass(frozen=True, slots=True)
class Decision:
    outcome: str
    reason: str
    meaningful_advantages: tuple[str, ...]
    regressions: tuple[str, ...]


def percentile(values: list[float], percentile_value: float) -> float | None:
    """Return a nearest-rank percentile without optional dependencies."""
    if not values:
        return None
    if not 0 < percentile_value <= 100:
        raise ValueError("Percentile must be in the interval (0, 100].")
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile_value / 100.0 * len(ordered)))
    return ordered[rank - 1]


def percentage_change(candidate: float, baseline: float) -> float:
    """Return positive percentage when candidate is lower/better."""
    if baseline <= 0:
        raise ValueError("Benchmark baseline must be positive.")
    return (baseline - candidate) / baseline * 100.0


def decide(
    widgets: dict[str, float | bool | None],
    qml: dict[str, float | bool | None],
) -> Decision:
    """Apply the documented adoption guardrails to aggregate metrics."""
    if not widgets.get("supported") or not qml.get("supported"):
        return Decision(
            outcome="defer",
            reason="Both prototypes must complete before QML can be considered.",
            meaningful_advantages=(),
            regressions=("incomplete_variant",),
        )

    comparisons = {
        "startup": (
            float(widgets["startup_ms"]),
            float(qml["startup_ms"]),
        ),
        "memory": (
            float(widgets["rss_delta_mb"]),
            float(qml["rss_delta_mb"]),
        ),
        "interaction": (
            float(widgets["interaction_p95_ms"]),
            float(qml["interaction_p95_ms"]),
        ),
        "frame_pacing": (
            float(widgets["frame_interval_p95_ms"]),
            float(qml["frame_interval_p95_ms"]),
        ),
    }
    improvements = {
        name: percentage_change(candidate, baseline)
        for name, (baseline, candidate) in comparisons.items()
    }
    advantages = tuple(
        name
        for name in ("startup", "frame_pacing")
        if improvements[name] >= MEANINGFUL_ADVANTAGE_PCT
    )
    regressions = tuple(
        name
        for name, improvement in improvements.items()
        if improvement < -MAX_REGRESSION_PCT
    )
    qml_jank = float(qml["frame_jank_pct"])
    if qml_jank > 5.0:
        regressions += ("qml_jank",)

    if advantages and not regressions:
        return Decision(
            outcome="candidate",
            reason=(
                "QML meets the prototype threshold; a representative visual and "
                "packaging benchmark is still required before migration."
            ),
            meaningful_advantages=advantages,
            regressions=(),
        )
    return Decision(
        outcome="defer",
        reason=(
            "The isolated prototype does not show a regression-free advantage "
            f"of at least {MEANINGFUL_ADVANTAGE_PCT:g}%."
        ),
        meaningful_advantages=advantages,
        regressions=regressions,
    )


def _frame_statistics(
    timestamps: list[float],
) -> tuple[float | None, float | None]:
    intervals = [
        (current - previous) * 1000.0
        for previous, current in zip(timestamps, timestamps[1:], strict=False)
    ]
    p95 = percentile(intervals, 95)
    if not intervals:
        return p95, None
    jank = sum(value > JANK_THRESHOLD_MS for value in intervals) / len(intervals)
    return p95, jank * 100.0


def _run_widgets_worker(frames: int) -> VariantMetrics:
    rss_before = psutil.Process().memory_info().rss
    import_started = time.perf_counter()
    from PyQt6.QtCore import Qt, QTimer
    from PyQt6.QtWidgets import (
        QApplication,
        QGridLayout,
        QLabel,
        QProgressBar,
        QPushButton,
        QVBoxLayout,
        QWidget,
    )

    import_ms = (time.perf_counter() - import_started) * 1000.0
    construction_started = time.perf_counter()
    app = QApplication.instance() or QApplication([])
    paint_times: list[float] = []
    interaction_samples: list[float] = []
    collecting_frames = [False]

    class BenchmarkWindow(QWidget):
        def paintEvent(self, event) -> None:
            if collecting_frames[0]:
                paint_times.append(time.perf_counter())
            super().paintEvent(event)

    root = BenchmarkWindow()
    root.setWindowTitle("JARVIS Widgets benchmark")
    root.resize(800, 600)
    layout = QVBoxLayout(root)
    title = QLabel("JARVIS SYSTEM STATUS")
    title.setObjectName("title")
    layout.addWidget(title)
    progress = QProgressBar()
    progress.setRange(0, 100)
    layout.addWidget(progress)
    grid = QGridLayout()
    values: list[QLabel] = []
    for index in range(12):
        grid.addWidget(QLabel(f"METRIC {index + 1:02d}"), index // 3, index % 3)
        value = QLabel("000")
        values.append(value)
        grid.addWidget(value, index // 3 + 4, index % 3)
    layout.addLayout(grid)
    button = QPushButton("PING")
    button.clicked.connect(lambda: values[0].setText("ACK"))
    layout.addWidget(button)
    root.setStyleSheet(
        "QWidget{background:#020b10;color:#70eaff}"
        "QLabel#title{font-size:24px;font-weight:700}"
        "QPushButton{border:1px solid #2bc9ed;padding:8px}"
    )
    construction_ms = (time.perf_counter() - construction_started) * 1000.0
    first_frame_started = time.perf_counter()
    collecting_frames[0] = True
    root.show()
    for _ in range(20):
        app.processEvents()
        if paint_times:
            break
    first_frame = (
        (paint_times[0] - first_frame_started) * 1000.0
        if paint_times
        else None
    )
    collecting_frames[0] = False
    paint_times.clear()

    for index in range(120):
        started = time.perf_counter()
        values[index % len(values)].setText(str(index))
        button.click()
        app.processEvents()
        interaction_samples.append((time.perf_counter() - started) * 1000.0)

    tick = [0]

    def update_frame() -> None:
        tick[0] += 1
        progress.setValue(tick[0] % 101)
        root.update()
        if len(paint_times) >= frames:
            app.quit()

    timer = QTimer()
    timer.setTimerType(Qt.TimerType.PreciseTimer)
    timer.setInterval(round(TARGET_FRAME_MS))
    timer.timeout.connect(update_frame)
    collecting_frames[0] = True
    timer.start()
    QTimer.singleShot(5000, app.quit)
    app.exec()
    rss_after = psutil.Process().memory_info().rss
    frame_p95, jank = _frame_statistics(paint_times[:frames])
    root.close()
    return VariantMetrics(
        variant="widgets",
        supported=len(paint_times) >= max(2, frames // 2),
        import_ms=import_ms,
        construction_ms=construction_ms,
        first_frame_ms=first_frame,
        rss_delta_mb=max(0.0, (rss_after - rss_before) / (1024 * 1024)),
        interaction_p95_ms=float(percentile(interaction_samples, 95) or 0.0),
        frame_interval_p95_ms=frame_p95,
        frame_jank_pct=jank,
        frames_observed=len(paint_times),
    )


_QML_SOURCE = b"""
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window

Window {
    id: root
    visible: true
    width: 800
    height: 600
    color: "#020b10"
    title: "JARVIS QML benchmark"
    property int tick: 0

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 18
        spacing: 12
        Label {
            text: "JARVIS SYSTEM STATUS"
            color: "#70eaff"
            font.pixelSize: 24
            font.bold: true
        }
        ProgressBar {
            Layout.fillWidth: true
            value: (root.tick % 101) / 100
        }
        GridLayout {
            columns: 3
            Repeater {
                model: 12
                delegate: Rectangle {
                    required property int index
                    Layout.fillWidth: true
                    implicitHeight: 54
                    color: "#061821"
                    border.color: "#17566a"
                    Text {
                        anchors.centerIn: parent
                        text: "METRIC " + (index + 1) + " / " + root.tick
                        color: "#70eaff"
                    }
                }
            }
        }
        Button {
            text: "PING"
            onClicked: root.tick += 1
        }
        Item { Layout.fillHeight: true }
    }
    Timer {
        interval: 17
        running: true
        repeat: true
        onTriggered: root.tick += 1
    }
}
"""


def _run_qml_worker(frames: int) -> VariantMetrics:
    rss_before = psutil.Process().memory_info().rss
    import_started = time.perf_counter()
    from PyQt6.QtCore import QTimer
    from PyQt6.QtGui import QGuiApplication
    from PyQt6.QtQml import QQmlApplicationEngine

    import_ms = (time.perf_counter() - import_started) * 1000.0
    construction_started = time.perf_counter()
    app = QGuiApplication.instance() or QGuiApplication([])
    engine = QQmlApplicationEngine()
    first_frame_started = time.perf_counter()
    engine.loadData(_QML_SOURCE)
    roots = engine.rootObjects()
    if not roots:
        return VariantMetrics(
            variant="qml",
            supported=False,
            import_ms=import_ms,
            construction_ms=(time.perf_counter() - construction_started) * 1000.0,
            first_frame_ms=None,
            rss_delta_mb=0.0,
            interaction_p95_ms=0.0,
            frame_interval_p95_ms=None,
            frame_jank_pct=None,
            frames_observed=0,
            error="QML engine did not create a root window.",
        )
    root = roots[0]
    construction_ms = (time.perf_counter() - construction_started) * 1000.0
    frame_times: list[float] = []
    first_frame_times: list[float] = []
    interaction_samples: list[float] = []

    def observe_first_frame() -> None:
        first_frame_times.append(time.perf_counter())

    root.afterRendering.connect(observe_first_frame)
    for _ in range(20):
        app.processEvents()
        if first_frame_times:
            break
    root.afterRendering.disconnect(observe_first_frame)
    first_frame = (
        (first_frame_times[0] - first_frame_started) * 1000.0
        if first_frame_times
        else None
    )

    def after_rendering() -> None:
        frame_times.append(time.perf_counter())
        if len(frame_times) >= frames:
            QTimer.singleShot(0, app.quit)

    for index in range(120):
        started = time.perf_counter()
        root.setProperty("tick", index)
        app.processEvents()
        interaction_samples.append((time.perf_counter() - started) * 1000.0)

    root.afterRendering.connect(after_rendering)
    QTimer.singleShot(5000, app.quit)
    app.exec()
    rss_after = psutil.Process().memory_info().rss
    frame_p95, jank = _frame_statistics(frame_times[:frames])
    root.close()
    return VariantMetrics(
        variant="qml",
        supported=len(frame_times) >= max(2, frames // 2),
        import_ms=import_ms,
        construction_ms=construction_ms,
        first_frame_ms=first_frame,
        rss_delta_mb=max(0.0, (rss_after - rss_before) / (1024 * 1024)),
        interaction_p95_ms=float(percentile(interaction_samples, 95) or 0.0),
        frame_interval_p95_ms=frame_p95,
        frame_jank_pct=jank,
        frames_observed=len(frame_times),
        error=None if frame_times else "No QML frames were observed offscreen.",
    )


def _worker(variant: str, frames: int) -> int:
    try:
        metrics = (
            _run_widgets_worker(frames)
            if variant == "widgets"
            else _run_qml_worker(frames)
        )
    except Exception as error:
        metrics = VariantMetrics(
            variant=variant,
            supported=False,
            import_ms=0.0,
            construction_ms=0.0,
            first_frame_ms=None,
            rss_delta_mb=0.0,
            interaction_p95_ms=0.0,
            frame_interval_p95_ms=None,
            frame_jank_pct=None,
            frames_observed=0,
            error=f"{type(error).__name__}: {error}",
        )
    print(json.dumps(asdict(metrics), sort_keys=True))
    return 0 if metrics.supported else 2


def _run_isolated(variant: str, frames: int) -> VariantMetrics:
    environment = dict(os.environ)
    environment.update(
        {
            "QT_QPA_PLATFORM": "offscreen",
            "QT_QUICK_BACKEND": "software",
            "QSG_RHI_BACKEND": "software",
            "QSG_RENDER_LOOP": "basic",
        }
    )
    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--worker",
            variant,
            "--frames",
            str(frames),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
        env=environment,
        check=False,
    )
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        return VariantMetrics(
            variant=variant,
            supported=False,
            import_ms=0.0,
            construction_ms=0.0,
            first_frame_ms=None,
            rss_delta_mb=0.0,
            interaction_p95_ms=0.0,
            frame_interval_p95_ms=None,
            frame_jank_pct=None,
            frames_observed=0,
            error=(result.stderr.strip() or f"Worker exited {result.returncode}")[:500],
        )
    return VariantMetrics(**json.loads(lines[-1]))


def aggregate(samples: list[VariantMetrics]) -> dict[str, float | bool | None]:
    supported = [sample for sample in samples if sample.supported]
    if not supported:
        return {"supported": False}

    def median_of(name: str) -> float:
        values = [
            float(value)
            for sample in supported
            if (value := getattr(sample, name)) is not None
        ]
        return float(statistics.median(values))

    return {
        "supported": len(supported) == len(samples),
        "runs": len(samples),
        "startup_ms": (
            median_of("import_ms")
            + median_of("construction_ms")
            + median_of("first_frame_ms")
        ),
        "import_ms": median_of("import_ms"),
        "construction_ms": median_of("construction_ms"),
        "first_frame_ms": median_of("first_frame_ms"),
        "rss_delta_mb": median_of("rss_delta_mb"),
        "interaction_p95_ms": median_of("interaction_p95_ms"),
        "frame_interval_p95_ms": median_of("frame_interval_p95_ms"),
        "frame_jank_pct": median_of("frame_jank_pct"),
        "frames_observed": median_of("frames_observed"),
    }


def run_benchmark(runs: int, frames: int) -> dict[str, Any]:
    if runs <= 0 or frames < 10:
        raise ValueError("Runs must be positive and frames must be at least 10.")
    samples = {
        variant: [_run_isolated(variant, frames) for _ in range(runs)]
        for variant in ("widgets", "qml")
    }
    aggregates = {
        variant: aggregate(variant_samples)
        for variant, variant_samples in samples.items()
    }
    decision = decide(aggregates["widgets"], aggregates["qml"])
    return {
        "schema_version": SCHEMA_VERSION,
        "scope": "isolated_headless_prototype",
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "qt_qpa_platform": "offscreen",
            "qt_quick_backend": "software",
        },
        "thresholds": {
            "meaningful_advantage_pct": MEANINGFUL_ADVANTAGE_PCT,
            "max_regression_pct": MAX_REGRESSION_PCT,
            "jank_threshold_ms": JANK_THRESHOLD_MS,
        },
        "samples": {
            variant: [asdict(sample) for sample in variant_samples]
            for variant, variant_samples in samples.items()
        },
        "aggregate": aggregates,
        "decision": asdict(decision),
        "limitations": [
            "Headless software rendering is not representative of the production GPU.",
            "The prototypes approximate the shell; they do not load JarvisLive or real workspaces.",
            "Packaging, accessibility, visual parity, hardware and input devices are not measured.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare isolated Widgets and QML UI prototypes."
    )
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--frames", type=int, default=45)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--worker", choices=("widgets", "qml"))
    args = parser.parse_args()
    if args.worker:
        return _worker(args.worker, args.frames)

    report = run_benchmark(args.runs, args.frames)
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
