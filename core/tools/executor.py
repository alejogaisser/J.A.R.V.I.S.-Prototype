"""Common asynchronous execution path for conventional tools."""

from __future__ import annotations

import asyncio
import inspect
import time
from collections.abc import Mapping
from dataclasses import replace

from core.request_context import RequestContext
from .definitions import (
    EffectStatus,
    ExecutionStatus,
    RiskLevel,
    RollbackStatus,
    ToolResult,
    VerificationStatus,
)
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


def _legacy_effect(risk: RiskLevel | None) -> EffectStatus:
    return EffectStatus.NONE if risk == RiskLevel.READ_ONLY else EffectStatus.UNKNOWN


def normalize_tool_output(
    name: str,
    value,
    default_result: str,
    *,
    risk: RiskLevel | None = None,
) -> ToolResult:
    """Convert legacy handler output without turning silence into success."""
    if isinstance(value, ToolResult):
        return value
    if isinstance(value, Mapping) and value.get("schema_version") == 2:
        return ToolResult.from_dict(dict(value))
    if value is None:
        return ToolResult(
            False,
            f"Tool '{name}' did not report a verifiable result.",
            error_code="missing_result",
            execution_status=ExecutionStatus.FAILED,
            effect_status=_legacy_effect(risk),
            verification_status=VerificationStatus.UNKNOWN,
        )
    if isinstance(value, bool):
        return ToolResult(
            value,
            default_result if value else f"Tool '{name}' reported failure.",
            data=value,
            error_code=None if value else "handler_reported_failure",
            execution_status=(
                ExecutionStatus.SUCCEEDED if value else ExecutionStatus.FAILED
            ),
            effect_status=_legacy_effect(risk),
            verification_status=VerificationStatus.NOT_REQUESTED,
            rollback_status=RollbackStatus.NOT_AVAILABLE,
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
                execution_status=ExecutionStatus.FAILED,
                effect_status=_legacy_effect(risk),
                verification_status=VerificationStatus.UNKNOWN,
            )
        message = value.get("message") or value.get("result") or str(value)
        return ToolResult(
            True,
            str(message),
            data=value,
            execution_status=ExecutionStatus.SUCCEEDED,
            effect_status=_legacy_effect(risk),
        )

    message = str(value).strip()
    if not message:
        return ToolResult(
            False,
            f"Tool '{name}' returned an empty result.",
            error_code="missing_result",
            execution_status=ExecutionStatus.FAILED,
            effect_status=_legacy_effect(risk),
            verification_status=VerificationStatus.UNKNOWN,
        )
    if message.casefold().startswith(_FAILURE_PREFIXES):
        return ToolResult(
            False,
            message,
            data=value,
            error_code="handler_reported_failure",
            execution_status=ExecutionStatus.FAILED,
            effect_status=_legacy_effect(risk),
            verification_status=VerificationStatus.UNKNOWN,
        )
    return ToolResult(
        True,
        message,
        data=value,
        execution_status=ExecutionStatus.SUCCEEDED,
        effect_status=_legacy_effect(risk),
    )


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
        duration_ms = (time.monotonic() - started_at) * 1000
        self._audit(
            context,
            "completed",
            name,
            outcome="success" if result.success else "error",
            error_code=result.error_code,
            duration_ms=duration_ms,
            execution_status=result.execution_status.value,
            effect_status=result.effect_status.value,
            verification_status=result.verification_status.value,
            rollback_status=result.rollback_status.value,
        )
        return replace(
            result,
            request_id=context.request_id if context is not None else result.request_id,
            duration_ms=duration_ms,
        )

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
                ToolResult(
                    False,
                    str(exc),
                    error_code="unavailable",
                    execution_status=ExecutionStatus.REJECTED,
                    effect_status=EffectStatus.NOT_APPLIED,
                ),
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
                    execution_status=ExecutionStatus.REJECTED,
                    effect_status=EffectStatus.NOT_APPLIED,
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
                normalize_tool_output(
                    name,
                    value,
                    definition.default_result,
                    risk=definition.risk,
                ),
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
                    execution_status=ExecutionStatus.TIMED_OUT,
                    effect_status=EffectStatus.UNKNOWN,
                    verification_status=VerificationStatus.UNKNOWN,
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
                    execution_status=ExecutionStatus.FAILED,
                    effect_status=EffectStatus.UNKNOWN,
                    verification_status=VerificationStatus.UNKNOWN,
                ),
                context,
                name,
                started_at,
            )
