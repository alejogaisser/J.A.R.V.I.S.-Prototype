from __future__ import annotations

import json
from pathlib import Path

from core.clock import local_now

AUDIT_FILE = Path(__file__).resolve().parents[1] / "config" / "connector_audit.jsonl"


def record(provider: str, operation: str, *, outcome: str = "ok", count: int | None = None,
           destination: str | None = None) -> None:
    """Record metadata only; never subjects, bodies, queries, tokens, or addresses."""
    event = {
        "timestamp": local_now().isoformat(),
        "provider": provider,
        "operation": operation,
        "outcome": outcome,
    }
    if count is not None:
        event["count"] = count
    if destination:
        event["destination_name"] = Path(destination).name
    AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with AUDIT_FILE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")
