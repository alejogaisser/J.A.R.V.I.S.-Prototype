"""Sanitized JSONL lifecycle events for tool requests."""

from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

from .request_context import RequestContext

DEFAULT_AUDIT_FILE = Path(__file__).resolve().parents[1] / "logs" / "request_audit.jsonl"
_SAFE_LABEL = re.compile(r"^[a-zA-Z0-9_.:-]{1,64}$")
_EVENTS = {
    "requested",
    "policy",
    "confirmation",
    "started",
    "completed",
    "response",
}


def _label(value: object, fallback: str = "unknown") -> str:
    text = str(value or "").strip()
    return text if _SAFE_LABEL.fullmatch(text) else fallback


class RequestAuditSink:
    """Append metadata only; arguments and user/model content are not accepted."""

    def __init__(
        self,
        path: str | Path = DEFAULT_AUDIT_FILE,
        *,
        enabled: bool | None = None,
    ) -> None:
        self.path = Path(path)
        self.enabled = (
            os.environ.get("JARVIS_REQUEST_AUDIT", "1") != "0"
            if enabled is None
            else enabled
        )
        self._lock = threading.Lock()

    def record(
        self,
        context: RequestContext,
        event: str,
        tool: str,
        *,
        outcome: str | None = None,
        operation: str | None = None,
        policy: str | None = None,
        error_code: str | None = None,
        duration_ms: float | None = None,
        execution_status: str | None = None,
        effect_status: str | None = None,
        verification_status: str | None = None,
        rollback_status: str | None = None,
    ) -> bool:
        if not self.enabled:
            return False
        event_label = _label(event)
        if event_label not in _EVENTS:
            return False
        payload: dict[str, object] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "request_id": _label(context.request_id),
            "event": event_label,
            "tool": _label(tool),
            "source": context.source_label,
        }
        if context.tool_call_id:
            payload["tool_call_id"] = _label(context.tool_call_id)
        if outcome is not None:
            payload["outcome"] = _label(outcome)
        if operation is not None:
            payload["operation"] = _label(operation, "custom")
        if policy is not None:
            payload["policy"] = _label(policy)
        if error_code is not None:
            payload["error_code"] = _label(error_code)
        if duration_ms is not None:
            payload["duration_ms"] = max(0.0, round(float(duration_ms), 3))
        if execution_status is not None:
            payload["execution_status"] = _label(execution_status)
        if effect_status is not None:
            payload["effect_status"] = _label(effect_status)
        if verification_status is not None:
            payload["verification_status"] = _label(verification_status)
        if rollback_status is not None:
            payload["rollback_status"] = _label(rollback_status)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True)
            with self._lock, self.path.open("a", encoding="utf-8") as handle:
                handle.write(encoded + "\n")
            return True
        except (OSError, TypeError, ValueError):
            return False
