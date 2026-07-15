import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from actions import obsidian_connector as module
from core.permissions import PermissionPolicy
from core.tools import RiskLevel, ToolDefinition


class ObsidianConnectorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / ".obsidian").mkdir()
        (self.root / "Materias").mkdir()
        (self.root / "Materias" / "Analisis.md").write_text("# Límites\nTeorema del valor medio", encoding="utf-8")
        self.settings = patch.object(module, "_settings", return_value=(self.root, "Test Vault"))
        self.settings.start()

    def tearDown(self):
        self.settings.stop()
        self.temp.cleanup()

    def test_search_and_read_are_vault_relative(self):
        found = json.loads(module.obsidian_connector({"action": "search", "query": "valor medio"}))
        self.assertEqual(found[0]["path"], "Materias/Analisis.md")
        read = json.loads(module.obsidian_connector({"action": "read", "path": "Materias/Analisis"}))
        self.assertIn("Límites", read["content"])

    def test_write_creates_backup_and_internal_paths_are_blocked(self):
        result = module.obsidian_connector({"action": "write", "path": "Materias/Analisis.md", "content": "nuevo"})
        self.assertIn("backup:", result)
        self.assertEqual((self.root / "Materias" / "Analisis.md").read_text(encoding="utf-8"), "nuevo")
        blocked = module.obsidian_connector({"action": "read", "path": ".obsidian/app.json"})
        self.assertIn("protected", blocked)

    def test_permission_policy_only_confirms_changes(self):
        tool = ToolDefinition("obsidian_connector", "", {"type": "OBJECT", "properties": {}},
                              handler=lambda args: None, risk=RiskLevel.SENSITIVE)
        policy = PermissionPolicy()
        self.assertEqual(policy.evaluate(tool, {"action": "read"}).policy, "free")
        self.assertEqual(policy.evaluate(tool, {"action": "write"}).policy, "confirm_once")


if __name__ == "__main__":
    unittest.main()
