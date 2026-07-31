# Reproducible baseline

## Scope

This base line covers installation, imports, syntax, non-interactive booting and
Automated suite. Do not open Gemini Live nor use microphone, camera, browser,
accounts, LAN dashboard or tools with real effects.

Reference environment audited on 2026-07-28:

- Windows 10/11, 64 bits;
- Python 3.14.6;
- 37 tool statements;
- 213 tests and 65 subtests approved from a worktree and virtual environment
clean after this stage;
- an external warning from `google-genai` on Python 3.17.

Python 3.12 is the recommended version for a new installation.
3.13-3.14 is supported when all the wheels of the dependencies are
available for Windows.

## Clean installation

From PowerShell, at the root of the repository:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
python -m playwright install chromium
Copy-Item config\api_keys.example.json config\api_keys.json
```

The configuration copy serves only as a template. The base line check
does not need a real key and must never be versioned `config/api_keys.json`.

## Reproducible validation

With the active virtual environment:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\validate_baseline.ps1
```

An explicit interpreter may also be indicated:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\validate_baseline.ps1 `
  -Python .\.venv\Scripts\python.exe
```

For a quick iteration that keeps all the checkups except the suite
complete:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\validate_baseline.ps1 `
  -Python .\.venv\Scripts\python.exe -SkipFullTests
```

The command executes, in order:

1. `python -m pip check`;
2. `python jarvis_launcher.py --help`;
3. kernel, launcher, memory and wake word imports;
4. import of `main.py` with Qt offscreen and 37 tool check;
5. `compileall` on code and tests;
6. tool inventory contract;
7. complete suite, except for use of `-SkipFullTests`;
8. `git diff --check`.

## Capacities and dependencies

`requirements.txt` represents the main published runtime.
`requirements-dev.txt` includes it and adds `pytest`, necessary to run the
suite and validation command. Some routes
Advanced processing load optional dependencies only when used.
The audit detected optional imports of `python-docx`, `pandas`, `openpyxl`,
`PyPDF2`/`pdfplumber`, `pydub`, `faster-whisper`, `kokoro`, `miniaudio` and
`torch`. They are not added to the main set until verified by capacity:

- the route can be reached from a registered tool;
- there is a supported Python-compatible wheel;
- the installation cost is proportional;
- the absence produces a clear error and not a boot failure.

`beautifulsoup4` remains declared although no use of runtime was observed.
Retirement is pending pending confirmation that it is not a planned
an optional capacity.

## Behaviour baseline

| Border | Automated check | Limitation |
| --- | --- | --- |
| Launcher | `--help` finishes correctly | Does not initiate child processes |
| Imports | kernel, wake, memory and `main.py` import | Not Validate Hardware |
| UI | `main.py` imports with `QT_QPA_PLATFORM=offscreen` | No visual interaction verified |
| Tools | 37 statements match matrix | Does not execute real effects |
| Syntax | `compileall` of Python Tree | Does not replace lint or type checking |
| Units | `pip check` | Clean installation check is recorded by execution |
| Regressions | Complete suite | Red, Gemini, accounts and SO get jacked |

Wake metrics, interruption, reconnection and shutdown require hardware or
failure specific injection and still pending in `ROADMAP.md`.

## Outcome of the baseline implementation

A new virtual environment was created with Python 3.14.6 and installed
`requirements-dev.txt` and Chromium for Playwright. Full validation
ended with:

- `pip check`: no broken dependencies;
- launcher `--help`: correct;
- smoke imports: correct;
- `main.py` offscreen: correct, 37 tools;
- `compileall`: correct;
- inventory: 1 test and 37 subtests approved;
- Suite: 213 tests and 65 subtests approved;
- `git diff --check`: no errors.

The first clean execution stated that
`tests/test_script_memory.py` depended on `memory/scripts.json`, a file
The test now creates its routine in `TemporaryDirectory`, by
which does not read or modify real memory.

## Rollback

This stage does not modify the runtime. It can be reversed by deleting this document,
the matrix, the synchronization test and the validation script.
