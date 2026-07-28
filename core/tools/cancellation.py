"""Thread-safe cooperative cancellation primitives for tool handlers."""

from __future__ import annotations

import threading
from collections.abc import Callable

from .definitions import EffectStatus, RollbackStatus, VerificationStatus


class ToolCancelled(Exception):
    """A handler acknowledged cancellation and described its observed state."""

    def __init__(
        self,
        message: str = "Tool execution cancelled.",
        *,
        effect_status: EffectStatus = EffectStatus.UNKNOWN,
        verification_status: VerificationStatus = VerificationStatus.UNKNOWN,
        rollback_status: RollbackStatus = RollbackStatus.UNKNOWN,
        evidence: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.effect_status = effect_status
        self.verification_status = verification_status
        self.rollback_status = rollback_status
        self.evidence = tuple(evidence)


class CancellationToken:
    """One-shot signal shared safely between the asyncio loop and workers."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._reason: str | None = None
        self._callbacks: list[Callable[[str], None]] = []

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> str | None:
        with self._lock:
            return self._reason

    def wait(self, timeout: float | None = None) -> bool:
        return self._event.wait(timeout)

    def cancel(self, reason: str = "cancelled") -> bool:
        with self._lock:
            if self._event.is_set():
                return False
            self._reason = str(reason)
            callbacks = tuple(self._callbacks)
            self._callbacks.clear()
            self._event.set()
        for callback in callbacks:
            try:
                callback(self._reason)
            except Exception:
                pass
        return True

    def add_callback(self, callback: Callable[[str], None]) -> None:
        with self._lock:
            if not self._event.is_set():
                self._callbacks.append(callback)
                return
            reason = self._reason or "cancelled"
        try:
            callback(reason)
        except Exception:
            pass

    def raise_if_cancelled(
        self,
        *,
        effect_status: EffectStatus = EffectStatus.UNKNOWN,
        verification_status: VerificationStatus = VerificationStatus.NOT_REQUESTED,
        rollback_status: RollbackStatus = RollbackStatus.UNKNOWN,
        evidence: tuple[str, ...] = (),
    ) -> None:
        if self.cancelled:
            raise ToolCancelled(
                f"Tool execution cancelled: {self.reason or 'cancelled'}.",
                effect_status=effect_status,
                verification_status=verification_status,
                rollback_status=rollback_status,
                evidence=evidence,
            )
