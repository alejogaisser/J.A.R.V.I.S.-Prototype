# Session, audio, vision, and lifecycle ownership

## Boundary

`JarvisLive` remains the composition root and maintains Gemini transport,
existing queues and tasks. `RuntimeServices` concentrates mutable state
which was previously distributed in flags:

- `SessionService`: identity of the observed transport, generation, connections,
Reconnections and `LiveSessionState`;
- `AudioService`: explicit interruption, anti-stal generation, watchdog,
heartbeat and microphone recoveries;
- `VisionService`: flight analysis, cooldown and frame backpressure;
- `LifecycleService`: closing request, farewell audio, drainage,
back-up and start shutdown exactly once.
- `WorkerSupervisor`: Intent, Health, Delimited Restort and Cleanup of Workers
registered; browser and vision are the first adapters.

Each service exhibits transitions, does not require UI or matter Gemini.
snapshots are immutable dataclasses and contain only counters/states.

## Rules

1. Only `SessionService.bind()` and `unbind()` change the observed identity of
transport. A second simultaneous transport is rejected and a disconnect
You can't clean up the current one.
2. A reconnection preserves the summary checkpoint and counters, but restarts
Interruption, watchdog, in-flight analysis and pending frame.
3. Every ESC creates a generation. An old recovery task cannot
release a subsequent interruption.
4. Vision and camera use `try/finally`: the owner releases busy/frame even before
exception. Concurrent frames are discarded and accounted for.
5. Shutdown only progresses after goodbye+drainage or deadline.
Finally, it's idepotent.
6. A worker only restarts after `stop()` is finished and health confirms
that the above instance no longer lives; otherwise there is `failed`.

## Compatibility and rollback

Do not change the model Live, `send_realtime_input`, `session.receive()`, formats
PCM, camera blobs or UI signals. Rollback consists of returning to the
`JarvisLive` flags; `core/live_session.py` preserves its public types.

## Outstanding limits

- `session` is still a composition reference used by IO in `main.py`.
- `_phone_active`, `audio_in_queue`, `out_queue` and physical streams were not
extracted.
- No microphone, camera or actual Gemini session were executed.
- The browser/vision lifecycle already has supervisor; UI, dashboard, monitor,
proactivity and other workers continue to be distributed.
- Metrics are available in snapshots, but are not yet exported to
telemetry or UI.
