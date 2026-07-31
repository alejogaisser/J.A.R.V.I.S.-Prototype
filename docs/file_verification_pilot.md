# File verification pilot

## Scope

`file_controller` produces `ToolResult` v2 for three file operations
regular:

- `create_file`;
- `copy`;
- `move`.

Directory operations and the rest of the controller maintain return
legacy. This allows to disable the pilot by returning the dispatch to the handlers.
existing, without changing their signatures.

## Evidence and states

The verifier reopens the destination after the operation and captures:

- absolute route resolved;
- size in bytes;
- SHA-256 read from the filesystem.

Create compares the observed hash to the requested content. Copy and move
compare the size and hash of the origin with the destination; moving also requires absence
of origin. Only then does the result declare
`succeeded/applied/verified`.

A destiny conflict is rejected before writing and remains
`rejected/not_applied`. If the operation ends but the evidence cannot
be observed or not matched, the result remains `succeeded` with verification
failed and never communicates the effect as verified.

## Rollback declared

The result includes an explicit recipe and marks rollback as available:

- create/copy: send the destination to the wastebasket;
- move: move the destination back to the source path.

The automatic execution of these recipes is not part of this pilot.
pending to incorporate it behind policy and also verify its result.

## Limits

- There is no recursive directory tree verification.
- An atomic snapshot is not guaranteed if another process modifies a file
between the operation and the reading of evidence.
- SHA-256 proves equality of observed content, no identity or provenance.
- Executor timeout still doesn't cancel a running synchronous handler.
