# Cancellation and isolation of tools

## Cooperative contract

`ToolExecutor` creates a `CancellationToken` per execution. It only delivers it to a
handler marked as cancelable whose signature explicitly accepts
`cancellation_token`; inherited handlers continue to receive only
Your arguments.

An execution with `RequestContext` can be marked by
`ToolExecutor.cancel(request_id)`. Timeout uses the same signal.
waits for a limited grace for the handler to clean up resources and declare his
status:

- `ToolCancelled` carries effect, verification, rollback and evidence;
- a structured response produced after the signal retains its states;
- lack of recognition remains `cancellation_unacknowledged` and
`effect=unknown`.

The token is thread-safe, single-use and supports callbacks. It does not interrupt
Threds by force.

## Processes

`run_cancellable_process()` starts a process without `shell`, consult the token and
the timeout, and before returning it ends and collects the created tree.
uses the exact PID of `Popen` and its descendants by `psutil`; never searches
processes by name.

The first pilot was the `dev_agent` project execution command.
Phase 13 that automatic execution was withdrawn: the agent retains checkpoints
between planning and contained scripts, and `AgentSupervisor` removes the
files created by the task if it fails or cancels. The runner is still available
for explicit tools that run reliable and allowed processes.

## Limits

- Handlers with no cancellation parameter maintain legacy behavior.
- Python does not allow you to safely stop an arbitrary thread; a handler who
ignore the token can continue.
- Model blocking calls still depend on the external timeout of the
ToolExecutor; Python cannot finish your thread by force.
- `dev_agent` no longer installs, opens editor, or executes the preview.
will require an operating system sandbox and another confirmation, not just `cwd`.
- Automatic rollback covers only new files owned by the
task; existing projects are rejected before writing.
- `cancel(request_id)` requires active execution with `RequestContext`.
