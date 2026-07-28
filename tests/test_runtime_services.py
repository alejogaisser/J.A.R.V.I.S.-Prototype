import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace

from services.runtime import RuntimeServices


class SessionServiceTests(unittest.TestCase):
    def test_main_composes_runtime_owners_without_duplicate_state_flags(self):
        source = Path("main.py").read_text(encoding="utf-8")

        self.assertIn("self._runtime       = RuntimeServices()", source)
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
        lifecycle.observe_farewell_audio()
        self.assertFalse(lifecycle.ready_to_finish(now=21.0))
        lifecycle.observe_playback_drained()
        self.assertTrue(lifecycle.ready_to_finish(now=21.0))
        self.assertTrue(lifecycle.begin_finish())
        self.assertFalse(lifecycle.begin_finish())
        self.assertEqual(lifecycle.shutdown_requests, 1)

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
