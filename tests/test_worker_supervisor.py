from __future__ import annotations

import asyncio
import io
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from actions import browser_control as browser_module
from actions import screen_processor as vision_module
from core.events import EventBus, WorkerPhase, WorkerStateChanged
from core.structured_logging import StructuredRuntimeLog
from services.workers import (
    WorkerSpec,
    WorkerStartError,
    WorkerStopError,
    WorkerSupervisor,
)


class FakeWorker:
    def __init__(self) -> None:
        self.alive = False
        self.responsive = True
        self.starts = 0
        self.stops = 0
        self.fail_start = False
        self.ignore_stop = False
        self.start_delay = 0.0

    def start(self) -> None:
        self.starts += 1
        if self.start_delay:
            time.sleep(self.start_delay)
        if self.fail_start:
            raise RuntimeError("simulated start failure")
        self.alive = True
        self.responsive = True

    def stop(self) -> None:
        self.stops += 1
        if self.ignore_stop:
            raise RuntimeError("simulated blocked cleanup")
        self.alive = False

    def health(self) -> bool:
        return self.alive and self.responsive


def _supervisor(
    worker: FakeWorker,
    *,
    events: EventBus | None = None,
    max_restarts: int = 2,
    backoff: float = 0.0,
    clock=time.monotonic,
) -> WorkerSupervisor:
    supervisor = WorkerSupervisor(
        events=events,
        monitor_interval_seconds=60.0,
        clock=clock,
    )
    supervisor.register(
        WorkerSpec(
            name="test-worker",
            start=worker.start,
            stop=worker.stop,
            health=worker.health,
            max_restarts=max_restarts,
            restart_backoff_seconds=backoff,
        )
    )
    return supervisor


def test_start_cancel_and_close_are_idempotent_and_observable():
    worker = FakeWorker()
    bus = EventBus()
    events: list[WorkerStateChanged] = []
    bus.subscribe(
        lambda event: (
            events.append(event)
            if isinstance(event, WorkerStateChanged)
            else None
        )
    )
    supervisor = _supervisor(worker, events=bus)

    first = supervisor.start("test-worker")
    second = supervisor.start("test-worker")
    stopped = supervisor.cancel("test-worker")
    stopped_again = supervisor.cancel("test-worker")
    report = supervisor.close()
    report_again = supervisor.close()

    assert first.phase is WorkerPhase.RUNNING
    assert second.phase is WorkerPhase.RUNNING
    assert stopped.phase is WorkerPhase.STOPPED
    assert stopped_again.phase is WorkerPhase.STOPPED
    assert worker.starts == 1
    assert worker.stops == 1
    assert report.failed == 0
    assert report_again.stopped == report_again.failed == 0
    assert [event.phase for event in events] == [
        WorkerPhase.STARTING,
        WorkerPhase.RUNNING,
        WorkerPhase.STOPPING,
        WorkerPhase.STOPPED,
    ]


def test_dead_worker_restarts_and_exhausts_its_bounded_budget():
    now = [10.0]
    worker = FakeWorker()
    supervisor = _supervisor(
        worker,
        max_restarts=2,
        backoff=1.0,
        clock=lambda: now[0],
    )
    supervisor.start("test-worker")

    worker.alive = False
    assert supervisor.poll_once()[0].phase is WorkerPhase.DEGRADED
    now[0] += 1.0
    restarted = supervisor.poll_once()[0]
    assert restarted.phase is WorkerPhase.RUNNING
    assert restarted.restarts == 1

    worker.alive = False
    worker.fail_start = True
    supervisor.poll_once()
    now[0] += 1.0
    degraded = supervisor.poll_once()[0]
    assert degraded.phase is WorkerPhase.FAILED
    assert degraded.restarts == 2
    assert degraded.failures == 3

    supervisor.close()


