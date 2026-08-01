# Technical audit of JARVIS Mark LI

## Scope and method

Audit carried out on 2026-07-28 on the local working tree and contrasted with the architecture PDF v1.1. We reviewed:

- complete versioned structure;
- entrypoints, runtime, audio, UI, wake word, tools, permissions, memory, connectors, dashboard and actions;
- imports and dependencies;
- exception patterns, subprocess, network, configuration and secrets;
- suite, syntax, imports and non-interactive boot.

No key content, OAuth, certificates, personal memory or logs were read. No actual system actions, external network, accounts, Gemini Live, microphone, camera or LAN dashboard were executed.

Phase 10 incorporated reproducible preventive control over files
versioned and blobs staged. Checking blocks sensitive routes and shapes of
high confidence credentials without displaying the value. It does not replace the review
the remote history, the rotation of an exposed credential or a detector
specializing in entropy.

## Verified baseline

| Check | Outcome |
| --- | --- |
| Dedicated branch | `codex/audit-architecture-v1-1` |
| Base | `0f60519` |
| Previous local changes | 4 modified wake/launcher files and `output/` unversioned |
| Python | 3.14.6 |
| `pip check` | no broken dependencies installed |
| Launcher | `jarvis_launcher.py --help` correct |
| Smoke imports | launcher, wake, tools, permissions, Live, runtime and memory correct |
| Import `main.py` offscreen | correct; 37 tools |
| `compileall` | Right. |
| Suite | 218 passed, 1 skipped, 28 subtests; 1 external warning |
| Count | 102 Python, 27,876 lines, 22 tests, 37 tools |
| Static debt | 360 `except Exception/BaseException` wide, 67 with `pass`, 303 `print()` |

## PDF-code discrepancies

1. **Remote origin:** the policy knows how to raise non-local sources, but the runtime always builds `ExecutionContext(source="local")`.
2. **Universal Police:** `save_memory` runs before registration and policy.
3. **Central Dispatch:** ToolExecutor exists, but the special routes remain within `main.py` and there are unattainable inherited branches.
4. **Tool matrix:** solved in Phase 0 by means of
`docs/tool_migration_matrix.md` and a test that synchronizes the 37 tools with the
effective registration.
5. **Dependencies:** the main runtime and pytest are reproduced by
`requirements-dev.txt`; optional capabilities announced not yet
They have verified extras.
6. **Atomity:**Memory and runtime state replace temporary; PermissionStore no.
7. **UI:**`ui_mk2` separates several pieces, but recorded actions can play Qt from worker threads.
8. **Observability:** CrashReporter and connector audit exist; there is no structured trace of all tool calls.

## Critical Findings

### C-01 - Remote origin degrades to local

- **Status:**solved in Phase 1.
- **Description:** All tool calls are evaluated as local, even if the text or audio comes from the dashboard.
- **Evidence:** `main.py:1350-1354` fixed `ExecutionContext(source="local")`; `dashboard/server.py:778-784` and `main.py:2126-2143` re-inject commands without preserving origin. Remote elevation does exist in `core/permissions/policy.py:97-110`.
- **Impact:** An authenticated LAN client can receive minimums more permissive than those designed for a remote source.
- **Recommended solution:** Create `RequestContext/InputSource`, keep it from each entry and require it in policy/executor.
- **Effort:** medium.
- **Priority:** P0, before expanding dashboard or tools.
- **Resolution:** `InputSource` type the five entries; text and audio from
dashboard fix a remote source that cannot be degraded within the turn, and
`_execute_tool()` delivers it to `PermissionPolicy`.

### C-02 - `file_processor` can write or run with read-only rating

- **Status:**solved in Phase 1 for central policy.
- **Description:**The tool does not appear in `RISK` or `CONFIRMATION`, so it takes defaults `READ_ONLY/NEVER`; without specific rule, policy remains `FREE`.
- **Evidence:** `core/tools/builtins.py:11-56`; `run/test` operations and `actions/file_processor.py:455-510` scripts; extraction to destination in `actions/file_processor.py:713-741`.
- **Impact:** uploaded content or model instructions can run code, write results or extract files without central confirmation.
- **Recommended solution:** classify by operation, block default execution, validate destination and separate consultative processing of effects.
- **Effort:** medium.
- **Priority:** P0.
- **Resolution:** `SENSITIVE` metadata and minima per operation: queries
Free, transformations with confirmation and always confirmed `run/test`.

### C-03 - `code_helper write/edit` contradicts security confirmation

- **Status:**solved in Phase 1.
- **Description:**`confirmation_request()` prepares confirmation to write/edit, but policy declares those operations `FREE`, so the gate is never invoked.
- **Evidence:**`core/permissions/policy.py:63-66`; written in `actions/code_helper.py:75-81`, `344` and `425-427`; expected confirmation in `core/security.py:63-68`.
- **Impact:** local code modification initiated by model without effective approval.
- **Recommended solution:** `explain=FREE`; `write/edit=CONFIRM_ONCE` or `ALWAYS`; `run/build/auto=CONFIRM_ALWAYS`; integration tests policy -> gate.
- **Effort:**low.
- **Priority:** P0.
- **Resolution:** `explain=FREE`, `write/edit/optimize=CONFIRM_ONCE` and the rest,
including execution, `CONFIRM_ALWAYS`.

## High Findings

### H-01 - Timeout does not cancel synchronous handlers

- **Status:** mitigated in Phase 6 for cooperative handlers and the process of
execution of `dev_agent`; open for handlers legacy and transports that do not
They accept signal.
- **Description:**`asyncio.wait_for()` stops waiting, but work started with `asyncio.to_thread()` can continue.
- **Evidence:** `core/tools/executor.py:88-102`.
- **Impact:** a tool can continue to write, automate or execute after reporting timeout.
- **Recommended solution:** cooperative token, subprocess groups, cleanup and status `TIMED_OUT_EFFECT_UNKNOWN`.
- **Effort:** high.
- **Priority:** P0/P1.
- ** Partial resolution:** the executor records tokens by `request_id`, notes
timeout/cancellation and wait for cleanup limited. Handler can declare effect
partial and rollback using `ToolCancelled`; if you do not recognize the signal
preserves `effect=unknown`. The pilot runner finishes and collects the tree from
`dev_agent` processes, without assuming that model or installation calls already
be cancelable.

### H-02 - `PermissionStore.save()` is not atomic

