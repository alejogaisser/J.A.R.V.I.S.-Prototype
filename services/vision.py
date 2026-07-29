"""Owner for vision cooldown and camera-frame backpressure."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock

from core.events import (
    EventHeader,
    EventPublisher,
    NullEventPublisher,
    VisionAnalysisChanged,
    publish_safely,
)


@dataclass(frozen=True, slots=True)
class VisionSnapshot:
    busy: bool
    last_analysis_at: float
    analyses_started: int
    camera_frame_pending: bool
    camera_generation: int
    frames_accepted: int
    frames_dropped: int


@dataclass(slots=True)
class VisionService:
    busy: bool = False
    last_analysis_at: float = 0.0
    analyses_started: int = 0
    camera_frame_pending: bool = False
    camera_generation: int = 0
    frames_accepted: int = 0
    frames_dropped: int = 0
    events: EventPublisher = field(default_factory=NullEventPublisher, repr=False)
    _analysis_request_id: str | None = field(default=None, repr=False)
    _lock: RLock = field(default_factory=RLock, repr=False)

    def try_begin_analysis(
        self,
        *,
        now: float,
        cooldown: float,
        request_id: str | None = None,
    ) -> bool:
        with self._lock:
            if self.busy or now - self.last_analysis_at < cooldown:
                return False
            self.busy = True
            self.last_analysis_at = now
            self.analyses_started += 1
            self._analysis_request_id = request_id
            event = VisionAnalysisChanged(
                header=EventHeader.create(request_id=request_id, observed_at=now),
                busy=True,
                analyses_started=self.analyses_started,
                reason="analysis_started",
            )
        publish_safely(self.events, event)
        return True

    def cooldown_remaining(self, *, now: float, cooldown: float) -> float:
        with self._lock:
            return max(0.0, cooldown - (now - self.last_analysis_at))

    def finish_analysis(self) -> None:
        with self._lock:
            if not self.busy:
                return
            self.busy = False
            request_id = self._analysis_request_id
            self._analysis_request_id = None
            event = VisionAnalysisChanged(
                header=EventHeader.create(request_id=request_id),
                busy=False,
                analyses_started=self.analyses_started,
                reason="analysis_finished",
            )
        publish_safely(self.events, event)

    def try_queue_camera_frame(self) -> int | None:
        with self._lock:
            if self.camera_frame_pending:
                self.frames_dropped += 1
                return None
            self.camera_generation += 1
            self.camera_frame_pending = True
            self.frames_accepted += 1
            return self.camera_generation

    def finish_camera_frame(self, generation: int | None = None) -> bool:
        with self._lock:
            if (
                generation is not None
                and generation != self.camera_generation
            ):
                return False
            if generation is None:
                self.camera_generation += 1
            self.camera_frame_pending = False
            return True

    def reset_for_transport(self) -> None:
        with self._lock:
            was_busy = self.busy
            request_id = self._analysis_request_id
            self.busy = False
            self.last_analysis_at = 0.0
            self._analysis_request_id = None
            self.camera_generation += 1
            self.camera_frame_pending = False
            event = VisionAnalysisChanged(
                header=EventHeader.create(request_id=request_id),
                busy=False,
                analyses_started=self.analyses_started,
                reason="transport_reset",
            )
        if was_busy:
            publish_safely(self.events, event)

    def snapshot(self) -> VisionSnapshot:
        with self._lock:
            return VisionSnapshot(
                busy=self.busy,
                last_analysis_at=self.last_analysis_at,
                analyses_started=self.analyses_started,
                camera_frame_pending=self.camera_frame_pending,
                camera_generation=self.camera_generation,
                frames_accepted=self.frames_accepted,
                frames_dropped=self.frames_dropped,
            )
