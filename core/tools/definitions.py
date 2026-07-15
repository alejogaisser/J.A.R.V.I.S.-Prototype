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
    success: bool
    message: str
    data: Any = None
    error_code: str | None = None
