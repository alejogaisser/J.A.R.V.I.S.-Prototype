"""Central, file-backed catalog of reusable JARVIS routine previews."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from threading import Lock

from core.clock import local_now

BASE = (
    Path(sys.executable).parent
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parent.parent
)
SCRIPT_MEMORY_PATH = BASE / "memory" / "scripts.json"
_lock = Lock()


def _key(name: str) -> str:
    return (
        re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_")
        or "unnamed_routine"
    )


def load_scripts() -> dict:
    try:
        data = json.loads(SCRIPT_MEMORY_PATH.read_text(encoding="utf-8"))
        if data.get("version") == 2 and isinstance(data.get("scripts"), dict):
            return data
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass
    return {"version": 2, "scripts": {}}


def register_script(
    name: str,
    code: str,
    purpose: str,
    language: str = "python",
) -> dict:
    data = load_scripts()
    entry = {
        "name": name.strip(),
        "purpose": purpose.strip()[:600],
        "language": language.lower().strip(),
        "code": code,
        "updated": local_now().isoformat(),
    }
    data["scripts"][_key(name)] = entry
    SCRIPT_MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        SCRIPT_MEMORY_PATH.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return entry


def get_script(name: str) -> dict | None:
    return load_scripts()["scripts"].get(_key(name))


def is_registered_script(name: str) -> bool:
    return get_script(name) is not None


def run_script(name: str, timeout: int = 30) -> str:
    """Block legacy raw-code execution until routines become declarative.

    The caller still passes through ToolRegistry and PermissionPolicy, but an
    approval cannot turn arbitrary stored source into safely sandboxed code.
    """
    del timeout
    entry = get_script(name)
    if not entry:
        return f"Unknown routine: {name}"
    return (
        f"Routine '{entry['name']}' is stored as a preview but execution is blocked. "
        "Migrate it to declarative allowlisted actions before running it."
    )


def format_scripts_for_prompt(limit: int = 25) -> str:
    entries = list(load_scripts()["scripts"].values())[-limit:]
    if not entries:
        return ""
    return (
        "[KNOWN ROUTINE PREVIEWS — stored internally; raw execution is blocked]\n"
        + "\n".join(
            f"- {entry['name']}: {entry['purpose']} | "
            f"language={entry['language']}"
            for entry in entries
        )
        + "\n"
    )
