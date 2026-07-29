"""Bounded lifecycle supervision for restartable background workers."""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from threading import Event, RLock, Thread, current_thread

from core.diagnostics import redact_diagnostic_text
from core.events import (
    EventHeader,
    EventPublisher,
    NullEventPublisher,
    WorkerPhase,
    WorkerStateChanged,
    publish_safely,
)

_SAFE_WORKER_NAME = re.compile(r"^[a-zA-Z0-9_.:-]{1,64}$")


class WorkerSupervisorError(RuntimeError):
    """Base error for invalid or failed worker lifecycle transitions."""


class WorkerAlreadyRegisteredError(WorkerSupervisorError):
    pass


class WorkerNotRegisteredError(WorkerSupervisorError):
    pass


class WorkerStartError(WorkerSupervisorError):
    pass


class WorkerStopError(WorkerSupervisorError):
    pass


@dataclass(frozen=True, slots=True)
class WorkerSpec:
    name: str
    start: Callable[[], None]
    stop: Callable[[], None]
    health: Callable[[], bool]
    max_restarts: int = 2
    restart_backoff_seconds: float = 0.25

    def __post_init__(self) -> None:
        if not _SAFE_WORKER_NAME.fullmatch(self.name):
            raise ValueError("Worker name must be a safe non-empty label.")
        if not callable(self.start) or not callable(self.stop):
            raise TypeError("Worker start and stop callbacks must be callable.")
        if not callable(self.health):
            raise TypeError("Worker health callback must be callable.")
        if self.max_restarts < 0:
            raise ValueError("max_restarts cannot be negative.")
        if self.restart_backoff_seconds < 0:
            raise ValueError("restart_backoff_seconds cannot be negative.")


@dataclass(frozen=True, slots=True)
class WorkerHealth:
    name: str
    phase: WorkerPhase
    desired_running: bool
    healthy: bool
    starts: int
    restarts: int
    failures: int
    last_error: str | None
    last_transition_at: float


@dataclass(frozen=True, slots=True)
class WorkerCloseReport:
    stopped: int
    failed: int


@dataclass(slots=True)
class _WorkerRecord:
    spec: WorkerSpec
    phase: WorkerPhase = WorkerPhase.STOPPED
    desired_running: bool = False
    starts: int = 0
    restarts: int = 0
    failures: int = 0
    last_error: str | None = None
    next_restart_at: float = 0.0
    last_transition_at: float = 0.0


