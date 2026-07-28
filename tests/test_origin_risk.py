import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from core.permissions import (
    ExecutionContext,
    InputSource,
    PermissionDecision,
    PermissionLevel,
    PermissionPolicy,
)
from core.tools import ConfirmationPolicy, RiskLevel, ToolDefinition, ToolExecutor, ToolRegistry
from core.tools.builtins import build_builtin_registry


SCHEMA = {"type": "OBJECT", "properties": {}}


def tool(
    name: str,
    risk: RiskLevel = RiskLevel.READ_ONLY,
    confirmation: ConfirmationPolicy = ConfirmationPolicy.NEVER,
) -> ToolDefinition:
    return ToolDefinition(
        name,
        name,
        SCHEMA,
        handler=lambda _args: "ok",
        risk=risk,
        confirmation=confirmation,
    )


class InputSourceTests(unittest.TestCase):
    def test_known_sources_distinguish_trusted_and_remote_ingress(self):
        self.assertFalse(ExecutionContext(InputSource.LOCAL).is_remote)
        self.assertFalse(ExecutionContext(InputSource.UI).is_remote)
        self.assertFalse(ExecutionContext(InputSource.WAKE).is_remote)
        self.assertTrue(ExecutionContext(InputSource.DASHBOARD_TEXT).is_remote)
        self.assertTrue(ExecutionContext(InputSource.DASHBOARD_AUDIO).is_remote)

    def test_unknown_source_fails_closed_as_remote(self):
        self.assertTrue(ExecutionContext("unexpected_transport").is_remote)

    def test_dashboard_text_is_forwarded_with_explicit_source(self):
        from main import JarvisLive

        class Session:
            def __init__(self):
                self.texts = []

            async def send_realtime_input(self, *, text):
                self.texts.append(text)

        class UI:
            def __init__(self):
                self.logs = []

            def write_log(self, value):
                self.logs.append(value)

        jarvis = JarvisLive.__new__(JarvisLive)
        jarvis.session = Session()
        jarvis.ui = UI()
        jarvis._active_input_source = InputSource.LOCAL
        jarvis._handle_confirmation_text = lambda _text: False

        asyncio.run(jarvis._forward_dashboard_command("create a reminder"))

        self.assertEqual(jarvis._active_input_source, InputSource.DASHBOARD_TEXT)
        self.assertEqual(jarvis.session.texts, ["create a reminder"])

    def test_execute_tool_passes_active_source_to_policy(self):
        from main import JarvisLive

        captured = []

        class CapturingPolicy:
            def evaluate(self, _tool, _args, context):
                captured.append(context)
                return PermissionDecision(
                    allowed=True,
                    requires_confirmation=False,
                    simulated=False,
                    policy="free",
                    reason="test",
                    operation="default",
                )

        class UI:
            microphone_enabled = False

            def set_state(self, _state):
                pass

        definition = tool("test_status")
        jarvis = JarvisLive.__new__(JarvisLive)
        jarvis.ui = UI()
        jarvis._pending_confirmation_fc = None
        jarvis._pending_confirmation_source = None
        jarvis._active_input_source = InputSource.DASHBOARD_TEXT
        jarvis._remote_drive_folders = set()
        jarvis.tool_registry = ToolRegistry([definition])
        jarvis.tool_executor = ToolExecutor(jarvis.tool_registry)
        jarvis.permission_policy = CapturingPolicy()

        response = asyncio.run(
            jarvis._execute_tool(
                SimpleNamespace(name="test_status", args={}, id="call-1")
            )
        )

        self.assertTrue(response.response["success"])
        self.assertEqual(captured[0].source, InputSource.DASHBOARD_TEXT)

    def test_dashboard_command_origin_reaches_function_policy(self):
        from main import JarvisLive

        captured = []

        class Session:
            async def send_realtime_input(self, *, text):
                self.text = text

        class CapturingPolicy:
            def evaluate(self, _tool, _args, context):
                captured.append(context)
                return PermissionDecision(
                    allowed=True,
                    requires_confirmation=False,
                    simulated=False,
                    policy="free",
                    reason="test",
                    operation="default",
                )

        class UI:
            microphone_enabled = False

            def write_log(self, _value):
                pass

            def set_state(self, _state):
                pass

        async def exercise():
            definition = tool("test_status")
            jarvis = JarvisLive.__new__(JarvisLive)
            jarvis.session = Session()
            jarvis.ui = UI()
            jarvis._active_input_source = InputSource.LOCAL
            jarvis._input_source_locked = False
            jarvis._pending_confirmation_fc = None
            jarvis._pending_confirmation_source = None
            jarvis._remote_drive_folders = set()
            jarvis._handle_confirmation_text = lambda _text: False
            jarvis.tool_registry = ToolRegistry([definition])
            jarvis.tool_executor = ToolExecutor(jarvis.tool_registry)
            jarvis.permission_policy = CapturingPolicy()

            await jarvis._forward_dashboard_command("check status")
            return await jarvis._execute_tool(
                SimpleNamespace(name="test_status", args={}, id="call-dashboard")
            )

        response = asyncio.run(exercise())

        self.assertTrue(response.response["success"])
        self.assertEqual(captured[0].source, InputSource.DASHBOARD_TEXT)
        self.assertTrue(captured[0].is_remote)

    def test_dashboard_audio_queue_marks_remote_source(self):
        self.assertTrue(
            ExecutionContext(InputSource.DASHBOARD_AUDIO).is_remote
        )

    def test_remote_source_cannot_be_downgraded_by_local_audio(self):
        from main import JarvisLive

        jarvis = JarvisLive.__new__(JarvisLive)
        jarvis._active_input_source = InputSource.DASHBOARD_TEXT
        jarvis._input_source_locked = True

        jarvis._set_input_source(InputSource.LOCAL)

        self.assertEqual(jarvis._active_input_source, InputSource.DASHBOARD_TEXT)
        jarvis._reset_input_source()
        self.assertEqual(jarvis._active_input_source, JarvisLive._default_source())
        self.assertFalse(jarvis._input_source_locked)

    def test_remote_save_memory_reaches_policy_before_any_write(self):
        from main import JarvisLive

        class UI:
            microphone_enabled = False

            def __init__(self):
                self.logs = []

            def set_state(self, _state):
                pass

            def write_log(self, value):
                self.logs.append(value)

        class Gate:
            def authorize_or_stage(self, *_args):
                return False

        definition = ToolDefinition(
            "save_memory",
            "Save memory",
            {
                "type": "OBJECT",
                "properties": {
                    "category": {"type": "STRING"},
                    "key": {"type": "STRING"},
                    "value": {"type": "STRING"},
                },
                "required": ["category", "key", "value"],
            },
            handler=None,
            risk=RiskLevel.LOCAL_CHANGE,
            special=True,
        )
        jarvis = JarvisLive.__new__(JarvisLive)
        jarvis.ui = UI()
        jarvis._pending_confirmation_fc = None
        jarvis._pending_confirmation_source = None
        jarvis._active_input_source = InputSource.DASHBOARD_TEXT
        jarvis._remote_drive_folders = set()
        jarvis._confirmation_gate = Gate()
        jarvis.tool_registry = ToolRegistry([definition])
        jarvis.tool_executor = ToolExecutor(jarvis.tool_registry)
        jarvis.permission_policy = PermissionPolicy()
        fc = SimpleNamespace(
            name="save_memory",
            args={"category": "notes", "key": "k", "value": "v"},
            id="call-memory",
        )

        with patch("main.create_memory") as create_memory:
            response = asyncio.run(jarvis._execute_tool(fc))

        create_memory.assert_not_called()
        self.assertIn("VOICE_CONFIRMATION_REQUIRED", response.response["result"])
        self.assertIs(jarvis._pending_confirmation_fc, fc)
        self.assertEqual(
            jarvis._pending_confirmation_source,
            InputSource.DASHBOARD_TEXT,
        )

    def test_wake_supervision_selects_wake_as_default_source(self):
        from main import JarvisLive

        with patch.dict(os.environ, {"JARVIS_WAKE_SUPERVISED": "1"}):
            self.assertEqual(JarvisLive._default_source(), InputSource.WAKE)
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(JarvisLive._default_source(), InputSource.LOCAL)


