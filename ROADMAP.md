# JARVIS Mark LI incremental roadmap

## Principles of implementation

- Do not rewrite from scratch.
- A phase-by-phase change and a technical frontier at the same time.
- Preserve wake word, audio interrupt, UI, memory, vision, reminders and functional tools.
- Do not withdraw legacy until proven equivalence and rollback.
- Do not start a massive tool migration until you complete a real array of the 37 `ToolDefinition`.
- Before each phase: `git status`, baseline, sensitive files outside the diff and relevant tests.
- Do not commit or push without explicit request.

## Immediate priority

The order of the PDF conforms to the repository's evidence: before introducing general traceability, two security gaps observed in the current dispatch — remote origin and tool classification — must be closed by means of tests that fail first. `RequestContext` and atomic persistence can then be implemented without altering the visual behavior or Gemini protocol.

### Incremental advance - 2026-07-31 - Google API and confirmation flow

- Google file/folder and native Docs, Sheets and Slides creation no longer asks
  for an extra confirmation; edits still use central policy.
- Explicit approval authored in the original local/UI/dashboard request can
  satisfy one non-destructive confirmation. Delete, clear, forget, disconnect,
  remove and trash operations always require a fresh confirmation.
- An identical model retry during the 10 seconds after a confirmed execution
  reuses the sanitized result and cannot execute or request confirmation again.
- `account_connector` now returns `ToolResult` v2, so API exceptions and partial
  file creations cannot be normalized as successes.
- Initial Docs/Sheets/Slides content verification is retained in the creation
  result. Calendar adds API-verified create/update/delete event operations;
  deletion remains `confirm_always`.
- Automated verification uses injected/mocked providers only. Real OAuth smoke
  remains a manual user test because tests must not open accounts or browsers.

### Incremental advance - 2026-07-30

- The OAuth owner of `GoogleDriveConnector` was extended to native content of
Google Docs, Sheets and Slides using an internal injectable service; do not
added a tool or parallel authentication.
- The external creation and editing operations of `account_connector`
now have minimum `confirm_once`; read, search and download remain
Free after OAuth, and disconnect is left in `confirm_always`.
- Added narrow readings, size limits/cells, audit without
bodies and verification by later reading or range/page observed.
- Real Smoke Approved: Docs, Sheets and Slides Completed Creation, Writing and
reading; all three temporary artifacts were sent to wastebasket and
verified as `trashed=true`.
- This completes only the connector risk classification within Phase 1.
The remote end-to-end origin and the rest of the
subclassified tools.

## Phases

### Phase 0 - Reproducible baseline and inventory

- **Status:** completed and integrated into `main` on 2026-07-28 since
`codex/01-baseline-inventory`.
- **Objective:** Document a clean installation, distinguish main/optional/legacy dependencies, measure baseline and complete the array of 37 special tools and paths.
- **Intended files:** `requirements.txt`, `readme.md`, possible `requirements-optional.txt` or extras, `docs/baseline.md`, `docs/tool_migration_matrix.md`, import tests.
- **Risk:** low; a dependency correction can be heavy in Python 3.14.
- **Dependencies:** hardware and a separate clean installation; do not use actual credentials.
- **Criterio of acceptance:** new environment installs; launcher `--help`, imports and UI offscreen work; each tool has return, risk, policy, preview, verify, rollback, timeout, path and registered tests.
- **Tests:** `pip check`, smoke imports, `compileall`, complete suite, installation test in empty environment.
- **Rollback:**reverse only documentation/manifest; do not play runtime.
- **Evidence:** new installation in Python 3.14.6; `requirements-dev.txt`;
`scripts/validate_baseline.ps1`; test synchronized matrix; `pip check`,
launcher, imports, UI offscreen, `compileall`, 213 tests and 65 subtests
Optional units remain explicitly pending.

### Phase 1 - Close source and risk classification

