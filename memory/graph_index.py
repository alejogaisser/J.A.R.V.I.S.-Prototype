"""Build the visual graph exclusively from real JARVIS memory records."""

from __future__ import annotations

from typing import Any

from memory.memory_manager import list_memories


def _label(value: Any) -> str:
    return str(value or "memory").replace("_", " ").strip().title()


def _context(value: Any) -> str:
    return "_".join(str(value or "").strip().lower().replace("-", " ").split())


def build_memory_graph(
    *,
    memory_records: list[dict[str, Any]] | None = None,
    **_legacy_options: Any,
) -> dict[str, Any]:
    """Return category/context nuclei plus one content node per real memory.

    Legacy vault arguments are accepted and intentionally ignored so callers
    cannot accidentally reintroduce Obsidian notes as memory points.
    """
    records = memory_records if memory_records is not None else list_memories(
        status="active", include_sensitive=False
    )
    valid_records = [record for record in records if str(record.get("id", "")).strip()]
    categories = sorted({str(record.get("category") or "notes") for record in valid_records})
    contexts = sorted({
        _context(context)
        for record in valid_records
        for context in record.get("contexts", [])
        if _context(context)
    })

    nodes: list[dict[str, Any]] = [
        {
            "id": f"category:{category}", "kind": "category",
            "label": _label(category), "group": "PRIMARY MEMORY",
            "count": sum(str(record.get("category") or "notes") == category for record in valid_records),
        }
        for category in categories
    ]
    nodes.extend({
        "id": f"context:{context}", "kind": "context",
        "label": _label(context), "group": "EXPLICIT CONTEXT",
        "count": sum(context in {_context(item) for item in record.get("contexts", [])} for record in valid_records),
    } for context in contexts)

    edges: list[dict[str, str]] = []
    known_ids = {str(record["id"]) for record in valid_records}
    for record in valid_records:
        record_id = str(record["id"])
        category = str(record.get("category") or "notes")
        sensitive = str(record.get("sensitivity", "normal")) == "sensitive"
        nodes.append({
            "id": f"memory:{record_id}", "record_id": record_id, "kind": "memory",
            "label": _label(record.get("key")), "group": category,
            "value": "[protected]" if sensitive else str(record.get("value", ""))[:380],
            "sensitivity": str(record.get("sensitivity", "normal")),
            "contexts": list(record.get("contexts", [])),
            "updated": str(record.get("updated_at", "")),
        })
        edges.append({
            "source": f"category:{category}", "target": f"memory:{record_id}",
            "kind": "membership",
        })
        for context in record.get("contexts", []):
            normalized = _context(context)
            if normalized:
                edges.append({
                    "source": f"context:{normalized}", "target": f"memory:{record_id}",
                    "kind": "context",
                })
        # Related-memory edges are rendered only when explicit record IDs are
        # present. No similarity or semantic relationship is fabricated here.
        for related_id in record.get("related_ids", []):
            related_id = str(related_id)
            if related_id in known_ids and related_id != record_id:
                source, target = sorted((record_id, related_id))
                edges.append({
                    "source": f"memory:{source}", "target": f"memory:{target}",
                    "kind": "explicit_relation",
                })

    deduplicated = list({
        (edge["source"], edge["target"], edge["kind"]): edge for edge in edges
    }.values())
    return {
        "nodes": nodes,
        "edges": deduplicated,
        "stats": {
            "memories": len(valid_records),
            "categories": len(categories),
            "contexts": len(contexts),
            "content_nodes": len(valid_records),
            "synthetic_content_nodes": 0,
        },
    }
