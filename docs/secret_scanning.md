# Automated secret scanning

## Objective

`scripts/check_secrets.py` prevents the normal validation cycle from publishing
known private files or credentials with high confidence formats. No
reads ignored files or prints the text that produced a match.

## Sources inspected

- Each route returned by `git ls-files`.
- The content of the working tree for unchanged files.
- The exact index blob for files added or modified in tagging.

Using the blob staged prevents a credential prepared to commit from remaining
hidden by a back and secure copy in the working tree. The symlinks that
solve outside the repository make the check fail.

## Policy

The gate rejects `.env*` files, real API/OAuth configuration,
certificates, real audits, personal memory and logs. It also detects
high-confidence forms of Google, GitHub, OpenAI, AWS and Slack keys, plus
of private keyheads.

Each finding contains only:

- route versioned;
- line, where applicable;
- rule identifier;
- source `working-tree` or `staged`.

Matching value is never part of the result.

## Implementation

```powershell
python scripts/check_secrets.py --repo-root .
```

`scripts/validate_baseline.ps1` executes this command after `compileall` and
before the tests.

## Limits

- Unversed files are not inspected: `.gitignore` and revision
They remain mandatory at the local level.
- High-confidence formats are prioritized to avoid false positives; it is not
a generic entropy analysis.
- The gate does not clear the history or revoke credentials.
- A credential that reached a commit or remote should be rotated even after
Delete.

## Rollback

The integration is independent of the runtime. Faced with a false positive, adjust
a rule and retain a regression test. Withdraw the call temporarily
baseline does not modify JARVIS, but removes a preventive barrier and must
to be documented.
