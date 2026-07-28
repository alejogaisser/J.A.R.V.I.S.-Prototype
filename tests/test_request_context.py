import asyncio
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from core.permissions import InputSource, PermissionPolicy
from core.request_audit import RequestAuditSink
from core.request_context import RequestContext
from core.tools import RiskLevel, ToolDefinition, ToolExecutor, ToolRegistry


SCHEMA = {"type": "OBJECT", "properties": {}}


class CapturingSink:
    def __init__(self):
        self.events = []

    def record(self, context, event, tool, **metadata):
        self.events.append(
            {
                "request_id": context.request_id,
                "event": event,
                "tool": tool,
                **metadata,
            }
        )
        return True


class RequestContextTests(unittest.TestCase):
    def test_request_ids_are_unique_and_source_is_preserved(self):
        first = RequestContext.create(InputSource.DASHBOARD_TEXT, tool_call_id="fc-1")
        second = RequestContext.create(InputSource.DASHBOARD_TEXT, tool_call_id="fc-2")

        self.assertNotEqual(first.request_id, second.request_id)
        self.assertEqual(first.source, InputSource.DASHBOARD_TEXT)
        self.assertTrue(first.is_remote)
        self.assertEqual(first.tool_call_id, "fc-1")

    def test_unknown_source_fails_closed(self):
        context = RequestContext.create("new_transport")

        self.assertTrue(context.is_remote)

    def test_audit_sink_writes_only_allowlisted_metadata(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "requests.jsonl"
            sink = RequestAuditSink(path)
            context = RequestContext.create(
                InputSource.UI,
                tool_call_id="fc-safe",
            )

            written = sink.record(
                context,
                "policy",
                "send_message",
                operation="default",
                policy="confirm_always",
                outcome="confirmation_required",
            )

            self.assertTrue(written)
            event = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(event["request_id"], context.request_id)
            self.assertEqual(event["source"], "ui")
            self.assertEqual(event["tool"], "send_message")
            self.assertEqual(event["operation"], "default")
            self.assertNotIn("arguments", event)
            self.assertNotIn("message", event)
            self.assertNotIn("token", event)
            self.assertNotIn("body", event)

    def test_audit_sink_failure_does_not_break_execution(self):
        with TemporaryDirectory() as directory:
            sink = RequestAuditSink(Path(directory))
            context = RequestContext.create(InputSource.LOCAL)

            self.assertFalse(sink.record(context, "requested", "system_status"))

    def test_disabled_sink_does_not_create_a_file(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "requests.jsonl"
            sink = RequestAuditSink(path, enabled=False)
            context = RequestContext.create(InputSource.LOCAL)

            self.assertFalse(sink.record(context, "requested", "system_status"))
            self.assertFalse(path.exists())

    def test_executor_uses_one_request_id_for_started_and_completed(self):
        definition = ToolDefinition(
            "status",
            "Status",
            SCHEMA,
            handler=lambda _args: "ok",
        )
        registry = ToolRegistry([definition])
        sink = CapturingSink()
        executor = ToolExecutor(registry, audit_sink=sink)
        context = RequestContext.create(InputSource.WAKE, tool_call_id="fc-executor")

        result = asyncio.run(executor.execute("status", {}, context=context))

        self.assertTrue(result.success)
        self.assertEqual(result.request_id, context.request_id)
        self.assertEqual(
            [event["event"] for event in sink.events],
            ["started", "completed"],
        )
        self.assertEqual(
            {event["request_id"] for event in sink.events},
            {context.request_id},
        )

    def test_executor_remains_compatible_without_context_or_sink(self):
        definition = ToolDefinition(
            "status",
            "Status",
            SCHEMA,
            handler=lambda _args: "ok",
        )
        executor = ToolExecutor(ToolRegistry([definition]))

        result = asyncio.run(executor.execute("status", {}))

        self.assertTrue(result.success)
        self.assertIsNone(result.request_id)

    def test_normal_runtime_route_correlates_full_lifecycle(self):
        from main import JarvisLive

        class UI:
            microphone_enabled = False

            def set_state(self, _state):
                pass

        definition = ToolDefinition(
            "status",
            "Status",
            SCHEMA,
            handler=lambda _args: "ok",
        )
        sink = CapturingSink()
        jarvis = JarvisLive.__new__(JarvisLive)
        jarvis.ui = UI()
        jarvis._pending_confirmation_fc = None
        jarvis._pending_confirmation_source = None
        jarvis._pending_confirmation_context = None
        jarvis._active_input_source = InputSource.UI
        jarvis._remote_drive_folders = set()
        jarvis.request_audit = sink
        jarvis.tool_registry = ToolRegistry([definition])
        jarvis.tool_executor = ToolExecutor(
            jarvis.tool_registry,
            audit_sink=sink,
        )
        jarvis.permission_policy = PermissionPolicy()

        response = asyncio.run(
            jarvis._execute_tool(
                SimpleNamespace(name="status", args={}, id="fc-normal")
            )
        )

        request_id = response.response["request_id"]
        self.assertEqual(
            [event["event"] for event in sink.events],
            [
                "requested",
                "policy",
                "confirmation",
                "started",
                "completed",
                "response",
            ],
        )
        self.assertEqual(
            {event["request_id"] for event in sink.events},
            {request_id},
        )

    def test_special_runtime_route_correlates_full_lifecycle(self):
        from main import JarvisLive

        class UI:
            microphone_enabled = False

            def set_state(self, _state):
                pass

            def refresh_memory_graph(self):
                pass

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
        sink = CapturingSink()
        jarvis = JarvisLive.__new__(JarvisLive)
        jarvis.ui = UI()
        jarvis._pending_confirmation_fc = None
        jarvis._pending_confirmation_source = None
        jarvis._pending_confirmation_context = None
        jarvis._active_input_source = InputSource.LOCAL
        jarvis._remote_drive_folders = set()
        jarvis.request_audit = sink
        jarvis.tool_registry = ToolRegistry([definition])
        jarvis.tool_executor = ToolExecutor(
            jarvis.tool_registry,
            audit_sink=sink,
        )
        jarvis.permission_policy = PermissionPolicy()

        with patch(
            "main.create_memory",
            return_value={"result": "created"},
        ):
            response = asyncio.run(
                jarvis._execute_tool(
                    SimpleNamespace(
                        name="save_memory",
                        args={"category": "notes", "key": "k", "value": "secret body"},
                        id="fc-special",
                    )
                )
            )

        request_id = response.response["request_id"]
        self.assertEqual(
            [event["event"] for event in sink.events],
            [
                "requested",
                "policy",
                "confirmation",
                "started",
                "completed",
                "response",
            ],
        )
        self.assertEqual(
            {event["request_id"] for event in sink.events},
            {request_id},
        )
        self.assertNotIn("secret body", json.dumps(sink.events))

    def test_pending_confirmation_reuses_original_request_id(self):
        from main import JarvisLive

        class UI:
            microphone_enabled = False

            def set_state(self, _state):
                pass

            def write_log(self, _value):
                pass

        class Gate:
            def authorize_or_stage(self, *_args):
                return False

        definition = ToolDefinition(
            "sensitive_action",
            "Sensitive",
            SCHEMA,
            handler=lambda _args: "done",
            risk=RiskLevel.SENSITIVE,
        )
        sink = CapturingSink()
        jarvis = JarvisLive.__new__(JarvisLive)
        jarvis.ui = UI()
        jarvis._pending_confirmation_fc = None
        jarvis._pending_confirmation_source = None
        jarvis._pending_confirmation_context = None
        jarvis._active_input_source = InputSource.LOCAL
        jarvis._remote_drive_folders = set()
        jarvis._confirmation_gate = Gate()
        jarvis.request_audit = sink
        jarvis.tool_registry = ToolRegistry([definition])
        jarvis.tool_executor = ToolExecutor(
            jarvis.tool_registry,
            audit_sink=sink,
        )
        jarvis.permission_policy = PermissionPolicy()
        fc = SimpleNamespace(name="sensitive_action", args={}, id="fc-confirm")

        staged = asyncio.run(jarvis._execute_tool(fc))
        pending_context = jarvis._pending_confirmation_context
        completed = asyncio.run(
            jarvis._execute_tool(
                fc,
                preapproved=True,
                request_context=pending_context,
            )
        )

        self.assertEqual(
            staged.response["request_id"],
            completed.response["request_id"],
        )
        self.assertEqual(
            {event["request_id"] for event in sink.events},
            {pending_context.request_id},
        )
        self.assertEqual(
            [event["event"] for event in sink.events].count("requested"),
            1,
        )
        self.assertIn(
            {
                "request_id": pending_context.request_id,
                "event": "confirmation",
                "tool": "sensitive_action",
                "outcome": "approved",
            },
            sink.events,
        )


if __name__ == "__main__":
    unittest.main()
