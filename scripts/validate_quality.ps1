param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$QualityFiles = @(
    "config/settings.py",
    "core/diagnostics.py",
    "core/events.py",
    "core/request_audit.py",
    "core/request_context.py",
    "core/structured_logging.py",
    "services/agents.py",
    "services/audio.py",
    "services/lifecycle.py",
    "services/runtime.py",
    "services/session.py",
    "services/vision.py",
    "services/workers.py",
    "scripts/check_secrets.py",
    "tests/test_secret_scanner.py",
    "tests/test_settings.py",
    "tests/test_structured_logging.py",
    "tests/test_runtime_events.py",
    "tests/test_agent_supervisor.py",
    "tests/test_worker_supervisor.py"
)

Write-Host "==> Ruff (migrated surface)"
& $Python -m ruff check @QualityFiles
if ($LASTEXITCODE -ne 0) {
    throw "Ruff failed with exit code $LASTEXITCODE"
}

Write-Host "==> mypy (typed production surface)"
& $Python -m mypy
if ($LASTEXITCODE -ne 0) {
    throw "mypy failed with exit code $LASTEXITCODE"
}

Write-Host "Incremental quality validation completed successfully."
