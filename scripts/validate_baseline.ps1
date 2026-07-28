param(
    [string]$Python = "python",
    [switch]$SkipFullTests
)

$ErrorActionPreference = "Stop"
$env:QT_QPA_PLATFORM = "offscreen"

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Label,
        [Parameter(Mandatory = $true)]
        [scriptblock]$Command
    )

    Write-Host "==> $Label"
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE"
    }
}

Invoke-Checked "Dependency consistency" {
    & $Python -m pip check
}
Invoke-Checked "Launcher help" {
    & $Python jarvis_launcher.py --help
}
Invoke-Checked "Core smoke imports" {
    $smokeImports = "import core.live_session, core.permissions, core.tools, jarvis_launcher, memory.memory_manager, wake_word; print(1)"
    & $Python -c $smokeImports
}
Invoke-Checked "Main import and tool count (Qt offscreen)" {
    $mainImport = "import main; assert len(main.TOOL_DECLARATIONS) == 37; print(len(main.TOOL_DECLARATIONS))"
    & $Python -c $mainImport
}
Invoke-Checked "Python syntax" {
    & $Python -m compileall -q actions config connectors core dashboard memory tests ui_mk2 utils main.py ui.py wake_word.py jarvis_launcher.py
}
Invoke-Checked "Tool inventory contract" {
    & $Python -m pytest -q tests/test_tool_inventory.py
}

if (-not $SkipFullTests) {
    Invoke-Checked "Full test suite" {
        & $Python -m pytest -q
    }
}

Invoke-Checked "Git whitespace check" {
    git diff --check
}

Write-Host "Baseline validation completed successfully."
