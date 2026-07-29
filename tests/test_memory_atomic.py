import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import memory.memory_manager as memory


class AtomicMemoryStoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.original_path = memory.MEMORY_PATH
        memory.MEMORY_PATH = Path(self.directory.name) / "long_term.json"

    def tearDown(self):
        memory.MEMORY_PATH = self.original_path
        self.directory.cleanup()

    def test_save_uses_same_directory_replace_and_fsync(self):
        with (
            patch("memory.memory_manager.os.replace", wraps=os.replace) as replace,
            patch("memory.memory_manager.os.fsync", wraps=os.fsync) as fsync,
        ):
            memory.create_memory("notes", "topic", "value")

        source, destination = replace.call_args_list[-1].args
        self.assertEqual(Path(source).parent, memory.MEMORY_PATH.parent)
        self.assertEqual(Path(destination), memory.MEMORY_PATH)
        self.assertTrue(fsync.called)

    def test_replace_failure_preserves_primary_and_cleans_temporary(self):
        memory.create_memory("notes", "topic", "first")
        original = memory.MEMORY_PATH.read_bytes()

        with patch(
            "memory.memory_manager.os.replace",
            side_effect=OSError("simulated publish failure"),
        ):
            with self.assertRaises(OSError):
                memory.create_memory("notes", "other", "second")

        self.assertEqual(memory.MEMORY_PATH.read_bytes(), original)
        self.assertEqual(
            list(memory.MEMORY_PATH.parent.glob(".long_term.json.*.tmp")),
            [],
        )

    def test_corrupt_primary_recovers_valid_backup(self):
        memory.create_memory("notes", "topic", "first")
        memory.create_memory("notes", "other", "second")
        memory.MEMORY_PATH.write_text("{partial", encoding="utf-8")

        loaded = memory.load_memory()

        self.assertEqual(loaded["notes"]["topic"]["value"], "first")
        self.assertNotIn("other", loaded["notes"])

    def test_corrupt_primary_does_not_replace_valid_backup(self):
        memory.create_memory("notes", "topic", "first")
        memory.create_memory("notes", "other", "second")
        backup = memory.MEMORY_PATH.with_suffix(".json.bak")
        valid_backup = backup.read_bytes()
        memory.MEMORY_PATH.write_text("{partial", encoding="utf-8")

        memory.create_memory("notes", "third", "value")

        self.assertEqual(backup.read_bytes(), valid_backup)
        payload = json.loads(memory.MEMORY_PATH.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema_version"], memory.SCHEMA_VERSION)

    def test_corrupt_primary_and_backup_fail_closed(self):
        memory.MEMORY_PATH.write_text("{partial", encoding="utf-8")
        memory.MEMORY_PATH.with_suffix(".json.bak").write_text(
            "{also partial",
            encoding="utf-8",
        )

        self.assertEqual(memory.load_memory()["notes"], {})


if __name__ == "__main__":
    unittest.main()