- **Status:** completed and integrated into `main` on 2026-07-28 since
`codex/02-origin-risk`.
- **Objective:** prevent remote entries from being evaluated as local and correct subclassified tools (`file_processor`, `code_helper`, browser, reminder and connector writing).
- **Intended files:**`main.py`,`dashboard/server.py`,`core/permissions/models.py`,`core/permissions/policy.py`,`core/tools/builtins.py`,policy/security tests.
- **Risk:** high; you can add confirmations to today's free flows.
- **Dependencies:** matrix of tools and explicit definition of origin.
- **Criterio of acceptance:**all commands retain `local`, `dashboard_text`, `dashboard_audio`, `ui` or `wake`; no writing/execution action remains with `READ_ONLY/FREE` by default.
- **Tests:** Dashboard integration -> function call -> policy; parameterized table of minimums per operation; negative tests without real effects.
- **Rollback:** reverse the risk/origin mapping; keep the tests as decision specification.
- **Evidence:** `InputSource` distinguishes `local`, `ui`, `wake`,
`dashboard_text` and `dashboard_audio`; remote shifts retain their origin
up to policy and confirmation; `save_memory` no longer prevents policy; matrix of
Parametrized minimums for processor, code, browser, reminder, connectors and
file creation/copying. Clean baseline: 226 tests and 102 subtests
approved, 37 tool inventory, `compileall`, imports, launcher and
`pip check`; the same line was successfully repeated on the merge
`900c7c7`.

### Phase 2 - `RequestContext` and structured traceability

- **Status:** completed and integrated into `main` on 2026-07-28 since
`codex/03-request-context`.
- **Objective:** end-to-end correlation without changing Gemini Live, audio or visual UI.
- **Intended files:** new `core/request_context.py`, `core/tools/definitions.py`, `core/tools/executor.py`, `core/permissions/*`, `main.py`, new Sanitized Audit Synk, `docs/request_lifecycle.md`.
- **Risk:** medium-high; touches the central path of tools.
- **Dependencies:** Phase 1 and event contract.
- **Criteria of acceptance:** `request_id` unique in requested, policy, confirmation, started, completed and responded; logs without tokens, bodies, memory or sensitive arguments.
- **Tests:** singleness, propagation, sanitization, sink failures, normal/special route correlation.
- **Rollback:** adapters with optional context; feature flag for sink.
- **Evidence:** `RequestContext` unique comes to policy, confirmation, executor,
`ToolResult` and `FunctionResponse`; normal and special routes emit
`requested`, `policy`, `confirmation`, `started`, `completed` and `response`.
The sink JSONL uses allowlist, does not receive arguments, tolerates failures and can
deactivated. Baseline: 236 tests and 102 subtests approved before and after
of the merge `19a2adc`.

### Phase 3 - Atomic permission persistence

- **Status:** completed and integrated into `main` on 2026-07-28 since
`codex/04-atomic-permission-store`.
- **Objective:** avoid partial JSON and fail closed.
- **Intended files:** `core/permissions/store.py`, permission tests and default injection.
- **Risk:** medium; affects security preferences.
- **Dependencies:** none of runtime Live.
- **Criteria of acceptance:** temporary in the same volume, flush/fsync where applicable, `os.replace`, backup/recovery and validation before publication.
- **Tests:** simulated cutting, corrupt JSON, writing error, unknown version, basic continuance.
- **Rollback:** reader compatible with previous version and copy of previous file.
- **Evidence:** temporary in the same directory, `flush`/`fsync`, rereading and
validation before `os.replace`; backup of only one valid primary and
primary recovery/backup/defaults. Track-shared lock for
competition between instances of the process. Baseline: 247 tests and 102 subtests
approved before and after the `f4fe895` merge.

### Phase 4 - `ToolResult` v2 compatible

- **Status:** completed and integrated into `main` on 2026-07-28 since
`codex/05-tool-result-v2`.
- **Objective:**separate execution, effect and verification.
- **Intended files:** `core/tools/definitions.py`, `executor.py`, standardization adaptors, tests; without migrating the 37 tools.
- **Risk:** high; cross-sectional contract.
- **Dependencies:** `RequestContext`.
- **Criteria of acceptance:** legacy adapters retain behavior; states of execution/effect/verification and latency are not inferred from text.
- **Tests:** semantic matrix, serialization, timeouts, errors, compatibility with legacy returns.
- **Rollback:** hold the constructor/adapter v1 until the migration ends.
- **Evidence:** independent enums for execution, effect, verification and
rollback; serialization duration and evidence; text adapters, bool,
mapping, `None` and v2. Timeout declares unknown effect, previous rejection
declare not applied and the 37 tools retain legacy fields. Baseline: 257
tests and 102 subtests approved before and after the `d150a2a` merge.

### Phase 5 - Verification pilot

