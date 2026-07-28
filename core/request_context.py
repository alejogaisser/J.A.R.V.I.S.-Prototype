"""Correlation context shared by permission, execution, audit, and response."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4


class InputSource(str, Enum):
    LOCAL = "local"
    UI = "ui"
    WAKE = "wake"
    DASHBOARD_TEXT = "dashboard_text"
    DASHBOARD_AUDIO = "dashboard_audio"

    @property
    def is_remote(self) -> bool:
        return self in {self.DASHBOARD_TEXT, self.DASHBOARD_AUDIO}


@dataclass(frozen=True, slots=True)
class RequestContext:
    request_id: str
    source: InputSource | str = InputSource.LOCAL
    tool_call_id: str | None = None
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def __post_init__(self) -> None:
        if isinstance(self.source, InputSource):
            return
        try:
            normalized = InputSource(str(self.source).strip().lower())
        except ValueError:
            # Preserve the unknown label for diagnostics while treating it as remote.
            return
        object.__setattr__(self, "source", normalized)

    @classmethod
    def create(
        cls,
        source: InputSource | str = InputSource.LOCAL,
        *,
        tool_call_id: str | None = None,
    ) -> "RequestContext":
        return cls(
            request_id=uuid4().hex,
            source=source,
            tool_call_id=tool_call_id,
        )

    @property
    def is_remote(self) -> bool:
        if isinstance(self.source, InputSource):
            return self.source.is_remote
        return True

    @property
    def source_label(self) -> str:
        if isinstance(self.source, InputSource):
            return self.source.value
        return "unknown"
