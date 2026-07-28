"""Types used by the JARVIS tool registry."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


class RiskLevel(str, Enum):
    READ_ONLY = "read_only"
    LOCAL_CHANGE = "local_change"
    SENSITIVE = "sensitive"
    EXTERNAL_EFFECT = "external_effect"


class ConfirmationPolicy(str, Enum):
    NEVER = "never"
    DEPENDS_ON_ARGUMENTS = "depends_on_arguments"
    ALWAYS = "always"


class ExecutionStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REJECTED = "rejected"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


class EffectStatus(str, Enum):
    NONE = "none"
    NOT_APPLIED = "not_applied"
    APPLIED = "applied"
    PARTIAL = "partial"
    UNKNOWN = "unknown"


class VerificationStatus(str, Enum):
    NOT_REQUESTED = "not_requested"
    VERIFIED = "verified"
    FAILED = "failed"
    UNKNOWN = "unknown"


class RollbackStatus(str, Enum):
    NOT_AVAILABLE = "not_available"
    AVAILABLE = "available"
    NOT_NEEDED = "not_needed"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"


ToolHandler = Callable[[dict[str, Any]], Any]


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler | None = None
    risk: RiskLevel = RiskLevel.READ_ONLY
    confirmation: ConfirmationPolicy = ConfirmationPolicy.NEVER
    platforms: frozenset[str] = field(
        default_factory=lambda: frozenset({"windows", "macos", "linux"})
    )
    dependencies: frozenset[str] = field(default_factory=frozenset)
    timeout: float = 30.0
    cancellable: bool = False
    background: bool = False
    enabled: bool = True
    special: bool = False
    default_result: str = "Done."

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("Tool name cannot be empty")
        if self.timeout <= 0:
            raise ValueError(f"Tool '{self.name}' timeout must be positive")
        if not self.special and self.handler is None:
            raise ValueError(f"Tool '{self.name}' requires a handler")

    def declaration(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


@dataclass(frozen=True, slots=True)
class ToolResult:
    """Versioned result with legacy fields preserved for existing callers."""

    success: bool
    message: str
    data: Any = None
    error_code: str | None = None
    request_id: str | None = None
    execution_status: ExecutionStatus | str | None = None
    effect_status: EffectStatus | str = EffectStatus.UNKNOWN
    verification_status: VerificationStatus | str = VerificationStatus.NOT_REQUESTED
    rollback_status: RollbackStatus | str = RollbackStatus.NOT_AVAILABLE
    duration_ms: float | None = None
    evidence: tuple[str, ...] = ()
    schema_version: int = 2

    def __post_init__(self) -> None:
        execution = self.execution_status
        if execution is None:
            execution = (
                ExecutionStatus.SUCCEEDED
                if self.success
                else ExecutionStatus.FAILED
            )
        elif not isinstance(execution, ExecutionStatus):
            execution = ExecutionStatus(str(execution))
        effect = (
            self.effect_status
            if isinstance(self.effect_status, EffectStatus)
            else EffectStatus(str(self.effect_status))
        )
        verification = (
            self.verification_status
            if isinstance(self.verification_status, VerificationStatus)
            else VerificationStatus(str(self.verification_status))
        )
        rollback = (
            self.rollback_status
            if isinstance(self.rollback_status, RollbackStatus)
            else RollbackStatus(str(self.rollback_status))
        )
        evidence = tuple(str(item) for item in self.evidence)

        if self.schema_version != 2:
            raise ValueError("Unsupported ToolResult schema version")
        if self.duration_ms is not None and self.duration_ms < 0:
            raise ValueError("ToolResult duration cannot be negative")
        if self.success and execution != ExecutionStatus.SUCCEEDED:
            raise ValueError("Successful results require succeeded execution")
        if self.success and verification == VerificationStatus.FAILED:
            raise ValueError("A failed verification cannot be successful")
        if (
            not self.success
            and execution == ExecutionStatus.SUCCEEDED
            and verification != VerificationStatus.FAILED
        ):
            raise ValueError(
                "A succeeded execution may be unsuccessful only when verification failed"
            )

        object.__setattr__(self, "execution_status", execution)
        object.__setattr__(self, "effect_status", effect)
        object.__setattr__(self, "verification_status", verification)
        object.__setattr__(self, "rollback_status", rollback)
        object.__setattr__(self, "evidence", evidence)

    def to_dict(self, *, include_data: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "success": self.success,
            "message": self.message,
            "error_code": self.error_code,
            "request_id": self.request_id,
            "execution_status": self.execution_status.value,
            "effect_status": self.effect_status.value,
            "verification_status": self.verification_status.value,
            "rollback_status": self.rollback_status.value,
            "duration_ms": self.duration_ms,
            "evidence": list(self.evidence),
        }
        if include_data:
            payload["data"] = self.data
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ToolResult":
        if not isinstance(payload, dict):
            raise TypeError("ToolResult payload must be an object")
        if not isinstance(payload.get("success"), bool):
            raise TypeError("ToolResult success must be boolean")
        if not isinstance(payload.get("message"), str):
            raise TypeError("ToolResult message must be a string")
        duration = payload.get("duration_ms")
        if duration is not None and not isinstance(duration, (int, float)):
            raise TypeError("ToolResult duration must be numeric")
        return cls(
            success=payload["success"],
            message=payload["message"],
            data=payload.get("data"),
            error_code=payload.get("error_code"),
            request_id=payload.get("request_id"),
            execution_status=payload.get("execution_status"),
            effect_status=payload.get("effect_status", EffectStatus.UNKNOWN),
            verification_status=payload.get(
                "verification_status",
                VerificationStatus.NOT_REQUESTED,
            ),
            rollback_status=payload.get(
                "rollback_status",
                RollbackStatus.NOT_AVAILABLE,
            ),
            duration_ms=float(duration) if duration is not None else None,
            evidence=tuple(payload.get("evidence") or ()),
            schema_version=int(payload.get("schema_version", 2)),
        )
