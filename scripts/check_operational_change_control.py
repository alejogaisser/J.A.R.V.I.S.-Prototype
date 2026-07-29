from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

EXPECTED_CONTROL_IDS = frozenset(
    {
        *(f"OP-{index:02d}" for index in range(1, 12)),
        *(f"REF-{index:02d}" for index in range(1, 9)),
    }
)
VALID_VERIFICATION = frozenset({"automated", "documented", "manual"})
VALID_ABSTRACTION_BENEFITS = frozenset(
    {
        "eliminates_duplication",
        "reduces_authority",
        "verifies_effect",
        "simplifies_test",
        "no_new_abstraction",
    }
)
VALID_REAL_BEHAVIOR = frozenset(
    {"automated_without_hardware", "manual_hardware", "mixed"}
)
VALID_POLICY_ROUTES = frozenset({"central", "partial", "not_applicable"})
VALID_OUTCOMES = frozenset({"passed", "failed", "pending"})
SENSITIVE_PREFIXES = (
    ".env",
    "config/api_keys.json",
    "config/certs",
    "config/google_oauth_client.json",
    "config/microsoft_oauth_client.json",
    "memory/long_term.json",
    "logs",
)
REQUIRED_CHANGE_FIELDS = frozenset(
    {
        "phase",
        "title",
        "motivation",
        "objective",
        "files",
        "risks",
        "tests",
        "metrics",
        "rollback",
        "owner",
        "policy_route",
        "effect_verification",
        "cancellation_timeout_reconnect",
        "compatibility",
        "abstraction_benefit",
        "real_behavior",
        "limitations",
        "destructive",
        "confirmation",
        "preview",
        "obsidian_note",
    }
)


