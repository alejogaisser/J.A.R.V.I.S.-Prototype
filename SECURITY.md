# Security

## Reporting a vulnerability

Do not publish credentials or exploitable details in an issue. If this
repository is hosted on GitHub, use **Security → Report a vulnerability** to
send a private report to the maintainer.

## Data that must never be published

The repository deliberately excludes:

- `config/api_keys.json`, `.env` files, and certificates;
- OAuth clients and external-service tokens;
- personal configuration and connector audit data;
- `memory/long_term.json` and other personal memory;
- logs, screenshots, local workspaces, and virtual environments;
- generated artifacts under `output/`;
- `AGENTS.md`, which contains local development instructions.

Before making a fork or copy public, inspect both the current tree and the
entire Git history. Immediately rotate any credential that has ever been
published, even if the containing commit was later removed.

`*.example.json` files are secret-free templates and may be committed.

## Preventive scan

Run this command before every commit:

```powershell
python scripts/check_secrets.py --repo-root .
```

The command inspects tracked files and uses the index blob for staged files. It
fails when it detects a known private path or a high-confidence credential,
without printing the matched value.

This check does not inspect untracked files and does not prove that the full
history is clean. If a credential reached a commit or remote, revoke and rotate
it; deleting the file alone is not sufficient.

General runtime events use `StructuredRuntimeLog`: it accepts only allowlisted
metadata, sanitizes messages, and rotates `logs/runtime.jsonl`. Tool events
remain in `RequestAuditSink` and accept neither arguments nor bodies. Real logs
remain outside Git.

## Minimum checklist before changing visibility

1. Scan secrets in the working tree and the entire history.
2. Confirm that templates contain only recognizable placeholders.
3. Review branches and tags, because they also become visible.
4. Confirm that `git status` contains no personal artifacts waiting to be
   added.
5. Verify credits, licenses, and third-party notices.
6. Remember that copies or forks created while the repository is public cannot
   be removed from other people's systems by making the repository private
   again.

## Scope

JARVIS performs local actions and can connect to external services. Keep
confirmations enabled for sensitive operations, apply the principle of least
privilege, and review each integration before granting access.
