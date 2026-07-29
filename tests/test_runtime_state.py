import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import core.runtime_state as runtime_state


class RuntimeStatePersistenceTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.original_directory = runtime_state.STATE_DIR
        runtime_state.STATE_DIR = Path(self.directory.name)

    def tearDown(self):
        runtime_state.STATE_DIR = self.original_directory
        self.directory.cleanup()

    def test_state_is_durable_atomic_and_reserved_fields_cannot_be_overridden(self):
        with (
            patch("core.runtime_state.os.replace", wraps=os.replace) as replace,
            patch("core.runtime_state.os.fsync", wraps=os.fsync) as fsync,
        ):
            runtime_state.update_runtime_state(
                "wake_word",
                "listening",
                pid=-1,
                updated_at="spoofed",
            )

        target = runtime_state.STATE_DIR / "wake_word_status.json"
        payload = json.loads(target.read_text(encoding="utf-8"))
        source, destination = replace.call_args.args
        self.assertEqual(Path(source).parent, target.parent)
        self.assertEqual(Path(destination), target)
        self.assertEqual(payload["component"], "wake_word")
        self.assertEqual(payload["state"], "listening")
        self.assertEqual(payload["pid"], os.getpid())
        self.assertTrue(fsync.called)

    def test_publish_failure_preserves_previous_state_and_cleans_temporary(self):
        runtime_state.update_runtime_state("jarvis", "on")
        target = runtime_state.STATE_DIR / "jarvis_status.json"
        original = target.read_bytes()

        with patch(
            "core.runtime_state.os.replace",
            side_effect=OSError("simulated publish failure"),
        ):
            runtime_state.update_runtime_state("jarvis", "off")

        self.assertEqual(target.read_bytes(), original)
        self.assertEqual(list(target.parent.glob(".jarvis_status.json.*.tmp")), [])

    def test_unserializable_details_do_not_break_startup_or_publish_partial_json(self):
        runtime_state.update_runtime_state("jarvis", "on")
        target = runtime_state.STATE_DIR / "jarvis_status.json"
        original = target.read_bytes()

        runtime_state.update_runtime_state("jarvis", "off", invalid=object())

        self.assertEqual(target.read_bytes(), original)

    def test_empty_component_is_ignored(self):
        runtime_state.update_runtime_state("../", "on")

        self.assertEqual(list(runtime_state.STATE_DIR.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
