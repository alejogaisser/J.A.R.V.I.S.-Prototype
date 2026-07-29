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
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
STATE_DIR = BASE_DIR / "logs"


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
