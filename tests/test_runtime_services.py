import asyncio
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace

from services.runtime import RuntimeServices
from services.session import (
    LiveReconnectPolicy,
    LiveSessionConnectTimeout,
    LiveSessionRotationRequested,
    bounded_live_connect,
    contains_live_session_rotation,
)


class SessionServiceTests(unittest.TestCase):
    def test_main_composes_runtime_owners_without_duplicate_state_flags(self):
        source = Path("main.py").read_text(encoding="utf-8")

        self.assertIn(
            "self._runtime       = RuntimeServices(events=self._events)",
            source,
        )
        self.assertIn(
            "self._runtime.on_transport_connected",
            source,
        )
        self.assertIn(
            "self._runtime.on_transport_disconnected",
            source,
        )
        for legacy_assignment in (
            "self._vision_busy          =",
            "self._camera_frame_pending =",
            "self._interrupted          =",
            "self._shutdown_after_turn =",
        ):
            self.assertNotIn(legacy_assignment, source)

    def test_reconnect_resets_transients_but_preserves_resume_checkpoint(self):
        services = RuntimeServices()
        first_transport = object()

        self.assertEqual(
            services.on_transport_connected(first_transport, now=100.0),
            "online",
        )
        services.session.resumption.observe_resumption_update(
            SimpleNamespace(resumable=True, new_handle="checkpoint-1")
        )
        services.audio.begin_interrupt(now=101.0)
        services.audio.watchdog.sleeping = True
        services.vision.try_begin_analysis(now=101.0, cooldown=0)
        services.vision.try_queue_camera_frame()

        self.assertTrue(services.on_transport_disconnected(first_transport))
        second_transport = object()
        self.assertEqual(
            services.on_transport_connected(second_transport, now=110.0),
            "restored",
        )

        self.assertEqual(
            services.session.resumption.resumption_handle,
            "checkpoint-1",
        )
        self.assertFalse(services.audio.interrupted)
        self.assertFalse(services.audio.watchdog.sleeping)
        self.assertFalse(services.vision.busy)
        self.assertFalse(services.vision.camera_frame_pending)
        self.assertEqual(services.session.snapshot().reconnects, 1)

    def test_session_owner_rejects_two_live_transports(self):
        services = RuntimeServices()
        services.on_transport_connected(object())

        with self.assertRaisesRegex(RuntimeError, "already bound"):
            services.on_transport_connected(object())

    def test_stale_disconnect_cannot_clear_new_transport(self):
        services = RuntimeServices()
        old = object()
        new = object()
        services.on_transport_connected(old)
        services.on_transport_disconnected(old)
        services.on_transport_connected(new)

        self.assertFalse(services.on_transport_disconnected(old))
        self.assertIs(services.session.transport, new)

    def test_go_away_rotates_current_transport_once_and_resets_on_bind(self):
        services = RuntimeServices()
        first = object()
        stale = object()
        services.on_transport_connected(first)

        self.assertFalse(services.on_transport_go_away(stale))
        self.assertTrue(services.on_transport_go_away(first))
        self.assertFalse(services.on_transport_go_away(first))
        snapshot = services.session.snapshot()
        self.assertTrue(snapshot.rotation_requested)
        self.assertEqual(snapshot.rotations, 1)

        services.on_transport_disconnected(first)
        services.on_transport_connected(object())
        self.assertFalse(services.session.snapshot().rotation_requested)
        self.assertEqual(services.session.snapshot().rotations, 1)

    def test_task_group_rotation_signal_is_recognized(self):
        signal = LiveSessionRotationRequested("rotate")

        self.assertTrue(contains_live_session_rotation(signal))
        self.assertTrue(contains_live_session_rotation(
            ExceptionGroup("task group", [RuntimeError("other"), signal])
        ))
        self.assertFalse(contains_live_session_rotation(RuntimeError("other")))

    def test_receive_path_closes_transport_when_go_away_arrives(self):
        source = Path("main.py").read_text(encoding="utf-8")
        receive = source[
            source.index("    async def _receive_audio"):
            source.index("    async def _play_audio")
        ]

        self.assertLess(
            receive.index("observe_resumption_update"),
            receive.index("on_transport_go_away"),
        )
        self.assertIn("raise LiveSessionRotationRequested", receive)

    def test_nested_rate_limit_errors_use_one_bounded_backoff_owner(self):
        class RateLimited(RuntimeError):
            code = 429

        policy = LiveReconnectPolicy(
            rate_limit_base_seconds=5.0,
            max_seconds=30.0,
        )
        error = ExceptionGroup("live", [RuntimeError("wrapper"), RateLimited()])

        self.assertEqual(policy.delay_for(error, connected_seconds=0.0), 5.0)
        self.assertEqual(policy.delay_for(error, connected_seconds=1.0), 10.0)
        self.assertEqual(policy.delay_for(error, connected_seconds=1.0), 20.0)
        self.assertEqual(policy.delay_for(error, connected_seconds=1.0), 30.0)
        self.assertEqual(policy.snapshot().last_status_codes, (429,))

        # A genuinely stable session starts a fresh failure streak.
        self.assertEqual(policy.delay_for(error, connected_seconds=45.0), 5.0)

    def test_rotation_and_stalled_turn_have_fast_controlled_reconnects(self):
        policy = LiveReconnectPolicy()

        self.assertEqual(
            policy.delay_for(
                LiveSessionRotationRequested("rotate"),
                connected_seconds=2.0,
            ),
            0.0,
        )
        self.assertEqual(
            policy.delay_for(
                RuntimeError("live turn stalled"),
                connected_seconds=20.0,
                stalled_turn=True,
            ),
            1.0,
        )

    def test_session_turn_watchdog_ignores_local_tool_work_and_resets(self):
        services = RuntimeServices()
        session = services.session

        session.observe_user_activity(now=10.0)
        self.assertFalse(session.claim_stalled_turn(now=39.9, timeout=30.0))
        session.begin_local_work()
        self.assertFalse(session.claim_stalled_turn(now=100.0, timeout=30.0))
        session.end_local_work(now=100.0)
        self.assertFalse(session.claim_stalled_turn(now=129.9, timeout=30.0))
        self.assertTrue(session.claim_stalled_turn(now=130.0, timeout=30.0))
        self.assertEqual(session.snapshot().stalled_turns, 1)

        session.observe_user_activity(now=200.0)
        session.observe_remote_activity(now=220.0)
        self.assertFalse(session.claim_stalled_turn(now=249.9, timeout=30.0))
        session.complete_turn()
        self.assertFalse(session.snapshot().turn_pending)

    def test_main_wires_bounded_connect_and_live_turn_watchdog(self):
        source = Path("main.py").read_text(encoding="utf-8")
        receive = source[
            source.index("    async def _receive_audio"):
            source.index("    async def _play_audio")
        ]
        run = source[source.index("    async def run(self)"):]

        self.assertIn("bounded_live_connect(", run)
        self.assertIn("tg.create_task(self._watch_live_turn())", run)
        self.assertIn("observe_user_activity", receive)
        self.assertIn("observe_remote_activity", receive)
        self.assertIn("complete_turn", receive)
        self.assertIn("begin_local_work", receive)
        self.assertIn("end_local_work", receive)
        self.assertIn("expect_remote_activity", receive)
        self.assertIn("self._live_reconnect.delay_for", run)
        text_input = source[
            source.index("    async def _send_text_input"):
            source.index("    def _on_text_command")
        ]
        self.assertIn("_expect_remote_activity", text_input)


