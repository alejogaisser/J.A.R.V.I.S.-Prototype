# Operational change control

This gate converts section 16 of the governing PDF into a verifiable contract
for architectural phases. It does not replace technical judgment or demonstrate acts
external: obligates to record evidence and fails if a closure is left
incomplete or inconsistent.

## Scope

`docs/operational_change_control.json` contains:

- the 11 operating mandates `OP-01` to `OP-11`;
- all 8 questions prior to refactoring `REF-01` to `REF-08`;
- a phase-by-phase registration completed from phase 15.

Each record records motive, objective, files, risks, tests, metrics,
rollback, owner, policy pass, effect check, ante behavior
cancellation/timeout/reconnection, compatibility, benefit of abstractions,
limits of evidence and status of Obsidian note.

The gate checks:

- accurate and unduplicated inventory;
- existing evidence and files, relative and contained in the repository;
- the absence of sensitive routes in the registers;
- sequential phases and a single register per phase;
- approved results and note Obsidian updated before accepting a phase
marked as completed in `ROADMAP.md`;
- mandatory confirmation and preview when a change is declared destructive;
- explicit benefit for any abstraction.

## Use

```powershell
python scripts/check_operational_change_control.py --repo-root .
```

The database executes this command before pytest. For a new phase:

1. create the record with tests and Obsidian in `pending`;
2. implement and execute targeted tests;
3. record actual results and metrics, distinguishing hardware mocks;
4. update the Obsidian note;
5. change those states to `passed`/`updated`;
6. just then mark the completed phase in `ROADMAP.md`.

## Manual limits

IC cannot prove that an operator read `AGENTS.md`, observed `git status` or
has updated an external archive of Obsidian.
obligations and requires them to be declared, but the final evidence should be reviewed in the
Handoff. Nor does it transform a hacked test into hardware verification.

## Rollback

Remove call from `scripts/validate_baseline.ps1` disables gate without
change runtime. Reversing all files of this phase restores the baseline
previous; no data migration or productive adapter involved.
