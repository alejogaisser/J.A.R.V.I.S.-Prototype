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
    farewell_audio_at: float | None
    playback_drained: bool
    device_drained: bool
    shutdown_started: bool
    shutdown_requests: int
    deadline: float | None
    completion_deadline: float | None


@dataclass(slots=True)
class LifecycleService:
    shutdown_requested: bool = False
    farewell_audio_seen: bool = False
    farewell_audio_at: float | None = None
    playback_drained: bool = False
    device_drained: bool = False
    shutdown_started: bool = False
    shutdown_requests: int = 0
    deadline: float | None = None
    completion_deadline: float | None = None
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
            self.farewell_audio_at = None
            self.playback_drained = False
            self.device_drained = False
            self.shutdown_requests += 1
            self.deadline = observed_at + fallback_seconds
            self.completion_deadline = None
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

    def observe_farewell_audio(
        self,
        *,
        now: float | None = None,
        completion_timeout_seconds: float = 45.0,
    ) -> None:
        observed_at = time.monotonic() if now is None else now
        with self._lock:
            if self.shutdown_requested and not self.farewell_audio_seen:
                self.farewell_audio_seen = True
                self.farewell_audio_at = observed_at
                self.completion_deadline = (
                    observed_at + completion_timeout_seconds
                )

    def observe_playback_drained(self) -> None:
        with self._lock:
            if self.shutdown_requested:
                self.playback_drained = True

    def observe_device_drained(self) -> None:
        """Record PortAudio's proof that submitted buffers finished playing."""
        with self._lock:
            if self.shutdown_started:
                self.device_drained = True

    def ready_to_finish(self, *, now: float | None = None) -> bool:
        observed_at = time.monotonic() if now is None else now
        with self._lock:
            if not self.shutdown_requested or self.shutdown_started:
                return False
            if self.farewell_audio_seen:
                if self.playback_drained:
                    return True
                return (
                    self.completion_deadline is not None
                    and observed_at >= self.completion_deadline
                )
            return self.deadline is not None and observed_at >= self.deadline

    def active_deadline(self) -> float | None:
        """Return the current emergency deadline without changing state."""
        with self._lock:
            if not self.shutdown_requested or self.shutdown_started:
                return None
            if self.farewell_audio_seen and not self.playback_drained:
                return self.completion_deadline
            return self.deadline

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
                farewell_audio_at=self.farewell_audio_at,
                playback_drained=self.playback_drained,
                device_drained=self.device_drained,
                shutdown_started=self.shutdown_started,
                shutdown_requests=self.shutdown_requests,
                deadline=self.deadline,
                completion_deadline=self.completion_deadline,
            )
