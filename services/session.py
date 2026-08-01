"""Single owner for Live transport identity and reconnect metadata."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from threading import RLock
from typing import Any

from core.events import (
    EventHeader,
    EventPublisher,
    NullEventPublisher,
    SessionStateChanged,
    publish_safely,
)
from core.live_session import LiveSessionState


class LiveSessionRotationRequested(RuntimeError):
    """Internal control signal used to close a Live transport after GoAway."""


def contains_live_session_rotation(error: BaseException) -> bool:
    """Return whether an exception, including a TaskGroup, requests rotation."""
    if isinstance(error, LiveSessionRotationRequested):
        return True
    nested = getattr(error, "exceptions", ())
    return any(
        isinstance(item, BaseException) and contains_live_session_rotation(item)
        for item in nested
    )


@dataclass(frozen=True, slots=True)
class SessionSnapshot:
    connected: bool
    generation: int
    connections: int
    reconnects: int
    connected_at: float | None
    can_resume: bool
    resumption_updates: int
    rotation_requested: bool
    rotations: int


@dataclass(slots=True)
class SessionService:
    transport: Any = None
    resumption: LiveSessionState = field(default_factory=LiveSessionState)
    generation: int = 0
    connections: int = 0
    reconnects: int = 0
    connected_at: float | None = None
    rotation_requested: bool = False
    rotations: int = 0
    events: EventPublisher = field(default_factory=NullEventPublisher, repr=False)
    _lock: RLock = field(default_factory=RLock, repr=False)

    @property
    def ever_connected(self) -> bool:
        with self._lock:
            return self.connections > 0

    def bind(self, transport: Any, *, now: float | None = None) -> str:
        if transport is None:
            raise ValueError("Live transport cannot be None")
        observed_at = time.monotonic() if now is None else now
        with self._lock:
            if self.transport is not None and self.transport is not transport:
                raise RuntimeError("Live transport owner is already bound")
            if self.transport is transport:
                return "online" if self.connections == 1 else "restored"
            self.transport = transport
            self.generation += 1
            self.connections += 1
            self.reconnects = max(0, self.connections - 1)
            self.connected_at = observed_at
            self.rotation_requested = False
            outcome = "online" if self.connections == 1 else "restored"
            event = SessionStateChanged(
                header=EventHeader.create(observed_at=observed_at),
                connected=True,
                generation=self.generation,
                connections=self.connections,
                reconnects=self.reconnects,
                outcome=outcome,
            )
        publish_safely(self.events, event)
        return outcome

    def request_rotation(self, transport: Any) -> bool:
        """Record one server-requested rotation for the current transport."""
        with self._lock:
            if self.transport is not transport or self.rotation_requested:
                return False
            self.rotation_requested = True
            self.rotations += 1
            return True

    def unbind(self, transport: Any | None = None) -> bool:
        with self._lock:
            if self.transport is None:
                return False
            if transport is not None and self.transport is not transport:
                return False
            self.transport = None
            self.connected_at = None
            event = SessionStateChanged(
                header=EventHeader.create(),
                connected=False,
                generation=self.generation,
                connections=self.connections,
                reconnects=self.reconnects,
                outcome="disconnected",
            )
        publish_safely(self.events, event)
        return True

    def snapshot(self) -> SessionSnapshot:
        with self._lock:
            return SessionSnapshot(
                connected=self.transport is not None,
                generation=self.generation,
                connections=self.connections,
                reconnects=self.reconnects,
                connected_at=self.connected_at,
                can_resume=self.resumption.can_resume,
                resumption_updates=self.resumption.updates_seen,
                rotation_requested=self.rotation_requested,
                rotations=self.rotations,
            )
