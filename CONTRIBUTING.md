# Contributing to JARVIS Mark LI

Thank you for considering a contribution. This repository accepts occasional
external contributions through forks and pull requests; direct collaborator
access is not required. The maintainer may decline proposals that fall outside
the project's scope, safety model, or non-commercial licensing conditions.

## Before you begin

- Read [SECURITY.md](SECURITY.md), [ARCHITECTURE.md](ARCHITECTURE.md), and the
  [documentation index](docs/README.md).
- Review [LICENSE.md](LICENSE.md), [NOTICE.md](NOTICE.md), and
  [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Contributions must preserve
  existing attribution and non-commercial conditions.
- For a vulnerability, use the private reporting process in
  [SECURITY.md](SECURITY.md). Do not open a public issue containing exploitable
  details or credentials.
- Search existing issues and pull requests before proposing duplicate work.

## Contribution workflow

1. Fork the repository on GitHub.
2. Create a focused branch in your fork from the current `main` branch.
3. Install the project and development dependencies.
4. Make one scoped change without unrelated formatting or refactoring.
5. Run the relevant tests and safety checks.
6. Push the branch to your fork and open a pull request against this
   repository's `main` branch.

Do not request collaborator access for an occasional contribution. Keep your
fork available until review is complete so requested changes can be added to
the same pull request.

## Development setup

JARVIS is developed and validated primarily on 64-bit Windows with Python 3.12.
Create an isolated environment from the repository root:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
python -m playwright install chromium
```

Never use real accounts, Gemini sessions, microphones, cameras, desktop
automation, or private data in automated tests. Mock hardware, network,
Windows APIs, external services, accounts, and dangerous filesystem effects.

## Validation

Run tests targeted to the changed boundary first. Before requesting review,
run the repository baseline when your environment supports it:

```powershell
python scripts/check_secrets.py --repo-root .
python -m pytest -q
powershell -ExecutionPolicy Bypass -File scripts\validate_baseline.ps1 `
  -Python .\.venv\Scripts\python.exe
git diff --check
```

State exactly which commands ran and whether they passed. If a command could
not run because of the environment, hardware, a dependency, or an external
service, mark it as not verified. Passing mocks is not evidence that hardware
or external effects work.

## Change and commit standards

- Keep each commit limited to one objective and use a concise imperative
  subject such as `fix: preserve request origin` or `docs: clarify setup`.
- Preserve existing public APIs and legacy adapters unless the pull request
  includes evidence of functional equivalence and the change is in scope.
- Add types to new contracts and tests for changed behavior.
- Avoid broad exception suppression, success inferred from text, and new
  abstractions that do not clarify ownership or make effects verifiable.
- Do not combine functional changes with dependency updates, broad renames, or
  mass formatting.

## Security requirements

Never commit credentials, `.env` files, OAuth clients, tokens, certificates,
personal configuration, memory data, private logs, local workspaces, or account
content. Use unambiguous fictitious values in examples.

Any new or changed sensitive action must document:

- its risk level and availability conditions;
- argument validation and allowed scope;
- the preview or confirmation shown to the user;
- execution timeout or cancellation behavior;
- typed effect, verification evidence, audit behavior, and rollback limits.

Sensitive tool calls must use the existing registry, permission policy,
confirmation, execution, audit, and typed-result path. Do not introduce a
parallel bypass.

## Accepted scope

Good proposals include focused bug fixes, tests, documentation corrections,
security hardening, accessibility improvements, and bounded work already
aligned with the architecture and roadmap. Large features or architectural
changes should be discussed before implementation.

Pull requests may be declined when they introduce unrelated changes, weaken
confirmation or privacy controls, add unverifiable claims, conflict with
licensing, or expand the product beyond the maintainer's intended scope.

## Pull request expectations

Complete the pull request template, describe risks and rollback, include only
sanitized evidence, and respond to review on the same branch. Required CI must
be green before merge. Approval remains at the maintainer's discretion, and
merge signifies that the maintainer accepts responsibility for the change.

## AI-assisted development

AI assistance has been used to accelerate implementation drafts, review,
testing support, and documentation. The maintainer defines project objectives,
functional workflows, safety criteria, integration decisions, and acceptance
of changes. AI output is not treated as evidence or as an independent approval.

Every merged change is considered reviewed and accepted by the maintainer,
including changes prepared with AI assistance. See
[docs/development-process.md](docs/development-process.md) for the complete
responsibility and evidence policy.
