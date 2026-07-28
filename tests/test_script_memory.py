from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import memory.script_memory as script_memory
from core.permissions import PermissionPolicy
from core.tools import RiskLevel, ToolDefinition


class ScriptMemoryTests(unittest.TestCase):
    def test_open_daily_targets_codex_not_chatgpt_store_protocol(self):
        original = script_memory.SCRIPT_MEMORY_PATH
        try:
            with TemporaryDirectory() as directory:
                script_memory.SCRIPT_MEMORY_PATH = Path(directory) / "scripts.json"
                script_memory.register_script(
                    "open daily",
                    "print('codex://daily')",
                    "Open the Codex daily task",
                )
                routine = script_memory.get_script("open daily")
                self.assertIsNotNone(routine)
                self.assertIn("codex://", routine["code"])
                self.assertNotIn("chatgpt://", routine["code"])
        finally:
            script_memory.SCRIPT_MEMORY_PATH = original

    def test_register_and_format_script(self):
        original = script_memory.SCRIPT_MEMORY_PATH
        try:
            with TemporaryDirectory() as directory:
                script_memory.SCRIPT_MEMORY_PATH = Path(directory) / "scripts.json"
                entry = script_memory.register_script(
                    "open daily", "print('routine ok')", "Open three daily applications", "python"
                )
                self.assertEqual(entry["code"], "print('routine ok')")
                prompt = script_memory.format_scripts_for_prompt()
                self.assertIn("open daily", prompt)
                self.assertNotIn("file_path", prompt)
                self.assertTrue(script_memory.is_registered_script("open daily"))
                self.assertFalse(script_memory.is_registered_script("unknown"))
                self.assertIn("routine ok", script_memory.run_script("open daily"))
                code_tool = ToolDefinition(
                    "code_helper", "Code", {"type": "OBJECT", "properties": {}},
                    handler=lambda args: None, risk=RiskLevel.SENSITIVE,
                )
                self.assertTrue(
                    PermissionPolicy().evaluate(
                        code_tool, {"action": "run", "routine_name": "open daily"}
                    ).allowed
                )
        finally:
            script_memory.SCRIPT_MEMORY_PATH = original

    def test_confirmation_path_is_preapproved_and_cannot_be_replaced(self):
        source = Path("main.py").read_text(encoding="utf-8")
        self.assertIn("preapproved=True,", source)
        self.assertIn("source=source,", source)
        self.assertIn("VOICE_CONFIRMATION_ALREADY_PENDING", source)
        self.assertIn("decision.requires_confirmation and not preapproved", source)


if __name__ == "__main__":
    unittest.main()
