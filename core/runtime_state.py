"""Small, observable runtime-state files shared by JARVIS processes.

The wake detector and the main application are separate processes.  Keeping
their states in separate files avoids write races while still making it clear
which process owns the microphone at any moment.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent.parent
STATE_DIR = BASE_DIR / "logs"


def update_runtime_state(component: str, state: str, **details: Any) -> None:
    """Atomically publish one component's state without breaking shutdown."""
    safe_component = "".join(
        char for char in str(component).casefold() if char.isalnum() or char in "-_"
    )
    if not safe_component:
        return
    payload = {
        "component": safe_component,
        "state": str(state),
        "pid": os.getpid(),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        **details,
    }
    try:
        STATE_DIR.mkdir(exist_ok=True)
        target = STATE_DIR / f"{safe_component}_status.json"
        temporary = target.with_suffix(f".{os.getpid()}.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(target)
    except OSError:
        # Status reporting must never prevent either voice process from running.
        pass
