"""Common asynchronous execution path for conventional tools."""

from __future__ import annotations

import asyncio
import inspect
import threading
import time
from collections.abc import Mapping
from dataclasses import replace

from core.request_context import RequestContext
from .cancellation import CancellationToken, ToolCancelled
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
    def __init__(
        self,
        registry: ToolRegistry,
        audit_sink=None,
        *,
        cancellation_grace: float = 1.0,
    ) -> None:
        if cancellation_grace <= 0:
            raise ValueError("Cancellation grace must be positive")
        self.registry = registry
        self.audit_sink = audit_sink
        self.cancellation_grace = cancellation_grace
        self._active_lock = threading.Lock()
        self._active_tokens: dict[str, CancellationToken] = {}

    def cancel(self, request_id: str) -> bool:
        """Signal an active cooperative execution by its request ID."""
        with self._active_lock:
            token = self._active_tokens.get(str(request_id))
        return token.cancel("requested") if token is not None else False

    @staticmethod
    def _supports_cancellation(handler) -> bool:
        try:
            parameters = inspect.signature(handler).parameters.values()
        except (TypeError, ValueError):
            return False
        return any(
            parameter.name == "cancellation_token"
            or parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in parameters
        )

    def _register_active(
        self,
        supports_cancellation: bool,
        context: RequestContext | None,
        token: CancellationToken,
    ) -> str | None:
        if not supports_cancellation or context is None:
            return None
        request_id = context.request_id
        with self._active_lock:
            self._active_tokens[request_id] = token
        return request_id

    def _unregister_active(
        self,
        request_id: str | None,
        token: CancellationToken,
    ) -> None:
        if request_id is None:
            return
        with self._active_lock:
            if self._active_tokens.get(request_id) is token:
                self._active_tokens.pop(request_id, None)

    @staticmethod
    def _consume_background_result(task: asyncio.Task) -> None:
        try:
            task.result()
        except BaseException:
            pass

    async def _await_cancellation_cleanup(
        self,
        task: asyncio.Task,
        definition,
        name: str,
    ) -> tuple[bool, ToolCancelled | ToolResult | None]:
        try:
            value = await asyncio.wait_for(
                asyncio.shield(task),
                timeout=self.cancellation_grace,
            )
        except asyncio.TimeoutError:
            task.add_done_callback(self._consume_background_result)
            return False, None
        except ToolCancelled as exc:
            return True, exc
        except Exception:
            return True, None
        return True, normalize_tool_output(
            name,
            value,
            definition.default_result,
            risk=definition.risk,
        )

    @staticmethod
    def _interrupted_result(
        name: str,
        *,
        timed_out: bool,
        acknowledged: bool,
        outcome: ToolCancelled | ToolResult | None,
        timeout: float,
    ) -> ToolResult:
        if isinstance(outcome, ToolCancelled):
            effect = outcome.effect_status
            verification = outcome.verification_status
            rollback = outcome.rollback_status
            evidence = outcome.evidence
        elif isinstance(outcome, ToolResult):
            effect = outcome.effect_status
            verification = outcome.verification_status
            rollback = outcome.rollback_status
            evidence = outcome.evidence
        else:
            effect = EffectStatus.UNKNOWN
            verification = VerificationStatus.UNKNOWN
            rollback = RollbackStatus.UNKNOWN
            evidence = ()
        acknowledgement = (
            "cancellation_acknowledged"
            if acknowledged
            else "cancellation_unacknowledged"
        )
        if timed_out:
            message = (
                f"Tool '{name}' timed out after {timeout:g} seconds; "
                f"cancellation was {'acknowledged' if acknowledged else 'not acknowledged'}."
            )
            execution = ExecutionStatus.TIMED_OUT
            error_code = "timeout"
        else:
            message = (
                f"Tool '{name}' was cancelled; cleanup was "
                f"{'acknowledged' if acknowledged else 'not acknowledged'}."
            )
            execution = ExecutionStatus.CANCELLED
            error_code = "cancelled"
        return ToolResult(
            False,
            message,
            error_code=error_code,
            execution_status=execution,
            effect_status=effect,
            verification_status=verification,
            rollback_status=rollback,
            evidence=tuple(evidence) + (acknowledgement,),
        )

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

        token = CancellationToken()
        supports_cancellation = (
            definition.cancellable
            and self._supports_cancellation(definition.handler)
        )
        active_request_id = self._register_active(
            supports_cancellation,
            context,
            token,
        )

        async def invoke():
            call_kwargs = (
                {"cancellation_token": token}
                if supports_cancellation
                else {}
            )
            if inspect.iscoroutinefunction(definition.handler):
                return await definition.handler(args, **call_kwargs)
            return await asyncio.to_thread(
                definition.handler,
                args,
                **call_kwargs,
            )

        task = asyncio.create_task(invoke())
        try:
            value = await asyncio.wait_for(
                asyncio.shield(task),
                timeout=definition.timeout,
            )
            if token.cancelled:
                normalized = normalize_tool_output(
                    name,
                    value,
                    definition.default_result,
                    risk=definition.risk,
                )
                return self._completed(
                    self._interrupted_result(
                        name,
                        timed_out=False,
                        acknowledged=True,
                        outcome=normalized,
                        timeout=definition.timeout,
                    ),
                    context,
                    name,
                    started_at,
                )
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
            if supports_cancellation:
                token.cancel("timeout")
                acknowledged, outcome = await self._await_cancellation_cleanup(
                    task,
                    definition,
                    name,
                )
            else:
                task.add_done_callback(self._consume_background_result)
                acknowledged, outcome = False, None
            return self._completed(
                self._interrupted_result(
                    name,
                    timed_out=True,
                    acknowledged=acknowledged,
                    outcome=outcome,
                    timeout=definition.timeout,
                ),
                context,
                name,
                started_at,
            )
        except ToolCancelled as exc:
            return self._completed(
                self._interrupted_result(
                    name,
                    timed_out=token.reason == "timeout",
                    acknowledged=True,
                    outcome=exc,
                    timeout=definition.timeout,
                ),
                context,
                name,
                started_at,
            )
        except asyncio.CancelledError:
            token.cancel("caller_cancelled")
            acknowledged, outcome = await self._await_cancellation_cleanup(
                task,
                definition,
                name,
            )
            return self._completed(
                self._interrupted_result(
                    name,
                    timed_out=False,
                    acknowledged=acknowledged,
                    outcome=outcome,
                    timeout=definition.timeout,
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
        finally:
            self._unregister_active(active_request_id, token)