- **State:**solved in Phase 3 for atomity, recovery and attendance
intra-process.
- **Original description:** I wrote the final JSON directly.
- ** Original evidence:** `PermissionStore.save()` used `Path.write_text()`
on the final destination.
- **Impact:** cut or crash can leave partial preferences; the load returns to defaults and can alter the hardening of the user.
- **Recommended solution:** temporary in the same directory, flush/fsync, `os.replace`, validated backup and failed injection.
- **Effort:**low-medium.
- **Priority:** P0.
- **Resolution:** serialization and validation occur before publication;
Durable temporary lives in the same directory and is replaced with `os.replace`.
Only a valid primary update `.bak`; `load()` tries
primary → backup → safe defaults. Locking is still out of reach
interprocess.

### H-03 - Qt mutations can be run from tool threads

- **Status:** Phase 8 solution for `ToolExecutor` handlers and notifications
of runtime; camera and workspaces retain explicit Qt signals and locks.
- **Description:** ToolExecutor sends synchronous handlers to a worker; several registered handlers directly call UI methods.
- **Evidence:**`core/tools/executor.py:88-91`; UI handlers in `main.py:930-943`; `main.py:897-948` record/execution.
- **Impact:** Races, native crashes, intermittent visual states and closures difficult to reproduce.
- **Recommended solution:** command bus/signals Qt with future response; any widget mutation in the chart thread.
- **Effort:** medium-high.
- **Priority:** P1.
- **Resolution:** `UiCommandFacade` limits what a handler can ask from the
presentation; `JarvisUI` translates those commands to signals and only exposes
protected snapshots for file and microphone. Phase 11 replaces callback
dashboard→runtime by `DashboardConnected`; the UI maintains its Qt signal.
camera callback is published/consumed under the session lock.

### H-04 - Common traceability and mandatory verification

- **Status:** Traceability resolved in Phase 2, Status contract resolved in
Phase 4 and first verification of files implemented in Phase 5; migration of
Other families are still pending.
- **Description:**`ToolResult` only has success/message/data/error; there is no request ID, effect, evidence, rollback or latency.
- **Evidence:** `core/tools/definitions.py:50-55`; console in `main.py:1297,1355-1358,1628`; audit limited to connectors in `connectors/audit.py`.
- **Impact:** you cannot reconstruct an action or distinguish successful execution from applied effect.
- **Recommended solution:** `RequestContext`, `ToolResult v2`, JSONL events sanitized and verified by family.
- **Effort:** high.
- **Priority:** P0/P1.
- **Partial resolution:**`RequestContext` correlation policy, confirmation,
execution and response; the sink JSONL only supports listed metadata and
`ToolResult` v2 separates execution, effect, verification, rollback, duration and
evidence. `file_controller` already observes route resolved, size and SHA-256 for
create, copy and move regular files, rejects conflicting destinations and does not
states verification if the effect cannot be observed.
families are still in the legacy adapter.

### H-05 - Special routes avoid parts of the common contract

- **Status:** mitigated in Phase 1 for `save_memory`; other special routes
They're still open.
- **Description:**`save_memory` returns before validation and policy; seven tools are implemented by specific clamps.
- **Evidence:** `main.py:1315-1334`; `core/tools/builtins.py:10-13`; `main.py:1482-1605`.
- **Impact:** uneven coverage of permits, audit, timeout, cancellation and result.
- **Recommended solution:**`SpecialToolHandler` with the same interface of policy/context/result; one-way migration at a time.
- **Effort:** high.
- **Priority:** P1.

### H-06 - Browser, reminders and connectors have too wide minimums

- **Status:** Phase 1 solution for browser, reminder and account connector.
- **Description:**`browser_control`, `reminder` and other tools are in `_FREE_TOOLS`; `account_connector` is always `FREE`, even for creation on Drive.
- **Evidence:** `core/permissions/policy.py:20-25,47-50`; declaration of operations in `main.py:389-415,228-238,793-813`.
- **Impact:** clicks, forms, persistent tasks or external writings may not reflect the actual risk of the operation.
- **Recommended solution:** policy by operation and origin; free reading, changes/submit/create with confirmation and verification.
- **Effort:** medium.
- **Priority:** P0/P1.
- **Resolution:** navigation/reading are separated from interaction and writing;
reminders require confirmation; creation/disconnection of connector requires
permanent confirmation.

### H-07 - Installable units do not reproduce announced capabilities

- **Status:** partially mitigated in Phase 0; still open for extras.
- **Description:** a clean main runtime installation and tests already is
reproducible, but missing verified extras for PDF, Word, Excel, audio and
TTS/STT modules.
- **Evidence:** `requirements-dev.txt` declares pytest and was installed in a
vacuum environment with Python 3.14.6; optional imports in
`actions/file_processor.py` and `core/stt.py`/`core/tts.py` still include
`python-docx`, `pandas`, `openpyxl`, `PyPDF2`, `pdfplumber`, `pydub`,
`faster-whisper`, `kokoro`, `miniaudio` and `torch`.
- **Impact:** a clean installation does not fulfill everything promised in README; failures appear only when using the function.
- **Recommended solution:** define core vs. extras; import tests; document optional functions; remove unconnected legacy dependencies.
- **Effort:** medium.
- **Priority:** P0 reproducibility.

### H-08 - Providers and model selection are scattered

- **Status:** mitigated in Phase 9 with Live/Text/Vision/Search and
complete migration of `web_search`; other actions are still pending.
- **Description:**Numerous actions create Gemini clients, read API key and choose models.
- **Evidence:** imports/calls in `main.py`, `actions/code_helper.py`, `computer_control.py`, `computer_settings.py`, `desktop.py`, `dev_agent.py`, `file_processor.py`, `flight_finder.py`, `screen_processor.py`, `web_search.py` and `youtube_video.py`.
- **Impact:**Retries, timesouts, models, secrets and evidence are inconsistent.
- **Recommended solution:** Separate adapters Live/Text/Vision/Search and `ModelPolicy`; migrate a pilot action.
- **Effort:** high.
- **Priority:** P1/P2.
- **Partial resolution:**`web_search` receives `GroundedSearchProvider` and no longer
import SDK, read secrets or select models. Google adapter
contains HTTP deadline, grounded search, model failback only for
Transitional faults and typulated errors for timeout, quota and rejection
Permanent. DDG remains as fallback of the use case.

### H-09 - Atomic memory only within a process

