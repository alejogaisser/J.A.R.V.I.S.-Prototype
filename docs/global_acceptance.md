# Global acceptance gate

This gate translates the 19 criteria of section 15 of the governing PDF into a
verified and verifiable inventory. The source of data is
`docs/global_acceptance.json`; `scripts/check_global_acceptance.py` validates that
there is no lack of criteria, that states are explicit and that all evidence
stay inside the repository and exist.

States:

- `verified`: the available automated evidence meets the criterion;
- `partial`: Real implementation exists, but coverage does not reach the full
area declared;
- `manual`: hardware, packaging, visual observation or measurement required
real that mocks cannot prove;
- `blocked`: cannot be advanced without an external dependency or decision.

Basic validation executes integrity mode:

```powershell
python scripts/check_global_acceptance.py --repo-root .
```

That mode fails with incomplete inventory, non-existent evidence, paths
external or incoherent state, but allows pending states.
strict overall consultation is carried out separately:

```powershell
python scripts/check_global_acceptance.py --repo-root . --require-complete
```

As long as there is a criterion other than `verified`, the second command ends
with code 2. By design, stage 15 can deliver a reliable gate without
to affirm that the historical gaps are already resolved.

## Initial result

Memory persistence and `runtime_state` hardened at this stage:
temporary in the same directory, `flush`/`fsync`, validation before publishing,
`os.replace`, failure cleaning and preservation of the last valid primary.
Memory recovers from validated backup; runtime status, to be
best effort telemetry, retains the last complete document and never
It stops the start.

The main outstanding issues remain:

- central envelope for special routes and migration of tools legacy;
- complete dashboard/shutdown ownership and supervision of the rest of workers;
- universal propagation/audit outside the central tool path;
- migration of text, Live and vision providers;
- actual wake metrics, audio, reconnection and shutdown.

## Rollback

Reversing the commit of the stage restores the previous writers.
memory regression forces manual rollback, preserve `long_term.json` and
`long_term.json.bak`, validate both as Scheme 2 JSON and restore only the
most recent valid copy with JARVIS arrested.
