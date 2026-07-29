from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

EXPECTED_SOURCE_IDS = frozenset(f"SRC-{index:02d}" for index in range(1, 9))
EXPECTED_LIMIT_IDS = frozenset(f"LIM-{index:02d}" for index in range(1, 6))
VALID_LIMIT_STATUSES = frozenset(
    {"not_performed", "target_calibration_required", "automated"}
)
VALID_CLOSURE_STATUSES = frozenset({"closed_with_open_risks", "verified_complete"})
ACCEPTANCE_STATUSES = ("verified", "partial", "manual", "blocked")


def _load_json(path: Path, label: str) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise ValueError(f"Unsupported {label} document")
    return payload


def load_closure(path: Path) -> dict[str, Any]:
    return _load_json(path, "audit closure")


def _resolve_evidence(repo_root: Path, raw_path: object, label: str) -> Path:
    path = Path(str(raw_path))
    if path.is_absolute():
        raise ValueError(f"{label}: paths must be repository-relative")
    resolved_root = repo_root.resolve()
    resolved = (resolved_root / path).resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"{label}: path escapes the repository") from exc
    if not resolved.exists():
        raise ValueError(f"{label}: missing path {path}")
    return resolved


def _validate_inventory(
    items: object,
    expected_ids: frozenset[str],
    repo_root: Path,
    *,
    kind: str,
    path_field: str,
) -> None:
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise TypeError(f"{kind} must be a list of objects")
    identifiers = [str(item.get("id")) for item in items]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError(f"{kind} IDs must be unique")
    if set(identifiers) != expected_ids:
        missing = sorted(expected_ids - set(identifiers))
        extra = sorted(set(identifiers) - expected_ids)
        raise ValueError(f"{kind} mismatch; missing={missing}, extra={extra}")
    for item in items:
        identifier = str(item["id"])
        values = item.get(path_field)
        if not isinstance(values, list) or not values:
            raise ValueError(f"{identifier}: {path_field} is required")
        for raw_path in values:
            _resolve_evidence(repo_root, raw_path, identifier)


def _acceptance_counts(global_matrix: dict[str, Any]) -> Counter[str]:
    criteria = global_matrix.get("criteria")
    if not isinstance(criteria, list):
        raise TypeError("Global acceptance criteria must be a list")
    counts: Counter[str] = Counter()
    for criterion in criteria:
        if not isinstance(criterion, dict):
            raise TypeError("Global acceptance criteria must contain objects")
        status = criterion.get("status")
        if status not in ACCEPTANCE_STATUSES:
            raise ValueError(f"Invalid global acceptance status: {status!r}")
        counts[str(status)] += 1
    return counts


def validate_closure(payload: dict[str, Any], repo_root: Path) -> tuple[int, int, int]:
    _validate_inventory(
        payload.get("source_groups"),
        EXPECTED_SOURCE_IDS,
        repo_root,
        kind="source groups",
        path_field="paths",
    )
    _validate_inventory(
        payload.get("limits"),
        EXPECTED_LIMIT_IDS,
        repo_root,
        kind="limits",
        path_field="evidence",
    )
    for limit in payload["limits"]:
        if not str(limit.get("statement", "")).strip():
            raise ValueError(f"{limit['id']}: statement is required")
        if limit.get("status") not in VALID_LIMIT_STATUSES:
            raise ValueError(f"{limit['id']}: invalid limit status")

    status = payload.get("closure_status")
    if status not in VALID_CLOSURE_STATUSES:
        raise ValueError("Invalid closure status")
    if not str(payload.get("snapshot_date", "")).strip():
        raise ValueError("snapshot_date is required")
    if not str(payload.get("review_date", "")).strip():
        raise ValueError("review_date is required")
    if not str(payload.get("conclusion", "")).strip():
        raise ValueError("conclusion is required")

    matrix = _load_json(repo_root / "docs" / "global_acceptance.json", "global acceptance")
    actual = _acceptance_counts(matrix)
    declared = payload.get("global_acceptance")
    if not isinstance(declared, dict):
        raise TypeError("global_acceptance summary must be an object")
    total = sum(actual[name] for name in ACCEPTANCE_STATUSES)
    expected_summary = {
        "total": total,
        **{name: actual[name] for name in ACCEPTANCE_STATUSES},
    }
    if declared != expected_summary:
        raise ValueError(
            f"Global acceptance summary is stale; expected={expected_summary}"
        )
    unresolved = total - actual["verified"]
    if unresolved and status != "closed_with_open_risks":
        raise ValueError("Unresolved global criteria forbid verified_complete closure")
    if not unresolved and status != "verified_complete":
        raise ValueError("All global criteria are verified; closure status is stale")
    return len(EXPECTED_SOURCE_IDS), len(EXPECTED_LIMIT_IDS), unresolved


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the section 17 audit closure.")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--closure", type=Path, default=Path("docs/audit_closure.json"))
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    closure_path = args.closure
    if not closure_path.is_absolute():
        closure_path = repo_root / closure_path
    sources, limits, unresolved = validate_closure(
        load_closure(closure_path),
        repo_root,
    )
    print(
        "Audit closure valid: "
        f"source_groups={sources}, limits={limits}, unresolved_global={unresolved}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
