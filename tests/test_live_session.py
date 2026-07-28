import unittest
from pathlib import Path
from types import SimpleNamespace

from core.live_session import AudioInactivityWatchdog, LiveSessionState, pcm16_rms


class LiveSessionStateTests(unittest.TestCase):
    def test_audio_watchdog_sleeps_and_wakes_without_session_reset(self):
        watchdog = AudioInactivityWatchdog(
            idle_seconds=12.0,
            voice_rms_threshold=350.0,
            last_voice_at=100.0,
        )
        silence = b"\x00\x00" * 640
        voice = (1000).to_bytes(2, "little", signed=True) * 640

        self.assertEqual(watchdog.observe_pcm(silence, active=True, now=111.9), "quiet")
        self.assertEqual(watchdog.observe_pcm(silence, active=True, now=112.0), "sleep")
        self.assertTrue(watchdog.sleeping)
        self.assertEqual(watchdog.observe_pcm(silence, active=True, now=112.5), "sleeping")
        self.assertEqual(watchdog.observe_pcm(voice, active=True, now=113.0), "wake")
        self.assertFalse(watchdog.sleeping)

    def test_app_level_standby_does_not_arm_automatic_wake(self):
        watchdog = AudioInactivityWatchdog(last_voice_at=10.0)
        silence = b"\x00\x00" * 10

        self.assertEqual(watchdog.observe_pcm(silence, active=False, now=100.0), "quiet")
        self.assertFalse(watchdog.sleeping)
        self.assertEqual(watchdog.last_voice_at, 100.0)

    def test_pcm16_rms_distinguishes_silence_from_voice(self):
        self.assertEqual(pcm16_rms(b"\x00\x00" * 4), 0.0)
        voice = (1000).to_bytes(2, "little", signed=True) * 4
        self.assertEqual(pcm16_rms(voice), 1000.0)

    def test_keeps_latest_resumable_handle(self):
        state = LiveSessionState()

        self.assertTrue(state.observe_resumption_update(SimpleNamespace(
            resumable=True, new_handle="checkpoint-1"
        )))
        self.assertTrue(state.can_resume)
        self.assertEqual(state.resumption_handle, "checkpoint-1")

        self.assertFalse(state.observe_resumption_update(SimpleNamespace(
            resumable=False, new_handle=None
        )))
        self.assertEqual(state.resumption_handle, "checkpoint-1")

        self.assertTrue(state.observe_resumption_update(SimpleNamespace(
            resumable=True, new_handle="checkpoint-2"
        )))
        self.assertEqual(state.resumption_handle, "checkpoint-2")
        self.assertEqual(state.updates_seen, 3)

    def test_ignores_empty_or_incomplete_updates(self):
        state = LiveSessionState()

        self.assertFalse(state.observe_resumption_update(None))
        self.assertFalse(state.observe_resumption_update(SimpleNamespace(
            resumable=True, new_handle=""
        )))
        self.assertFalse(state.can_resume)

    def test_checkpoint_updates_are_not_shown_in_the_chat(self):
        source = Path("main.py").read_text(encoding="utf-8")
        self.assertIn(
            "self._runtime.session.resumption.observe_resumption_update",
            source,
        )
        self.assertNotIn("Conversation checkpoint updated", source)


if __name__ == "__main__":
    unittest.main()
