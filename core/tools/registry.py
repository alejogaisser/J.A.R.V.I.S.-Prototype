"""Registration, lookup and availability checks for trusted tools."""

from __future__ import annotations

import platform
from collections.abc import Iterable

from .definitions import ToolDefinition


def current_platform() -> str:
    value = platform.system().lower()
    return "macos" if value == "darwin" else value


class ToolRegistry:
    def __init__(self, definitions: Iterable[ToolDefinition] = ()) -> None:
        self._tools: dict[str, ToolDefinition] = {}
        for definition in definitions:
            self.register(definition)

    def register(self, definition: ToolDefinition) -> ToolDefinition:
        if definition.name in self._tools:
            raise ValueError(f"Duplicate tool name: {definition.name}")
        self._tools[definition.name] = definition
        return definition

    def get(self, name: str) -> ToolDefinition:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError(f"Unknown tool: {name}") from exc

    def enabled(self, platform_name: str | None = None) -> tuple[ToolDefinition, ...]:
        target = platform_name or current_platform()
        return tuple(
            tool for tool in self._tools.values()
            if tool.enabled and target in tool.platforms
        )

    def declarations(self, platform_name: str | None = None, predicate=None) -> list[dict]:
        tools = self.enabled(platform_name)
        return [tool.declaration() for tool in tools if predicate is None or predicate(tool)]

    def validate_for_execution(
        self, name: str, platform_name: str | None = None
    ) -> ToolDefinition:
        tool = self.get(name)
        if not tool.enabled:
            raise PermissionError(f"Tool is disabled: {name}")
        target = platform_name or current_platform()
        if target not in tool.platforms:
            raise RuntimeError(f"Tool '{name}' is not available on {target}")
        return tool

    @staticmethod
    def validate_arguments(tool: ToolDefinition, args: dict) -> None:
        if not isinstance(args, dict):
            raise TypeError(f"Arguments for '{tool.name}' must be an object")
        schema = tool.parameters or {}
        required = schema.get("required", [])
        missing = [key for key in required if key not in args or args[key] is None]
        if missing:
            raise ValueError(
                f"Tool '{tool.name}' is missing required arguments: {', '.join(missing)}"
            )
        properties = schema.get("properties", {})
        expected_types = {
            "STRING": str,
            "INTEGER": int,
            "NUMBER": (int, float),
            "BOOLEAN": bool,
            "ARRAY": list,
            "OBJECT": dict,
        }
        for key, value in args.items():
            expected = expected_types.get(properties.get(key, {}).get("type"))
            if expected and not isinstance(value, expected):
                raise TypeError(f"Argument '{key}' for '{tool.name}' has the wrong type")

    def __len__(self) -> int:
        return len(self._tools)
