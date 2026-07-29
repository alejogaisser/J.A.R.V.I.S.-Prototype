"""Sanitized structured runtime logging with bounded local retention."""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import IO, Mapping

from .diagnostics import redact_diagnostic_text
from .events import RuntimeEvent
from .request_context import RequestContext

DEFAULT_RUNTIME_LOG_FILE = (
    Path(__file__).resolve().parents[1] / "logs" / "runtime.jsonl"
)
_SAFE_LABEL = re.compile(r"^[a-zA-Z0-9_.:-]{1,64}$")
_SAFE_METADATA_FIELDS = {
    "analyses_started",
    "busy",
    "connected",
    "connections",
    "deadline",
    "duration_ms",
    "event_id",
    "error_code",
    "failures",
    "generation",
    "healthy",
    "interrupted",
    "interrupts",
    "modality",
    "operation",
    "occurred_at_monotonic",
    "occurred_at_utc",
    "reason",
    "restarts",
    "reconnects",
    "shutdown_requests",
    "status",
    "starts",
    "surface",
    "wake_supervised",
    "worker",
}
_SAFE_NUMERIC_METADATA_FIELDS = {
    "analyses_started",
    "connections",
    "deadline",
    "generation",
    "interrupts",
    "occurred_at_monotonic",
    "reconnects",
    "restarts",
    "shutdown_requests",
    "starts",
    "failures",
}


def _label(value: object, fallback: str = "unknown") -> str:
    text = str(value or "").strip()
    return text if _SAFE_LABEL.fullmatch(text) else fallback


def _safe_metadata(metadata: Mapping[str, object] | None) -> dict[str, object]:
    safe: dict[str, object] = {}
    for key, value in (metadata or {}).items():
        normalized_key = str(key).strip().lower()
        if normalized_key not in _SAFE_METADATA_FIELDS:
            continue
        if normalized_key == "duration_ms":
            if isinstance(value, bool) or not isinstance(value, (int, float, str)):
                continue
            try:
                safe[normalized_key] = max(0.0, round(float(value), 3))
            except (TypeError, ValueError):
                continue
        elif normalized_key in _SAFE_NUMERIC_METADATA_FIELDS:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            normalized_value = max(0, value)
            safe[normalized_key] = (
                normalized_value
                if isinstance(normalized_value, int)
                else round(normalized_value, 6)
            )
        elif isinstance(value, bool):
            safe[normalized_key] = value
        else:
            safe[normalized_key] = redact_diagnostic_text(str(value))[:160]
    return safe


class StructuredRuntimeLog:
    """Own console/file handlers and tolerate unavailable logging outputs."""

    def __init__(
        self,
        path: str | Path = DEFAULT_RUNTIME_LOG_FILE,
        *,
        console: bool = True,
        stream: IO[str] | None = None,
        max_bytes: int = 1_048_576,
        backup_count: int = 3,
    ) -> None:
        self.path = Path(path)
        self._logger = logging.Logger(
            f"jarvis.runtime.{id(self)}",
            level=logging.INFO,
        )
        self._logger.propagate = False
        formatter = logging.Formatter("%(message)s")

        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(
                self.path,
                maxBytes=max(256, int(max_bytes)),
                backupCount=max(1, int(backup_count)),
                encoding="utf-8",
                delay=False,
            )
            file_handler.setFormatter(formatter)
            self._logger.addHandler(file_handler)
        except (OSError, ValueError):
            pass

        if console:
            try:
                console_handler = logging.StreamHandler(stream or sys.stderr)
                console_handler.setFormatter(formatter)
                self._logger.addHandler(console_handler)
            except (OSError, ValueError):
                pass

    @property
    def available(self) -> bool:
        return bool(self._logger.handlers)

    def record(
        self,
        event: str,
        *,
        level: int = logging.INFO,
        component: str = "runtime",
        message: str | None = None,
        context: RequestContext | None = None,
        request_id: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> bool:
        if not self.available:
            return False
        payload: dict[str, object] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": logging.getLevelName(level),
            "event": _label(event),
            "component": _label(component),
        }
        if message:
            payload["message"] = redact_diagnostic_text(str(message))[:512]
        if context is not None:
            payload["request_id"] = _label(context.request_id)
            payload["source"] = context.source_label
            if context.tool_call_id:
                payload["tool_call_id"] = _label(context.tool_call_id)
        elif request_id:
            payload["request_id"] = _label(request_id)
        payload.update(_safe_metadata(metadata))
        try:
            encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True)
            self._logger.log(level, encoded)
            return True
        except (OSError, TypeError, ValueError):
            return False

    def record_runtime_event(self, event: RuntimeEvent) -> None:
        self.record(
            event.event_name,
            component=event.component,
            request_id=event.header.request_id,
            metadata=event.log_metadata(),
        )

    def close(self) -> None:
        for handler in tuple(self._logger.handlers):
            self._logger.removeHandler(handler)
            try:
                handler.flush()
                handler.close()
            except OSError:
                continue
