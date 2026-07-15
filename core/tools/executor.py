"""Common asynchronous execution path for conventional tools."""

from __future__ import annotations

import asyncio
import inspect

from .definitions import ToolResult
from .registry import ToolRegistry


class ToolExecutor:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    async def execute(self, name: str, args: dict) -> ToolResult:
        try:
            definition = self.registry.validate_for_execution(name)
            self.registry.validate_arguments(definition, args)
        except (KeyError, PermissionError, RuntimeError, TypeError, ValueError) as exc:
            return ToolResult(False, str(exc), error_code="unavailable")
        if definition.special:
            return ToolResult(
                False,
                f"Tool '{name}' requires its session-specific executor.",
                error_code="special_executor_required",
            )

        async def invoke():
            if inspect.iscoroutinefunction(definition.handler):
                return await definition.handler(args)
            return await asyncio.to_thread(definition.handler, args)

        try:
            value = await asyncio.wait_for(invoke(), timeout=definition.timeout)
            return ToolResult(True, str(value or definition.default_result), data=value)
        except asyncio.TimeoutError:
            return ToolResult(
                False,
                f"Tool '{name}' timed out after {definition.timeout:g} seconds.",
                error_code="timeout",
            )
        except Exception as exc:
            return ToolResult(False, f"Tool '{name}' failed: {exc}", error_code="exception")
