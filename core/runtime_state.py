"""Small, observable runtime-state files shared by JARVIS processes.

The wake detector and the main application are separate processes.  Keeping
their states in separate files avoids write races while still making it clear
which process owns the microphone at any moment.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from threading import RLock
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
STATE_DIR = BASE_DIR / "logs"


class ActivationPhase(str, Enum):
    """Authoritative cross-surface lifecycle for one JARVIS activation."""

    CLOSED = "closed"
    OPENING = "opening"
    OPEN = "open"
    CLOSING = "closing"


@dataclass(frozen=True)
class ActivationSnapshot:
    phase: ActivationPhase
    generation: int
    reason: str
    target_pid: int | None


class ActivationStateOwner:
    """Serialize wake/manual open and every observed process close."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._phase = ActivationPhase.CLOSED
        self._generation = 0
        self._reason = "startup"
        self._target_pid: int | None = None

    def snapshot(self) -> ActivationSnapshot:
        with self._lock:
            return ActivationSnapshot(
                phase=self._phase,
                generation=self._generation,
                reason=self._reason,
                target_pid=self._target_pid,
            )

    def request_open(self, *, reason: str) -> bool:
        with self._lock:
            if self._phase is not ActivationPhase.CLOSED:
                return False
            self._generation += 1
            self._phase = ActivationPhase.OPENING
            self._reason = str(reason)
            self._target_pid = None
            return True

    def mark_open(self, *, target_pid: int, reason: str = "process_started") -> None:
        if int(target_pid) <= 0:
            raise ValueError("target_pid must be positive")
        with self._lock:
            if self._phase not in {ActivationPhase.OPENING, ActivationPhase.OPEN}:
                raise RuntimeError(
                    f"Cannot mark activation open from {self._phase.value}"
                )
            self._phase = ActivationPhase.OPEN
            self._reason = str(reason)
            self._target_pid = int(target_pid)

    def request_close(self, *, reason: str) -> bool:
        with self._lock:
            if self._phase in {ActivationPhase.CLOSED, ActivationPhase.CLOSING}:
                return False
            self._phase = ActivationPhase.CLOSING
            self._reason = str(reason)
            return True

    def mark_closed(self, *, reason: str) -> None:
        with self._lock:
            self._phase = ActivationPhase.CLOSED
            self._reason = str(reason)
            self._target_pid = None

    def reconcile(
        self,
        *,
        running: bool,
        reason: str,
        target_pid: int | None = None,
    ) -> None:
        """Recover from manual launch, crash, shutdown, or a fresh OS boot."""
        with self._lock:
            if not running:
                self._phase = ActivationPhase.CLOSED
                self._reason = str(reason)
                self._target_pid = None
                return
            if target_pid is None or int(target_pid) <= 0:
                raise ValueError("A running activation requires a positive target_pid")
            if self._phase is ActivationPhase.CLOSED:
                self._generation += 1
            self._phase = ActivationPhase.OPEN
            self._reason = str(reason)
            self._target_pid = int(target_pid)


def _fsync_directory(directory: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(directory, flags)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        # Windows and some filesystems do not support directory fsync.
        pass
    finally:
        os.close(descriptor)


def _publish_state(target: Path, content: bytes) -> None:
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())

        decoded = json.loads(temporary_path.read_text(encoding="utf-8"))
        if not isinstance(decoded, dict):
            raise TypeError("Runtime state must be an object")
        os.replace(temporary_path, target)
        temporary_path = None
        _fsync_directory(target.parent)
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass


def update_runtime_state(component: str, state: str, **details: Any) -> None:
    """Atomically publish one component's state without breaking shutdown."""
    safe_component = "".join(
        char for char in str(component).casefold() if char.isalnum() or char in "-_"
    )
    if not safe_component:
        return
    payload = {
        **details,
        "component": safe_component,
        "state": str(state),
        "pid": os.getpid(),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        target = STATE_DIR / f"{safe_component}_status.json"
        content = (
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8")
        _publish_state(target, content)
    except (OSError, UnicodeError, TypeError, ValueError, json.JSONDecodeError):
        # Status reporting must never prevent either voice process from running.
        pass