def test_monitor_detects_dead_worker_without_manual_poll():
    worker = FakeWorker()
    supervisor = WorkerSupervisor(monitor_interval_seconds=0.01)
    supervisor.register(
        WorkerSpec(
            name="monitored-worker",
            start=worker.start,
            stop=worker.stop,
            health=worker.health,
            max_restarts=1,
            restart_backoff_seconds=0.0,
        )
    )
    supervisor.start("monitored-worker")
    worker.alive = False

    deadline = time.monotonic() + 1.0
    while worker.starts < 2 and time.monotonic() < deadline:
        time.sleep(0.01)

    assert worker.starts == 2
    assert supervisor.snapshot("monitored-worker").restarts == 1
    supervisor.close()


def test_start_failure_is_typed_and_remains_eligible_for_restart():
    worker = FakeWorker()
    worker.fail_start = True
    supervisor = _supervisor(worker)

    with pytest.raises(WorkerStartError, match="simulated start failure"):
        supervisor.start("test-worker")

    snapshot = supervisor.snapshot("test-worker")
    assert snapshot.phase is WorkerPhase.DEGRADED
    assert snapshot.desired_running
    assert snapshot.failures == 1
    supervisor.close()


def test_worker_error_snapshot_redacts_credentials():
    worker = FakeWorker()

    def fail_with_secret() -> None:
        secret = "AI" + "za" + "A" * 30
        raise RuntimeError("api_" + "key=" + secret)

    supervisor = WorkerSupervisor(monitor_interval_seconds=60.0)
    supervisor.register(
        WorkerSpec(
            name="secret-worker",
            start=fail_with_secret,
            stop=worker.stop,
            health=worker.health,
        )
    )

    with pytest.raises(WorkerStartError):
        supervisor.start("secret-worker")

    error = supervisor.snapshot("secret-worker").last_error
    assert error is not None
    assert "AIza" not in error
    assert "[REDACTED" in error
    supervisor.close()


def test_unresponsive_worker_is_stopped_before_bounded_restart():
    worker = FakeWorker()
    supervisor = _supervisor(worker, backoff=0.0)
    supervisor.start("test-worker")
    worker.responsive = False

    degraded = supervisor.poll_once()[0]
    restarted = supervisor.poll_once()[0]

    assert degraded.phase is WorkerPhase.DEGRADED
    assert restarted.phase is WorkerPhase.RUNNING
    assert restarted.restarts == 1
    assert worker.starts == 2
    assert worker.stops == 1
    supervisor.close()


def test_failed_cleanup_disables_restart_to_avoid_duplicate_worker():
    worker = FakeWorker()
    supervisor = _supervisor(worker, backoff=0.0)
    supervisor.start("test-worker")
    worker.responsive = False
    worker.ignore_stop = True

    failed = supervisor.poll_once()[0]
    supervisor.poll_once()

    assert failed.phase is WorkerPhase.FAILED
    assert not failed.desired_running
    assert worker.starts == 1
    with pytest.raises(WorkerStartError, match="explicit cleanup"):
        supervisor.start("test-worker")
    worker.ignore_stop = False
    worker.stop()
    supervisor.close()


def test_stop_failure_reports_worker_that_would_be_orphaned():
    worker = FakeWorker()
    supervisor = _supervisor(worker)
    supervisor.start("test-worker")
    worker.ignore_stop = True

    with pytest.raises(WorkerStopError, match="did not stop cleanly"):
        supervisor.cancel("test-worker")

    snapshot = supervisor.snapshot("test-worker")
    assert snapshot.phase is WorkerPhase.FAILED
    assert snapshot.healthy
    worker.ignore_stop = False
    worker.stop()
    supervisor.close()


def test_unregister_keeps_failed_worker_observable_until_cleanup_succeeds():
    worker = FakeWorker()
    supervisor = _supervisor(worker)
    supervisor.start("test-worker")
    worker.ignore_stop = True

    with pytest.raises(WorkerStopError):
        supervisor.unregister("test-worker")

    assert supervisor.snapshot("test-worker").phase is WorkerPhase.FAILED
    worker.ignore_stop = False
    removed = supervisor.unregister("test-worker")
    assert removed.phase is WorkerPhase.STOPPED
    assert supervisor.snapshots() == ()
    supervisor.close()


