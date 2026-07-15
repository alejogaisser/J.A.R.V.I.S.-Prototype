from __future__ import annotations

import json
from pathlib import Path

from .models import PermissionLevel


DEFAULT_PREFERENCES = {
    "system_status": PermissionLevel.FREE,
    "send_message": PermissionLevel.CONFIRM_ALWAYS,
    "dev_agent": PermissionLevel.CONFIRM_ALWAYS,
}


class PermissionStore:
    """Load versioned user preferences; malformed data fails closed to defaults."""

    VERSION = 1

    def __init__(self, path: str | Path = "config/permissions.json") -> None:
        self.path = Path(path)

    def load(self) -> dict[str, PermissionLevel]:
        preferences = dict(DEFAULT_PREFERENCES)
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if payload.get("version") != self.VERSION or not isinstance(payload.get("tools"), dict):
                return preferences
            validated = {}
            for name, raw_level in payload["tools"].items():
                if not isinstance(name, str):
                    raise TypeError("Tool names must be strings")
                validated[name] = PermissionLevel.parse(raw_level)
            preferences.update(validated)
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            pass
        return preferences

    def save(self, preferences: dict[str, PermissionLevel | str]) -> None:
        tools = {name: PermissionLevel.parse(level).label for name, level in preferences.items()}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"version": self.VERSION, "tools": tools}, indent=2) + "\n",
            encoding="utf-8",
        )
