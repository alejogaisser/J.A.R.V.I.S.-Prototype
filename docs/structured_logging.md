# Structured runtime logging

## Scope

`core.structured_logging.StructuredRuntimeLog` is the owner of general logs
of the main process. It complements, but does not replace:

- `RequestAuditSink`, which preserves the sanitized phases of each tool call;
- `CrashReporter` and `faulthandler`, which preserves diagnosis of fatal failures;
- the specific wake word console, required for audio support.

This increase does not massively convert the inherited `print()`.

## Outputs

By default each event is posted as a JSON line in:

- the diagnostic console;
- `logs/runtime.jsonl`.

The file uses `RotatingFileHandler`, up to 1 MiB and three backups.
`logs/` folder remains ignored by Git.

## Contract

Base fields:

- `timestamp` UTC;
- `level`;
- `event`;
- `component`;
- `message` sanitized and tapered, when it exists.

If the producer delivers a `RequestContext`, `request_id`, `source` are added
and `tool_call_id`. The additional metadata is restricted to a list of
status, operation, duration, error code, surface and motive.
arguments, prompts and unknown fields are discarded.

`main.py`, as the temporary composition root, configures the owner and registers:

- `application_started`;
- `runner_failed`;
- `application_stopped`.

## Sanitization

`redact_diagnostic_text()` covers sensitive mappings and URL parameters,
in addition to high-confidence formats from Google, GitHub, OpenAI, AWS and Slack and
Private keyheads. Matching value should never reach the
file or console.

## Degradation and competition

`logging` standard handlers serialize scripts between threads.
file cannot be opened, console remains active. If no output can
configure, `record()` returns `False`; boot continues.

## Limits

- The inherited `print()` still have no level or correlation.
- `RequestAuditSink` keeps its file separate and not yet rotated.
- `CrashReporter` retains its separate traceback and file format.
- No hardware was measured or Gemini, wake, camera or microphone started.

## Local measurement

In the clean validation environment, 1,000 sequential events with file
JSONL, disabled console and 1 MiB limit took 64,829 ms in total
(0,064829 ms per event). It is a microoverhead test of the writer, not a
JARVIS latency measurement or interactive hardware.

## Rollback

Remove construction and all three calls from `main.py` restores the
previous behavior without affecting `RequestAuditSink`, crash reports or runtime.
The module can remain without consumers until correcting the problem that
It motivated the rollback.