class BoundedLiveConnectTests(unittest.IsolatedAsyncioTestCase):
    async def test_connect_setup_is_bounded_and_success_is_closed(self):
        class SlowContext:
            async def __aenter__(self):
                await asyncio.sleep(1.0)

            async def __aexit__(self, *_args):
                return False

        with self.assertRaises(LiveSessionConnectTimeout):
            async with bounded_live_connect(SlowContext(), timeout=0.01):
                self.fail("slow connection must never be yielded")

        class ReadyContext:
            def __init__(self):
                self.closed = False

            async def __aenter__(self):
                return "session"

            async def __aexit__(self, *_args):
                self.closed = True
                return False

        ready = ReadyContext()
        async with bounded_live_connect(ready, timeout=0.1) as session:
            self.assertEqual(session, "session")
        self.assertTrue(ready.closed)


class AudioServiceTests(unittest.TestCase):
    def test_interrupt_generation_prevents_stale_release(self):
        audio = RuntimeServices().audio

        first = audio.begin_interrupt(now=10.0)
        second = audio.begin_interrupt(now=11.0)

        self.assertFalse(audio.release_interrupt(first))
        self.assertTrue(audio.interrupted)
        self.assertTrue(audio.release_interrupt(second))
        self.assertFalse(audio.interrupted)
        self.assertEqual(audio.interrupts, 2)

    def test_microphone_stall_metric_is_counted_once_per_recovery(self):
        audio = RuntimeServices().audio
        audio.mark_microphone_callback(now=10.0)

        self.assertFalse(audio.microphone_stalled(now=11.9, threshold=2.0))
        self.assertTrue(audio.microphone_stalled(now=12.1, threshold=2.0))
        audio.mark_microphone_recovery()
        self.assertEqual(audio.microphone_recoveries, 1)