- **Status:** mitigated in Phase 15 for durability, validation, backup and
Recovery; interprocess locking and optional encryption are still pending.
- **Original description:**used `RLock`, temporary and `os.replace`, but did not
lock between processes or `fsync`.
- **Evidence:** `memory/memory_manager.py:25-36,76-80,102-135`.
- **Impact:** two processes/writers or a cut may lose the last update; sensitive privacy remains in plain text.
- **Recommended solution:** Locking interprocess, fsync, proven recovery and optional encryption.
- **Effort:** medium-high.
- **Priority:** P1.
- **Partial resolution:** the temporal lives in the same directory, is validated
before publishing, use `flush`/`fsync` and `os.replace`, and clean before
failure. Only a validated primary replaces backup; a corrupt primary
recovers the last valid backup. Tests inject write failures and
publication. The remaining risk is lost update between processes and
sensitive storage without encryption.

### H-10 - Execution and generated installation have broad authority

- **Status:** Phase 13 solution for `dev_agent` and inherited raw routines.
- **Description:**`dev_agent` installs determined dependencies by model output and executes commands/projects; memorized scripts execute code.
- **Evidence:** `actions/dev_agent.py:239-272,295-344,519-549`; `memory/script_memory.py:23-34`.
- **Impact:** supply-chain, arbitrary execution, persistent changes and exits without strict limit.
- **Recommended solution:** isolated workspace, allowlist, virtual environment per project, preview, confirmation always, exit limits and audit.
- **Effort:** high.
- **Priority:** P1 security.
- **Resolution:** the agent only creates previews in a new project content
by canonical routes, typed budget and rollback of your own files.
`run_command` or dependence proposed by the model is rejected before
write; installation, execution and opening of handler IDE were withdrawn.
`script_memory.run_script()` no longer interprets stored code and policy
no longer grant `FREE` to a routine because it is registered.
previews will remain locked until you have real sandbox and a second
explicit confirmation.

## Media Findings

### M-01 - Legacy dispatch is unreachable

- **Description:**After `if name not in SPECIAL_TOOLS`, `elif` appears for non-special tools.
- **Evidence:**`main.py:1419-1480` and `1546-1594`.
- **Impact:** duplication, false impression of coverage and risk of divergence.
- **Recommended solution:** equivalency tests and limited elimination of dead branch.
- **Effort:**low.
- **Priority:** P1.

### M-02 - Validation of arguments is a subset of JSON Schema

- **Description:**only valid requires and basic types; does not control enum, ranges, items, additional or formats.
- **Evidence:** `core/tools/registry.py:57-83`.
- **Impact:** dangerous or invalid values reach handlers.
- **Recommended solution:** compatible validator or tool validators without heavy dependence.
- **Effort:** medium.
- **Priority:** P1.

### M-03 - Wide exceptions and silent errors

- **Description:** 360 wide handlers, 67 with `pass`.
- **Evidence:** maximum in `file_processor.py`, `ui.py`, `game_updater.py`, `browser_control.py`, `dashboard/server.py` and `main.py`.
- **Impact:** incomplete diagnoses and falsely normal states.
- **Recommended solution:** gradual migration to specific exceptions and logging with traceback/stable code.
- **Effort:** high and gradual.
- **Priority:** P1/P2.

### M-04 - Fragmented Logging

- **Status:** partially mitigated in Phase 10 with a structured owner and
rotation for runtime; legacy `print()` migration is still pending.
- **Description:**303 `print()`; CrashReporter only covers unmanaged exceptions and connector audit does not cover tools.
- **Evidence:** AST and `core/diagnostics.py` counts.
- **Impact:** without levels, session, request ID or uniform latency.
- **Recommended solution:** `logging` structured and rotary, preserving wake diagnostic console.
- **Effort:** medium.
- **Priority:** P1.
- **Partial resolution:**`StructuredRuntimeLog` issues JSON allowed to
console and `RotatingFileHandler`, supports correlation with `RequestContext` and
fails without preventing booting. `main.py` records the start limits,
fatal error and closure. The common sanitizer now covers forms of credentials
Google, GitHub, OpenAI, AWS and Slack, as well as private keys.
structured tools continues in `RequestAuditSink`.

### M-05 - Duplicate Configuration and Hidden Bugs

- **Status:** resolved in Phase 10 for the reading and writing of the
local configuration.
- **Description:**`api_keys.json` is read from multiple modules; `config.get_config()` captures any exception and returns `{}`.
- **Evidence:** `config/__init__.py:5-18` and multiple `_get_api_key()` in actions.
- **Impact:** inconsistent models/paths and unclear late errors.
- **Recommended solution:** immutable settings validated for bootstrap and injection.
- **Effort:** medium-high.
- **Priority:** P1/P2.
- **Resolution:**`AppSettings` validates JSON and types, normalizes OS, maintains
Extras compatible and fails with `SettingsError` stable. Snapshot is cached
by route and all productive borders consume it without opening the file
`update_settings()` validates the full document before
publish it atomically with temporal, `fsync` and `os.replace`, and update the
cache under the same lock. The key is excluded from `repr`; a test
Static blocks new parallel readers.

### M-06 - `ui.py` and `main.py` continue to concentrate responsibilities

- **Status:** partially mitigated in Phase 7 for session status, audio,
vision and shutdown, and in Phase 8 for the UI command border; transport,
IO and use cases continue in `main.py`.
- **Description:**4,535 and 2,331 lines respectively, with mixed status, IO and lifecycle.
- **Evidence:** direct count and class/method outlines.
- **Impact:** changes in UI/audio have wide regression radius.
- **Recommended solution:** extract services/presenters by ownership, not by mechanical transfer.
- **Effort:** very high.
- **Priority:** P2 after P0/P1.
- **Partial resolution:**`RuntimeServices` composes four owners with
explicit transitions, locks where they cross threads, immutable snapshots and
metrics. Duplicate flags of `JarvisLive` were removed without changing the
Gemini protocol or move UI/hardware. Tails, streams and suppliers continue
`UiCommandFacade` reduces handler access to the
presentation without attempting to mechanically divide `ui.py`. Phase 11 adds a
`EventBus` typed for session facts, interruption, vision, shutdown and
dashboard; watchers run out of the owner's lock and their bugs are left
It does not replace queues, commands or lifecycle of workers.

### M-07 - Queues and tasks lack a single policy

