from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

EXPECTED_IDS = frozenset(
    {
        "SEC-01",
        "SEC-02",
        "SEC-03",
        "SEC-04",
        "LIFE-01",
        "LIFE-02",
        "LIFE-03",
        "LIFE-04",
        "OBS-01",
        "OBS-02",
        "OBS-03",
        "OBS-04",
        "UI-01",
        "UI-02",
        "UI-03",
        "TEST-01",
        "TEST-02",
        "TEST-03",
        "TEST-04",
    }
)
VALID_STATUSES = frozenset({"verified", "partial", "manual", "blocked"})
VALID_CATEGORIES = frozenset(
    {"tools_security", "state_lifecycle", "observability", "ui_providers", "tests_performance"}
)


def load_matrix(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise ValueError("Unsupported global acceptance matrix")
    return payload


def validate_matrix(payload: dict[str, Any], repo_root: Path) -> Counter[str]:
    criteria = payload.get("criteria")
    if not isinstance(criteria, list):
        raise TypeError("criteria must be a list")
    if not all(isinstance(item, dict) for item in criteria):
        raise TypeError("Each criterion must be an object")

    identifiers: list[str] = [str(item.get("id")) for item in criteria]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("Global acceptance criterion IDs must be unique")
    if set(identifiers) != EXPECTED_IDS:
        missing = sorted(EXPECTED_IDS - set(identifiers))
        extra = sorted(set(identifiers) - EXPECTED_IDS)
        raise ValueError(f"Criterion inventory mismatch; missing={missing}, extra={extra}")

    counts: Counter[str] = Counter()
    resolved_root = repo_root.resolve()
    for item in criteria:
        criterion_id = item["id"]
        status = item.get("status")
        if status not in VALID_STATUSES:
            raise ValueError(f"{criterion_id}: invalid status {status!r}")
        if item.get("category") not in VALID_CATEGORIES:
            raise ValueError(f"{criterion_id}: invalid category")
        if not str(item.get("statement", "")).strip():
            raise ValueError(f"{criterion_id}: statement is required")
        gap = str(item.get("gap", "")).strip()
        if status == "verified" and gap:
            raise ValueError(f"{criterion_id}: verified criteria cannot retain a gap")
        if status != "verified" and not gap:
            raise ValueError(f"{criterion_id}: non-verified criteria must describe the gap")

        evidence = item.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            raise ValueError(f"{criterion_id}: evidence is required")
        for raw_path in evidence:
            path = Path(str(raw_path))
            if path.is_absolute():
                raise ValueError(f"{criterion_id}: evidence paths must be repository-relative")
            resolved = (resolved_root / path).resolve()
            try:
                resolved.relative_to(resolved_root)
            except ValueError as exc:
                raise ValueError(f"{criterion_id}: evidence escapes the repository") from exc
            if not resolved.exists():
                raise ValueError(f"{criterion_id}: missing evidence path {path}")
        counts[status] += 1
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the section 15 acceptance matrix.")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--matrix", type=Path, default=Path("docs/global_acceptance.json"))
    parser.add_argument(
        "--require-complete",
        action="store_true",
        help="Fail unless every global criterion is verified.",
    )
    args = parser.parse_args()

    repo_root = args.repo_root.resolve()
    matrix_path = args.matrix
    if not matrix_path.is_absolute():
        matrix_path = repo_root / matrix_path
    counts = validate_matrix(load_matrix(matrix_path), repo_root)
    ordered = ", ".join(f"{name}={counts[name]}" for name in sorted(VALID_STATUSES))
    print(f"Global acceptance matrix valid: {ordered}")
    if args.require_complete and counts["verified"] != len(EXPECTED_IDS):
        print("Global acceptance is not complete; unresolved criteria remain.")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
