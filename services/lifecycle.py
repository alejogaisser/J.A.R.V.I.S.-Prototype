"""Owner for the farewell-to-shutdown state machine."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from threading import RLock

from core.events import (
    EventHeader,
    EventPublisher,
    NullEventPublisher,
    ShutdownPhase,
    ShutdownStateChanged,
    publish_safely,
)


@dataclass(frozen=True, slots=True)
class LifecycleSnapshot:
    shutdown_requested: bool
    farewell_audio_seen: bool
    playback_drained: bool
    shutdown_started: bool
    shutdown_requests: int
    deadline: float | None


@dataclass(slots=True)
class LifecycleService:
    shutdown_requested: bool = False
    farewell_audio_seen: bool = False
    playback_drained: bool = False
    shutdown_started: bool = False
    shutdown_requests: int = 0
    deadline: float | None = None
    events: EventPublisher = field(default_factory=NullEventPublisher, repr=False)
    _request_id: str | None = field(default=None, repr=False)
    _lock: RLock = field(default_factory=RLock, repr=False)

    def request_shutdown(
        self,
        *,
        now: float | None = None,
        fallback_seconds: float = 12.0,
        request_id: str | None = None,
    ) -> bool:
        observed_at = time.monotonic() if now is None else now
        with self._lock:
            if self.shutdown_requested or self.shutdown_started:
                return False
            self.shutdown_requested = True
            self.farewell_audio_seen = False
            self.playback_drained = False
            self.shutdown_requests += 1
            self.deadline = observed_at + fallback_seconds
            self._request_id = request_id
            event = ShutdownStateChanged(
                header=EventHeader.create(
                    request_id=request_id,
                    observed_at=observed_at,
                ),
                phase=ShutdownPhase.REQUESTED,
                shutdown_requests=self.shutdown_requests,
                deadline=self.deadline,
            )
        publish_safely(self.events, event)
        return True

    def observe_farewell_audio(self) -> None:
        with self._lock:
            if self.shutdown_requested:
                self.farewell_audio_seen = True

    def observe_playback_drained(self) -> None:
        with self._lock:
            if self.shutdown_requested:
                self.playback_drained = True

    def ready_to_finish(self, *, now: float | None = None) -> bool:
        observed_at = time.monotonic() if now is None else now
        with self._lock:
            if not self.shutdown_requested or self.shutdown_started:
                return False
            farewell_complete = (
                self.farewell_audio_seen and self.playback_drained
            )
            deadline_reached = (
                self.deadline is not None and observed_at >= self.deadline
            )
            return farewell_complete or deadline_reached

    def begin_finish(self) -> bool:
        with self._lock:
            if not self.shutdown_requested or self.shutdown_started:
                return False
            self.shutdown_started = True
            self.shutdown_requested = False
            event = ShutdownStateChanged(
                header=EventHeader.create(request_id=self._request_id),
                phase=ShutdownPhase.STARTED,
                shutdown_requests=self.shutdown_requests,
                deadline=self.deadline,
            )
        publish_safely(self.events, event)
        return True

    def snapshot(self) -> LifecycleSnapshot:
        with self._lock:
            return LifecycleSnapshot(
                shutdown_requested=self.shutdown_requested,
                farewell_audio_seen=self.farewell_audio_seen,
                playback_drained=self.playback_drained,
                shutdown_started=self.shutdown_started,
                shutdown_requests=self.shutdown_requests,
                deadline=self.deadline,
            )