def load_contract(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise ValueError("Unsupported operational change-control contract")
    return payload


def _resolve_repo_path(repo_root: Path, raw_path: object, label: str) -> Path:
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


def _completed_phases(roadmap: Path, start: int) -> set[int]:
    source = roadmap.read_text(encoding="utf-8")
    matches = list(re.finditer(r"(?m)^### Fase (\d+) - .+$", source))
    completed: set[int] = set()
    for index, match in enumerate(matches):
        phase = int(match.group(1))
        if phase < start:
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(source)
        block = source[match.end() : end]
        if re.search(r"\*\*Estado:\*\*\s+completad[ao]", block, re.IGNORECASE):
            completed.add(phase)
    return completed


def _validate_controls(controls: object, repo_root: Path) -> None:
    if not isinstance(controls, list) or not all(
        isinstance(control, dict) for control in controls
    ):
        raise TypeError("controls must be a list of objects")
    identifiers = [str(control.get("id")) for control in controls]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("Operational control IDs must be unique")
    if set(identifiers) != EXPECTED_CONTROL_IDS:
        missing = sorted(EXPECTED_CONTROL_IDS - set(identifiers))
        extra = sorted(set(identifiers) - EXPECTED_CONTROL_IDS)
        raise ValueError(f"Operational control mismatch; missing={missing}, extra={extra}")

    for control in controls:
        identifier = str(control["id"])
        if not str(control.get("statement", "")).strip():
            raise ValueError(f"{identifier}: statement is required")
        if control.get("verification") not in VALID_VERIFICATION:
            raise ValueError(f"{identifier}: invalid verification mode")
        evidence = control.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            raise ValueError(f"{identifier}: evidence is required")
        for raw_path in evidence:
            _resolve_repo_path(repo_root, raw_path, identifier)


def _validate_test(test: object, label: str) -> None:
    if not isinstance(test, dict):
        raise TypeError(f"{label}: tests must contain objects")
    if test.get("scope") not in {"directed", "integration", "smoke", "baseline"}:
        raise ValueError(f"{label}: invalid test scope")
    if test.get("outcome") not in VALID_OUTCOMES:
        raise ValueError(f"{label}: invalid test outcome")
    if not str(test.get("command", "")).strip() or not str(test.get("result", "")).strip():
        raise ValueError(f"{label}: test command and result are required")


def _validate_change(change: object, repo_root: Path, completed: bool) -> int:
    if not isinstance(change, dict):
        raise TypeError("changes must contain objects")
    missing = REQUIRED_CHANGE_FIELDS - set(change)
    if missing:
        raise ValueError(f"Change record is missing fields: {sorted(missing)}")
    phase = change.get("phase")
    if not isinstance(phase, int) or phase < 0:
        raise ValueError("Change phase must be a non-negative integer")
    label = f"phase {phase}"

    for field in (
        "title",
        "motivation",
        "objective",
        "rollback",
        "owner",
        "effect_verification",
        "cancellation_timeout_reconnect",
        "compatibility",
        "limitations",
    ):
        if not str(change.get(field, "")).strip():
            raise ValueError(f"{label}: {field} is required")

    files = change.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError(f"{label}: files are required")
    for raw_path in files:
        normalized = str(raw_path).replace("\\", "/").casefold()
        if any(
            normalized == prefix or normalized.startswith(f"{prefix}/")
            for prefix in SENSITIVE_PREFIXES
        ):
            raise ValueError(f"{label}: sensitive file cannot be recorded")
        _resolve_repo_path(repo_root, raw_path, label)

    for field in ("risks", "metrics"):
        values = change.get(field)
        if not isinstance(values, list) or not values or not all(
            str(value).strip() for value in values
        ):
            raise ValueError(f"{label}: {field} must be a non-empty string list")

    tests = change.get("tests")
    if not isinstance(tests, list) or not tests:
        raise ValueError(f"{label}: tests are required")
    for test in tests:
        _validate_test(test, label)
    if completed and any(test.get("outcome") != "passed" for test in tests):
        raise ValueError(f"{label}: completed phases cannot retain pending or failed tests")

    if change.get("policy_route") not in VALID_POLICY_ROUTES:
        raise ValueError(f"{label}: invalid policy route")
    if change.get("abstraction_benefit") not in VALID_ABSTRACTION_BENEFITS:
        raise ValueError(f"{label}: invalid abstraction benefit")
    if change.get("real_behavior") not in VALID_REAL_BEHAVIOR:
        raise ValueError(f"{label}: invalid real-behavior classification")
    if change.get("obsidian_note") not in {"updated", "pending", "not_applicable"}:
        raise ValueError(f"{label}: invalid Obsidian status")
    if completed and change.get("obsidian_note") != "updated":
        raise ValueError(f"{label}: completed phases must record the Obsidian update")

    destructive = change.get("destructive")
    if not isinstance(destructive, bool):
        raise TypeError(f"{label}: destructive must be boolean")
    if destructive:
        if change.get("confirmation") != "required":
            raise ValueError(f"{label}: destructive changes require confirmation")
        if change.get("preview") not in {"required", "available"}:
            raise ValueError(f"{label}: destructive changes require a preview")
    return phase


def validate_contract(payload: dict[str, Any], repo_root: Path) -> tuple[int, int]:
    start = payload.get("enforcement_start_phase")
    if not isinstance(start, int) or start < 0:
        raise ValueError("enforcement_start_phase must be a non-negative integer")
    _validate_controls(payload.get("controls"), repo_root)

    completed_phases = _completed_phases(repo_root / "ROADMAP.md", start)
    changes = payload.get("changes")
    if not isinstance(changes, list):
        raise TypeError("changes must be a list")
    recorded: list[int] = []
    for change in changes:
        phase_value = change.get("phase") if isinstance(change, dict) else None
        recorded.append(
            _validate_change(
                change,
                repo_root,
                completed=isinstance(phase_value, int) and phase_value in completed_phases,
            )
        )
    if len(recorded) != len(set(recorded)):
        raise ValueError("Each phase must have exactly one change record")
    recorded_set = set(recorded)
    if completed_phases - recorded_set:
        raise ValueError(
            f"Completed phases lack change records: {sorted(completed_phases - recorded_set)}"
        )
    expected_sequence = set(range(start, max(recorded_set, default=start - 1) + 1))
    if recorded_set != expected_sequence:
        raise ValueError("Change records must be sequential from the enforcement floor")
    return len(EXPECTED_CONTROL_IDS), len(recorded)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate operational change control.")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--contract",
        type=Path,
        default=Path("docs/operational_change_control.json"),
    )
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    contract_path = args.contract
    if not contract_path.is_absolute():
        contract_path = repo_root / contract_path
    controls, changes = validate_contract(load_contract(contract_path), repo_root)
    print(f"Operational change control valid: controls={controls}, changes={changes}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