- **Status:** partially mitigated in Phase 12.
- **Description:**`audio_in_queue` does not have maximum; dashboard tasks are created outside of a common lifecycle.
- **Evidence:** `main.py:2184-2214`, `1043-1053`.
- **Impact:** growing memory or orphan tasks under prolonged failures.
- **Recommended solution:** ownership, limits, depth metrics and explicit closure.
- **Effort:** medium.
- **Priority:** P1 with lifecycle.
- **Partial resolution:**`WorkerSupervisor` provides start/cancell/close
idempotents, active health, backoff and limited subtract. Browser and vision are
pilots: close loop/thread and fail closed if cleanup does not prove that the
previous worker finished. Live tails, dashboard, monitor, proactivity and
remaining workers retain inherited lifecycle.

### M-08 - Cross-platform pledges exceed verification

- **Status:** partially mitigated in Phase 10 with reproducible CI on
Windows/Python 3.12; macOS/Linux and hardware remain unverified.
- **Description:**The project announces Windows main with partial macOS/Linux support, but there is no CI/hardware matrix for those platforms.
- **Evidence:** handlers with OS branches and conditioned dependencies; suite executed only on Windows.
- **Impact:** silent regressions outside Windows.
- **Recommended solution:** declare capabilities per platform in the matrix and IC smoke where realistic.
- **Effort:** medium.
- **Priority:** P2.
- **Partial resolution:**`.github/workflows/quality.yml` installs manifests
versioned and runs the complete database with timeout and permissions only
reading. Ruff/mypy are restricted to migrated modules to avoid debt conversion
historical in false blockades.

### M-09 - Non-canonical comparison of routes on the Obsidian connector

- **Status:** resolved after Phase 11.
- **Description:** the fate of a note was resolved, but it could be compared
against a non-standardized representation of the root of the Vault.
- **Impact:** Windows CI rejected valid notes; a future comparison by
prefix would also have been vulnerable to vaults with misleading names.
- **Resolution:** first solve the root, accept only relative entries,
resolve the destination and use `Path.relative_to()` to test real offspring.
The same validation protects backups and blocks traversal, absolute routes,
internal folders and symlinks that escape.
- **Tests:** read with/without `.md`, write with backup, root not standardized,
`..`, absolute path, misleading prefix and symlink when Windows allows.

### M-10 - QML does not demonstrate a net advantage for the current UI

- **Status:** decision closed in Phase 14; preserve PyQt Widgets.
- **Description:**The PDF allows to consider QML only by means of a prototype
isolated and a measurable advantage, not as rewrite assumed.
- **Evidence:** five processes per variant, 45 frames per process,
Windows/Python 3.14.6/Qt 6.11 offscreen with backend software. QML improved
packing p95 16.3%, but worsened cold startup 239.6% and incremental RSS 58.8%.
- **Impact:** migrating now would add cost and risk of parity without evidence
of global improvement.
- **Resolution:** keep `ui.py`/`ui_mk2` in Widgets. Reopen only with screen
real, visible GPU, functional/visual/accessible parity and frozen packaging
meet the 15% threshold with no regressions greater than 10%.
- **Rollback:** the benchmark is independent; removing it does not change runtime.

## Low Findings

### L-00A - Snapshot limits were not synchronized with the closure

- **Status:** resolved in Phase 17 as closure with open risks.
- **Description:** the sources and limits of section 17 were static text;
could become obsolete or coexist with a false claim of acceptance
Complete.
- **Impact:** loss of reach traceability and confusion between baseline
mocking, real hardware and fully verified architecture.
- **Resolution:**exact manifest of 8 sources/5 limits, paths contained and
automatic crossing with the global matrix. With 13 open criteria,
`verified_complete` fails.
- **Limit:** existence of a file does not demonstrate semantic revision
comprehensive; the outstanding ones remain in global acceptance.
- **Rollback:** remove gate/manifesto does not change runtime.

### L-00 - Operating instructions without structured gate

- **Status:**solved in Phase 16 from the phase of enforcement 15.
- **Description:** Section 16 and `AGENTS.md` required motive, files,
risks, tests, metrics, rollbacks and architectural questions, but their
compliance depended only on free text.
- **Impact:** a phase could be declared complete by omitting evidence or
confusing mocks with real behavior.
- **Resolution:** contract of 19 controls and one sequential record per phase;
validation of contained evidence, sensitive routes, results, Obsidian,
destruction and benefit of abstractions.
- **Limit:** IC cannot demonstrate human actions or read portablely
the external obsidian note. These points are still documented for review of
Handoff and they're not marked as automated.
- **Rollback:**Removing the gate from the baseline and reversing your artifacts does not change
Runtime.

### L-01 - Unit declared without use of observed runtime

- **Description:**`beautifulsoup4` only appears in the installer and requirements; there is no import/use in functional code.
- **Evidence:** `requirements.txt`; `core/installer.py:24`.
- **Impact:** unnecessary installation and larger surface area.
- **Recommended solution:** confirm intention and remove or use.
- **Effort:**low.
- **Priority:** P3.

### L-02 - Obsidian note path in `AGENTS.md` became obsolete

- **Description:**The file indicated without suffix does not exist; the actual note found is called `Jarvis Futuras implementaciones - General.md`.
- **Evidence:** search by name on OneDrive.
- **Impact:** Future agents cannot comply with the mandatory registration.
- **Recommended solution:** update the route keeping the same valt.
- **Effort:**low.
- **Priority:** P0 documentary.

### L-03 - No static import cycle confirmed

- **Description:**No direct cycle appeared in the inspected cores or in smoke imports, but local and deferred imports complicate a comprehensive opinion.
- **Evidence:** Correct base runtime imports and delayed load in `main._load_action_dependencies()`.
- **Impact:** immediate low; risk when extracting services.
- **Recommended solution:** add graph analysis of imports in Phase 0.
- **Effort:**low.
- **Priority:** P2.

## Top 10 risks

1. Remote source treated as local.
2. `file_processor` free with writing/execution.
3. `code_helper write/edit` free.
4. Timeout that does not cancel the effect.
5. Tool calls without request ID, evidence or verification.
6. UI Qt played from workers.
7. Non-atomic permissionStore.
8. Special tools outside the common contract.
9. Incomplete clean installation for announced capabilities.
10. Comprehensive authority of agents/scripts and distributed suppliers.

## Quick wins

