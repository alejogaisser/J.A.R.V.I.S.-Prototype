# Typed runtime events

## Scope

Phase 11 implements the PDF `P2 Event bus` only for facts that
`core.events.EventBus` connects runners time, dashboard,
composition root and logging without transporting commands or replacing calls
local.

Current events:

- `SessionStateChanged`: connection, disconnection and reconnection;
- `AudioInterruptionChanged`: start, release and reset of an interruption;
- `VisionAnalysisChanged`: start, end and reset of analysis;
- `ShutdownStateChanged`: request and effective start of closure;
- `DashboardConnected`: connection by PIN, QR or known device;
- `InputReceived`: presence of remote text/wake, never its content.

## Invariants

- Events are immutable dataclasses with `event_id`, UTC and time
monotonic.
- `request_id` is only included when a secure identifier already exists; vision
and shutdown retain that of the tool that originated the transition.
- No text, prompts, audio, images, tokens, device IDs or bodies are published.
- Owners build the event inside the lock and post it after
release him.
- Handlers are copied under lock and executed in order, without keeping the lock
from the bus.
- A failed handler does not prevent the following or reverse the transition.
- Delivery is synchronous: a subscriber should be brief or glue his own
I work.

## Compatibility

The composition root consumes `DashboardConnected` instead of registering a
direct callback. `DashboardServer.set_connect_callback()` and
`set_wake_callback()` remain as legacy adapters for consumers
But JARVIS no longer depends on them.

`StructuredRuntimeLog.record_runtime_event()` consumes the metadata allowed
and correlation by `event_id`/`request_id`. Logging continues to be best
Effort and does not receive sensitive payload.

## Evidence

`tests/test_runtime_events.py` covers:

- order, desubscription and re-entry;
- concurrent publication;
- isolation of exceptions;
- real events of the four owners;
- vision/shutdown correlation;
- dashboard callback compatibility;
- absence of command/taken/device data;
- serialization allowed;
- composition without direct callback dashboard→runtime.

## Risks and rollback

The bus is local to the process and does not persist or retry events.
synchronous is not suitable for slow IO. Callbacks inherited from wake and camera
They're still out of this pilot.

Rollback: build `RuntimeServices` without a shared bus, remove the
logger subscription and temporarily return to the connection setter
dashboard. Owners and their public APIs retain supported defaults.
