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

    VERSION = 2

    def __init__(self, path: str | Path = "config/permissions.json") -> None:
        self.path = Path(path)

    def load(self) -> dict[str, PermissionLevel]:
        preferences = dict(DEFAULT_PREFERENCES)
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if payload.get("version") not in {1, self.VERSION} or not isinstance(payload.get("tools"), dict):
                return preferences
            validated = {}
            for name, raw_level in payload["tools"].items():
                if not isinstance(name, str):
                    raise TypeError("Tool names must be strings")
                validated[name] = PermissionLevel.parse(raw_level)
            preferences.update(validated)
            operations = payload.get("operations", {})
            if isinstance(operations, dict):
                for tool_name, tool_operations in operations.items():
                    if not isinstance(tool_name, str) or not isinstance(tool_operations, dict):
                        raise TypeError("Operation preferences must be nested objects")
                    for operation, raw_level in tool_operations.items():
                        preferences[f"{tool_name}:{operation}"] = PermissionLevel.parse(raw_level)
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            pass
        return preferences

    def save(self, preferences: dict[str, PermissionLevel | str]) -> None:
        tools = {}
        operations: dict[str, dict[str, str]] = {}
        for name, level in preferences.items():
            parsed = PermissionLevel.parse(level).label
            if ":" in name:
                tool_name, operation = name.split(":", 1)
                operations.setdefault(tool_name, {})[operation] = parsed
            else:
                tools[name] = parsed
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(
                {"version": self.VERSION, "tools": tools, "operations": operations},
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )
