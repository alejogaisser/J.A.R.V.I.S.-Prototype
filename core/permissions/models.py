from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class PermissionLevel(IntEnum):
    FREE = 0
    CONFIRM_ONCE = 1
    CONFIRM_ALWAYS = 2
    BLOCKED = 3

    @classmethod
    def parse(cls, value: object) -> "PermissionLevel":
        if isinstance(value, cls):
            return value
        return cls[str(value).strip().upper()]

    @property
    def label(self) -> str:
        return self.name.lower()


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    source: str = "local"
    simulate: bool = False


@dataclass(frozen=True, slots=True)
class PermissionDecision:
    allowed: bool
    requires_confirmation: bool
    simulated: bool
    policy: str
    reason: str
    operation: str