- **Status:** completed and integrated into `main` on 2026-07-28 since
`codex/06-file-verification-pilot`.
- **Objective:** implement verifier for two or three secure operations of `file_controller`.
- **Intended files:**`actions/file_controller.py`, new verifier module, `core/tools/*`, tests.
- **Risk:** medium.
- **Dependencies:** ToolResult v2 and matrix.
- **Criteria of acceptance:** create/copy/move report resolved path and evidence; an unobserved effect is not reported as verified.
- **Tests:** `tmp_path`, hash/size, conflicting destination, rollback by trash/reverse movement.
- **Rollback:**disable verifier and return to adaptor legacy without changing handlers.
- **Branch evidence:** `create_file`, `copy` and `move` on regular files
return `ToolResult` v2 with resolved path, size and SHA-256 observed.
Conflicts are rejected without overwriting; an unobservable destiny remains
`verification=failed`; directories are still in the legacy adapter.
Focused: 67 tests and 22 subtests approved.
`fa664e4` approved 264 tests and 104 subtests.

### Phase 6 - Cancellation and isolation of tools

- **Status:** completed and integrated into `main` on 2026-07-28 since
`codex/07-tool-cancellation`.
- **Objective:** that timeout does not mean just to stop waiting while the thread continues.
- **Intended files:** `core/tools/executor.py`, cancellation contracts, long stock pilots, fail-injection tests.
- **Risk:** high.
- **Dependencies:** ToolResult v2.
- **Criteria of acceptance:** cooperative handlers receive signal; child processes are finished in a limited way; partial effects are explicit.
- **Tests:** handler blocked, subprocess timeout, cancellation, cleanup and absence of threads/orphan processes.
- **Rollback:** hold previous executor for tools not yet migrated.
- **Branch evidence:** `CancellationToken` thread-safe and cancellation by
`request_id`; the executor expects cleanup during a limited grace and preserves
effect/rollback declared by the handler. The process runner ends and
collects the tree initiated by JARVIS. `dev_agent` is the first pilot:
incorporates checkpoints and your project process is not running after
timeout. The post-merge baseline `9e1e97a` approved 273 tests and 104
subtests.

### Phase 7 - Session, audio, vision, and lifecycle ownership

- **Status:** completed and integrated into `main` on 2026-07-28 since
`codex/08-session-lifecycle`.
- **Objective:** extract services with a single writer per state without changing the Gemini protocol.
- **Intended files:** new `services/session.py`, `audio.py`, `vision.py`, `lifecycle.py`; `main.py`; tests.
- **Risk:** very high.
- **Dependencies:** traceability, minimal events and latency baseline.
- **Criteria of acceptance:** documented owners; reconnection, interruption and shutdown maintain metrics; `main.py` composes instead of implementing.
- **Tests:** fail injection of network/mic/camera, double session, audio in queue, shutdown and recovery.
- **Rollback:** facade delegating to inherited behavior by service.
- **Branch evidence:** `RuntimeServices` composes separate session owners,
audio, vision and lifecycle. Reconnection preserves checkpoint and restarts only
transitions; generations avoid releasing a new interruption from a
old task; camera applies backpressure; shutdown is idempotent and preserves
`main.py` retains existing transport and protocol,
The post-merge baseline `49e0677` approved 283
tests and 104 subtests.
- **Correction 2026-07-31:** `SessionService` now owns Gemini `GoAway`
rotation state and metrics. The receive task preserves the latest resumption
checkpoint, closes the current TaskGroup/WebSocket before the server deadline
and reconnects immediately. Stale or duplicate rotation requests are ignored.
Rollback: remove the rotation signal and owner fields to restore the previous
passive `GoAway` logging behavior.
- **Correction 2026-07-31:** farewell shutdown now distinguishes the application
audio queue, PortAudio's pending device buffers and the emergency deadline.
Once farewell audio starts, the initial 12-second no-response timeout cannot
cut it off; `RawOutputStream.stop()` proves pending buffers played before the
runtime publishes `off` and exits. A separate 45-second completion deadline
prevents a permanently stalled device from hanging shutdown. Rollback: restore
the single deadline and fixed post-queue sleep.

### Phase 8 - UI boundary

- **Status:** completed and integrated in `main`.
- **Objective:** all widget mutations in the Qt thread; UI emits commands and consumes snapshots.
- **Intended files:** `ui.py`, `ui_mk2/*`, presenters/ViewModels and workers.
- **Risk:** high.
- **Dependencies:** minimum typed services and events.
- **Criteria of acceptance:** no `ToolExecutor` handler switches widgets from `to_thread`; filesystem/network/subprocess exit the visual layer.
- **Tests:** Qt offscreen, thread affinity, camera closure, quick panel changes and Pet/Main.
- **Rollback:** Signals/facades compatible with current methods.
- **Branch evidence:** `core/ui_boundary.py` defines a minimum façade for
handlers; `main.py` stops delivering `JarvisUI` to tools; phone, Study,
selected file and camera cross the limit by means of signals, snapshots or
locks. `tests/test_ui_thread_boundary.py` covers public surface, affinity
Real Qt and static regressions, along with Mk II/Mk III suites.
`10000db` implementation was integrated using `a7370bd`; the previous baseline
al merge approved 290 tests and 104 subtests.

