# ToolResult v2

## Independent States

`ToolResult` retains the inherited fields `success`, `message`, `data`,
`error_code` and `request_id`, and adds a versioned contract:

- `execution_status`: `succeeded`, `failed`, `rejected`, `timed_out` or
`cancelled`;
- `effect_status`: `none`, `not_applied`, `applied`, `partial` or `unknown`;
- `verification_status`: `not_requested`, `verified`, `failed` or `unknown`;
- `rollback_status`: availability or result of rollback;
- `duration_ms`;
- `evidence`: short identifiers provided by a verifier.

`to_dict()` and `from_dict()` produce and validate scheme 2.
Contradictory, unknown versions and negative durations are rejected.

## Inherited adaptation

Existing tools can continue to return text, booleans, mappings,
`None` or the previous `ToolResult`:

- a successful legacy reading adapts as `succeeded/none`;
- a tool with possible effect that only returns textual success
`succeeded/unknown`;
- an inherited failure does not invent that the effect was reversed or not applied;
- a result v2 returned by the handler retains effect, verification,
rollback and evidence;
- the complete executor `request_id` and measured duration.

`success/message/data/error_code` compatibility remains available during
Batch migration of the 37 tools.

## Timeout and errors

A timeout is always represented as `execution_status=timed_out`.
handler legacy non-cooperative preserves `effect_status=unknown` and evidence
`cancellation_unacknowledged`, because the thread can continue to run.

An opt-in handler receives `CancellationToken`. If you recognize the signal inside the
executor grace, `ToolCancelled` retains effect, verification, rollback
and evidence actually observed and adds `cancellation_acknowledged`.
explicit cancellation uses `execution_status=cancelled`; it is located by the
`request_id` active.

An application rejected before invoking the handler uses
`rejected/not_applied`. An exception during handler uses `failed/unknown`.

## Integration

Normal and special routes include v2 metadata in `FunctionResponse` and in the
`completed` event of the sink audit. `data` is not serialized within that metadata
response.

Phase 5 incorporates the first concrete verifier: `create_file`, `copy` and
`move` regular files capture resolve path, size and SHA-256. A copy
o movement only remains `applied/verified` if the fate evidence matches
with the source; `move` further requires that the source no longer exists. If the effect does not
is observed, the message does not present it as verified.
directories temporarily retain the legacy adapter.
