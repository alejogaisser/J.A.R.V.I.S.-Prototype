from __future__ import annotations

import ast
import io
import json
import logging
from pathlib import Path

from core.request_context import InputSource, RequestContext
from core.structured_logging import StructuredRuntimeLog


def _events(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def test_writes_sanitized_json_to_file_and_console(tmp_path: Path):
    path = tmp_path / "runtime.jsonl"
    console = io.StringIO()
    runtime_log = StructuredRuntimeLog(path, stream=console)
    context = RequestContext.create(InputSource.UI, tool_call_id="fc-safe")

    written = runtime_log.record(
        "tool_completed",
        level=logging.WARNING,
        component="tools",
        message="api_key=do-not-log",
        context=context,
        metadata={
            "duration_ms": 12.34567,
            "status": "verified",
            "content": "private body",
        },
    )
    runtime_log.close()

    assert written
    event = _events(path)[0]
    assert event["request_id"] == context.request_id
    assert event["source"] == "ui"
    assert event["tool_call_id"] == "fc-safe"
    assert event["duration_ms"] == 12.346
    assert event["status"] == "verified"
    assert event["message"] == "api_key=[REDACTED]"
    assert "content" not in event
    assert "do-not-log" not in path.read_text(encoding="utf-8")
    assert "do-not-log" not in console.getvalue()


def test_redacts_high_confidence_token_shapes(tmp_path: Path):
    path = tmp_path / "runtime.jsonl"
    token = "ghp_" + ("z" * 36)
    runtime_log = StructuredRuntimeLog(path, console=False)

    assert runtime_log.record("provider_failed", message=f"credential={token}")
    runtime_log.close()

    content = path.read_text(encoding="utf-8")
    assert token not in content
    assert "[REDACTED_CREDENTIAL]" in content


def test_rotates_file_with_bounded_backups(tmp_path: Path):
    path = tmp_path / "runtime.jsonl"
    runtime_log = StructuredRuntimeLog(
        path,
        console=False,
        max_bytes=256,
        backup_count=2,
    )

    for index in range(20):
        assert runtime_log.record(
            "rotation_probe",
            message=f"event-{index}-" + ("x" * 80),
        )
    runtime_log.close()

    assert path.exists()
    assert path.with_suffix(".jsonl.1").exists()
    assert len(list(tmp_path.glob("runtime.jsonl*"))) <= 3


def test_invalid_file_target_does_not_prevent_startup(tmp_path: Path):
    console = io.StringIO()
    runtime_log = StructuredRuntimeLog(tmp_path, console=False, stream=console)

    assert not runtime_log.available
    assert not runtime_log.record("startup")


def test_console_remains_available_when_file_target_fails(tmp_path: Path):
    console = io.StringIO()
    runtime_log = StructuredRuntimeLog(tmp_path, stream=console)

    assert runtime_log.available
    assert runtime_log.record("startup", component="main")
    runtime_log.close()

    event = json.loads(console.getvalue())
    assert event["event"] == "startup"
    assert event["component"] == "main"


def test_main_configures_logging_at_composition_root():
    source = Path("main.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    runtime_events = {
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "runtime_log"
        and node.func.attr == "record"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    }

    assert "StructuredRuntimeLog()" in source
    assert {"application_started", "runner_failed", "application_stopped"} <= runtime_events
