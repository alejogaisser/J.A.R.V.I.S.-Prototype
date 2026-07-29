import json
import os
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
        self.outside_temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.outside = Path(self.outside_temp.name)
        (self.root / ".obsidian").mkdir()
        (self.root / "Materias").mkdir()
        (self.root / "Materias" / "Analisis.md").write_text("# Límites\nTeorema del valor medio", encoding="utf-8")
        (self.outside / "outside.md").write_text("outside", encoding="utf-8")
        self.settings = patch.object(module, "_settings", return_value=(self.root, "Test Vault"))
        self.settings.start()

    def tearDown(self):
        self.settings.stop()
        self.temp.cleanup()
        self.outside_temp.cleanup()

    def test_search_and_read_with_or_without_extension_are_vault_relative(self):
        found = json.loads(module.obsidian_connector({"action": "search", "query": "valor medio"}))
        self.assertEqual(found[0]["path"], "Materias/Analisis.md")
        without_extension = json.loads(
            module.obsidian_connector({"action": "read", "path": "Materias/Analisis"})
        )
        with_extension = json.loads(
            module.obsidian_connector({"action": "read", "path": "Materias/Analisis.md"})
        )
        self.assertIn("Límites", without_extension["content"])
        self.assertEqual(without_extension, with_extension)

    def test_write_creates_backup_and_internal_paths_are_blocked(self):
        result = module.obsidian_connector({"action": "write", "path": "Materias/Analisis.md", "content": "nuevo"})
        self.assertIn("backup:", result)
        self.assertEqual((self.root / "Materias" / "Analisis.md").read_text(encoding="utf-8"), "nuevo")
        blocked = module.obsidian_connector({"action": "read", "path": ".obsidian/app.json"})
        self.assertIn("protected", blocked)

    def test_configured_vault_is_resolved_before_descendant_check(self):
        unresolved_root = self.root / "Materias" / ".."
        with patch.object(
            module,
            "_settings",
            return_value=(unresolved_root, "Test Vault"),
        ):
            read = json.loads(
                module.obsidian_connector(
                    {"action": "read", "path": "Materias/Analisis"}
                )
            )

        self.assertEqual(read["path"], "Materias/Analisis.md")

    def test_traversal_absolute_and_lookalike_prefix_are_blocked(self):
        traversal = module.obsidian_connector(
            {"action": "read", "path": "../outside.md"}
        )
        absolute = module.obsidian_connector(
            {"action": "read", "path": str(self.outside / "outside.md")}
        )
        lookalike = self.root.parent / f"{self.root.name}-Backup"
        lookalike.mkdir()
        try:
            (lookalike / "outside.md").write_text("outside", encoding="utf-8")
            prefix_escape = module.obsidian_connector(
                {"action": "read", "path": str(lookalike / "outside.md")}
            )
        finally:
            (lookalike / "outside.md").unlink(missing_ok=True)
            lookalike.rmdir()

        self.assertIn("stay inside", traversal)
        self.assertIn("stay inside", absolute)
        self.assertIn("stay inside", prefix_escape)

    def test_symlink_outside_vault_is_blocked_when_supported(self):
        link = self.root / "Linked"
        try:
            os.symlink(self.outside, link, target_is_directory=True)
        except (NotImplementedError, OSError) as exc:
            self.skipTest(f"Directory symlinks are unavailable: {exc}")

        result = module.obsidian_connector(
            {"action": "read", "path": "Linked/outside.md"}
        )

        self.assertIn("stay inside", result)

    def test_permission_policy_only_confirms_changes(self):
        tool = ToolDefinition("obsidian_connector", "", {"type": "OBJECT", "properties": {}},
                              handler=lambda args: None, risk=RiskLevel.SENSITIVE)
        policy = PermissionPolicy()
        self.assertEqual(policy.evaluate(tool, {"action": "read"}).policy, "free")
        self.assertEqual(policy.evaluate(tool, {"action": "write"}).policy, "confirm_once")


if __name__ == "__main__":
    unittest.main()
