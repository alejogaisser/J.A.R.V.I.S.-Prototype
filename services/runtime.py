"""Composition facade for session, audio, vision and lifecycle owners."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.events import EventBus, EventPublisher

from .audio import AudioService, AudioSnapshot
from .lifecycle import LifecycleService, LifecycleSnapshot
from .session import SessionService, SessionSnapshot
from .vision import VisionService, VisionSnapshot


@dataclass(frozen=True, slots=True)
class RuntimeSnapshot:
    session: SessionSnapshot
    audio: AudioSnapshot
    vision: VisionSnapshot
    lifecycle: LifecycleSnapshot


@dataclass(slots=True)
class RuntimeServices:
    events: EventPublisher = field(default_factory=EventBus, repr=False)
    session: SessionService = field(init=False)
    audio: AudioService = field(init=False)
    vision: VisionService = field(init=False)
    lifecycle: LifecycleService = field(init=False)

    def __post_init__(self) -> None:
        self.session = SessionService(events=self.events)
        self.audio = AudioService(events=self.events)
        self.vision = VisionService(events=self.events)
        self.lifecycle = LifecycleService(events=self.events)

    def on_transport_connected(
        self,
        transport: Any,
        *,
        now: float | None = None,
    ) -> str:
        outcome = self.session.bind(transport, now=now)
        self.audio.reset_for_transport(now=now)
        self.vision.reset_for_transport()
        return outcome

    def on_transport_disconnected(self, transport: Any | None = None) -> bool:
        return self.session.unbind(transport)

    def snapshot(self) -> RuntimeSnapshot:
        return RuntimeSnapshot(
            session=self.session.snapshot(),
            audio=self.audio.snapshot(),
            vision=self.vision.snapshot(),
            lifecycle=self.lifecycle.snapshot(),
        )
