# Supervision and health of workers

## Scope

Phase 12 implements the `P2 Workers` of the governing document.
`services.workers.WorkerSupervisor` administers existing workers through
typed callbacks of `start`, `stop` and `health`; does not replace your work or
enter a second runtime.

The pilots are:

- Playwright sessions of `actions.browser_control`;
- Live session inherited from `actions.screen_processor`.

No change Gemini Live principal, PCM, physical camera, visual UI, wake word
No suppliers.

## Contract

Each `WorkerSpec` declares a secure name, callbacks, reset budget
and backoff. The supervisor exposes immutable snapshots with:

- phase (`stopped`, `starting`, `running`, `degraded`, `restarting`,
`stopping` or `failed`);
- intention to implement;
- current health;
- start, subtract and failure;
- last sanitized error and transition monotonic time.

`start()`, `cancel()` and `close()` are idepotent. A local monitor performs
health checks limited and publishes `WorkerStateChanged` without payloads. Events
only contain name, phase and counters allowed.

## Anti-duplication rule

A dead or non-responsive worker stops before consuming budget
restart. The supervisor only restarts if the adapter proves that the resource
previous was no longer healthy and `stop()` reported no error.

If cleanup fails or the worker is still alive:

1. the phase passes to `failed`;
2. the intention to execute is deactivated;
3. no other worker is started;
4. the bug is available in health and logging.

This rule prefers visible degradation over threads, loops or processes
duplicates.

## Browser Pilot

`_BrowserSession.stop()` now closes context and Playwright, stops event
loop and makes `join` from thread. `start()` clean state above and can create a
new thread. Health sends a callback to the loop and demands response within the
timeout; `thread.is_alive()` alone is not considered sufficient evidence.

`_SessionRegistry` registers each browser with the supervisor, unregisters to
close and offer snapshots. Composition root runs the global cleanup at
Get out.

## Vision Pilot

`_VisionSession` retains the root task of its event loop. `stop()` cancels it,
wait for the thread and let the existing `finally` shut down the audio stream.
The loop also responds to a health ping. Connection, models, blobs and
Gemini's internal attempts remain inherited.

## Evidence

`tests/test_worker_supervisor.py` uses hardware-free fakes and loops to cover:

- double start/cancell/close;
- start attendance;
- dead and non-responsible worker;
- backoff and exhausted budget;
- startup and cleanup failure;
- blocking of restart when there would be duplication;
- order and sanitization of events;
- logging allowed;
- real restore/close loops browser and vision without Playwright, camera, audio,
network or Gemini;
- cleanup configured in `main.py`.

The local phase baseline approved 369 tests and 104 subtests.

## Risks and rollback

Health callbacks should be brief. The supervisor cannot end up with
force an arbitrary Python thread: that responsibility is left in the adapter.
Pilots use loop and joint cancellation; a bug is left `failed` and
It doesn't restart.

Rollback: Remove the configuration/cleanup from the composition root and return to
invoke `start()`/`close()` directly into the two adapters.
does not alter your payloads or functional APIs.