### Phase 9 - Provider adapters

- **Status:** completed and integrated in `main`.
- **Objective:** to separate Live, text, vision and search; to inject interfaces into actions.
- **Intended files:** `core/model_fallback.py`, new adaptors, pilot actions, `main.py`.
- **Risk:** medium-high.
- **Dependencies:** contracts and central configuration.
- **Criteria of acceptance:**The pilot action does not matter `google.genai`, does not choose models or read secrets.
- **Tests:** fake suppliers, timeouts, failback, permanent/transitory error and quota.
- **Rollback:**Adjuster that wraps current calls.
- **Branch evidence:** `core/providers` declares stable ports for the
four capabilities and a Google search adapter. `web_search` is the
pilot: receives the provider from `JarvisLive`, preserves DDG as fallback and
does not know SDK, key or models. Live concrete migrations, text and
The vision remains as subsequent batches on the contracts already defined.
commit `f47954b` was integrated by `9bffe3e`; the baseline approved 301 tests and
104 subtests.

### Phase 10 - Continuous configuration, observability and quality

- **Status:** completed. `codex/11-settings-bootstrap` implemented the bootstrap of
settings and `codex/12-secret-scanning` adds preventive checkup of
`codex/13-structured-logging` incorporates JSONL console and file
`codex/14-quality-ci` limits Ruff/mypy to the migrated surface and
adds CI Windows and `codex/15-settings-consumers` consolidates all
Inherited consumers and writers.
- **Objective:** validated configuration, structured logging, incremental checks and IC.
- **Intended files:** new setting module, batch-migrated actions, logging, `pyproject.toml`, CI.
- **Risk:** medium.
- **Dependencies:** RequestContext.
- **Criteria of acceptance:** single reading of secrets/config by process; console + rotary file; lint/type checking only on migrated surface; secret checking.
- **Tests:** absent/malformed configuration, writing, rotation, import check and IC.
- **Rollback:** Configuration and Logging adapters with supported defaults.
- **Branch evidence:** `config.settings.AppSettings` is immutable, hidden the
key in `repr`, validates types/OS and caches one instance per file.
`main.py`, UI, actions, dashboard, memory and LLM client consume the same
snapshot cached. `update_settings()` validates, preserves extras and publishes by
temporary + `fsync` + `os.replace`; UI, vision and memory no longer write the
file directly. An ownership test prevents reintroduction of readers
parallels. `scripts/check_secrets.py` inspects the versioned content and
the blob staged, rejects sensitive routes and high confidence credentials without
print the detected value; the baseline runs it before the suite.
`StructuredRuntimeLog` retains levels, allowed fields and `request_id`
optional in console + JSONL with rotation; `main.py` publishes start, fatal error
and still unreplaced `print()` diagnostics. Ruff and mypy
run an explicit list, the baseline includes them and GitHub Actions
plays that database on Windows/Python 3.12 without secrets or hardware.
The local closure approved 343 tests and 104 subtests.

### Phase 11 - Boundary-scoped typed events

- **Status:** completed in `codex/16-typed-runtime-events`.
- **Objective:** decrease cross callbacks and make the facts of
session, audio, vision, lifecycle and dashboard without eventifying local logic.
- **Files:** `core/events.py`, `services/*`, `dashboard/server.py`,
`core/structured_logging.py`, `main.py`, tests and documentation.
- **Risk:** medium; crosses threads, but does not change transport, physical audio or visual UI.
- **Dependencies:** Phase 7 owners, Phase 8 UI border and Phase 10 logging.
- **Criteria of acceptance:** immutable/sanitized events; publication out
lock; tested order and subscription; failed observers do not change
status; Dashboard connection without direct callback in the composition root.
- **Tests:** continuance, reentrance, failure to subscribe, correlation,
Dashboard compatibility, logging allowed and complete suite.
- **Rollback:**null printers by default and setters inherited from dashboard.
- **Branch evidence:** `EventBus` delivers synchronous facts in order, copy
Subscribers under `RLock` and invoke them without holding it. Owners publish
session, interruption, analysis and shutdown; dashboard publishes connection e
remote input without text, token, audio, image or device ID. Logger consumes
metadata allowed and view/shutdown preserve `request_id`.
local approved 351 tests and 104 subtests.