class RiskMinimumTests(unittest.TestCase):
    def assertMinimum(self, tool_name, action, expected, **kwargs):
        definition = tool(
            tool_name,
            kwargs.get("risk", RiskLevel.SENSITIVE),
            kwargs.get("confirmation", ConfirmationPolicy.DEPENDS_ON_ARGUMENTS),
        )
        actual = PermissionPolicy.minimum(definition, action)
        self.assertEqual(actual, expected)

    def test_operation_minimums_cover_read_write_and_execution(self):
        cases = [
            ("file_processor", "info", PermissionLevel.FREE),
            ("file_processor", "explain", PermissionLevel.FREE),
            ("file_processor", "resize", PermissionLevel.CONFIRM_ONCE),
            ("file_processor", "extract", PermissionLevel.CONFIRM_ONCE),
            ("file_processor", "run", PermissionLevel.CONFIRM_ALWAYS),
            ("file_processor", "test", PermissionLevel.CONFIRM_ALWAYS),
            ("code_helper", "explain", PermissionLevel.FREE),
            ("code_helper", "write", PermissionLevel.CONFIRM_ONCE),
            ("code_helper", "edit", PermissionLevel.CONFIRM_ONCE),
            ("code_helper", "optimize", PermissionLevel.CONFIRM_ONCE),
            ("code_helper", "run", PermissionLevel.CONFIRM_ALWAYS),
            ("code_helper", "build", PermissionLevel.CONFIRM_ALWAYS),
            ("code_helper", "auto", PermissionLevel.CONFIRM_ALWAYS),
            ("browser_control", "get_text", PermissionLevel.FREE),
            ("browser_control", "get_url", PermissionLevel.FREE),
            ("browser_control", "go_to", PermissionLevel.FREE),
            ("browser_control", "click", PermissionLevel.CONFIRM_ONCE),
            ("browser_control", "fill_form", PermissionLevel.CONFIRM_ONCE),
            ("browser_control", "type", PermissionLevel.CONFIRM_ONCE),
            ("browser_control", "unknown", PermissionLevel.CONFIRM_ALWAYS),
            ("account_connector", "status", PermissionLevel.FREE),
            ("account_connector", "search", PermissionLevel.FREE),
            ("account_connector", "read", PermissionLevel.FREE),
            ("account_connector", "connect", PermissionLevel.CONFIRM_ONCE),
            ("account_connector", "download", PermissionLevel.CONFIRM_ONCE),
            ("account_connector", "disconnect", PermissionLevel.CONFIRM_ALWAYS),
            ("account_connector", "create_file", PermissionLevel.CONFIRM_ALWAYS),
            ("account_connector", "create_folder", PermissionLevel.CONFIRM_ALWAYS),
            ("file_controller", "create_file", PermissionLevel.CONFIRM_ONCE),
            ("file_controller", "copy", PermissionLevel.CONFIRM_ONCE),
        ]
        for tool_name, action, expected in cases:
            with self.subTest(tool=tool_name, action=action):
                self.assertMinimum(tool_name, action, expected)

    def test_reminder_requires_confirmation(self):
        self.assertMinimum(
            "reminder",
            "default",
            PermissionLevel.CONFIRM_ONCE,
            risk=RiskLevel.EXTERNAL_EFFECT,
        )

    def test_builtin_metadata_does_not_default_effectful_tools_to_read_only(self):
        declarations = [
            {"name": name, "description": "", "parameters": SCHEMA}
            for name in (
                "file_processor",
                "browser_control",
                "reminder",
                "account_connector",
            )
        ]
        handlers = {item["name"]: (lambda _args: "ok") for item in declarations}
        registry = build_builtin_registry(declarations, handlers)

        self.assertEqual(registry.get("file_processor").risk, RiskLevel.SENSITIVE)
        self.assertEqual(registry.get("browser_control").risk, RiskLevel.SENSITIVE)
        self.assertEqual(registry.get("reminder").risk, RiskLevel.EXTERNAL_EFFECT)
        self.assertEqual(registry.get("account_connector").risk, RiskLevel.EXTERNAL_EFFECT)
        for name in ("file_processor", "browser_control", "reminder", "account_connector"):
            with self.subTest(tool=name):
                self.assertEqual(
                    registry.get(name).confirmation,
                    ConfirmationPolicy.DEPENDS_ON_ARGUMENTS,
                )

    def test_remote_dashboard_elevates_otherwise_free_read(self):
        definition = tool("system_status")
        decision = PermissionPolicy().evaluate(
            definition,
            {},
            ExecutionContext(InputSource.DASHBOARD_TEXT),
        )
        self.assertTrue(decision.requires_confirmation)
        self.assertEqual(decision.policy, "confirm_once")


if __name__ == "__main__":
    unittest.main()