- Remote source tests and risk classification.
- Correct `file_processor`/`code_helper`.
- Atomity of PermissionStore.
- 37 tool matrix generated from code.
- Separate core/optional units.
- Remove dead dispatch after testing.
- Structured Sink sanitized with request ID.

## Recommendation

Do not start audio extraction, session or UI yet. The next change should be small, reversible and focused on source/risk tests and the tool array; then, `RequestContext` and PermissionStore atomic.

## Change verified - 2026-07-30 - Google Workspace native

### Scope

- `GoogleDriveConnector` remains the unique owner of OAuth, Drive and
Workspace files.
- `connectors/google_workspace.py` encapsulates the native APIs of Docs, Sheets
and Slides with the same token, injected builder, limits and errors
specific.
- `account_connector` incorporated native reading; Docs creation and append;
creation, writing and append of Sheets; and creation/append of Slides.
- `main.py` remains the composition root and registers the same tool;
did not change audio, vision, UI, dashboard or Gemini Live.

### Safety and evidence

- Read, search and download continues free after OAuth.
- Any creation or remote editing requires at least `confirm_once`;
`disconnect` requires `confirm_always`.
- Readings have text/cell limits and the scripts validate
content, matrix and size.
- Docs is checked by final content; Sheets by rank/cells and reading
back; Slides by page ID and observed text.
- The audit records only supplier, operation and count. It does not record
bodies, values, queries, IDs or tokens.

### Discrepancies and risks

- **Discrepance partially resolved with H-06:** the deeds of
`account_connector` are no longer `FREE`. Browser sorting,
Reminders and other connectors are still pending.
- Google Workspace APIs were enabled manually in the project
Google Cloud. The real account was tested using the existing protected token,
without reading or displaying OAuth configuration, identity, previous files or
non-smoke test content.
- Creating a file and populating its contents are two remote effects: if the
second, the error reports that the empty file has already been created and does not attempt
delete it silently.
- Check is local to connector; `ToolResult v2` and `request_id` continue
outstanding according to Phases 2 and 4.

### Verification and rollback

- Complete Suite: `226 passed, 1 skipped, 41 subtests passed`; a Warning
external future deprecation in `google.genai`.
- `pip check`, `compileall`, `jarvis_launcher.py --help` and `git diff --check`:
correct with the Python of the virtual environment.
- Google Workspace's real Smoke: Docs, Sheets and Slides Completed
`create -> write -> readback`; all three temporary artifacts moved to
the wastebasket and `trashed=true` was again verified using Drive API.
- No visual browser, Gemini, microphone, camera or dashboard were executed.
- Rollback: Remove native actions and `GoogleWorkspaceService`, restore
the capabilities/policy matrix and retain the previous Drive connector. No
requires migration of local data or tokens.

## Change verified - 2026-07-30 - Wake fast and fullscreen base surface

### Cause and scope

- Wake boot run `main.py --pet`, while direct start
`JarvisUI` fullscreen was already opened. That divergence was eliminated: both routes
start base surface and Pet Mode is still available only by transition
explicit.
- With OpenWakeWord available, `wake_word.main()` loaded Vosk shape
synchronous before opening the stream. Local measurement was ~439 ms for
OpenWakeWord and ~1.498 ms additional for Vosk.
- The hybrid fallback expected a final result `hey`, but grammar did not
included `hey` as a standalone input. In addition, an empty ending could
disarm the window before receiving the second term.
- `AsyncVoskFallback` loads the heavy model into a thread daemon; OpenWakeWord
listen immediately and the Vosk recognizer connects when ready.
Grammar includes `hey` and empty endings no longer alter the sequence.

### Ownership, compatibility and recovery

- `wake_word.py` retains ownership detector, stream, failback and process
`JarvisUI` retains ownership of fullscreen and App/Pet.
- They didn't change Gemini Live, conversation audio, camera, dashboard, policy
Nor Pet Mode's Qt signals.
- A stream without callbacks is considered locked at 2 s and retry afterwards
of 1 s; before were 5 s and 3 s. The reset retains cleaning of tail and state
neural before reopening.
- Rollback: back to load synchronous Vosk, timeout 5/3 and argument `--pet`; no
There is configuration migration or data.

### Evidence and limits

- Targeted launcher/wake/UI tests: `72 passed`.
- Complete suite: `229 passed, 1 skipped, 41 subtests passed`.
- `pip check`, `compileall`, launcher `--help` and `git diff --check`: correct.
- Repeated measurement: OpenWakeWord ready in ~160 ms; Vosk ready in background
a ~1.190 ms. are local loading times, not Wake -> UI.
- Supervisor and detector were restarted only; both remained active,
OpenWakeWord reported listening status and no new errors appeared.
- No audio was recorded or the phrase was acoustically verified.
Wake -> Visible UI and real fullscreen focus require manual testing.

## Verified correction - 2026-07-31 - First frame, restoration and greeting

### Subsequent evidence and cause

- The July 31 manual test confirmed three gaps in the previous change:
slow opening, window only present in the task bar and greeting issued
Just after we moved on to Pet Mode.
- `main.py` imported `google.genai` before building the UI. The local profile
attributed ~1.871 ms accumulated to SDK and measured ~2.241 ms to import `main`.
- The two focus attempts used `SW_SHOW`, which does not restore a minimized HWND.
- `_briefing_sent` was marked when programming the greeting, not after playing it.
An initial failure or disconnection prevented it from retrying; in addition, the emptying of
audio could release the wait without distinguishing audio discarded from play.

### Implementation and ownership

- Gemini is imported late and thread-safe into the owner
`JarvisLive`; Qt builds, displays and paints the base surface before
start the thread `jarvis-core`.
- `JarvisUI` maintains ownership of visual status. In Windows it restores with
`SW_RESTORE`, removes `WindowMinimized`, applies `WindowFullScreen` and retrys
focus in a narrow way. Late callbacks do not reverse a transition
Explicit to Pet Mode.
- The greeting preserves separate states `inflight`, `played` and `sent`.
It is only completed after draining your audio; a disconnect releases the task
without declaring success and allows you to try again in the next session.
- App/Pet, policy, tools, camera, dashboard, or
Account adapters.

### Evidence, risks and rollback

