from __future__ import annotations

import io
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from pathlib import Path
from threading import Lock

import pytest

from core.events import (
    AudioInterruptionChanged,
    DashboardConnected,
    DashboardConnectionKind,
    EventBus,
    EventHeader,
    InputModality,
    InputReceived,
    SessionStateChanged,
    ShutdownPhase,
    ShutdownStateChanged,
    VisionAnalysisChanged,
)
from core.request_context import InputSource
from core.structured_logging import StructuredRuntimeLog
from dashboard.server import DashboardServer
from services.audio import AudioService
from services.runtime import RuntimeServices


def test_bus_preserves_order_isolates_failure_and_unsubscribes():
    bus = EventBus()
    calls: list[str] = []
    event = InputReceived(
        header=EventHeader.create(),
        source=InputSource.UI,
        modality=InputModality.TEXT,
    )
    first = bus.subscribe(lambda _event: calls.append("first"))

    def fail(_event):
        calls.append("failed")
        raise RuntimeError("observer failed")

    failed = bus.subscribe(fail)
    last = bus.subscribe(lambda _event: calls.append("last"))

    report = bus.publish(event)
    failed.close()
    second_report = bus.publish(event)
    first.close()
    last.close()

    assert calls == ["first", "failed", "last", "first", "last"]
    assert (report.delivered, report.failed) == (2, 1)
    assert (second_report.delivered, second_report.failed) == (2, 0)


def test_subscription_can_close_itself_without_deadlock():
    bus = EventBus()
    event = InputReceived(
        header=EventHeader.create(),
        source=InputSource.UI,
        modality=InputModality.TEXT,
    )
    subscription = None

    def close_self(_event):
        assert subscription is not None
        subscription.close()

    subscription = bus.subscribe(close_self)

    assert bus.publish(event).delivered == 1
    assert bus.publish(event).delivered == 0


def test_concurrent_publish_is_thread_safe():
    bus = EventBus()
    counter = 0
    counter_lock = Lock()

    def count(_event):
        nonlocal counter
        with counter_lock:
            counter += 1

    bus.subscribe(count)

    def publish(index: int):
        return bus.publish(
            InputReceived(
                header=EventHeader.create(observed_at=float(index)),
                source=InputSource.UI,
                modality=InputModality.TEXT,
            )
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        reports = list(pool.map(publish, range(100)))

    assert counter == 100
    assert all(report.delivered == 1 and report.failed == 0 for report in reports)


def test_runtime_owners_emit_correlated_immutable_boundary_facts():
    bus = EventBus()
    events = []
    bus.subscribe(events.append)
    runtime = RuntimeServices(events=bus)
    transport = object()

    runtime.on_transport_connected(transport, now=10.0)
    generation = runtime.audio.begin_interrupt(now=11.0)
    runtime.audio.release_interrupt(generation)
    assert runtime.vision.try_begin_analysis(
        now=12.0,
        cooldown=0.0,
        request_id="request-vision",
    )
    runtime.vision.finish_analysis()
    assert runtime.lifecycle.request_shutdown(
        now=13.0,
        request_id="request-shutdown",
    )
    assert runtime.lifecycle.begin_finish()
    runtime.on_transport_disconnected(transport)

    assert [type(event) for event in events] == [
        SessionStateChanged,
        AudioInterruptionChanged,
        AudioInterruptionChanged,
        VisionAnalysisChanged,
        VisionAnalysisChanged,
        ShutdownStateChanged,
        ShutdownStateChanged,
        SessionStateChanged,
    ]
    assert events[3].header.request_id == "request-vision"
    assert events[4].header.request_id == "request-vision"
    assert events[5].header.request_id == "request-shutdown"
    assert events[6].phase is ShutdownPhase.STARTED
    with pytest.raises(FrozenInstanceError):
        events[0].connected = False


def test_observer_failure_cannot_change_owner_transition():
    class RaisingPublisher:
        def publish(self, _event):
            raise RuntimeError("transport unavailable")

    audio = AudioService(events=RaisingPublisher())

    generation = audio.begin_interrupt(now=1.0)

    assert generation == 1
    assert audio.interrupted


def test_dashboard_events_contain_no_command_token_or_device_data():
    bus = EventBus()
    events = []
    bus.subscribe(events.append)
    server = DashboardServer(events=bus)
    legacy_calls: list[str] = []
    server.set_connect_callback(lambda: legacy_calls.append("connected"))
    server.set_wake_callback(lambda: legacy_calls.append("wake"))

    server._notify_connected(DashboardConnectionKind.QR)
    server._notify_input(InputModality.TEXT)

    assert isinstance(events[0], DashboardConnected)
    assert events[0].connection_kind is DashboardConnectionKind.QR
    assert isinstance(events[1], InputReceived)
    assert events[1].source is InputSource.DASHBOARD_TEXT
    assert legacy_calls == ["connected", "wake"]
    serialized = repr(events)
    for forbidden in ("token", "command", "device", "body"):
        assert forbidden not in serialized.casefold()


def test_structured_log_consumes_allowlisted_runtime_event(tmp_path: Path):
    path = tmp_path / "runtime.jsonl"
    console = io.StringIO()
    runtime_log = StructuredRuntimeLog(path, stream=console)
    event = ShutdownStateChanged(
        header=EventHeader.create(request_id="request-safe", observed_at=25.0),
        phase=ShutdownPhase.REQUESTED,
        shutdown_requests=1,
        deadline=37.0,
    )

    runtime_log.record_runtime_event(event)
    runtime_log.close()

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["event"] == "shutdown_state_changed"
    assert payload["component"] == "lifecycle"
    assert payload["request_id"] == "request-safe"
    assert payload["status"] == "requested"
    assert payload["deadline"] == 37.0
    assert payload["occurred_at_monotonic"] == 25.0
    assert "occurred_at_utc" in payload
    assert payload["event_id"] == event.header.event_id


def test_composition_root_uses_typed_bus_instead_of_dashboard_callback():
    source = Path("main.py").read_text(encoding="utf-8")

    assert "runtime_events = EventBus()" in source
    assert "runtime_log.record_runtime_event" in source
    assert "RuntimeServices(events=self._events)" in source
    assert "self._dashboard_factory(events=self._events)" in source
    assert "set_connect_callback(self._on_phone_connected)" not in source