#### Post-stabilization - Secure Obsidian routes

- The connector interprets notes as paths related to the canonical vault and adds
`.md` when reading does not bring extension.
- The offspring are verified on routes resolved with `Path.relative_to()`;
text prefixes are not used. Internal backups and locks are retained.
- The regressions cover valid routes, traversal, absolute, valts with
misleading prefixes and external symlinks when the system supports them.

### Phase 12 - Supervision and health of workers

- **Status:** completed in `codex/17-worker-supervision`.
- **Objective:** re-initiable, re-cancellable workers with health snapshots without toppling JARVIS.
- **Intended files:** new supervisor in `services/`, browser/vision as
pilots, `main.py`, fail-injection tests.
- **Risk:** high.
- **Dependencies:** lifecycle and typed events.
- **Criteria of acceptance:** start/cancel/close idepotent, restart limited,
without threads/orphan processes and observable health status.
- **Tests:** Dead/locked worker, backoff, double start, shutdown and cleanup.
- **Rollback:** adapter that retains the current lifecycle by worker.
- **Branch evidence:** `WorkerSupervisor` offers phases and snapshots
immutable, sanitized events, monitor, backoff and budget. A cleanup
failed disable subtract to prevent duplicates. Browser closes
Playwright+loop+thread; vision cancels the root task and waits for your thread.
tests use fakes/event loops and do not start browser, camera, audio, network or
Gemini. The local baseline approved 369 tests and 104 subtests.

### Phase 13 - Contracts and containment of agents

- **Status:** completed in `codex/18-agent-containment`.
- **Objective:** `AgentTask`/`AgentResult`, Budget, Workspace and Allowlist;
no agent prevents `ToolRegistry`/`PermissionPolicy`.
- **Intended files:** `actions/dev_agent.py`, `memory/script_memory.py`,
contracts/supervisor of agents and tests.
- **Risk:** high.
- **Dependencies:** Phase 12, cancellation and policy.
- **Criteria of acceptance:** without arbitrary installation/command from departure
model; preview/confirmation; tipped budget and evidence.
- **Tests:** prompt injection, unallowed dependency, timeout, output
excessive, workspace escape and partial rollback.
- **Rollback:** keep the inherited agent locked behind policy.
- **Branch evidence:** `services/agents.py` defines `AgentTask`,
`AgentBudget`, `AgentResult` and `AgentSupervisor`; solves the workspace and
each destination before writing, limits files/bytes/time/output, rejects
overwrite, traversal, absolutes, external symlinks, commands and dependencies
of the model, and reverses only files created by the task.
`dev_agent` generates a new preview without `pip`, `subprocess`, opening
IDE or automatic execution. `script_memory` routines retain
catalog and compatibility, but the raw code is blocked and no longer
reduces policy to `FREE`. Future manual execution requires another tool call
confirmed and operating system sandbox; no `cwd` presented as
Isolation enough.

### Phase 14 - QML decision by benchmark

- **Status:** completed in `codex/19-qml-benchmark`; decision: to retain
PyQt Widgets and differ QML.
- **Objective:** decide with an isolated test whether QML reduces complexity or improves
performance against PyQt Widgets.
- **Intended files:**mark/isolated prototype and documentation; no
replace `ui.py` during evaluation.
- **Risk:** medium-high if adopted; low if only measured.
- **Dependencies:** stable and UI baseline presenters/workers.
- **Criteria of acceptance:** decision documented with metrics; adoption only
against measurable advantage.
- **Tests:** startup, memory, frame packaging, interaction and packaging.
- **Rollback:** discard the prototype without touching the productive UI.
- **Branch evidence:** five processes isolated by variant, 45 frames by
process, Qt 6.11/offscreen/software. QML improved frame packaging p95 from 16,14 to
13.52 ms, but raised cold startup from 63.93 to 217.07 ms and incremental RSS
20.62 to 32.74 MiB. Both had 0% jank and the interaction difference did not
was material. Predefined Guardrails refuse adoption if an advantage
of at least 15% introduces regressions greater than 10%; the result is
`defer`. `ui.py` and `ui_mk2/*` were not modified.

### Phase 15 - Global acceptance gate

