from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from memory.graph_index import build_memory_graph


class MemoryGraphTests(unittest.TestCase):
    def test_content_nodes_are_only_real_memory_records(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".obsidian").mkdir()
            (root / "Decorative Note.md").write_text(
                "[[Another Note]] #decorative", encoding="utf-8"
            )
            graph = build_memory_graph(
                vault_root=root,
                memory_records=[{
                    "id": "mem_1", "category": "relationships", "key": "study_friend",
                    "value": "A friend from university", "sensitivity": "normal",
                    "contexts": ["university"], "updated_at": "2026-07-22",
                }],
            )

        content = [node for node in graph["nodes"] if node["kind"] == "memory"]
        self.assertEqual(len(content), 1)
        self.assertEqual(content[0]["id"], "memory:mem_1")
        self.assertEqual(content[0]["label"], "Study Friend")
        self.assertNotIn("note", {node["kind"] for node in graph["nodes"]})
        self.assertNotIn("tag", {node["kind"] for node in graph["nodes"]})
        self.assertEqual(graph["stats"]["synthetic_content_nodes"], 0)
        self.assertEqual(graph["stats"]["content_nodes"], 1)

    def test_category_and_explicit_context_are_nuclei_not_memories(self):
        graph = build_memory_graph(memory_records=[{
            "id": "mem_1", "category": "relationships", "key": "person",
            "value": "Known person", "contexts": ["University Life"],
        }])
        nodes = {node["id"]: node for node in graph["nodes"]}
        self.assertEqual(nodes["category:relationships"]["kind"], "category")
        self.assertEqual(nodes["context:university_life"]["kind"], "context")
        self.assertEqual(nodes["context:university_life"]["count"], 1)
        edges = {(edge["source"], edge["target"], edge["kind"]) for edge in graph["edges"]}
        self.assertIn(("category:relationships", "memory:mem_1", "membership"), edges)
        self.assertIn(("context:university_life", "memory:mem_1", "context"), edges)

    def test_sensitive_memory_remains_a_real_but_redacted_node(self):
        graph = build_memory_graph(memory_records=[{
            "id": "mem_secret", "category": "notes", "key": "private_detail",
            "value": "secret", "sensitivity": "sensitive",
        }])
        memory = next(node for node in graph["nodes"] if node["kind"] == "memory")
        self.assertEqual(memory["value"], "[protected]")

    def test_only_explicit_related_ids_create_memory_to_memory_edges(self):
        records = [
            {"id": "a", "category": "notes", "key": "a", "value": "Alpha", "related_ids": ["b"]},
            {"id": "b", "category": "notes", "key": "b", "value": "Beta"},
            {"id": "c", "category": "notes", "key": "c", "value": "Alpha-like text"},
        ]
        graph = build_memory_graph(memory_records=records)
        related = [edge for edge in graph["edges"] if edge["kind"] == "explicit_relation"]
        self.assertEqual(related, [{"source": "memory:a", "target": "memory:b", "kind": "explicit_relation"}])


if __name__ == "__main__":
    unittest.main()