class VisionServiceTests(unittest.TestCase):
    def test_analysis_cooldown_and_camera_backpressure_have_one_owner(self):
        vision = RuntimeServices().vision

        self.assertTrue(vision.try_begin_analysis(now=10.0, cooldown=4.0))
        self.assertFalse(vision.try_begin_analysis(now=11.0, cooldown=4.0))
        vision.finish_analysis()
        self.assertFalse(vision.try_begin_analysis(now=12.0, cooldown=4.0))
        self.assertTrue(vision.try_begin_analysis(now=14.0, cooldown=4.0))
        vision.finish_analysis()

        first_frame = vision.try_queue_camera_frame()
        self.assertIsNotNone(first_frame)
        self.assertIsNone(vision.try_queue_camera_frame())
        vision.finish_camera_frame()
        second_frame = vision.try_queue_camera_frame()
        self.assertIsNotNone(second_frame)
        self.assertFalse(vision.finish_camera_frame(first_frame))
        self.assertTrue(vision.camera_frame_pending)
        self.assertTrue(vision.finish_camera_frame(second_frame))
        self.assertEqual(vision.frames_accepted, 2)
        self.assertEqual(vision.frames_dropped, 1)


class LifecycleServiceTests(unittest.TestCase):
    def test_shutdown_finishes_once_after_audio_or_deadline(self):
        lifecycle = RuntimeServices().lifecycle

        lifecycle.request_shutdown(now=20.0, fallback_seconds=12.0)
        self.assertFalse(
            lifecycle.request_shutdown(now=21.0, fallback_seconds=12.0)
        )
        self.assertFalse(lifecycle.ready_to_finish(now=31.9))
        lifecycle.observe_farewell_audio(now=21.0)
        self.assertFalse(lifecycle.ready_to_finish(now=21.0))
        lifecycle.observe_playback_drained()
        self.assertTrue(lifecycle.ready_to_finish(now=21.0))
        self.assertTrue(lifecycle.begin_finish())
        self.assertFalse(lifecycle.begin_finish())
        lifecycle.observe_device_drained()
        self.assertTrue(lifecycle.snapshot().device_drained)
        self.assertEqual(lifecycle.shutdown_requests, 1)

    def test_initial_timeout_cannot_cut_off_started_farewell(self):
        lifecycle = RuntimeServices().lifecycle
        lifecycle.request_shutdown(now=20.0, fallback_seconds=12.0)
        lifecycle.observe_farewell_audio(
            now=31.5,
            completion_timeout_seconds=45.0,
        )

        self.assertEqual(lifecycle.active_deadline(), 76.5)
        self.assertFalse(lifecycle.ready_to_finish(now=32.0))
        self.assertFalse(lifecycle.ready_to_finish(now=76.49))
        self.assertTrue(lifecycle.ready_to_finish(now=76.5))

    def test_first_audio_chunk_owns_one_completion_deadline(self):
        lifecycle = RuntimeServices().lifecycle
        lifecycle.request_shutdown(now=10.0)
        lifecycle.observe_farewell_audio(now=11.0)
        lifecycle.observe_farewell_audio(now=20.0)

        snapshot = lifecycle.snapshot()
        self.assertEqual(snapshot.farewell_audio_at, 11.0)
        self.assertEqual(snapshot.completion_deadline, 56.0)

    def test_shutdown_deadline_is_a_fallback_without_audio(self):
        lifecycle = RuntimeServices().lifecycle
        lifecycle.request_shutdown(now=20.0, fallback_seconds=12.0)

        self.assertFalse(lifecycle.ready_to_finish(now=31.99))
        self.assertTrue(lifecycle.ready_to_finish(now=32.0))

    def test_runtime_snapshot_is_immutable_and_correlated(self):
        services = RuntimeServices()
        services.on_transport_connected(object(), now=5.0)
        services.audio.begin_interrupt(now=6.0)
        services.lifecycle.request_shutdown(now=7.0)

        snapshot = services.snapshot()

        self.assertEqual(snapshot.session.connections, 1)
        self.assertEqual(snapshot.audio.interrupts, 1)
        self.assertTrue(snapshot.lifecycle.shutdown_requested)
        with self.assertRaises(FrozenInstanceError):
            snapshot.audio.interrupts = 0


if __name__ == "__main__":
    unittest.main()
