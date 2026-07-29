"""Fail closed when versioned Git content contains likely credentials.

The scanner reports only rule names and locations. It never prints the matched
value, which keeps CI and local validation output safe to share.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable


_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    (
        "github_token",
        re.compile(r"\b(?:gh[pousr]_[0-9A-Za-z]{36,255}|github_pat_[0-9A-Za-z_]{20,255})\b"),
    ),
    (
        "openai_api_key",
        re.compile(r"\bsk-(?:(?:proj|svcacct)-)?[0-9A-Za-z_-]{20,}\b"),
    ),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{20,}\b")),
    (
        "private_key",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    ),
)

_FORBIDDEN_EXACT = {
    "config/api_keys.json",
    "config/connector_audit.jsonl",
    "config/google_oauth_client.json",
    "config/microsoft_oauth_client.json",
    "memory/long_term.json",
    "memory/scripts.json",
}
_FORBIDDEN_PREFIXES = ("config/certs/", "logs/")


@dataclass(frozen=True, slots=True)
class Finding:
    path: str
    rule: str
    line: int | None = None
    source: str = "working-tree"

    def display(self) -> str:
        location = self.path if self.line is None else f"{self.path}:{self.line}"
        return f"{location}: {self.rule} ({self.source})"


class GitScanError(RuntimeError):
    """Git state could not be read safely."""


def normalize_git_path(path: str) -> str:
    normalized = PurePosixPath(path.replace("\\", "/")).as_posix()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized.lstrip("/")


def forbidden_path_rule(path: str) -> str | None:
    normalized = normalize_git_path(path).casefold()
    name = PurePosixPath(normalized).name
    if name == ".env" or name.startswith(".env."):
        return "forbidden_env_file"
    if normalized in _FORBIDDEN_EXACT:
        return "forbidden_sensitive_file"
    if normalized.startswith(_FORBIDDEN_PREFIXES):
        return "forbidden_sensitive_path"
    if normalized.endswith(".log"):
        return "forbidden_log_file"
    if normalized.startswith("memory/long_term.json."):
        return "forbidden_memory_file"
    return None


def scan_text(path: str, text: str, *, source: str) -> list[Finding]:
    findings: list[Finding] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for rule, pattern in _SECRET_PATTERNS:
            if pattern.search(line):
                findings.append(
                    Finding(
                        path=normalize_git_path(path),
                        rule=rule,
                        line=line_number,
                        source=source,
                    )
                )
    return findings


def scan_blob(path: str, content: bytes, *, source: str) -> list[Finding]:
    path_rule = forbidden_path_rule(path)
    findings = (
        [Finding(normalize_git_path(path), path_rule, source=source)]
        if path_rule
        else []
    )
    if b"\x00" in content[:8192]:
        return findings
    text = content.decode("utf-8", errors="replace")
    findings.extend(scan_text(path, text, source=source))
    return findings


def _run_git(repo_root: Path, *args: str) -> bytes:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=15,
        )
    except subprocess.TimeoutExpired as exc:
        raise GitScanError(f"git {' '.join(args)} timed out") from exc
    if completed.returncode:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise GitScanError(detail or f"git {' '.join(args)} failed")
    return completed.stdout


def _nul_paths(raw: bytes) -> tuple[str, ...]:
    return tuple(
        item.decode("utf-8", errors="surrogateescape")
        for item in raw.split(b"\0")
        if item
    )


def _safe_worktree_blob(repo_root: Path, path: str) -> bytes | None:
    root = repo_root.resolve()
    candidate = (root / Path(path)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise GitScanError(f"tracked path escapes repository: {path}") from exc
    if not candidate.is_file():
        return None
    return candidate.read_bytes()


def scan_repository(repo_root: Path) -> list[Finding]:
    root = repo_root.resolve()
    top_level = Path(
        _run_git(root, "rev-parse", "--show-toplevel")
        .decode("utf-8", errors="replace")
        .strip()
    ).resolve()
    if top_level != root:
        raise GitScanError("--repo-root must point to the Git top-level directory")
    tracked = _nul_paths(_run_git(root, "ls-files", "-z"))
    staged = set(
        _nul_paths(
            _run_git(
                root,
                "diff",
                "--cached",
                "--name-only",
                "--diff-filter=ACMR",
                "-z",
            )
        )
    )

    findings: list[Finding] = []
    for path in tracked:
        if path in staged:
            content = _run_git(root, "show", f":{path}")
            source = "staged"
        else:
            content = _safe_worktree_blob(root, path)
            source = "working-tree"
            if content is None:
                continue
        findings.extend(scan_blob(path, content, source=source))
    return findings


def _sorted_findings(findings: Iterable[Finding]) -> list[Finding]:
    return sorted(
        findings,
        key=lambda item: (item.path.casefold(), item.line or 0, item.rule),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scan tracked and staged Git content for likely secrets."
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="Repository root (defaults to the current directory).",
    )
    args = parser.parse_args(argv)

    try:
        findings = _sorted_findings(scan_repository(args.repo_root))
    except (GitScanError, OSError) as exc:
        print(f"Secret scan failed closed: {exc}", file=sys.stderr)
        return 2

    if findings:
        print(f"Secret scan blocked: {len(findings)} finding(s).", file=sys.stderr)
        for finding in findings:
            print(f"  {finding.display()}", file=sys.stderr)
        return 1

    print("Secret scan passed: tracked and staged content is clean.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