- Qt offscreen test from minimized state: visible window, fullscreen,
not minimized and surface `main`.
- In the same environment, the import of `main` dropped from ~2.241 ms to ~509 ms
(approx. 77%); the UI construction measured was ~492 ms. This measures local load,
no Wake -> UI on hardware.
- Targeted Tests: `124 passed, 20 subtests passed`. Complete Suite:
`231 passed, 1 skipped, 41 subtests passed`; `pip check`, `compileall` and
`git diff --check` correct.
- Only the resident supervisor and wake detector were restarted; both
were active and enabled with the updated code.
- Pending risk: repeat “Hey Jarvis” on the real team and check focus,
fullscreen, audible greeting and extreme latency.
the main app, Gemini, camera, dashboard or accounts; the suite automated
kept microphone and other hardware mocked.
- Rollback: restore eager imports, immediate start of runner, `SW_SHOW`
and the previous Boolean brief. No data migration/configuration.

## Verified preparation - 2026-07-31 - Non-commercial publication

### Scope and provenance

- Repository visibility was not changed, commit/push was not made and
modified productive logic.
- The provenance now links Mark XLVIII's `d178f6b` public commit,
created by FatihMakes and published under CC BY-NC 4.0.
- `NOTICE.md` explicitly separates original material, Mark LI modifications
and third-party components. `LICENSE.md` limits the copyright claimed to
own contributions and describes the repository as a public source code
for personal and non-commercial use.
- Added non-affiliation notice with Marvel Entertainment, Marvel Studios
and The Walt Disney Company; their brands or characters are not claimed.

### Hygiene and prevention of regression

- `config/google_oauth_client.example.json` uses placeholders only
The real OAuth file remained ignored; its contents were not
showed or changed.
- `/output/` was left in `.gitignore` to prevent PDFs and other artifacts
generated by accident enter into a publication.
- `SECURITY.md` includes a pre-public visibility checklist.
- `tests/test_public_release.py` verifies placeholders, ignore, attribution,
disclaimer and license of the wake models.

### Verification, pending risk and rollback

- Targeted tests: `5 passed, 7 subtests passed`.
- Complete suite: `236 passed, 1 skipped, 48 subtests passed`.
- `pip check`, `compileall`, Secret Scanning and `git diff --check`:
Right.
- PyQt6 was neither migrated nor relicensed. GPLv3/Commercial compatibility with
the non-commercial scheme remains a pending decision before declaring
the repository is legally ready.
- The history retains an old fictional chain of random appearance in the
OAuth template; does not match current local credentials. Not rewritten
nor was any branch forced to prevent a destructive operation.
- Rollback: remove `NOTICE.md` and test, restore previous texts, the
Example template and `/output/` input. No runtime migration,
credentials or data.

## CI correction - 2026-07-31 - Internationalized tool matrix

- The publication translation changed the headers in
  `docs/tool_migration_matrix.md` to English, while
  `tests/test_tool_inventory.py` still required the former Spanish headers.
  The `Quality` workflow therefore failed all 37 tool subtests with the same
  `KeyError`; runtime behavior and registry metadata were not involved.
- The test contract now follows the English matrix headers. The workflow also
  uses `actions/checkout@v6` and `actions/setup-python@v6`, whose Node.js 24
  runtime removes the Node.js 20 deprecation warning emitted by GitHub-hosted
  runners.
- The operational change-control parser now recognizes both the former Spanish
  `Fase`/`Estado: completada` markers and the internationalized
  `Phase`/`Status: completed` markers. This preserves compatibility with the
  pre-translation roadmap while restoring the completed-phase safeguards.
- Risk: low; test/document synchronization and CI action runtime only. No
  application, permission, tool, audio, UI, provider, or account behavior is
  changed.
- Verification: `8 passed, 37 subtests passed` across the directed contracts;
  the full baseline passed with `436 passed, 2 skipped, 134 subtests passed`,
  clean Ruff/mypy, dependency consistency, compilation, secret scan,
  inventories, launcher smoke checks and `git diff --check`. Rollback: restore
  the previous header names, roadmap parser and action majors; this does not
  migrate runtime state or user data.

### Integration on the modern main

- Changes were first saved in two recoverable committs and then
carried a branch born of the modern `main`, which was 55 commissions by
ahead. Architectural phases were not overwritten or eliminated.
- Conflicts were resolved by retaining injection of suppliers, events,
traceability and minima of modern main policy. `read_workspace_file`
is free; `connect`/`download` requires unique confirmation and all
Remote writing or disconnection always requires confirmation.
- SDK's deferred load keeps `_function_response` self-sufficient for
adapters and tests that build `JarvisLive` without running `__init__`.
- Verification on the integrated tree: `434 passed, 3 skipped,
131 subtests passed`; dependencies, compilation and scanning of secrets
Right.
- The local `main` pointer was advanced by fast-forward to the tree
There was no push or change of visibility; PyQt6 remains without
changes.
- The identity of the maintainer was normalized as Alejo Gaisser
(`@alejogaisser`, formerly `@AlejoGaisser07`) on license, NOTICE and
README. The cloning command uses the current canonical URL.

## Verified correction - 2026-07-31 - Pet to app input handoff

- The first correction released a possible Pet mouse grab, but the user's
  subsequent Windows test proved that navigation still failed. The reproduced
  root cause was an orphaned control-bar builder inside `_request_pet_mode()`:
  every Pet click replaced the live Chat/Files/Camera/Memory/Geo references
  with buttons owned by a temporary widget that Qt immediately deleted.
- The orphaned builder was removed. Pet is now explicitly non-checkable because
  it is a surface transition rather than a persistent workspace. The existing
  Pet pointer reset remains defensive ownership of drag/capture state.
- A real Qt offscreen regression performs App -> Pet -> App -> Chat -> Files,
  verifies that the original button objects remain alive and confirms that the
  side panel opens and switches content.
- Verification: directed UI suites `44 passed`; full suite `438 passed, 2
  skipped, 134 subtests passed`. The user's Windows reproduction established
  the failure; confirmation on the updated build remains pending.
- Scope is limited to `ui.py`, `ui_mk2/pet.py`, their UI regression and
  documentation. Session ownership, camera shutdown, tools, policy and
  providers are unchanged.
- Risk: low. The deleted block had no valid caller result and created an
  unparented duplicate bar only as a side effect. Rollback: restore that block,
  Pet checkability and remove the regressions; no configuration or data
  migration is involved.

## Verified correction - 2026-07-31 - Reliable wake and faster first frame

