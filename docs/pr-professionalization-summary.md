# Repository professionalization

## Objective

Improve the public GitHub presentation, documentation navigation,
contribution workflow, transparency, release guidance, and repository metadata
without changing JARVIS runtime behavior, architecture, APIs, or dependencies.

## Changes

- reorganized the README first impression with verified badges, prototype and
  safety warnings, a real product screenshot, concise capabilities, and quick
  navigation;
- added a complete documentation index plus honest current-status and
  known-limitations sections;
- added fork-based contribution guidance, pull request and issue templates,
  secret checklists, and CODEOWNERS;
- clarified Mark XLVIII provenance, Mark LI modification scope,
  non-commercial conditions, AI-assisted development, and maintainer
  responsibility;
- documented the existing `v2.0.0` tag with requirements, installation,
  limitations, and a reproducible validation procedure;
- added the authorized public GitHub topics without changing visibility,
  licensing, collaborators, merge settings, or branch protections.

No product source code, runtime configuration, dependency declaration, API, or
architecture was changed by this pull request.

## Verification performed

Environment: 64-bit Windows, Python 3.14.6, pytest 9.1.1.

- `python -m pip install -r requirements-dev.txt`: completed; every requirement
  was already satisfied.
- `python -m pip check`: passed with no broken requirements.
- Relative Markdown validation: 65 links across 33 tracked Markdown files;
  all targets resolved, including the single referenced image.
- `python scripts/check_secrets.py --repo-root .`: passed for tracked and
  staged content.
- `python -m pytest`: 444 passed, 2 skipped, 1 dependency deprecation warning.
- `scripts/validate_baseline.ps1`: completed successfully, including launcher
  help, smoke imports, 37-tool inventory, Python syntax, Ruff, mypy over 17
  typed source files, secret scanning, structured inventories, 444 tests, 134
  subtests, and Git whitespace validation.
- `git diff --check`: passed.

The warning comes from `google-genai` using a Python typing alias deprecated
for future Python 3.17 removal; it did not fail the suite.

## Evidence limits

The validation did not start direct or wake mode, open Gemini, use a microphone
or camera, activate desktop automation, connect external accounts, start the
LAN dashboard, or execute tools with real external effects. Passing mocks and
offscreen imports is not hardware, account, network, or service validation.

CI validates Windows with Python 3.12. The local validation above used Python
3.14.6. Platform behavior outside Windows remains limited and was not verified
by this work.

## Risks and rollback

The changes affect public documentation, GitHub contribution templates, one
image asset, CODEOWNERS, and repository topics. The main risk is inaccurate or
stale public guidance; claims were therefore limited to repository evidence and
explicitly qualified where hardware or external services were not exercised.

Before merge, rollback is closing the pull request and deleting its branch.
After merge, revert the pull request as one unit to restore the prior public
documentation and repository files. GitHub topics are remote metadata and can
be removed independently without changing repository history.