- **Status:** completed in `codex/20-global-acceptance`.
- **Objective:** convert the global criteria of section 15 of the PDF to
evidence reversed and failed-closed, without declaring complete the gaps that
are still partial or require hardware.
- **Archives:** `docs/global_acceptance.*`,
`scripts/check_global_acceptance.py`, memory persistence/runtime state,
quality tests and cats.
- **Risk:** medium; harden local persistence and baseline, uninitiated
audio, camera, Gemini, dashboard or accounts.
- **Dependencies:** phases 0-14 and its documentary/automated evidence.
- **Criteria of acceptance:**exact inventory of the 19 criteria; evidence
existing and contained in the repository; strict lock-down while
unverified states; memory and runtime state publish documents
validated and durable without exposing partials to failure injection.
- **Tests:** integrity/strict mode of failed gate, writing and replacement,
memory recovery, non-serializable details, complete suite and
baseline.
- **Rollback:** reverse gate does not modify runtime; for memory preserve
valid primary/backup and restore with JARVIS stopped.
- **Branch evidence:** initial matrix with 6 verified criteria, 11
partial and 2 manual. `--require-complete` mode returns code 2 up to
resolve the earrings. Memory and runtime state use temporary of the same
directory, `flush`/`fsync`, previous validation, `os.replace` and cleanup; the
memory preserves and recovers the last valid backup.
passed 398 tests, omitted 2 and approved 106 subtests.

### Phase 16 - Operational change control

- **Status:** completed in `codex/21-operational-change-control`.
- **Objective:** make the 11 operational instructions and 8 operational instructions verifiable
questions prior to refactoring from section 16 of the PDF.
- **Archives:** `docs/operational_change_control.*`,
`scripts/check_operational_change_control.py`, quality tests and cats.
- **Riesgo:** low; only adds documentary/CI control and does not change runtime.
- **Dependencies:** Phase 15 global gate and `ROADMAP.md` evidence.
- **Criteria of acceptance:**exact inventory of 19 controls; one record
single and sequential phase completed since 15; motive, files, risks,
mandatory tests, metrics, rollback and architectural questions; routes
blocked; results and obsidian closed before
status completed.
- **Tests:** incomplete inventory, absent phase, sensitive/external path,
result pending, Obsidian pending, destructive change without controls and
abstraction without benefit allowed.
- **Rollback:** withdraw the call from the baseline and reverse contract/script/test;
There is no data migration or productive change.
- **Branch evidence:** 7 guided tests, clean Ruff, mypy error-free in 16
modules and baseline with 405 approved tests, 2 omitted and 106 subtests.
`AGENTS.md`, `git status` and the external note remain verifications
explicit human beings: the gate does not claim to observe what IC cannot prove.

### Phase 17 - Methodological closure, scope and limits

- **Status:** completed in `codex/22-audit-closure`; route closure
PDF with open risks.
- **Objective:** to preserve the sources and limits of section 17 and to block one
global statement completes as long as evidence is lacking.
- **Files:** `docs/audit_closure.*`, `scripts/check_audit_closure.py`, tests,
operational control and quality gates.
- **Risk:** low; documentary/CI change with no productive effect.
- **Dependencies:** Global Phase 15 matrix and Phase 16 operational control.
- **Criteria of acceptance:**exact inventory of 8 source groups and 5
boundaries; contained and existing paths; synchronised summary with acceptance
Global; `verified_complete` rejected while open criteria are in place.
- **Tests:** absent group/limit, external/non-existent route, summary
outdated and complete false closure.
- **Rollback:** remove the gate from the baseline and reverse their artifacts; there is no
data migration and runtime change.
- **Branch evidence:** 12 tests conducted between closure/operational control,
Clean Ruff, error-free mypy in 17 modules and baseline with 410 tests
Approved, 2 omitted and 106 subtests. The PDF tour is closed as
`closed_with_open_risks`: 6 verified global criteria and 13 still open.

## Baseline and initial budgets

The following PDF values are provisional targets, not measured results:

| Metric | Initial objective | State |
| --- | --- | --- |
| Wake -> Visible UI | < 500 ms | hardware pending |
| ESC -> audio stopped | < 150 ms | measurement harness |
| Simple local tool | < 300 ms | Benchmark pending |
| Recoverable reconnection | < 5 s | failure-injection harness |
| Clean Shutdown | < 3 s | Pending observation of resources |

### Incremental Wake Measurement - 2026-07-30

