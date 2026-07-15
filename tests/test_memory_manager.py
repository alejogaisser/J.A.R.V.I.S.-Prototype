import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import memory.memory_manager as memory


class ControllableMemoryTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.original_path = memory.MEMORY_PATH
        memory.MEMORY_PATH = Path(self.directory.name) / "long_term.json"

    def tearDown(self):
        memory.MEMORY_PATH = self.original_path
        self.directory.cleanup()

    def test_legacy_migration_is_backed_up_and_idempotent(self):
        legacy = {"identity": {"name": {"value": "Alejo", "updated": "2026-07-14"}}}
        memory.MEMORY_PATH.write_text(json.dumps(legacy), encoding="utf-8")

        first = memory.load_memory()
        first_store = json.loads(memory.MEMORY_PATH.read_text(encoding="utf-8"))
        second = memory.load_memory()
        second_store = json.loads(memory.MEMORY_PATH.read_text(encoding="utf-8"))

        self.assertEqual(first["identity"]["name"]["value"], "Alejo")
        self.assertEqual(first, second)
        self.assertEqual(len(first_store["records"]), 1)
        self.assertEqual(len(second_store["records"]), 1)
        self.assertTrue(memory.MEMORY_PATH.with_suffix(".json.legacy.bak").exists())

    def test_crud_soft_delete_restore_conflict_and_expiry(self):
        created = memory.create_memory("preferences", "response_length", "short")
        record_id = created["record"]["id"]
        self.assertEqual(memory.search_memories("response length")[0]["id"], record_id)

        conflict = memory.create_memory("preferences", "response_length", "detailed")
        self.assertEqual(conflict["result"], "conflict")
        self.assertEqual(memory.list_memories("preferences")[0]["value"], "short")

        memory.update_memory_by_id(record_id, value="detailed")
        self.assertEqual(memory.list_memories("preferences")[0]["value"], "detailed")
        memory.forget_memory(record_id)
        self.assertNotIn("response_length", memory.load_memory()["preferences"])
        self.assertEqual(memory.list_memories(status="forgotten")[0]["id"], record_id)
        memory.restore_memory(record_id)
        self.assertIn("response_length", memory.load_memory()["preferences"])

        memory.create_memory("temporary", "old_exam", "finished", expires_at="2020-01-01T00:00:00-03:00")
        self.assertEqual(memory.list_memories("temporary", status="active"), [])
        self.assertEqual(len(memory.list_memories("temporary", status="expired")), 1)
        self.assertNotIn("old_exam", memory.format_memory_for_prompt())

    def test_sensitive_values_are_redacted_from_listing(self):
        memory.create_memory("notes", "private_detail", "secret", sensitivity="sensitive")
        self.assertEqual(memory.list_memories()[0]["value"], "[redacted]")
        self.assertEqual(memory.list_memories(include_sensitive=True)[0]["value"], "secret")


if __name__ == "__main__":
    unittest.main()
