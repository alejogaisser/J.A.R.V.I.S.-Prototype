# JARVIS Mark LI documentation

This index is the starting point for technical, security, validation, and
project-governance documentation. Evidence in these documents applies only to
the scope and environment each document explicitly describes.

## Project overview

- [Installation tutorial](../TUTORIAL.md) - Step-by-step Windows setup, Gemini
  configuration, first launch, updates, and common troubleshooting in Spanish.

- [Architecture](../ARCHITECTURE.md) — Current runtime boundaries, ownership,
  interaction flows, known structural problems, and the incremental target.
- [Baseline and validation](baseline.md) — Reproducible setup, validation
  commands, evidence collected, and limits of the automated baseline.
- [Quality gates](quality_gates.md) — Ruff, mypy, secret scanning, tests, and CI
  checks executed by the quality workflow.
- [Tool migration matrix](tool_migration_matrix.md) — Inventory of registered
  tools, risk levels, policy paths, verification, rollback, and migration state.
- [Security and permissions](../SECURITY.md) — Vulnerability reporting, private
  data exclusions, secret scanning, and publication safeguards.
- [Request lifecycle](request_lifecycle.md) — Request origin, correlation,
  policy, confirmation, execution, audit, and typed-result flow.
- [Audit and known debt](../AUDIT.md) — Verified findings, unresolved risks,
  evidence, and corrective work recorded against the real implementation.
- [Roadmap](../ROADMAP.md) — Incremental phases, completed work, remaining
  priorities, and validation expectations.
- [Optional integrations](../readme.md#optional-integrations) — Local setup for
  Obsidian, Google Workspace, and Microsoft Outlook.
- [Credits, attribution, and licensing](../NOTICE.md) — Project provenance and
  maintainer modifications; also review the [license](../LICENSE.md) and
  [third-party notices](../THIRD_PARTY_NOTICES.md).
- [Development process](development-process.md) — Maintainer responsibility,
  AI-assisted work, review expectations, and evidence requirements.

## Tool and effect contracts

- [ToolResult v2](tool_result_v2.md) — Typed execution, effect, verification,
  evidence, duration, and rollback fields.
- [Tool cancellation](tool_cancellation.md) — Cooperative cancellation pilot,
  timeouts, and the limits of inherited blocking handlers.
- [File verification pilot](file_verification_pilot.md) — Evidence collected
  after selected file operations and the boundaries of that verification.
- [Secret scanning](secret_scanning.md) — Tracked and staged-file scanning,
  safe reporting, and limitations for history and untracked content.

## Runtime and provider boundaries

- [Runtime ownership](runtime_ownership.md) — Owners and lifecycle contracts for
  session, audio, vision, dashboard, and shutdown state.
- [Runtime events](runtime_events.md) — Typed cross-boundary events and their
  compatibility layer.
- [Worker supervision](worker_supervision.md) — Worker health, containment,
  restart behavior, and shutdown coordination.
- [Provider adapters](provider_adapters.md) — Injected provider interfaces and
  the current migration boundary for models and external services.
- [Settings bootstrap](settings_bootstrap.md) — Validated settings ownership,
  atomic updates, and compatibility views.
- [Structured logging](structured_logging.md) — Sanitized runtime telemetry,
  allowlisted metadata, correlation, rotation, and failure behavior.

## UI and operational validation

- [UI thread boundary](ui_thread_boundary.md) — Qt-thread mutation rules,
  worker-to-UI data flow, snapshots, and compatibility constraints.
- [QML benchmark](ui_qml_benchmark.md) — Isolated prototype measurements,
  decision thresholds, and reasons PyQt Widgets remains the active UI.
- [Global acceptance](global_acceptance.md) — Structured acceptance inventory
  separating verified, partial, and manual evidence.
- [Operational change control](operational_change_control.md) — Required
  ownership, policy, verification, rollback, and compatibility evidence.
- [Audit closure](audit_closure.md) — Methodological closure of the prior audit
  plan without claiming that all architectural risks are resolved.