- **Root cause:** the configured microphone name selected the first matching
  DirectSound endpoint and forced it to 16 kHz/mono. Controlled acoustic tests
  heard real voice (`RMS 504` vs floor `45`) but the Hey Jarvis model reached
  only `0.0161` against threshold `0.35`. The same physical array through its
  native WASAPI endpoint at 48 kHz, stereo mix and reduction reached `0.2531`;
  a silent-room control peaked at `0.0244`.
- `InputCaptureProfile` keeps the existing wake owner and selects a matching
  native WASAPI endpoint when available. The callback normalizes interleaved
  stereo and exact 48/32 -> 16 kHz integer ratios with NumPy before either
  detector. The calibrated threshold is `0.08` and still requires recent real
  voice plus an unlocked Windows session; Vosk unknown text is not accepted.
- A second lifecycle gap was reproduced: virtual-environment launcher wrappers
  can outlive the real Qt child. Process discovery now prefers a visible
  top-level window, tolerates only a 15-second invisible startup grace and does
  not let an old invisible wrapper pause wake indefinitely. Supervisor start is
  mutex-guarded and stop rescans children created during termination.
- **Real evidence:** after a normal UI close the resident detector returned to
  `listening`; saying Hey Jarvis started `main.py` and produced a visible main
  window. No audio or transcription was stored. This verifies one Windows
  machine and does not constitute a general acoustic benchmark.
- **Startup evidence (offscreen, same machine):** median `import main` fell from
  `871.9 ms` to `433.2 ms` (50.3%); UI import from `605.5 ms` to `373.8 ms`
  (38.3%); construction/first events from `815.6 ms` to `632.4 ms` (22.5%).
  Audio/event-loop imports, OpenCV face detection, GEO client and WMI/GPU
  metrics now load behind the first frame without changing their owners.
- Scope: `wake_word.py`, `jarvis_launcher.py`, `main.py`, `ui.py`, wake/UI tests,
  example configuration and documentation. Gemini protocol, tools, policy,
  camera activation and account providers are unchanged.
- Risks: threshold calibration is based on one microphone/voice/environment;
  false-wake rate needs longer ambient observation. Rollback: restore mono
  16 kHz capture/`0.35`, eager imports and immediate metrics/OpenCV setup. No
  persistent data migration is required; local wake threshold can be restored.
- Final verification: `444 passed, 2 skipped, 134 subtests passed`; dependency
  consistency, compilation, launcher help, secret scan, operational change
  control and `git diff --check` also passed. The full suite first exposed six
  direct-construction routes that had bypassed the deferred `asyncio` load;
  `_load_asyncio_dependency()` now preserves lazy startup while making those
  routes self-sufficient, and all six regressions are covered.

## Verified correction - 2026-07-31 - Google APIs and agile confirmations

- **Root causes:** the confirmation gate only understood approval after staging
  an action and both partial/full speech transcripts could revisit the pending
  state. Separately, `account_connector` returned API exceptions as ordinary
  strings beginning with `Connector error`; legacy normalization did not treat
  that prefix as failure, so a failed or partial Google write could be reported
  as successful.
- **Policy:** Google Drive file/folder and native Docs/Sheets/Slides creation is
  direct for local, UI and authenticated dashboard origins. One explicit
  approval in the original request can authorize one non-destructive guarded
  action from the same source. Delete, remove, clear, forget, trash, purge and
  disconnect operations always require a fresh confirmation.
- **Repeated-call control:** a confirmed execution keeps a sanitized
  fingerprint/result for 10 seconds. An immediate identical model retry from
  the same source receives the prior result and cannot execute or prompt again.
- **Connectors:** `account_connector` returns typed `ToolResult` v2 with explicit
  effect and verification states. Docs/Sheets/Slides creation retains the
  verified initial-content update. Google Calendar now supports verified event
  create, update and delete through the API; its expanded `calendar.events`
  scope requires a one-time OAuth reauthorization for existing Calendar tokens.
- **Safety:** Calendar does not send attendee update emails automatically
  (`sendUpdates=none`). Automated tests inject providers and never open OAuth,
  accounts, browser, microphone, camera, dashboard or Gemini. Destructive event
  deletion remains freshly confirmed and verified by a 404/410 readback.
- **Risk and rollback:** approval intent is phrase-based, source-bound, expires
  after 45 seconds and is consumed once; unusual phrasing may still fall back to
  the normal confirmation. Rollback removes the upfront gate/Calendar writes,
  restores previous policy minima and legacy connector strings; no local data
  migration is required. Remote files/events already created must be managed in
  Google and are not silently removed.
- **Verification:** `457 passed, 2 skipped, 137 subtests passed`; `pip check`,
  full compilation, launcher help, repository quality gate, secret scan and
  `git diff --check` passed.
  One external `google.genai` deprecation warning remains unchanged.

## Verified correction - 2026-07-31 - Graceful Gemini Live rotation

- **Root cause:** the wake detector was healthy, receiving audio and approving
the phrase, while Gemini sessions repeatedly ended with WebSocket 1008. The
server had first sent `GoAway`, but `main.py` only displayed it and left every
infinite TaskGroup worker running until the server aborted the connection.
- **Correction:** `SessionService` owns a deduplicated rotation request and
counter for the current transport. The receive path saves the resumption
checkpoint first, raises a typed internal signal, closes the TaskGroup and SDK
session, and reconnects with zero intentional backoff. Expected rotations no
longer produce crash tracebacks.
- **Safety and scope:** no battery gate exists and the 20% charge was unrelated.
No microphone threshold, device, credentials, model, tool policy or external
account behavior changed. Tests do not start a real Live or hardware session.
- **Verification:** `460 passed, 2 skipped, 137 subtests passed`; `pip check`,
full compilation, launcher help, Ruff, mypy, the secret scan and
`git diff --check` passed. The one `google-genai` Python 3.17 deprecation
warning is pre-existing.
- **Risk:** correctness is verified against the observed protocol order and
mocked owner transitions; a real server rotation still requires manual Windows
confirmation. Rollback removes the rotation signal, owner fields and tests; no
persistent data migration is involved.

## Verified correction - 2026-07-31 - Complete farewell playback before exit