def test_concurrent_start_has_one_owner_and_one_start():
    worker = FakeWorker()
    worker.start_delay = 0.05
    supervisor = _supervisor(worker)

    with ThreadPoolExecutor(max_workers=8) as pool:
        snapshots = list(
            pool.map(lambda _index: supervisor.start("test-worker"), range(8))
        )

    assert worker.starts == 1
    assert any(item.phase is WorkerPhase.RUNNING for item in snapshots)
    assert all(
        item.phase in {WorkerPhase.STARTING, WorkerPhase.RUNNING}
        for item in snapshots
    )
    monitor = supervisor._monitor_thread
    supervisor.close()
    assert monitor is not None
    assert not monitor.is_alive()


def test_worker_event_contains_health_counts_without_payloads():
    worker = FakeWorker()
    bus = EventBus()
    events: list[WorkerStateChanged] = []
    bus.subscribe(
        lambda event: (
            events.append(event)
            if isinstance(event, WorkerStateChanged)
            else None
        )
    )
    supervisor = _supervisor(worker, events=bus)

    supervisor.start("test-worker")
    metadata = events[-1].log_metadata()
    supervisor.close()

    assert metadata["worker"] == "test-worker"
    assert metadata["status"] == "running"
    assert metadata["starts"] == 1
    for forbidden in ("command", "token", "body", "image", "audio"):
        assert forbidden not in repr(metadata).casefold()


def test_structured_log_consumes_allowlisted_worker_health(tmp_path):
    path = tmp_path / "workers.jsonl"
    runtime_log = StructuredRuntimeLog(path, stream=io.StringIO())
    worker = FakeWorker()
    bus = EventBus()
    bus.subscribe(runtime_log.record_runtime_event)
    supervisor = _supervisor(worker, events=bus)

    supervisor.start("test-worker")
    supervisor.close()
    runtime_log.close()

    payloads = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
    running = next(
        payload for payload in payloads if payload["status"] == "running"
    )
    assert running["component"] == "workers"
    assert running["worker"] == "test-worker"
    assert running["healthy"] is True
    assert running["starts"] == 1


def test_browser_event_loop_worker_stops_and_restarts_without_playwright(
    monkeypatch,
):
    session = browser_module._BrowserSession("chrome")

    async def fake_init():
        return None

    monkeypatch.setattr(session, "_async_init", fake_init)

    session.start()
    first_thread = session._thread
    assert session.is_healthy()
    session.stop()
    assert first_thread is not None
    assert not first_thread.is_alive()
    assert not session.is_healthy()

    session.start()
    second_thread = session._thread
    assert second_thread is not first_thread
    assert session.is_healthy()
    session.stop()
    assert second_thread is not None
    assert not second_thread.is_alive()


def test_browser_registry_closes_supervised_worker_without_orphan(
    monkeypatch,
):
    created: list[FakeWorker] = []

    class FakeBrowserWorker(FakeWorker):
        def __init__(self, browser_name: str) -> None:
            super().__init__()
            self.browser_name = browser_name
            created.append(self)

        def is_healthy(self) -> bool:
            return self.health()

    monkeypatch.setattr(browser_module, "_BrowserSession", FakeBrowserWorker)
    registry = browser_module._SessionRegistry()

    registry.get("chrome")
    assert registry.health()[0].phase is WorkerPhase.RUNNING
    assert registry.close_all() == "All browsers closed: chrome"
    assert registry.health() == ()
    assert created[0].stops == 1
    registry.shutdown()


def test_vision_event_loop_worker_cancels_and_joins_without_hardware(
    monkeypatch,
):
    session = vision_module._VisionSession()

    async def fake_session_loop():
        session._ready_evt.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(session, "_session_loop", fake_session_loop)

    session.start(timeout=1.0)
    thread = session._thread
    assert session.is_healthy()
    session.stop(timeout=1.0)
    assert thread is not None
    assert not thread.is_alive()
    assert not session.is_healthy()


def test_composition_root_configures_and_closes_action_workers():
    source = Path("main.py").read_text(encoding="utf-8")

    assert "configure_browser_worker_events(self._events)" in source
    assert "configure_vision_worker_events(self._events)" in source
    assert '("browser", "shutdown_browser_workers")' in source
    assert '("vision", "shutdown_vision_worker")' in source
