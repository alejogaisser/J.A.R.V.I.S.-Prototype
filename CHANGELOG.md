# Changelog

## English documentation — 2026-07-31

- translated the public-facing README, license, attribution notice, security
  policy, third-party notices, and changelog into English;
- translated `ARCHITECTURE.md`, `ROADMAP.md`, `AUDIT.md`, and every technical
  guide under `docs/` into English;
- preserved commands, paths, API names, legal meaning, authorship, and the
  previous maintainer alias;
- preserved Markdown tables, diagrams, code blocks, links, and contractual
  identifiers; local-only instructions and the private Obsidian project log
  remain in Spanish.

## Public release preparation — 2026-07-31

- added `NOTICE.md` with the exact provenance, author, license, and reference
  commit for Mark XLVIII;
- identified Alejo Gaisser through the current `@alejogaisser` account while
  preserving `@AlejoGaisser07` as the historical alias;
- clarified that Mark LI publishes source code for personal, non-commercial
  use without claiming rights over original or third-party material;
- added a non-affiliation notice for Marvel and Disney;
- replaced Google OAuth example values with unambiguous placeholders;
- excluded `output/` to prevent generated artifacts from being published;
- added regression tests for credits, placeholders, models, and publication
  metadata;
- ported the Google Workspace, wake, startup, and publication changes to the
  modern `main` branch while preserving its policy, provider, and traceability
  contracts.

## Safe publication — 2026-07-23

- added the project license, third-party notices, and security policy;
- excluded local development instructions from version control;
- prepared the removal of personal paths from all public commits and tags
  without changing the code in those versions.

## 2.0.0 — Mark LI — 2026-07-23

Mark LI consolidates the current evolution of JARVIS as a major update:

See the [v2.0.0 release notes](docs/releases/v2.0.0.md) for requirements,
limitations, installation, and the reproducible validation procedure.

- new holographic interface with Core, Pet Mode, and workspaces;
- local “Hey Jarvis” activation with OpenWakeWord and Vosk fallback;
- corrected the offset between voice input and neural score without reducing
  false-positive thresholds;
- automatic audio stream recovery after mute, silence, or driver lockups;
- user-controlled memory, expiration, and a graph containing only real
  memories;
- central tool registry, risk-based permissions, and voice confirmations;
- Study workspace for mathematics, physics, chemistry, anatomy, and 2D/3D
  visualizations;
- GEO workspace with open maps, geocoding, routing, and weather;
- shared primary session for voice and camera;
- hardened Google and Outlook connectors;
- sanitized diagnostics, detector supervision, and recoverable shutdown;
- 211 automated tests, 28 passing subtests, and one optional test skipped in
  the validated environment.

This release replaces the previous version as the default content of `main`.
Private files, credentials, personal memory, logs, local workspaces, and Vosk
models are not part of the repository.

## 1.5 — Legacy

The last version before the Mark LI migration remains frozen under the
`v1.5-legacy` tag. It can be inspected or downloaded from there without
keeping a duplicate copy on `main`.

## Origin

JARVIS Mark LI derives from Mark XLVIII, created by FatihMakes, and preserves
its attribution and non-commercial license.
