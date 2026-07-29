"""Containment contracts for model-assisted development agents."""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

_SAFE_PROJECT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_SAFE_DEPENDENCY = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]*(?:\[[A-Za-z0-9_,.-]+\])?"
    r"(?:\s*(?:===|==|~=|>=|<=|>|<)\s*[A-Za-z0-9.*+!_-]+)?$"
)


class AgentStatus(str, Enum):
    PREVIEW_READY = "preview_ready"
    REJECTED = "rejected"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AgentContainmentError(RuntimeError):
    """Base error for rejected or failed contained agent work."""


class AgentPlanRejected(AgentContainmentError):
    pass


class AgentBudgetExceeded(AgentContainmentError):
    pass


class AgentWorkspaceEscape(AgentContainmentError):
    pass


@dataclass(frozen=True, slots=True)
class AgentBudget:
    max_files: int = 24
    max_file_bytes: int = 256_000
    max_total_bytes: int = 1_000_000
    max_result_chars: int = 12_000
    timeout_seconds: float = 90.0

    def __post_init__(self) -> None:
        if self.max_files <= 0:
            raise ValueError("Agent file budget must be positive.")
        if self.max_file_bytes <= 0 or self.max_total_bytes <= 0:
            raise ValueError("Agent byte budgets must be positive.")
        if self.max_file_bytes > self.max_total_bytes:
            raise ValueError("Per-file budget cannot exceed total byte budget.")
        if self.max_result_chars <= 0:
            raise ValueError("Agent result budget must be positive.")
        if self.timeout_seconds <= 0:
            raise ValueError("Agent timeout must be positive.")


@dataclass(frozen=True, slots=True)
class AgentTask:
    request_id: str
    description: str
    workspace_root: Path
    project_name: str
    language: str = "python"
    allowed_dependencies: frozenset[str] = field(default_factory=frozenset)
    budget: AgentBudget = field(default_factory=AgentBudget)

    def __post_init__(self) -> None:
        if not self.request_id.strip():
            raise ValueError("Agent task requires a request_id.")
        if not self.description.strip():
            raise ValueError("Agent task requires a description.")
        if not _SAFE_PROJECT_NAME.fullmatch(self.project_name):
            raise ValueError("Project name must be a safe relative label.")
        if self.language.lower() not in {"python", "javascript", "typescript"}:
            raise ValueError("Agent language is not allowlisted.")


@dataclass(frozen=True, slots=True)
class AgentResult:
    request_id: str
    status: AgentStatus
    message: str
    workspace: Path | None
    files_written: tuple[str, ...] = ()
    total_bytes: int = 0
    rollback_performed: bool = False
    evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.request_id.strip():
            raise ValueError("Agent result requires a request_id.")
        if self.total_bytes < 0:
            raise ValueError("Agent result byte count cannot be negative.")


