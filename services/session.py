"""Single owner for Live transport identity and reconnect metadata."""

from __future__ import annotations

import asyncio
import re
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from threading import RLock
from typing import Any, AsyncIterator

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


class LiveSessionConnectTimeout(TimeoutError):
    """The Live WebSocket did not finish setup inside the local deadline."""


class LiveSessionStalled(TimeoutError):
    """A recognized user turn stopped making server-side progress."""


@asynccontextmanager
async def bounded_live_connect(
    manager: Any,
    *,
    timeout: float,
) -> AsyncIterator[Any]:
    """Bound only WebSocket setup while preserving normal context cleanup."""
    if timeout <= 0:
        raise ValueError("Live connection timeout must be positive")
    try:
        async with asyncio.timeout(timeout):
            session = await manager.__aenter__()
    except TimeoutError as exc:
        raise LiveSessionConnectTimeout(
            f"Live connection setup timed out after {timeout:g} seconds"
        ) from exc

    try:
        yield session
    except BaseException as exc:
        if not await manager.__aexit__(type(exc), exc, exc.__traceback__):
            raise
    else:
        await manager.__aexit__(None, None, None)


def contains_live_session_rotation(error: BaseException) -> bool:
    """Return whether an exception, including a TaskGroup, requests rotation."""
    if isinstance(error, LiveSessionRotationRequested):
        return True
    nested = getattr(error, "exceptions", ())
    return any(
        isinstance(item, BaseException) and contains_live_session_rotation(item)
        for item in nested
    )


def contains_live_session_stall(error: BaseException) -> bool:
    """Return whether a nested task failed the no-progress turn watchdog."""
    if isinstance(error, LiveSessionStalled):
        return True
    nested = getattr(error, "exceptions", ())
    return any(
        isinstance(item, BaseException) and contains_live_session_stall(item)
        for item in nested
    )


def _nested_errors(error: BaseException) -> tuple[BaseException, ...]:
    nested = tuple(
        item
        for item in getattr(error, "exceptions", ())
        if isinstance(item, BaseException)
    )
    if not nested:
        return (error,)
    return tuple(
        child
        for item in nested
        for child in _nested_errors(item)
    )


def live_error_status_codes(error: BaseException) -> tuple[int, ...]:
    """Extract retry-relevant status codes from nested SDK exception groups."""
    codes: set[int] = set()
    for item in _nested_errors(error):
        candidates = [
            getattr(item, "code", None),
            getattr(item, "status_code", None),
        ]
        response = getattr(item, "response", None)
        if response is not None:
            candidates.append(getattr(response, "status_code", None))
        for candidate in candidates:
            if isinstance(candidate, bool):
                continue
            if isinstance(candidate, int):
                code = candidate
            elif isinstance(candidate, str) and candidate.isdigit():
                code = int(candidate)
            else:
                continue
            if 400 <= code <= 599:
                codes.add(code)
        codes.update(
            int(match)
            for match in re.findall(r"(?<!\d)(429|500|502|503|504)(?!\d)", str(item))
        )
    return tuple(sorted(codes))


def live_error_has_marker(
    error: BaseException,
    markers: tuple[str, ...],
) -> bool:
    """Match known transport markers across nested exceptions."""
    normalized = tuple(marker.casefold() for marker in markers)
    return any(
        any(marker in str(item).casefold() for marker in normalized)
        for item in _nested_errors(error)
    )


@dataclass(frozen=True, slots=True)
class LiveReconnectSnapshot:
    failure_streak: int
    last_status_codes: tuple[int, ...]
    last_delay_seconds: float


@dataclass(slots=True)
class LiveReconnectPolicy:
    """Own bounded reconnect pacing so transient failures cannot self-amplify."""

    transient_base_seconds: float = 3.0
    rate_limit_base_seconds: float = 5.0
    max_seconds: float = 30.0
    stable_reset_seconds: float = 30.0
    failure_streak: int = 0
    last_status_codes: tuple[int, ...] = ()
    last_delay_seconds: float = 0.0
    _lock: RLock = field(default_factory=RLock, repr=False)

    def delay_for(
        self,
        error: BaseException,
        *,
        connected_seconds: float,
        stalled_turn: bool = False,
    ) -> float:
        with self._lock:
            if contains_live_session_rotation(error):
                self.failure_streak = 0
                self.last_status_codes = ()
                self.last_delay_seconds = 0.0
                return 0.0
            if connected_seconds >= self.stable_reset_seconds:
                self.failure_streak = 0

            self.failure_streak += 1
            self.last_status_codes = live_error_status_codes(error)
            if stalled_turn:
                delay = 1.0
            else:
                rate_limited = 429 in self.last_status_codes
                base = (
                    self.rate_limit_base_seconds
                    if rate_limited
                    else self.transient_base_seconds
                )
                delay = min(
                    self.max_seconds,
                    base * (2 ** (self.failure_streak - 1)),
                )
            self.last_delay_seconds = float(delay)
            return self.last_delay_seconds

    def snapshot(self) -> LiveReconnectSnapshot:
        with self._lock:
            return LiveReconnectSnapshot(
                failure_streak=self.failure_streak,
                last_status_codes=self.last_status_codes,
                last_delay_seconds=self.last_delay_seconds,
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
    turn_pending: bool
    stalled_turns: int


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
    turn_started_at: float | None = None
    turn_progress_at: float | None = None
    local_work_depth: int = 0
    stalled_turns: int = 0
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
            self.turn_started_at = None
            self.turn_progress_at = None
            self.local_work_depth = 0
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

    def expect_remote_activity(self, *, now: float | None = None) -> None:
        observed_at = time.monotonic() if now is None else now
        with self._lock:
            if self.turn_started_at is None:
                self.turn_started_at = observed_at
            self.turn_progress_at = observed_at

    def observe_user_activity(self, *, now: float | None = None) -> None:
        self.expect_remote_activity(now=now)

    def observe_remote_activity(self, *, now: float | None = None) -> None:
        observed_at = time.monotonic() if now is None else now
        with self._lock:
            if self.turn_started_at is not None:
                self.turn_progress_at = observed_at

    def begin_local_work(self) -> None:
        with self._lock:
            self.local_work_depth += 1

    def end_local_work(self, *, now: float | None = None) -> None:
        observed_at = time.monotonic() if now is None else now
        with self._lock:
            self.local_work_depth = max(0, self.local_work_depth - 1)
            if self.local_work_depth == 0 and self.turn_started_at is not None:
                self.turn_progress_at = observed_at

    def complete_turn(self) -> None:
        with self._lock:
            self.turn_started_at = None
            self.turn_progress_at = None
            self.local_work_depth = 0

    def claim_stalled_turn(
        self,
        *,
        timeout: float,
        now: float | None = None,
    ) -> bool:
        if timeout <= 0:
            raise ValueError("Live turn timeout must be positive")
        observed_at = time.monotonic() if now is None else now
        with self._lock:
            if (
                self.turn_started_at is None
                or self.turn_progress_at is None
                or self.local_work_depth > 0
                or observed_at - self.turn_progress_at < timeout
            ):
                return False
            self.stalled_turns += 1
            self.turn_started_at = None
            self.turn_progress_at = None
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
                turn_pending=self.turn_started_at is not None,
                stalled_turns=self.stalled_turns,
            )
