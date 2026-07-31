## Description

Describe the change and its boundaries.

## Motivation

Explain the problem being solved and why this approach is appropriate.

## Verification

List every command or manual check actually performed and its result. Mark
anything that was not verified; do not infer hardware or external-service
behavior from mocks.

## Risks and rollback

Describe affected boundaries, possible regressions, sensitive effects, and the
exact rollback approach.

## Evidence

Provide sanitized logs, screenshots, or measurements only when they are real
and relevant. Remove credentials, account data, personal paths, memory, and
private content.

## Checklist

- [ ] The pull request has one focused objective and no unrelated refactor or formatting.
- [ ] Relevant tests and checks were run, and their exact results are reported above.
- [ ] CI is passing, or any unavailable check is explicitly identified.
- [ ] No secrets, tokens, OAuth clients, personal configuration, memory data, or private logs are included.
- [ ] Examples use clearly fictitious values.
- [ ] Documentation and tests were updated where behavior or public guidance changed.
- [ ] New or changed sensitive actions document risk, validation, confirmation, verification, audit, and rollback.
- [ ] Attribution, third-party notices, and non-commercial licensing conditions are preserved.
