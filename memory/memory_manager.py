"""Versioned, user-controllable long-term memory for JARVIS.

Script routines deliberately live in ``script_memory.py`` / ``scripts.json`` and
are not migrated or modified here.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import uuid
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any

from core.clock import JARVIS_TIMEZONE, local_now


def get_base_dir() -> Path:
    return Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent


BASE_DIR = get_base_dir()
MEMORY_PATH = BASE_DIR / "memory" / "long_term.json"
SCHEMA_VERSION = 2
MAX_VALUE_LENGTH = 380
MEMORY_MAX_CHARS = 2200  # prompt budget; storage is never trimmed silently
VALID_CATEGORIES = {"identity", "preferences", "projects", "relationships", "wishes", "notes", "temporary"}
VALID_SENSITIVITY = {"normal", "personal", "sensitive"}
_lock = RLock()


def _now() -> str:
    return local_now().isoformat()


def _key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).lower()).strip("_") or "note"


def _empty_store() -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "records": [], "history": []}


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=JARVIS_TIMEZONE) if parsed.tzinfo is None else parsed.astimezone(JARVIS_TIMEZONE)
    except (TypeError, ValueError):
        raise ValueError("expires_at must be an ISO-8601 date/time with an optional timezone")


def _atomic_write(data: dict[str, Any]) -> None:
    MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = MEMORY_PATH.with_suffix(MEMORY_PATH.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, MEMORY_PATH)


def _migrate_legacy(data: dict[str, Any]) -> dict[str, Any]:
    store = _empty_store()
    for category, items in data.items():
        if category not in VALID_CATEGORIES or not isinstance(items, dict):
            continue
        for key, old in items.items():
            value = old.get("value") if isinstance(old, dict) else old
            if value is None:
                continue
            updated = old.get("updated") if isinstance(old, dict) else None
            if updated and "T" not in str(updated):
                updated = f"{updated}T00:00:00-03:00"
            timestamp = updated or _now()
            store["records"].append({
                "id": f"mem_{uuid.uuid4().hex}", "category": category, "key": _key(key),
                "value": str(value)[:MAX_VALUE_LENGTH], "created_at": timestamp,
                "updated_at": timestamp, "expires_at": None, "source": "legacy_migration",
                "source_context": "long_term.json", "confidence": 1.0, "status": "active",
                "sensitivity": "normal", "confirmed": True,
            })
    store["history"].append({"event": "legacy_migrated", "at": _now(), "record_count": len(store["records"])})
    return store


def _load_store() -> dict[str, Any]:
    with _lock:
        if not MEMORY_PATH.exists():
            return _empty_store()
        try:
            data = json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("schema_version") == SCHEMA_VERSION and isinstance(data.get("records"), list):
                data.setdefault("history", [])
                return data
            if isinstance(data, dict):
                backup = MEMORY_PATH.with_suffix(MEMORY_PATH.suffix + ".legacy.bak")
                if not backup.exists():
                    shutil.copy2(MEMORY_PATH, backup)
                migrated = _migrate_legacy(data)
                _atomic_write(migrated)
                return migrated
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            backup = MEMORY_PATH.with_suffix(MEMORY_PATH.suffix + ".bak")
            if backup.exists():
                try:
                    recovered = json.loads(backup.read_text(encoding="utf-8"))
                    if recovered.get("schema_version") == SCHEMA_VERSION:
                        return recovered
                except (OSError, json.JSONDecodeError, AttributeError):
                    pass
            print(f"[Memory] Load error: {exc}")
        return _empty_store()


def _save_store(store: dict[str, Any]) -> None:
    with _lock:
        if MEMORY_PATH.exists():
            shutil.copy2(MEMORY_PATH, MEMORY_PATH.with_suffix(MEMORY_PATH.suffix + ".bak"))
        _atomic_write(store)


def _is_expired(record: dict[str, Any], now: datetime | None = None) -> bool:
    expires = _parse_time(record.get("expires_at"))
    return bool(expires and expires <= (now or local_now()))


def _active_records(store: dict[str, Any]) -> list[dict[str, Any]]:
    return [r for r in store["records"] if r.get("status") == "active" and not _is_expired(r)]


def load_memory() -> dict[str, dict[str, dict[str, str]]]:
    """Return the legacy category view used by existing prompt/action code."""
    result = {category: {} for category in VALID_CATEGORIES if category != "temporary"}
    result["temporary"] = {}
    for record in _active_records(_load_store()):
        result.setdefault(record["category"], {})[record["key"]] = {
            "value": record["value"], "updated": record["updated_at"][:10], "id": record["id"]
        }
    return result


def create_memory(category: str, key: str, value: Any, *, expires_at: str | None = None,
                  source: str = "user_statement", source_context: str = "conversation",
                  confidence: float = 1.0, sensitivity: str = "normal", confirmed: bool = True,
                  replace: bool = False) -> dict[str, Any]:
    category = category if category in VALID_CATEGORIES else "notes"
    key = _key(key)
    value = str(value).strip()[:MAX_VALUE_LENGTH]
    if not value:
        raise ValueError("Memory value cannot be empty")
    _parse_time(expires_at)
    if sensitivity not in VALID_SENSITIVITY:
        raise ValueError("Invalid sensitivity")
    store = _load_store()
    conflicts = [r for r in _active_records(store) if r["category"] == category and r["key"] == key]
    same = next((r for r in conflicts if r["value"] == value), None)
    if same:
        return {"result": "unchanged", "record": same}
    if conflicts and not replace:
        return {"result": "conflict", "existing": conflicts[0], "proposed_value": value}
    now = _now()
    if conflicts:
        record = conflicts[0]
        old = record["value"]
        record.update(value=value, updated_at=now, expires_at=expires_at, source=source,
                      source_context=source_context, confidence=max(0.0, min(1.0, float(confidence))),
                      sensitivity=sensitivity, confirmed=bool(confirmed))
        store["history"].append({"event": "updated", "record_id": record["id"], "at": now, "old_value": old})
        result = "updated"
    else:
        record = {"id": f"mem_{uuid.uuid4().hex}", "category": category, "key": key, "value": value,
                  "created_at": now, "updated_at": now, "expires_at": expires_at, "source": source,
                  "source_context": source_context, "confidence": max(0.0, min(1.0, float(confidence))),
                  "status": "active", "sensitivity": sensitivity, "confirmed": bool(confirmed)}
        store["records"].append(record)
        store["history"].append({"event": "created", "record_id": record["id"], "at": now})
        result = "created"
    _save_store(store)
    return {"result": result, "record": record}


def list_memories(category: str | None = None, status: str = "active", include_sensitive: bool = False) -> list[dict[str, Any]]:
    records = _load_store()["records"]
    output = []
    for record in records:
        effective = "expired" if record.get("status") == "active" and _is_expired(record) else record.get("status")
        if status and effective != status or category and record.get("category") != category:
            continue
        item = dict(record)
        item["status"] = effective
        if item.get("sensitivity") == "sensitive" and not include_sensitive:
            item["value"] = "[redacted]"
        output.append(item)
    return output


def search_memories(query: str = "", category: str | None = None) -> list[dict[str, Any]]:
    words = [w for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w) > 1]
    records = list_memories(category=category, status="active")
    if not words:
        return records
    return [r for r in records if any(w in f"{r['key']} {r['value']}".lower() for w in words)]


def update_memory_by_id(record_id: str, **changes: Any) -> dict[str, Any]:
    allowed = {"value", "expires_at", "sensitivity", "confirmed"}
    unknown = set(changes) - allowed
    if unknown:
        raise ValueError(f"Unsupported fields: {', '.join(sorted(unknown))}")
    store = _load_store()
    record = next((r for r in store["records"] if r["id"] == record_id), None)
    if not record:
        raise KeyError(record_id)
    if "expires_at" in changes:
        _parse_time(changes["expires_at"])
    if "value" in changes:
        changes["value"] = str(changes["value"]).strip()[:MAX_VALUE_LENGTH]
    old = {key: record.get(key) for key in changes}
    record.update(changes, updated_at=_now())
    store["history"].append({"event": "updated", "record_id": record_id, "at": _now(), "previous": old})
    _save_store(store)
    return record


def forget_memory(record_id: str) -> dict[str, Any]:
    store = _load_store()
    record = next((r for r in store["records"] if r["id"] == record_id), None)
    if not record:
        raise KeyError(record_id)
    record.update(status="forgotten", updated_at=_now())
    store["history"].append({"event": "forgotten", "record_id": record_id, "at": _now()})
    _save_store(store)
    return record


def restore_memory(record_id: str) -> dict[str, Any]:
    store = _load_store()
    record = next((r for r in store["records"] if r["id"] == record_id), None)
    if not record:
        raise KeyError(record_id)
    record.update(status="active", updated_at=_now())
    store["history"].append({"event": "restored", "record_id": record_id, "at": _now()})
    _save_store(store)
    return record


def update_memory(memory_update: dict) -> dict:
    """Compatibility adapter for existing callers; explicit updates replace by key."""
    for category, items in (memory_update or {}).items():
        if not isinstance(items, dict):
            continue
        for key, raw in items.items():
            value = raw.get("value") if isinstance(raw, dict) else raw
            if value is not None:
                create_memory(category, key, value, replace=True)
    return load_memory()


def save_memory(memory: dict) -> None:
    update_memory(memory)


def format_memory_for_prompt(memory: dict | None = None, query: str = "") -> str:
    records = search_memories(query) if query else list_memories(status="active")
    if not records:
        return ""
    labels = {"identity": "Identity", "preferences": "Preferences", "projects": "Projects / Goals",
              "relationships": "Relationships", "wishes": "Wishes / Plans", "notes": "Notes", "temporary": "Temporary"}
    lines = ["[USER MEMORY - active, relevant, and user-controllable]"]
    for category in labels:
        selected = [r for r in records if r["category"] == category]
        if selected:
            lines.append(f"{labels[category]}:")
            lines.extend(f"  - {r['key'].replace('_', ' ')}: {r['value']} [memory_id={r['id']}]" for r in selected)
    result = "\n".join(lines)
    return result[:MEMORY_MAX_CHARS] + ("..." if len(result) > MEMORY_MAX_CHARS else "") + "\n"


def remember(key: str, value: str, category: str = "notes") -> str:
    result = create_memory(category, key, value)
    return f"Memory {result['result']}: {category}/{_key(key)}"


def forget(key: str, category: str = "notes") -> str:
    match = next((r for r in list_memories(category=category) if r["key"] == _key(key)), None)
    if not match:
        return f"Not found: {category}/{key}"
    forget_memory(match["id"])
    return f"Forgotten: {category}/{key}"
