"""Common asynchronous execution path for conventional tools."""

from __future__ import annotations

import asyncio
import inspect
import time
from collections.abc import Mapping
from dataclasses import replace

from core.request_context import RequestContext
from .definitions import ToolResult
from .registry import ToolRegistry


_FAILURE_PREFIXES = (
    "access denied",
    "blocked",
    "cancelled",
    "could not",
    "error:",
    "failed",
    "invalid",
    "missing",
    "permission denied",
    "unable",
    "unknown action",
    "unknown tool",
)


def normalize_tool_output(name: str, value, default_result: str) -> ToolResult:
    """Convert legacy handler output without turning silence into success."""
    if isinstance(value, ToolResult):
        return value
    if value is None:
        return ToolResult(
            False,
            f"Tool '{name}' did not report a verifiable result.",
            error_code="missing_result",
        )
    if isinstance(value, bool):
        return ToolResult(
            value,
            default_result if value else f"Tool '{name}' reported failure.",
            data=value,
            error_code=None if value else "handler_reported_failure",
        )
    if isinstance(value, Mapping):
        explicit_success = value.get("success")
        error = value.get("error")
        if explicit_success is False or error:
            message = value.get("message") or value.get("result") or error
            return ToolResult(
                False,
                str(message or f"Tool '{name}' reported failure."),
                data=value,
                error_code=str(error or "handler_reported_failure"),
            )
        message = value.get("message") or value.get("result") or str(value)
        return ToolResult(True, str(message), data=value)

    message = str(value).strip()
    if not message:
        return ToolResult(
            False,
            f"Tool '{name}' returned an empty result.",
            error_code="missing_result",
        )
    if message.casefold().startswith(_FAILURE_PREFIXES):
        return ToolResult(
            False,
            message,
            data=value,
            error_code="handler_reported_failure",
        )
    return ToolResult(True, message, data=value)


class ToolExecutor:
    def __init__(self, registry: ToolRegistry, audit_sink=None) -> None:
        self.registry = registry
        self.audit_sink = audit_sink

    def _audit(self, context: RequestContext | None, event: str, name: str, **metadata) -> None:
        if context is None or self.audit_sink is None:
            return
        try:
            self.audit_sink.record(context, event, name, **metadata)
        except Exception:
            # Observability must never become an execution dependency.
            pass

    def _completed(
        self,
        result: ToolResult,
        context: RequestContext | None,
        name: str,
        started_at: float,
    ) -> ToolResult:
        self._audit(
            context,
            "completed",
            name,
            outcome="success" if result.success else "error",
            error_code=result.error_code,
            duration_ms=(time.monotonic() - started_at) * 1000,
        )
        if context is None:
            return result
        return replace(result, request_id=context.request_id)

    async def execute(
        self,
        name: str,
        args: dict,
        *,
        context: RequestContext | None = None,
    ) -> ToolResult:
        started_at = time.monotonic()
        try:
            definition = self.registry.validate_for_execution(name)
            self.registry.validate_arguments(definition, args)
        except (KeyError, PermissionError, RuntimeError, TypeError, ValueError) as exc:
            return self._completed(
                ToolResult(False, str(exc), error_code="unavailable"),
                context,
                name,
                started_at,
            )
        self._audit(context, "started", name)
        if definition.special:
            return self._completed(
                ToolResult(
                    False,
                    f"Tool '{name}' requires its session-specific executor.",
                    error_code="special_executor_required",
                ),
                context,
                name,
                started_at,
            )

        async def invoke():
            if inspect.iscoroutinefunction(definition.handler):
                return await definition.handler(args)
            return await asyncio.to_thread(definition.handler, args)

        try:
            value = await asyncio.wait_for(invoke(), timeout=definition.timeout)
            return self._completed(
                normalize_tool_output(name, value, definition.default_result),
                context,
                name,
                started_at,
            )
        except asyncio.TimeoutError:
            return self._completed(
                ToolResult(
                    False,
                    f"Tool '{name}' timed out after {definition.timeout:g} seconds.",
                    error_code="timeout",
                ),
                context,
                name,
                started_at,
            )
        except Exception as exc:
            return self._completed(
                ToolResult(
                    False,
                    f"Tool '{name}' failed: {exc}",
                    error_code="exception",
                ),
                context,
                name,
                started_at,
            )
