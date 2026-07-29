param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$QualityFiles = @(
    "config/settings.py",
    "core/diagnostics.py",
    "core/request_audit.py",
    "core/request_context.py",
    "core/structured_logging.py",
    "scripts/check_secrets.py",
    "tests/test_secret_scanner.py",
    "tests/test_settings.py",
    "tests/test_structured_logging.py"
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
