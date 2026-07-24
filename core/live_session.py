"""State that survives reconnects of the Gemini Live transport."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Any


def pcm16_rms(data: bytes) -> float:
    """Return the RMS level of little-endian signed 16-bit PCM audio."""
    if len(data) < 2:
        return 0.0
    samples = memoryview(data[: len(data) - (len(data) % 2)]).cast("h")
    if not samples:
        return 0.0
    return (sum(int(sample) ** 2 for sample in samples) / len(samples)) ** 0.5


@dataclass(slots=True)
class AudioInactivityWatchdog:
    """Detect mute/silence without touching the conversation session.

    ``sleep`` means the remote audio stream should receive ``audio_stream_end``.
    A later ``wake`` means that the current PCM block can reopen that same stream,
    preserving Gemini's conversation context and JARVIS's in-memory state.
    """

    idle_seconds: float = 12.0
    voice_rms_threshold: float = 350.0
    sleeping: bool = False
    last_voice_at: float = field(default_factory=time.monotonic)
    _lock: Lock = field(default_factory=Lock, repr=False)

    def observe_pcm(self, data: bytes, *, active: bool, now: float | None = None) -> str:
        """Return ``voice``, ``sleep``, ``sleeping``, ``wake`` or ``quiet``."""
        observed_at = time.monotonic() if now is None else now
        with self._lock:
            if not active:
                # App-level Toggle-to-Speak is deliberate standby, not a failed
                # microphone, so it must not arm an automatic recovery.
                self.last_voice_at = observed_at
                self.sleeping = False
                return "quiet"

            if pcm16_rms(data) >= self.voice_rms_threshold:
                self.last_voice_at = observed_at
                if self.sleeping:
                    self.sleeping = False
                    return "wake"
                return "voice"

            if not self.sleeping and observed_at - self.last_voice_at >= self.idle_seconds:
                self.sleeping = True
                return "sleep"
            if self.sleeping:
                return "sleeping"
            return "quiet"

    def reset(self, *, now: float | None = None) -> None:
        """Reset transient audio timing after a real transport reconnect."""
        with self._lock:
            self.sleeping = False
            self.last_voice_at = time.monotonic() if now is None else now


@dataclass(slots=True)
class LiveSessionState:
    """Retain the latest safe server handle across websocket reconnects.

    Gemini can emit updates while a session is active.  Only handles explicitly
    marked resumable are safe to use for the next connection.  A temporary
    ``resumable=False`` update must not erase the last known-good checkpoint.
    """

    resumption_handle: str | None = None
    updates_seen: int = 0

    @property
    def can_resume(self) -> bool:
        return bool(self.resumption_handle)

    def observe_resumption_update(self, update: Any) -> bool:
        """Store a new resumable checkpoint and report whether it changed."""
        if update is None:
            return False
        self.updates_seen += 1
        if getattr(update, "resumable", None) is not True:
            return False
        handle = getattr(update, "new_handle", None)
        if not isinstance(handle, str) or not handle.strip():
            return False
        changed = handle != self.resumption_handle
        self.resumption_handle = handle
        return changed
