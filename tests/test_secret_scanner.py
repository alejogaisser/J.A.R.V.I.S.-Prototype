from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.check_secrets import (
    GitScanError,
    forbidden_path_rule,
    scan_blob,
    scan_repository,
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _repository(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "tests@example.invalid")
    _git(tmp_path, "config", "user.name", "JARVIS Tests")
    (tmp_path / "safe.txt").write_text("safe\n", encoding="utf-8")
    _git(tmp_path, "add", "safe.txt")
    _git(tmp_path, "commit", "-q", "-m", "baseline")
    return tmp_path


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (".env", "forbidden_env_file"),
        ("config/.env.local", "forbidden_env_file"),
        ("config/api_keys.json", "forbidden_sensitive_file"),
        ("config/certs/client.pem", "forbidden_sensitive_path"),
        ("logs/runtime.jsonl", "forbidden_sensitive_path"),
        ("debug.log", "forbidden_log_file"),
        ("memory/long_term.json.bak", "forbidden_memory_file"),
        ("config/api_keys.example.json", None),
        ("docs/logging.md", None),
    ],
)
def test_forbidden_path_policy(path: str, expected: str | None):
    assert forbidden_path_rule(path) == expected


@pytest.mark.parametrize(
    ("rule", "secret"),
    [
        ("google_api_key", "AIza" + "A" * 35),
        ("github_token", "ghp_" + "b" * 36),
        ("openai_api_key", "sk-proj-" + "c" * 24),
        ("aws_access_key", "AKIA" + "D" * 16),
        ("slack_token", "xoxb-" + "1" * 12 + "-" + "e" * 20),
        ("private_key", "-----BEGIN " + "PRIVATE KEY-----"),
    ],
)
def test_secret_shapes_are_reported_without_echoing_values(rule: str, secret: str):
    findings = scan_blob("sample.txt", secret.encode(), source="test")

    assert [finding.rule for finding in findings] == [rule]
    assert secret not in findings[0].display()


def test_binary_content_is_not_decoded_but_forbidden_path_still_fails():
    findings = scan_blob(
        "config/certs/private.bin",
        b"\x00" + ("sk-" + "x" * 24).encode(),
        source="test",
    )

    assert [finding.rule for finding in findings] == ["forbidden_sensitive_path"]


def test_untracked_content_is_outside_versioned_scan(tmp_path: Path):
    repo = _repository(tmp_path)
    (repo / "scratch.txt").write_text("ghp_" + "z" * 36, encoding="utf-8")

    assert scan_repository(repo) == []


def test_staged_blob_wins_over_a_clean_worktree_copy(tmp_path: Path):
    repo = _repository(tmp_path)
    path = repo / "candidate.txt"
    path.write_text("sk-proj-" + "x" * 24, encoding="utf-8")
    _git(repo, "add", "candidate.txt")
    path.write_text("safe in worktree\n", encoding="utf-8")

    findings = scan_repository(repo)

    assert [(item.path, item.rule, item.source) for item in findings] == [
        ("candidate.txt", "openai_api_key", "staged")
    ]


def test_staged_forbidden_filename_is_rejected(tmp_path: Path):
    repo = _repository(tmp_path)
    path = repo / ".env.production"
    path.write_text("placeholder=true\n", encoding="utf-8")
    _git(repo, "add", ".env.production", "-f")

    findings = scan_repository(repo)

    assert [(item.path, item.rule) for item in findings] == [
        (".env.production", "forbidden_env_file")
    ]


def test_non_repository_fails_closed(tmp_path: Path):
    with pytest.raises(GitScanError):
        scan_repository(tmp_path)


def test_subdirectory_is_not_accepted_as_repository_root(tmp_path: Path):
    repo = _repository(tmp_path)
    subdirectory = repo / "nested"
    subdirectory.mkdir()

    with pytest.raises(GitScanError, match="top-level"):
        scan_repository(subdirectory)