- **Root cause:** the lifecycle treated an empty asyncio queue as completed
speaker playback. PortAudio can still hold submitted buffers after the final
`stream.write()`, while a fixed 250 ms thread delay called `os._exit`. The
independent 12-second fallback could also finish shutdown after farewell audio
had started but before playback drained.
- **Correction:** the existing `LifecycleService` now owns separate evidence for
farewell reception, queue drain and device drain. Starting farewell audio moves
the emergency deadline to 45 seconds; normal completion still happens as soon
as the queue drains. Finalization uses blocking `RawOutputStream.stop()`, closes
the device, records drain evidence, publishes `off` and exits in that order.
- **Compatibility:** the existing shutdown tool, wording, request correlation,
GoAway rotation, wake supervision, playback interruption and UI paths remain in
place. No parallel lifecycle or audio abstraction was introduced.
- **Verification:** `462 passed, 2 skipped, 137 subtests passed`; `pip check`,
full compilation, launcher help, Ruff, mypy, the secret scan and
`git diff --check` passed. The existing `google-genai` Python 3.17 deprecation
warning is unchanged.
- **Risk and rollback:** hardware timing is not exercised by automated tests;
the installed sounddevice contract states that `stop()` waits for pending
buffers. The 45-second bound handles a stuck device. Rollback restores the
single deadline and fixed 250 ms delay; no data migration is involved.

## Verified correction - 2026-07-31 - Study first-open readiness and extended wake phrase

- **Root causes:** Study executed `runJavaScript()` and selected its WebEngine
  view without evidence that the hidden startup page had finished loading. A
  later manual reopen worked because the page was ready by then. Separately,
  the dedicated neural detector could approve the short `Hey Jarvis` prefix by
  itself, leaving the observed false-positive surface unchanged.
- **Correction:** the existing Study owner now holds explicit loading, ready and
  failed states, defers artifact rendering, exposes a non-blank local loading
  surface and retries failures. The shared central-navigation method validates
  its stack postcondition before returning success.
- **Wake policy:** the active/default phrase is `Hey Jarvis wake up`.
  OpenWakeWord arms a bounded verifier but cannot activate the extended mode by
  itself. Vosk must provide the exact `wake up` word sequence with sufficient
  confidence, recent voiced audio and an unlocked Windows session; an unrelated
  final result or timeout clears the state. Exact full-phrase Vosk recognition
  is also accepted. Legacy short-phrase configuration remains compatible.
- **Scope and discrepancies:** current code remains the source of truth. Older
  historical notes describe both adding and later removing the suffix; this
  entry records the user-requested final state without rewriting that history.
  No parallel UI/audio owner was added, and prior GoAway and farewell fixes were
  not modified.
- **Verification:** directed tests passed (`67` and final behavioral `55`);
  full suite `467 passed, 2 skipped, 137 subtests passed`; full compilation and
  `pip check` passed. Real microphone false-positive rate and first-open monitor
  rendering remain manual checks. Rollback restores the prior defaults and
  direct WebEngine render; no data migration is involved.

### Follow-up finding - extended wake confirmation ordering

- **Confirmed code defect:** `listen_for_openwakeword()` passed a Vosk final to
  the suffix verifier before calling `observe_neural()` for the same audio
  block. A valid coincident final therefore saw an unarmed verifier. The exact
  equality check also lost valid continuous/segmented output when Vosk rendered
  the OOV name through an allowed alias.
- **Correction:** neural evidence is committed first; exact `wake up` must be
  the consecutive tail of the confident Vosk final. Prefix-only Jarvis aliases
  retain the already bounded window, unrelated finals cancel it, and the closed
  grammar now contains the corresponding extended alias phrases.
- **Model decision:** Gemini is unnecessary for this defect and would couple an
  always-on local wake boundary to network availability, API/session lifecycle,
  latency and external audio processing. The existing offline owners remain.
- **Runtime evidence:** the active listener had started before the corrected
  file timestamp, so it was still executing old code. Only the status-owned wake
  PID was terminated; the existing supervisor replaced it and published a new
  PID in `listening` state with `Hey Jarvis Wake Up`. No other process was
  targeted. Full verification: `469 passed, 2 skipped, 137 subtests passed`;
  dependency and secret checks plus `git diff --check` passed.
- **Second runtime correction:** twenty physical attempts produced no new
  approval while the listener remained healthy. Complete confident extended
  Vosk phrases now survive late endpointing independently of the neural timer;
  only suffix-only recognition still requires an armed neural prefix. The
  segmented bound is five seconds. The status-owned listener alone was reloaded
  and returned to `listening`; Gemini and all other owners remain unchanged.
- **Root-cause acceptance evidence:** with a clean diagnostic process tree, the
  microphone delivered real speech, OpenWakeWord reached `0.331` over `0.080`,
  Vosk produced the exact four-word category at confidence `1.000`, and the
  detector approved. The launcher started the app, found its main window and
  `jarvis_status` published `on`; the process remained responsive. Therefore
  Gemini, battery and application bootstrap are excluded for this incident.
  Temporary diagnostics were removed and the normal hidden supervisor restored
  while the launched app remained open.

## Verified correction - 2026-08-01 - Vosk endpoint starvation

- **Root cause:** the extended detector treated Vosk final output as mandatory.
  Under continuous ambient audio, Vosk can preserve the correct phrase only as
  a partial hypothesis and postpone its endpoint indefinitely. The code logged
  but categorically ignored that evidence, leaving an armed phrase stuck until
  timeout. A second availability mismatch allowed `listening` before mandatory
  Vosk had loaded.
- **Correction:** `StablePartialWakeConfirmation` requires the exact suffix for
  three unchanged blocks plus an armed neural prefix, recent voice and unlocked
  session. Any mismatch resets state. Confident final/full-phrase paths remain
  unchanged. Extended mode now waits for Vosk readiness; legacy mode does not.
- **Runtime evidence:** the clean active listener publishes `vosk_ready=true`
  and `verification_stage=waiting_prefix` with current heartbeats. No audio or
  transcript is placed in runtime state.
- **Scope:** only wake confirmation/readiness and tests changed in this pass.
  Microphone selection, thresholds, application launch, GoAway rotation,
  farewell drain, Study, permissions, providers and Gemini remain intact.
- **Verification:** `51` directed wake tests and `472 passed, 2 skipped, 137
  subtests passed` globally; compilation and `pip check` passed. Physical phrase
  acceptance on the final listener remains the last user observation.
- The initial `listening` publication now includes the same readiness fields as
  its heartbeat, including after microphone-stall recovery. Final runtime state:
  new listener, `vosk_ready=true`, `verification_stage=waiting_prefix`.
