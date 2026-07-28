"""Single owner for Live transport identity and reconnect metadata."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from threading import RLock
from typing import Any

from core.live_session import LiveSessionState


@dataclass(frozen=True, slots=True)
class SessionSnapshot:
    connected: bool
    generation: int
    connections: int
    reconnects: int
    connected_at: float | None
    can_resume: bool
    resumption_updates: int


@dataclass(slots=True)
class SessionService:
    transport: Any = None
    resumption: LiveSessionState = field(default_factory=LiveSessionState)
    generation: int = 0
    connections: int = 0
    reconnects: int = 0
    connected_at: float | None = None
    _lock: RLock = field(default_factory=RLock, repr=False)

    @property
    def ever_connected(self) -> bool:
        with self._lock:
            return self.connections > 0

    def bind(self, transport: Any, *, now: float | None = None) -> str:
        if transport is None:
            raise ValueError("Live transport cannot be None")
        with self._lock:
            if self.transport is not None and self.transport is not transport:
                raise RuntimeError("Live transport owner is already bound")
            if self.transport is transport:
                return "online" if self.connections == 1 else "restored"
            self.transport = transport
            self.generation += 1
            self.connections += 1
            self.reconnects = max(0, self.connections - 1)
            self.connected_at = time.monotonic() if now is None else now
            return "online" if self.connections == 1 else "restored"

    def unbind(self, transport: Any | None = None) -> bool:
        with self._lock:
            if self.transport is None:
                return False
            if transport is not None and self.transport is not transport:
                return False
            self.transport = None
            self.connected_at = None
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
            )
