# UI thread boundary

## Invariant

Only the proprietary thread of Qt can read or mutate widgets.
`ToolExecutor`, loop asyncio and dashboard callbacks can:

1. issue a presentation command;
2. wait for an explicit response when the command requires it;
3. consume an immutable snapshot protected by lock.

They cannot receive `MainWindow`, `JarvisUI._win` or specific widgets.

## Contract

`core.ui_boundary.UiCommandFacade` is the port that `main.py` delivers to the
handlers. Its surface is limited to:

- study log and results;
- content, Memory and GEO;
- transition to Pet and interface instructions;
- selected file and microphone snapshots.

The facade delegates to `JarvisUI`, whose public methods emit signals.
`MainWindow` slots perform mutation and, for Study e
`interface_control`, complete a `threading.Event` with result or error.

## Snapshots

`MainWindow.tool_snapshot()` copies under `_tool_state_lock`:

- `current_file`;
- `listen_mode`;
- `microphone_enabled`;
- `muted`.

Snapshot avoids consulting `DropZone` or any other QWidget from the
runtime. Main/Pet surface mode uses a separate lock because it belongs
to coordinator `JarvisUI`.

## Camera and closing

Start and close continue to enter by `_camera_request_sig`.
session prevents a previous camera from closing a new one.
is copied under `_cam_lock` and run off the lock; closing and replacement use
Same lock.

## Verification

`tests/test_ui_thread_boundary.py` checks the exact surface of the
front, that the handlers don't get the owner of widgets, the phone signal,
snapshots and camera synchronization. It also emits a signal from a
real thread and confirms that the slot runs on the thread of
`QCoreApplication`. Camera regressions, quick panels and Pet/Main
remain in `tests/test_ui_mk2.py` and `tests/test_ui_v3.py`.

## Rollback

The façade delegates to existing `JarvisUI` methods; it can be removed
temporarily re-injecting that adapter without changing stock signatures.
signals and snapshots should be stored as long as callbacks exist outside the
Qt thread.
