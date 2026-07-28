"""Thread-safe owner for microphone and explicit interruption state."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from threading import RLock

from core.live_session import AudioInactivityWatchdog


@dataclass(frozen=True, slots=True)
class AudioSnapshot:
    interrupted: bool
    interrupt_generation: int
    interrupts: int
    microphone_callback_at: float
    microphone_recoveries: int
    sleeping: bool


@dataclass(slots=True)
class AudioService:
    watchdog: AudioInactivityWatchdog = field(
        default_factory=AudioInactivityWatchdog
    )
    interrupted: bool = False
    interrupted_at: float = 0.0
    interrupt_generation: int = 0
    interrupts: int = 0
    microphone_callback_at: float = field(default_factory=time.monotonic)
    microphone_recoveries: int = 0
    _lock: RLock = field(default_factory=RLock, repr=False)

    def begin_interrupt(self, *, now: float | None = None) -> int:
        with self._lock:
            self.interrupt_generation += 1
            self.interrupts += 1
            self.interrupted = True
            self.interrupted_at = time.monotonic() if now is None else now
            return self.interrupt_generation

    def release_interrupt(self, generation: int) -> bool:
        with self._lock:
            if generation != self.interrupt_generation:
                return False
            self.interrupted = False
            self.interrupted_at = 0.0
            return True

    def mark_microphone_callback(self, *, now: float | None = None) -> None:
        with self._lock:
            self.microphone_callback_at = (
                time.monotonic() if now is None else now
            )

    def microphone_stalled(
        self,
        *,
        now: float | None = None,
        threshold: float = 2.0,
    ) -> bool:
        observed_at = time.monotonic() if now is None else now
        with self._lock:
            return observed_at - self.microphone_callback_at > threshold

    def mark_microphone_recovery(self) -> None:
        with self._lock:
            self.microphone_recoveries += 1

    def reset_for_transport(self, *, now: float | None = None) -> None:
        observed_at = time.monotonic() if now is None else now
        with self._lock:
            self.interrupt_generation += 1
            self.interrupted = False
            self.interrupted_at = 0.0
            self.microphone_callback_at = observed_at
            self.watchdog.reset(now=observed_at)

    def snapshot(self) -> AudioSnapshot:
        with self._lock:
            return AudioSnapshot(
                interrupted=self.interrupted,
                interrupt_generation=self.interrupt_generation,
                interrupts=self.interrupts,
                microphone_callback_at=self.microphone_callback_at,
                microphone_recoveries=self.microphone_recoveries,
                sleeping=self.watchdog.sleeping,
            )