class AgentSupervisor:
    """Validate a model plan and own all writes made by one agent task.

    Generated code is intentionally not executed here. A workspace boundary is
    not an operating-system sandbox, so execution and dependency installation
    require a separate, explicitly approved tool path.
    """

    def __init__(
        self,
        task: AgentTask,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.task = task
        self._clock = clock
        self._started_at = clock()
        self._root = task.workspace_root.resolve(strict=True)
        if not self._root.is_dir():
            raise AgentWorkspaceEscape("Agent workspace root must be a directory.")
        self.workspace = self._resolve_below(self._root / task.project_name)
        if self.workspace.exists() and any(self.workspace.iterdir()):
            raise AgentPlanRejected(
                "Agent workspace must be new or empty; existing projects require "
                "a separate edit workflow."
            )
        self._files_written: list[Path] = []
        self._created_directories: set[Path] = set()
        self._total_bytes = 0

    def validate_plan(self, plan: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
        """Return normalized file descriptors or reject the untrusted plan."""
        self.checkpoint()
        raw_files = plan.get("files")
        if not isinstance(raw_files, Sequence) or isinstance(
            raw_files, (str, bytes)
        ):
            raise AgentPlanRejected("Agent plan must contain a file list.")
        if not raw_files or len(raw_files) > self.task.budget.max_files:
            raise AgentBudgetExceeded("Agent plan exceeds the file budget.")

        dependencies = plan.get("dependencies", [])
        if not isinstance(dependencies, Sequence) or isinstance(
            dependencies, (str, bytes)
        ):
            raise AgentPlanRejected("Agent dependencies must be a list.")
        normalized_dependencies = tuple(str(item).strip() for item in dependencies)
        for dependency in normalized_dependencies:
            if (
                not _SAFE_DEPENDENCY.fullmatch(dependency)
                or dependency not in self.task.allowed_dependencies
            ):
                raise AgentPlanRejected(
                    f"Dependency is not explicitly allowlisted: {dependency!r}."
                )

        normalized: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in raw_files:
            if not isinstance(item, Mapping):
                raise AgentPlanRejected("Every planned file must be an object.")
            raw_path = str(item.get("path", "")).strip()
            target = self.resolve_file(raw_path)
            relative = target.relative_to(self.workspace).as_posix()
            if relative in seen:
                raise AgentPlanRejected(f"Duplicate planned file: {relative}.")
            seen.add(relative)
            normalized.append(
                {
                    "path": relative,
                    "description": str(item.get("description", ""))[:1000],
                    "imports": tuple(str(value) for value in item.get("imports", ())),
                }
            )

        entry_point = str(plan.get("entry_point", "")).strip()
        if entry_point not in seen:
            raise AgentPlanRejected("Entry point must be one of the planned files.")
        if plan.get("run_command"):
            raise AgentPlanRejected(
                "Model-provided run commands are not accepted; execution needs "
                "a separate approved tool call."
            )
        return tuple(normalized)

    def resolve_file(self, relative_path: str) -> Path:
        if not relative_path or "\x00" in relative_path:
            raise AgentPlanRejected("Agent file path is empty or invalid.")
        candidate = Path(relative_path)
        if candidate.is_absolute():
            raise AgentWorkspaceEscape("Agent file paths must be relative.")
        target = self._resolve_below(self.workspace / candidate)
        if target != self.workspace and self.workspace not in target.parents:
            raise AgentWorkspaceEscape("Agent file must stay inside its project.")
        if target == self.workspace:
            raise AgentPlanRejected("Agent file path must name a file.")
        return target

    def write_text(self, relative_path: str, content: str) -> Path:
        self.checkpoint()
        if len(self._files_written) >= self.task.budget.max_files:
            raise AgentBudgetExceeded("Agent file budget exhausted.")
        encoded = content.encode("utf-8")
        if len(encoded) > self.task.budget.max_file_bytes:
            raise AgentBudgetExceeded("Generated file exceeds its byte budget.")
        if self._total_bytes + len(encoded) > self.task.budget.max_total_bytes:
            raise AgentBudgetExceeded("Agent total byte budget exhausted.")

        target = self.resolve_file(relative_path)
        if target.exists():
            raise AgentPlanRejected(
                "Agent refuses to overwrite an existing file without a separate "
                "preview and confirmation."
            )
        self._create_parent_directories(target.parent)
        target.write_text(content, encoding="utf-8")
        self._files_written.append(target)
        self._total_bytes += len(encoded)
        return target

    def preview_result(self, message: str) -> AgentResult:
        self.checkpoint()
        return AgentResult(
            request_id=self.task.request_id,
            status=AgentStatus.PREVIEW_READY,
            message=self._bounded_message(message),
            workspace=self.workspace,
            files_written=tuple(
                path.relative_to(self.workspace).as_posix()
                for path in self._files_written
            ),
            total_bytes=self._total_bytes,
            evidence=(
                "workspace_resolved",
                "plan_validated",
                "generated_code_not_executed",
                "dependencies_not_installed",
            ),
        )

    def rejected_result(self, error: BaseException) -> AgentResult:
        rollback = self.rollback()
        return AgentResult(
            request_id=self.task.request_id,
            status=(
                AgentStatus.REJECTED
                if isinstance(error, AgentContainmentError)
                else AgentStatus.FAILED
            ),
            message=self._bounded_message(f"{type(error).__name__}: {error}"),
            workspace=self.workspace,
            total_bytes=self._total_bytes,
            rollback_performed=rollback,
            evidence=("agent_work_blocked", "owned_files_rolled_back"),
        )

    def rollback(self) -> bool:
        changed = False
        for path in reversed(self._files_written):
            try:
                path.unlink(missing_ok=True)
                changed = True
            except OSError:
                continue
        for directory in sorted(
            self._created_directories,
            key=lambda item: len(item.parts),
            reverse=True,
        ):
            try:
                directory.rmdir()
            except OSError:
                continue
        self._files_written.clear()
        return changed

    def checkpoint(self) -> None:
        if self._clock() - self._started_at > self.task.budget.timeout_seconds:
            raise AgentBudgetExceeded("Agent task exceeded its time budget.")

    def _resolve_below(self, candidate: Path) -> Path:
        resolved = candidate.resolve(strict=False)
        if resolved != self._root and self._root not in resolved.parents:
            raise AgentWorkspaceEscape("Agent path must stay inside its workspace.")
        return resolved

    def _create_parent_directories(self, parent: Path) -> None:
        missing: list[Path] = []
        current = parent
        while not current.exists() and current != self.workspace.parent:
            missing.append(current)
            current = current.parent
        parent.mkdir(parents=True, exist_ok=True)
        self._created_directories.update(missing)

    def _bounded_message(self, message: str) -> str:
        limit = self.task.budget.max_result_chars
        return message if len(message) <= limit else f"{message[:limit]}…"
