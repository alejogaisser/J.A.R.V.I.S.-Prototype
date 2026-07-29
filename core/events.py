"""Typed, synchronous events for facts that cross JARVIS boundaries."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from threading import RLock
from typing import Callable, Mapping, Protocol, TypeAlias
from uuid import uuid4

from .request_context import InputSource

_SAFE_CORRELATION_ID = re.compile(r"^[a-zA-Z0-9_.:-]{1,128}$")


def _safe_correlation_id(value: str | None) -> str | None:
    candidate = str(value or "").strip()
    return candidate if _SAFE_CORRELATION_ID.fullmatch(candidate) else None


@dataclass(frozen=True, slots=True)
class EventHeader:
    event_id: str
    occurred_at_utc: str
    occurred_at_monotonic: float
    request_id: str | None = None

    @classmethod
    def create(
        cls,
        *,
        request_id: str | None = None,
        observed_at: float | None = None,
    ) -> "EventHeader":
        return cls(
            event_id=uuid4().hex,
            occurred_at_utc=datetime.now(timezone.utc).isoformat(),
            occurred_at_monotonic=(
                time.monotonic() if observed_at is None else float(observed_at)
            ),
            request_id=_safe_correlation_id(request_id),
        )


def _event_metadata(
    header: EventHeader,
    values: Mapping[str, object],
) -> Mapping[str, object]:
    return {
        "event_id": header.event_id,
        "occurred_at_utc": header.occurred_at_utc,
        "occurred_at_monotonic": header.occurred_at_monotonic,
        **values,
    }


class ShutdownPhase(str, Enum):
    REQUESTED = "requested"
    STARTED = "started"


class DashboardConnectionKind(str, Enum):
    PIN = "pin"
    QR = "qr"
    KNOWN_DEVICE = "known_device"


class InputModality(str, Enum):
    TEXT = "text"
    WAKE = "wake"


class WorkerPhase(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    DEGRADED = "degraded"
    RESTARTING = "restarting"
    STOPPING = "stopping"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class SessionStateChanged:
    header: EventHeader
    connected: bool
    generation: int
    connections: int
    reconnects: int
    outcome: str

    @property
    def event_name(self) -> str:
        return "session_state_changed"

    @property
    def component(self) -> str:
        return "session"

    def log_metadata(self) -> Mapping[str, object]:
        return _event_metadata(
            self.header,
            {
                "connected": self.connected,
                "generation": self.generation,
                "connections": self.connections,
                "reconnects": self.reconnects,
                "status": self.outcome,
            },
        )


@dataclass(frozen=True, slots=True)
class AudioInterruptionChanged:
    header: EventHeader
    interrupted: bool
    generation: int
    interrupts: int
    reason: str

    @property
    def event_name(self) -> str:
        return "audio_interruption_changed"

    @property
    def component(self) -> str:
        return "audio"

    def log_metadata(self) -> Mapping[str, object]:
        return _event_metadata(
            self.header,
            {
                "interrupted": self.interrupted,
                "generation": self.generation,
                "interrupts": self.interrupts,
                "reason": self.reason,
            },
        )


@dataclass(frozen=True, slots=True)
class VisionAnalysisChanged:
    header: EventHeader
    busy: bool
    analyses_started: int
    reason: str

    @property
    def event_name(self) -> str:
        return "vision_analysis_changed"

    @property
    def component(self) -> str:
        return "vision"

    def log_metadata(self) -> Mapping[str, object]:
        return _event_metadata(
            self.header,
            {
                "busy": self.busy,
                "analyses_started": self.analyses_started,
                "reason": self.reason,
            },
        )


@dataclass(frozen=True, slots=True)
class ShutdownStateChanged:
    header: EventHeader
    phase: ShutdownPhase
    shutdown_requests: int
    deadline: float | None

    @property
    def event_name(self) -> str:
        return "shutdown_state_changed"

    @property
    def component(self) -> str:
        return "lifecycle"

    def log_metadata(self) -> Mapping[str, object]:
        metadata: dict[str, object] = {
            "status": self.phase.value,
            "shutdown_requests": self.shutdown_requests,
        }
        if self.deadline is not None:
            metadata["deadline"] = self.deadline
        return _event_metadata(self.header, metadata)


@dataclass(frozen=True, slots=True)
class DashboardConnected:
    header: EventHeader
    connection_kind: DashboardConnectionKind

    @property
    def event_name(self) -> str:
        return "dashboard_connected"

    @property
    def component(self) -> str:
        return "dashboard"

    def log_metadata(self) -> Mapping[str, object]:
        return _event_metadata(
            self.header,
            {
                "operation": self.connection_kind.value,
                "status": "connected",
            },
        )


@dataclass(frozen=True, slots=True)
class InputReceived:
    header: EventHeader
    source: InputSource
    modality: InputModality

    @property
    def event_name(self) -> str:
        return "input_received"

    @property
    def component(self) -> str:
        return "input"

    def log_metadata(self) -> Mapping[str, object]:
        return _event_metadata(
            self.header,
            {
                "surface": self.source.value,
                "modality": self.modality.value,
            },
        )


@dataclass(frozen=True, slots=True)
class WorkerStateChanged:
    header: EventHeader
    worker: str
    phase: WorkerPhase
    starts: int
    restarts: int
    failures: int
    healthy: bool

    @property
    def event_name(self) -> str:
        return "worker_state_changed"

    @property
    def component(self) -> str:
        return "workers"

    def log_metadata(self) -> Mapping[str, object]:
        return _event_metadata(
            self.header,
            {
                "worker": self.worker,
                "status": self.phase.value,
                "starts": self.starts,
                "restarts": self.restarts,
                "failures": self.failures,
                "healthy": self.healthy,
            },
        )


RuntimeEvent: TypeAlias = (
    SessionStateChanged
    | AudioInterruptionChanged
    | VisionAnalysisChanged
    | ShutdownStateChanged
    | DashboardConnected
    | InputReceived
    | WorkerStateChanged
)
RuntimeEventHandler: TypeAlias = Callable[[RuntimeEvent], None]
_RUNTIME_EVENT_TYPES = (
    SessionStateChanged,
    AudioInterruptionChanged,
    VisionAnalysisChanged,
    ShutdownStateChanged,
    DashboardConnected,
    InputReceived,
    WorkerStateChanged,
)


@dataclass(frozen=True, slots=True)
class PublishReport:
    delivered: int
    failed: int


class EventPublisher(Protocol):
    def publish(self, event: RuntimeEvent) -> PublishReport: ...


@dataclass(slots=True)
class EventSubscription:
    _bus: EventBus | None = field(repr=False)
    _token: int

    def close(self) -> None:
        bus = self._bus
        if bus is None:
            return
        self._bus = None
        bus._unsubscribe(self._token)

    def __enter__(self) -> "EventSubscription":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


@dataclass(slots=True)
class EventBus:
    """Deliver immutable facts in subscription order without holding its lock."""

    _handlers: dict[int, RuntimeEventHandler] = field(
        default_factory=dict,
        repr=False,
    )
    _next_token: int = 0
    _lock: RLock = field(default_factory=RLock, repr=False)

    def subscribe(self, handler: RuntimeEventHandler) -> EventSubscription:
        if not callable(handler):
            raise TypeError("Event handler must be callable.")
        with self._lock:
            self._next_token += 1
            token = self._next_token
            self._handlers[token] = handler
        return EventSubscription(self, token)

    def publish(self, event: RuntimeEvent) -> PublishReport:
        if not isinstance(event, _RUNTIME_EVENT_TYPES):
            raise TypeError("Unsupported runtime event type.")
        with self._lock:
            handlers = tuple(self._handlers.values())

        delivered = 0
        failed = 0
        for handler in handlers:
            try:
                handler(event)
                delivered += 1
            except Exception:
                failed += 1
        return PublishReport(delivered=delivered, failed=failed)

    def _unsubscribe(self, token: int) -> None:
        with self._lock:
            self._handlers.pop(token, None)


@dataclass(frozen=True, slots=True)
class NullEventPublisher:
    def publish(self, event: RuntimeEvent) -> PublishReport:
        if not isinstance(event, _RUNTIME_EVENT_TYPES):
            raise TypeError("Unsupported runtime event type.")
        return PublishReport(delivered=0, failed=0)


def publish_safely(
    publisher: EventPublisher,
    event: RuntimeEvent,
) -> PublishReport:
    """Keep observers from changing the state transition they observe."""
    try:
        return publisher.publish(event)
    except Exception:
        return PublishReport(delivered=0, failed=1)
