# Tool migration matrix

## Contract

Snapshot from the 37 `ToolDefinition` registry at 2026-07-28.
the current behavior, not the desired level. `No contract` means that
runtime still has no typed evidence/verification or rollback.

Since Phase 8 all `executor` handlers receive `UiCommandFacade`, no
`JarvisUI`. This closes the shortcut to widgets but does not by itself
convert their legacy returns into verifiable results.

The `tests/test_tool_inventory.py` test compares names, risk, route and timeout
against `main.py` and `core/tools/builtins.py`. A new tool cannot be incorporated
without adding a row and declaring its limits.

| Tool | Risk | Current Policy | Preview | Current return | Verification | Rollback | Timeout s | Route | Coverage | Pending migration |
| --- | --- | --- | --- | --- | --- | --- | ---: | --- | --- | --- |
| `open_app` | local_change | FREE | No | Legacy text | No contract | Manual closure | 30 | executor | Static safety | Evidence of process/window |
| `web_search` | read_only | FREE | No | Legacy text | Text sources | Not applicable | 30 | executor | Clock + provider fakes/fallback | Typed dates |
| `system_status` | read_only | FREE | No | Legacy text | Point-in-time reading | Not applicable | 30 | executor | Policy | Structured result |
| `weather_report` | read_only | FREE | No | Legacy text | Source in text | Not applicable | 30 | executor | Indirect | Provider injection |
| `send_message` | external_effect | CONFIRM_ALWAYS | Yes | Legacy text | No contract | Not available | 30 | executor | Policy/review | Remote ID + delivery status |
| `reminder` | external_effect | CONFIRM_ONCE | No | Legacy text | No contract | Manual | 30 | executor | Parametrized policy | Verify persistence |
| `youtube_video` | read_only | FREE | No | Legacy text | No contract | Close browser | 30 | executor | No direct proof | Typed result and destination |
| `screen_process` | read_only | FREE | No | Special route | Partial capture + cooldown owner | Not applicable | 30 | special | Safety + runtime owner | Common envelope + latency |
| `close_camera` | read_only | FREE | No | Special route | Owner releases pending frame; implicit UI | Reopen Camera | 30 | special | Safety + runtime owner | Event/camera verification |
| `camera_control` | read_only | FREE | No | Special route | Backpressure owner; implicit UI status | Reverse action | 30 | special | Camera + runtime owner | Risk per operation + event |
| `pet_mode` | local_change | FREE | No | Legacy text | Qt sign glued | Get out of Pet | 30 | executor | UI + Qt affinity | Typed result |
| `interface_control` | local_change | FREE | No | Legacy text | Confirmation of the Qt slot | Reverse action | 30 | executor | Interface + Qt affinity | Typed result |
| `visual_mouse` | read_only | FREE | No | Special route | AI/UI partial image | Not available | 30 | special | Static safety | Real risk + common envelope |
| `computer_settings` | sensitive | FREE; power CONFIRM_ALWAYS | No | Legacy text | No contract | Depending on operation | 30 | executor | Policy/security | Matrix per operation |
| `browser_control` | sensitive | FREE reading/navigation; ONCE interaction; unknown ALWAYS | No | Legacy text | No contract | Depending on operation | 30 | executor | Parametrized policy | Submission preview and verification |
| `file_controller` | sensitive | By action | Yes | `ToolResult` v2 for create/copy/move; rest legacy | Route, size and SHA-256; absence of moving origin | Create/copy bin; reverse motion for move | 30 | executor | Safety + pilot verifier | Recursive verification and migration of remaining operations |
| `desktop_control` | sensitive | CONFIRM_ONCE | No | Legacy text | No contract | Depending on operation | 30 | executor | No direct proof | Classification by operation |
| `code_helper` | sensitive | explain FREE; write/edit/optimize ONCE; rest ALWAYS | No | Legacy text | Registered raw routine is not executed | VCS/manual | 120 | executor | Policy/scripts | Migrate routines to declarative actions allowed |
| `dev_agent` | sensitive | CONFIRM_ONCE | Yes, new project not executed | Supported text + `AgentResult` internal | Workspace/archives/bytes/typed evidence | Automatic for files created by the task | 120 | executor | Policy + `AgentSupervisor` | Provider cancelable timeout; real sandbox before enabling execution |
| `computer_control` | sensitive | Common actions FREE; rest ONCE | No | Legacy text | AI/UI partial image | Not available | 30 | executor | Partial security | Risk per action + limits |
| `game_updater` | external_effect | CONFIRM_ONCE | No | Legacy text | No contract | External installer | 120 | executor | Static safety | Verification of installation status |
| `flight_finder` | read_only | FREE | No | Legacy text | Text sources | Not applicable | 30 | executor | No direct proof | Provider + result scheme |
| `shutdown_jarvis` | sensitive | FREE | No | Special route | Idempotent state machine with deadline | Manual restart | 30 | special | Policy + lifecycle owner | Shared sensitive policy + envelope |
| `file_processor` | sensitive | FREE reading; ONCE writing; ALWAYS execution | No | Text/legacy file | No contract | Depending on operation | 30 | executor | Parametrized policy | Verification of artifacts |
| `save_memory` | local_change | Policy bypass | No | Special route | Non-contractual subsequent reading | Forget/manual | 30 | special | Indirect memory | Pass policy and executor |
| `memory_list` | read_only | FREE | No | List/dict legacy | Loaded data | Not applicable | 30 | executor | Memory | Paged/typed result |
| `memory_search` | read_only | FREE | No | List/dict legacy | Loaded data | Not applicable | 30 | executor | Memory | Paged/typed result |
| `memory_update` | local_change | CONFIRM_ONCE | No | Bool/dict legacy | Partial persistence | History | 30 | executor | Policy/memory | Evidence + version |
| `memory_forget` | sensitive | CONFIRM_ALWAYS | No | Bool/dict legacy | Partial persistence | `memory_restore` | 30 | executor | Policy/memory | Evidence + version |
| `memory_restore` | local_change | CONFIRM_ONCE | No | Bool/dict legacy | Partial persistence | `memory_forget` | 30 | executor | Policy/memory | Evidence + version |
| `memory_graph` | read_only | FREE | No | Legacy text | Implicit reindexing via Qt signal | Not applicable | 30 | executor | Graph/UI + Qt affinity | Metrics |
| `geo_map` | read_only | FREE | No | Dict/text legacy | Provider response; coupled presentation | Not applicable | 30 | executor | GEO + Qt affinity | Typed provider |
| `math_engine` | read_only | FREE | No | Text/legacy file | Partial local calculation | Not applicable | 30 | executor | Math/security | Result/typed artefact |
| `study_engine` | local_change | FREE | No | Text/legacy file | Partial per operation | According to artifact | 30 | executor | Study | Risk and provider per operation |
| `account_connector` | external_effect | FREE reading; connect/download ONCE; create/disconnect ALWAYS | No | Text/JSON legacy | Partial Provider | Depending on operation | 30 | executor | Connectors/policy | Preview and external verification |
| `obsidian_connector` | sensitive | FREE reading; ONCE writing; rest of ALWAYS | No | Text/JSON legacy | Partial Filesystem | History/manual | 30 | executor | Obsidian/policy | Preview + note evidence |
| `permission_manager` | sensitive | FREE reading; ALWAYS changes | No | Special route | Store recharged | Restore preference | 30 | special | Policy/security | Common Atomic Store + Envelope |

## Special routes

Seven tools avoid the normal handler of the `ToolExecutor`:
`screen_process`, `close_camera`, `camera_control`, `visual_mouse`,
`shutdown_jarvis`, `save_memory` and `permission_manager`. Must be migrated by
small lots to the same speed of validation, policy, execution, audit and
result, preserving your UI/lifecycle requirements.

## Derived priority

1. Spread the remote source and add dashboard tests.
2. Correct `file_processor`, `code_helper`, browser, reminder and deeds
connectors.
3. Incorporate `RequestContext` before migrating special routes.
4. Extend by batch the already active pilot of file verification without
Infer the effects of legacy returns.
