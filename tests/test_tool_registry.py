import asyncio
import unittest

from core.tools import ToolDefinition, ToolExecutor, ToolRegistry
from core.tools.builtins import build_builtin_registry


SCHEMA = {"type": "OBJECT", "properties": {}}


class ToolRegistryTests(unittest.TestCase):
    def test_register_and_get(self):
        tool = ToolDefinition("status", "Status", SCHEMA, handler=lambda args: "ok")
        registry = ToolRegistry([tool])
        self.assertIs(registry.get("status"), tool)

    def test_rejects_empty_and_duplicate_names(self):
        with self.assertRaises(ValueError):
            ToolDefinition("", "Invalid", SCHEMA, handler=lambda args: None)
        tool = ToolDefinition("status", "Status", SCHEMA, handler=lambda args: None)
        registry = ToolRegistry([tool])
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            registry.register(tool)

    def test_unknown_disabled_and_wrong_platform_fail_closed(self):
        registry = ToolRegistry([
            ToolDefinition("off", "Off", SCHEMA, handler=lambda args: None, enabled=False),
            ToolDefinition(
                "linux_only", "Linux", SCHEMA, handler=lambda args: None,
                platforms=frozenset({"linux"}),
            ),
        ])
        with self.assertRaises(KeyError):
            registry.get("missing")
        with self.assertRaises(PermissionError):
            registry.validate_for_execution("off", "windows")
        with self.assertRaises(RuntimeError):
            registry.validate_for_execution("linux_only", "windows")

    def test_only_enabled_compatible_tools_are_declared(self):
        registry = ToolRegistry([
            ToolDefinition("on", "On", SCHEMA, handler=lambda args: None),
            ToolDefinition("off", "Off", SCHEMA, handler=lambda args: None, enabled=False),
        ])
        self.assertEqual([item["name"] for item in registry.declarations("windows")], ["on"])
        self.assertEqual(
            registry.declarations("windows", predicate=lambda item: item.name == "off"),
            [],
        )

    def test_required_arguments_and_types_are_validated(self):
        schema = {
            "type": "OBJECT",
            "properties": {"city": {"type": "STRING"}},
            "required": ["city"],
        }
        tool = ToolDefinition("weather", "Weather", schema, handler=lambda args: "ok")
        registry = ToolRegistry([tool])
        with self.assertRaises(ValueError):
            registry.validate_arguments(tool, {})
        with self.assertRaises(TypeError):
            registry.validate_arguments(tool, {"city": 123})
        registry.validate_arguments(tool, {"city": "Buenos Aires"})

    def test_executor_normalizes_results_errors_and_timeouts(self):
        def fail(args):
            raise RuntimeError("boom")

        async def slow(args):
            await asyncio.sleep(.05)

        registry = ToolRegistry([
            ToolDefinition("ok", "OK", SCHEMA, handler=lambda args: {"value": 1}),
            ToolDefinition("fail", "Fail", SCHEMA, handler=fail),
            ToolDefinition("slow", "Slow", SCHEMA, handler=slow, timeout=.001),
        ])
        executor = ToolExecutor(registry)
        self.assertTrue(asyncio.run(executor.execute("ok", {})).success)
        self.assertEqual(asyncio.run(executor.execute("fail", {})).error_code, "exception")
        self.assertEqual(asyncio.run(executor.execute("slow", {})).error_code, "timeout")

    def test_all_declarations_must_have_handlers_or_be_special(self):
        declarations = [{"name": "ordinary", "description": "", "parameters": SCHEMA}]
        with self.assertRaisesRegex(ValueError, "requires a handler"):
            build_builtin_registry(declarations, {})


if __name__ == "__main__":
    unittest.main()
