# Request lifecycle and auditing

## Contract

Each function call creates an immutable `RequestContext` with:

- `request_id`: local UUID, independent of provider ID;
- `source`: `local`, `ui`, `wake`, `dashboard_text` or `dashboard_audio`;
- `tool_call_id`: opaque function call identifier;
- `created_at`: timestamp UTC.

The same context goes through validation, policy, confirmation, execution and
response. A pending action reuses its context when it is approved; it does not create
another `request_id`. `ToolExecutor` callers not yet delivered
context retain the previous behavior.

## Events

`logs/request_audit.jsonl` receives metadata events in order:

1. `requested`;
2. `policy`;
3. `confirmation`;
4. `started`;
5. `completed`;
6. `response`.

A blocked or invalid request may end before `started`.
pending confirmation issues an interim response and continues with it
ID after approval. Denial closes the request as `denied`.

## Privacy

Sink accepts only fields listed: IDs, event, tool, source,
categorical result, normalized operation, policy, error code and duration.
It does not accept or serialize arguments, prompts, bodies, messages, memory, paths,
queries, addresses, tokens or tool results. Tags no
structured are replaced by `unknown` or `custom`.

Directory, opening, encoding or serialization errors return `False` and
do not interrupt policy, execution or response. Writing can be disabled
with `JARVIS_REQUEST_AUDIT=0`; the file is inside `logs/`, excluding Git.

## Deliberate limits

This phase adds correlation and duration of execution, but does not state that
external effect has been observed. Evidence, verification, rollback and states
of effect belong to `ToolResult v2` and phase verifiers
later.
