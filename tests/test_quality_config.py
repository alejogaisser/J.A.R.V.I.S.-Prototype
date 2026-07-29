from __future__ import annotations

import tomllib
from pathlib import Path


def test_type_checking_is_limited_to_migrated_production_surface():
    config = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    files = set(config["tool"]["mypy"]["files"])

    assert "core/structured_logging.py" in files
    assert "core/events.py" in files
    assert "services/runtime.py" in files
    assert "services/workers.py" in files
    assert "config/settings.py" in files
    assert "main.py" not in files
    assert all(not path.endswith("/*") for path in files)


def test_quality_script_names_the_incremental_surface():
    source = Path("scripts/validate_quality.ps1").read_text(encoding="utf-8")

    assert "core/structured_logging.py" in source
    assert "core/events.py" in source
    assert "tests/test_runtime_events.py" in source
    assert "tests/test_worker_supervisor.py" in source
    assert "tests/test_secret_scanner.py" in source
    assert "ruff check @QualityFiles" in source
    assert "python -m mypy" not in source


def test_ci_is_bounded_and_uses_the_reproducible_baseline():
    workflow = Path(".github/workflows/quality.yml").read_text(encoding="utf-8")

    assert "timeout-minutes: 30" in workflow
    assert "contents: read" in workflow
    assert "requirements-dev.txt" in workflow
    assert "validate_baseline.ps1" in workflow
    assert "workflow_dispatch" not in workflow
