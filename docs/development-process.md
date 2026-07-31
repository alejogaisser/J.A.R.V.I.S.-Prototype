# Development process and AI assistance

## Maintainer responsibility

Alejo Gaisser maintains the Mark LI adaptation and defines its objectives,
functional workflows, safety criteria, integration decisions, and acceptance
of changes. A merged change is considered reviewed and accepted by the
maintainer; tooling or automation does not transfer that responsibility.

This responsibility applies only to the Mark LI contributions and
modifications described in [NOTICE.md](../NOTICE.md). It does not imply
authorship or ownership of unchanged Mark XLVIII code, retained assets, or
third-party components.

## Use of AI assistance

AI assistance has been used to accelerate implementation drafts, code and
documentation review, test preparation, and technical writing. AI-generated
output is treated as an untrusted proposal that must be checked against the
repository, its tests, documented architecture, security policy, and licensing
conditions.

AI assistance is not accepted as evidence that a feature works, a test passed,
hardware is compatible, an external effect occurred, or a license permits a
use. Those claims require reproducible commands, typed results, direct
inspection, or other evidence appropriate to the boundary.

## Review and acceptance

Before acceptance, a change should have:

- a scoped objective and an identified owner;
- review against the current implementation and public documentation;
- relevant tests or an explicit statement of what could not be verified;
- security and privacy review for sensitive data or external effects;
- attribution and third-party-license review where applicable;
- documented risks, evidence limits, and rollback.

Mocks may establish contract behavior but do not prove microphone, camera,
desktop, account, network, or external-service behavior. Measurements and
screenshots must identify their real environment and must not be generalized
beyond the evidence collected.

## Contribution policy

External proposals follow [CONTRIBUTING.md](../CONTRIBUTING.md) and arrive
through fork-based pull requests. The maintainer may reject work that is out of
scope, unverifiable, unsafe, incompatible with the non-commercial conditions,
or inconsistent with the project's attribution obligations.
