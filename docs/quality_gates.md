# Incremental quality and CI

## Objective

Incorporate reproducible controls without requiring that all historical debt be
solve in a single stage. The surface only grows when another module obtains
contracts and sufficient types.

## Tools

`requirements-dev.txt` states:

- Ruff for imports, syntax errors, indefinite names and bug patterns;
- mypy for typed contracts;
- pytest for behavior.

`pyproject.toml` maintains the configuration. No rules are enabled
modernization that force external refactors.

## Scope

`scripts/validate_quality.ps1` delivers an explicit list of modules to Ruff
Mypy initially used six production modules;
Phase 11 extends the list to twelve with `core.events` and the five owner modules;
Phase 12 adds `services.workers` as production module number thirteen and Phase 13
incorporates `services.agents` as production contract number fourteen.
inspect `main.py`, `ui.py`, audio hardware and legacy actions until
migrate them one boundary at a time.

The Phase 14 isolated benchmark and its tests also go through Ruff. Not added
to mypy because it is reproducible instrumentation, not a productive contract.
baseline includes `benchmarks/` in `compileall`.

Phase 15 incorporates `scripts/check_global_acceptance.py` to Ruff and mypy, and its
test Ruff. The baseline executes the gate in integrity mode: it requires the 19
PDF criteria and valid local evidence, without confusing that control with the
strict closing of manual or partial gaps.

Phase 16 adds `scripts/check_operational_change_control.py` to Ruff/mypy and its
Ruff test. The baseline requires all 19 operational controls and a record
structured by phase completed since the 15th.

Phase 17 adds `scripts/check_audit_closure.py` to Ruff/mypy and its Ruff test.
The baseline retains the eight groups of sources, five boundaries and the state of
Open risks synchronized with global acceptance.

Implementation:

```powershell
.\scripts\validate_quality.ps1 -Python python
```

`scripts/validate_baseline.ps1` incorporates the same gate before scanning
secrets and the suite.

## CI

`.github/workflows/quality.yml` is activated for pushes to `main`,
`codex/**` and pull requests. Use:

- Windows, the main platform verified;
- Python 3.12;
- versioned dependencies;
- `contents: read` permissions;
- 30-minute timeout;
- the complete reproducible baseline.

It doesn't get credentials, it doesn't start direct/wake modes, and it doesn't access hardware,
Gemini doesn't even count.

## Expansion

To add a module:

1. correct it and add evidence within a stage of its own;
2. add it to `$QualityFiles`;
3. add it to `tool.mypy.files` only if your productive contract is typed;
4. execute the complete baseline;
5. document any omitted rule.

## Rollback

Withdrawing temporarily the call from the baseline or the workflow does not change runtime,
but removes a regression barrier. Ruff/mypy can be reversed by removing its
`requirements-dev.txt` entries; did not generate mass formatting or changes in
interfaces.