class WorkerSupervisor:
    """Monitor callback-backed workers without owning their implementation."""

    def __init__(
        self,
        *,
        events: EventPublisher | None = None,
        monitor_interval_seconds: float = 0.1,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if monitor_interval_seconds <= 0:
            raise ValueError("monitor_interval_seconds must be positive.")
        self._events: EventPublisher = events or NullEventPublisher()
        self._monitor_interval_seconds = monitor_interval_seconds
        self._clock = clock
        self._records: dict[str, _WorkerRecord] = {}
        self._lock = RLock()
        self._poll_lock = RLock()
        self._monitor_stop = Event()
        self._monitor_thread: Thread | None = None
        self._closed = False

    def set_event_publisher(self, events: EventPublisher) -> None:
        if events is None:
            raise TypeError("Event publisher cannot be None.")
        with self._lock:
            self._events = events

    def register(self, spec: WorkerSpec) -> None:
        with self._lock:
            if self._closed:
                raise WorkerSupervisorError("Worker supervisor is closed.")
            if spec.name in self._records:
                raise WorkerAlreadyRegisteredError(
                    f"Worker is already registered: {spec.name}"
                )
            self._records[spec.name] = _WorkerRecord(
                spec=spec,
                last_transition_at=self._clock(),
            )

    def unregister(self, name: str, *, stop: bool = True) -> WorkerHealth:
        if stop:
            snapshot = self.cancel(name)
        else:
            snapshot = self.snapshot(name)
            if snapshot.desired_running or snapshot.healthy:
                raise WorkerStopError(
                    f"Cannot unregister a running worker without stopping it: {name}"
                )
        with self._lock:
            self._records.pop(name, None)
        return snapshot

    def start(self, name: str) -> WorkerHealth:
        record = self._record(name)
        with self._lock:
            if self._closed:
                raise WorkerSupervisorError("Worker supervisor is closed.")
            if record.phase is WorkerPhase.FAILED:
                raise WorkerStartError(
                    f"Worker requires explicit cleanup before restart: {name}"
                )
            if record.desired_running and record.phase in {
                WorkerPhase.STARTING,
                WorkerPhase.RUNNING,
                WorkerPhase.RESTARTING,
            }:
                return self._snapshot_record(record)
            record.desired_running = True
            record.restarts = 0
            record.next_restart_at = 0.0
        self._ensure_monitor()
        return self._attempt_start(record, is_restart=False, raise_on_failure=True)

    def cancel(self, name: str) -> WorkerHealth:
        record = self._record(name)
        with self._lock:
            record.desired_running = False
            record.next_restart_at = 0.0
            if record.phase is WorkerPhase.STOPPED:
                return self._snapshot_record(record, healthy=False)
            event = self._transition(record, WorkerPhase.STOPPING, healthy=False)
        self._publish(event)

        stop_error: str | None = None
        try:
            record.spec.stop()
        except Exception as exc:
            stop_error = self._safe_error(exc)

        healthy, health_error = self._check_health(record)
        if stop_error is None and health_error is not None:
            stop_error = health_error
        with self._lock:
            if stop_error is not None or healthy:
                record.failures += 1
                error = stop_error or "Worker remained healthy after stop."
                event = self._transition(
                    record,
                    WorkerPhase.FAILED,
                    error=error,
                    healthy=healthy,
                )
                snapshot = self._snapshot_record(record, healthy=healthy)
            else:
                event = self._transition(
                    record,
                    WorkerPhase.STOPPED,
                    healthy=False,
                )
                snapshot = self._snapshot_record(record, healthy=False)
        self._publish(event)
        if snapshot.phase is WorkerPhase.FAILED:
            raise WorkerStopError(
                f"Worker did not stop cleanly: {name}: {snapshot.last_error}"
            )
        return snapshot

    def poll_once(self) -> tuple[WorkerHealth, ...]:
        with self._poll_lock:
            with self._lock:
                records = tuple(self._records.values())
            for record in records:
                self._poll_record(record)
            return self.snapshots()

    def snapshot(self, name: str) -> WorkerHealth:
        record = self._record(name)
        healthy, _ = self._check_health(record)
        with self._lock:
            return self._snapshot_record(record, healthy=healthy)

    def snapshots(self) -> tuple[WorkerHealth, ...]:
        with self._lock:
            names = tuple(self._records)
        return tuple(self.snapshot(name) for name in names)

    def close(self) -> WorkerCloseReport:
        with self._lock:
            if self._closed:
                return WorkerCloseReport(stopped=0, failed=0)
            self._closed = True
            names = tuple(self._records)
            monitor = self._monitor_thread
            self._monitor_stop.set()
        if monitor is not None and monitor is not current_thread():
            monitor.join(timeout=max(1.0, self._monitor_interval_seconds * 4))

        stopped = 0
        failed = int(monitor is not None and monitor.is_alive())
        for name in names:
            try:
                before = self.snapshot(name)
                self.cancel(name)
                if before.phase is not WorkerPhase.STOPPED:
                    stopped += 1
            except WorkerStopError:
                failed += 1
        return WorkerCloseReport(stopped=stopped, failed=failed)

    def _record(self, name: str) -> _WorkerRecord:
        with self._lock:
            try:
                return self._records[name]
            except KeyError as exc:
                raise WorkerNotRegisteredError(
                    f"Worker is not registered: {name}"
                ) from exc

    def _attempt_start(
        self,
        record: _WorkerRecord,
        *,
        is_restart: bool,
        raise_on_failure: bool,
    ) -> WorkerHealth:
        exhausted_event: WorkerStateChanged | None = None
        exhausted_snapshot: WorkerHealth | None = None
        with self._lock:
            if not record.desired_running:
                return self._snapshot_record(record, healthy=False)
            if is_restart:
                if record.restarts >= record.spec.max_restarts:
                    exhausted_event = self._transition(
                        record,
                        WorkerPhase.FAILED,
                        error=record.last_error or "Restart budget exhausted.",
                        healthy=False,
                    )
                    exhausted_snapshot = self._snapshot_record(
                        record,
                        healthy=False,
                    )
                else:
                    record.restarts += 1
                    phase = WorkerPhase.RESTARTING
            else:
                phase = WorkerPhase.STARTING
            if exhausted_event is None:
                event = self._transition(record, phase, healthy=False)
            else:
                event = exhausted_event
        if exhausted_event is not None and exhausted_snapshot is not None:
            self._publish(exhausted_event)
            return exhausted_snapshot
        self._publish(event)

        error: str | None = None
        try:
            record.spec.start()
            healthy, health_error = self._check_health(record)
            if not healthy:
                error = health_error or "Worker health check failed after start."
        except Exception as exc:
            healthy = False
            error = self._safe_error(exc)

        if error is not None:
            cleanup_error: str | None = None
            try:
                record.spec.stop()
            except Exception as stop_exc:
                cleanup_error = self._safe_error(stop_exc)
                error = f"{error}; cleanup: {cleanup_error}"
            still_healthy, post_health_error = self._check_health(record)
            if post_health_error is not None:
                cleanup_error = cleanup_error or post_health_error
            with self._lock:
                record.failures += 1
                unsafe_to_restart = cleanup_error is not None or still_healthy
                exhausted = record.restarts >= record.spec.max_restarts
                phase = (
                    WorkerPhase.FAILED
                    if unsafe_to_restart or exhausted
                    else WorkerPhase.DEGRADED
                )
                if unsafe_to_restart:
                    record.desired_running = False
                record.next_restart_at = (
                    self._clock() + record.spec.restart_backoff_seconds
                )
                event = self._transition(
                    record,
                    phase,
                    error=error,
                    healthy=False,
                )
                snapshot = self._snapshot_record(record, healthy=False)
            self._publish(event)
            if raise_on_failure:
                raise WorkerStartError(
                    f"Worker failed to start: {record.spec.name}: {error}"
                )
            return snapshot

        with self._lock:
            record.starts += 1
            record.next_restart_at = 0.0
            event = self._transition(
                record,
                WorkerPhase.RUNNING,
                error=None,
                healthy=True,
            )
            snapshot = self._snapshot_record(record, healthy=True)
        self._publish(event)
        return snapshot

    def _poll_record(self, record: _WorkerRecord) -> None:
        with self._lock:
            if not record.desired_running:
                return
            phase = record.phase

        if phase is WorkerPhase.RUNNING:
            healthy, error = self._check_health(record)
            if healthy:
                return
            stop_error: str | None = None
            try:
                record.spec.stop()
            except Exception as exc:
                stop_error = self._safe_error(exc)
                error = f"{error}; cleanup: {stop_error}" if error else stop_error
            still_healthy, post_health_error = self._check_health(record)
            if post_health_error is not None:
                stop_error = stop_error or post_health_error
            with self._lock:
                record.failures += 1
                unsafe_to_restart = stop_error is not None or still_healthy
                if unsafe_to_restart:
                    record.desired_running = False
                    phase = WorkerPhase.FAILED
                    record.next_restart_at = 0.0
                else:
                    phase = WorkerPhase.DEGRADED
                    record.next_restart_at = (
                        self._clock() + record.spec.restart_backoff_seconds
                    )
                event = self._transition(
                    record,
                    phase,
                    error=error or "Worker health check failed.",
                    healthy=still_healthy,
                )
            self._publish(event)
            return

        if phase is WorkerPhase.DEGRADED:
            with self._lock:
                due = self._clock() >= record.next_restart_at
            if due:
                self._attempt_start(
                    record,
                    is_restart=True,
                    raise_on_failure=False,
                )

    def _ensure_monitor(self) -> None:
        with self._lock:
            if self._monitor_thread and self._monitor_thread.is_alive():
                return
            self._monitor_stop.clear()
            self._monitor_thread = Thread(
                target=self._monitor_loop,
                daemon=True,
                name="JARVIS-WorkerSupervisor",
            )
            self._monitor_thread.start()

    def _monitor_loop(self) -> None:
        while not self._monitor_stop.wait(self._monitor_interval_seconds):
            self.poll_once()

    def _check_health(self, record: _WorkerRecord) -> tuple[bool, str | None]:
        try:
            return bool(record.spec.health()), None
        except Exception as exc:
            return False, self._safe_error(exc)

    def _transition(
        self,
        record: _WorkerRecord,
        phase: WorkerPhase,
        *,
        healthy: bool,
        error: str | None = None,
    ) -> WorkerStateChanged:
        record.phase = phase
        record.last_error = error
        record.last_transition_at = self._clock()
        return WorkerStateChanged(
            header=EventHeader.create(observed_at=record.last_transition_at),
            worker=record.spec.name,
            phase=phase,
            starts=record.starts,
            restarts=record.restarts,
            failures=record.failures,
            healthy=healthy,
        )

    def _snapshot_record(
        self,
        record: _WorkerRecord,
        *,
        healthy: bool | None = None,
    ) -> WorkerHealth:
        if healthy is None:
            healthy = record.phase is WorkerPhase.RUNNING
        return WorkerHealth(
            name=record.spec.name,
            phase=record.phase,
            desired_running=record.desired_running,
            healthy=healthy,
            starts=record.starts,
            restarts=record.restarts,
            failures=record.failures,
            last_error=record.last_error,
            last_transition_at=record.last_transition_at,
        )

    def _publish(self, event: WorkerStateChanged) -> None:
        with self._lock:
            publisher = self._events
        publish_safely(publisher, event)

    @staticmethod
    def _safe_error(exc: BaseException) -> str:
        label = type(exc).__name__
        message = redact_diagnostic_text(str(exc))
        message = message.replace("\r", " ").replace("\n", " ").strip()
        return f"{label}: {message[:240]}" if message else label