- Local sequential load base: OpenWakeWord ~439 ms plus Vosk ~1.498 ms
before you start listening.
- After the change: OpenWakeWord was available at ~160 ms in measurement
repeated; Vosk finished in the background at ~1.190 ms without blocking the listening.
- Theoretical recovery of a stream without callbacks low up to ~8 s
(`5 s + 3 s`) at ~3 s (`2 s + 1 s`).
- Supervisor and detector were restarted and left active without errors
New. Wake -> Visible UI Metric and Acoustic Rate of Hits Continue
pending a spoken test on the real hardware.

### Incremental start correction - 2026-07-31

- Manual validation revealed that the process could be minimized and that the
greeting was not retrying after an initial failed session.
- The UI now gets the first frame before loading Gemini, restores windows
iconic with `SW_RESTORE` and reaffirms fullscreen unaltered Pet Mode.
- Local import of `main` dropped from ~2,241 ms to ~509 ms (approx. 77%).
Qt offscreen confirmed `main` surface, visible, fullscreen and not minimized.
- The greeting is only marked sent after completion of its playback; audio
discarded by reconnection retains the greeting pending.
- Complete suite: `231 passed, 1 skipped, 41 subtests passed`.
- Monitor and wake detector restarted; both remained active and enabled.
- Manual Earrings: measure Wake -> first frame and confirm audible greeting,
focus and fullscreen on real hardware.

### Preparation of non-commercial publication - 2026-07-31

- Completed: attribution to the exact commit of Mark XLVIII, `NOTICE.md`, scope
CC BY-NC, disclaimer of non-affiliation, placeholder OAuth unambiguous,
exclusion of `/output/` and security checklist.
- Tests were added to preserve these requirements and the current scan did not
He's picked up some versioned secrets.
- Complete verification: `236 passed, 1 skipped, 48 subtests passed`.
- The visibility remains private and there was no commit, push or rewrite of
History.
- Pending before declaring publication legally ready: to decide on
PyQt6 GPLv3/commercial compatibility. This preparation does not modify PyQt6.
- Later local integration: changes were carried over the `main`
modern without withdrawing its 55 commissions of architecture. The integrated suite remained
in `434 passed, 3 skipped, 131 subtests passed`; the local `main` pointer
was updated by fast-forward. There was no push or change of visibility.

## Quick wins before the first sprint

1. Add tests that demonstrate the lost remote origin.
2. Mark `file_processor` and its real risk operations.
3. Correct the contradiction of `code_helper write/edit` free.
4. Create the automatic matrix of the 37 tools.
5. Separate optional/legacy dependencies and document them.
6. Remove only the unattainable dispatch after covering equivalence.
7. Convert `PermissionStore.save()` to atomic replacement.

## Next recommended change

A small PR/committee for safety and specification:

1. integration tests that retain `source=dashboard`;
2. Parametrized risk/operation inventory for 37 tools;
3. correction of `file_processor` and `code_helper`;
4. no changes in audio, wake, visual UI, models or Gemini Live.

Full traceability must begin immediately afterwards, on that correct border.

## Maintenance correction - 2026-07-31 - Pet navigation ownership

- **Status:** corrected after a second real Windows report; pending user
  confirmation on the updated build.
- **Objective:** guarantee that returning from Pet Mode preserves the live
  navigation controls and immediately restores access to Chat, Files and every
  other main-application action.
- **Implementation:** removed the orphaned duplicate-bar builder that replaced
  the live button references during every Pet request. Pet is non-checkable,
  while its existing owner still clears drag/capture state on exit.
- **Evidence:** a Qt offscreen round trip now verifies App -> Pet -> App -> Chat
  -> Files and object lifetime, rather than relying only on source assertions.
- **Automated verification:** directed UI suites `44 passed`; full suite `438
  passed, 2 skipped, 134 subtests passed`.
- **Rollback:** restore the removed duplicate builder and Pet checkability, and
  remove the regression; no state migration.

## Maintenance correction - 2026-07-31 - Wake capture and fast visible shell

- **Status:** implemented and verified on the target Windows machine.
- **Objective:** make Hey Jarvis reliably reach a visible application while the
  service stack loads behind an already painted UI.
- **Wake implementation:** native WASAPI profile selection, stereo-array mix,
  integer reduction to mono 16 kHz, calibrated `0.08` threshold with existing
  voice/session guards, visible-child preference and stale-wrapper grace.
- **Startup implementation:** defer audio/event-loop imports, OpenCV hand
  tracker, GEO networking and WMI/GPU polling until after the first frame.
