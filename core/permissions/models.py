from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum


class InputSource(str, Enum):
    LOCAL = "local"
    UI = "ui"
    WAKE = "wake"
    DASHBOARD_TEXT = "dashboard_text"
    DASHBOARD_AUDIO = "dashboard_audio"

    @property
    def is_remote(self) -> bool:
        return self in {self.DASHBOARD_TEXT, self.DASHBOARD_AUDIO}


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
    source: InputSource | str = InputSource.LOCAL
    simulate: bool = False

    def __post_init__(self) -> None:
        if isinstance(self.source, InputSource):
            return
        try:
            normalized = InputSource(str(self.source).strip().lower())
        except ValueError:
            # Unknown transports are untrusted by default.
            return
        object.__setattr__(self, "source", normalized)

    @property
    def is_remote(self) -> bool:
        if isinstance(self.source, InputSource):
            return self.source.is_remote
        return True


@dataclass(frozen=True, slots=True)
class PermissionDecision:
    allowed: bool
    requires_confirmation: bool
    simulated: bool
    policy: str
    reason: str
    operation: str