- **Evidence:** controlled phrase/ambient separation (`0.2531` vs `0.0244`),
  successful real Hey Jarvis -> visible window, `132 passed` directed wake/UI
  tests, and median startup reductions of 50.3% import, 38.3% UI import and
  22.5% construction/first events. Final baseline: `444 passed, 2 skipped, 134
  subtests passed`, plus clean dependency, compilation, launcher, secret,
  operational-control and diff checks.
- **Remaining risk:** monitor false wakes and repeat the acoustic/latency matrix
  with other voices, rooms and microphones. Rollback restores the prior capture
  profile, threshold and eager initialization; no state migration.

## Maintenance correction - 2026-07-31 - Study readiness and false-wake reduction

- **Status:** implemented and automatically verified; physical voice/monitor
  confirmation remains pending after the detector is restarted.
- **Study:** the first opening has an explicit loading/error state and artifacts
  wait for WebEngine readiness instead of being sent to an uninitialized page.
  Failed loads retry through the existing workspace. Central views verify the
  selected stack index before their tool call reports success.
- **Wake:** defaults and local configuration now use `Hey Jarvis wake up`.
  `Hey Jarvis` is a neural candidate, not activation: exact `wake up` tokens,
  confidence, recent voice and an unlocked session must all confirm within
  three seconds. Unrelated final speech cancels the pending candidate.
- **Compatibility:** an explicitly configured legacy `Hey Jarvis` keeps its
  former hybrid behavior. GoAway rotation, farewell drain, capture calibration,
  tool policy and providers were preserved.
- **Evidence:** directed suites `67 passed` and `55 passed`; full baseline `467
  passed, 2 skipped, 137 subtests passed`; compilation and dependency checks
  passed. Rollback restores the former phrase/default and direct Study render;
  no persistent-data migration is needed.

### Follow-up - confirmation was lost inside the local detector

- **Status:** code defect corrected; Gemini migration is not warranted.
- The listener previously evaluated Vosk before arming neural evidence from the
  same audio block. It also rejected full/segmented hypotheses such as
  `hey service wake up`, despite the correct exact suffix.
- Neural state is now recorded first. The closed grammar includes full acoustic
  alias variants, prefix-only aliases preserve the three-second window, and a
  final is accepted only when its last two tokens are exactly `wake up` under
  the existing confidence, voice and Windows-session guards.
- Rollback reverts only this ordering/tail recognition and its tests. No model,
  threshold, hardware, Gemini session or persistent state changes are involved.
- **Verification:** `48 passed` for the wake suite, `123 passed` plus 20 subtests
  for the directed regression, and `469 passed, 2 skipped, 137 subtests passed`
  globally. The stale listener was replaced by its supervisor and the new PID
  returned to `listening` with the extended phrase.
- After repeated physical failures, runtime evidence isolated late Vosk
  endpointing: complete four-word/alias results no longer depend on the neural
  timer, while suffix-only results remain gated. The segmented window is five
  seconds. The listener was reloaded again and returned to `listening`.
- **Physical acceptance:** a clean diagnostic supervisor captured real voiced
  audio, neural score `0.331`, an exact four-word Vosk final at confidence
  `1.000`, approval and the launch transition. The resulting application
  published `on`, its main window was found and its process remained responsive.
  Diagnostic mode was then removed without closing that application; the normal
  hidden supervisor is active for the next lifecycle.

## Final wake reliability pass - 2026-08-01

- **Root cause:** the hybrid path required a Vosk final, but continuous ambient
  sound can retain a correct phrase as `partial` without ever crossing an
  endpoint. All partials were intentionally ignored, so the confirmation could
  remain stuck even after correct neural and speech evidence.
- **Correction:** one bounded state machine accepts either the existing
  confident-final routes or an exact `wake up` partial stable across three
  consecutive blocks, only while the neural prefix is armed with recent voice
  and Windows unlocked. Noise, changed text, expiry or lock resets it.
- **Readiness:** extended mode waits for mandatory Vosk load before publishing
  `listening`; heartbeat now reports `vosk_ready` and `verification_stage`
  without transcript content. The active listener confirmed both fields.
- **Verification:** wake suite `51 passed`; full suite `472 passed, 2 skipped,
  137 subtests passed`; compilation and dependency checks passed. Rollback
  removes stable-partial confirmation/readiness gating and its tests; no model,
  threshold, UI, Gemini, lifecycle or persistent-data change is required.
