from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from core.permissions import (
    ExecutionContext, PermissionLevel, PermissionPolicy, PermissionStore, build_preview,
)
from core.tools import ConfirmationPolicy, RiskLevel, ToolDefinition


SCHEMA = {"type": "OBJECT", "properties": {}}


def tool(name, *, risk=RiskLevel.READ_ONLY, confirmation=ConfirmationPolicy.NEVER):
    return ToolDefinition(name, name, SCHEMA, handler=lambda args: "executed", risk=risk, confirmation=confirmation)


class PermissionPolicyTests(unittest.TestCase):
    def test_free_sensitive_blocked_and_user_hardening(self):
        status = tool("system_status")
        sender = tool("send_message", risk=RiskLevel.EXTERNAL_EFFECT)
        dev = tool("dev_agent", risk=RiskLevel.SENSITIVE)
        policy = PermissionPolicy({
            "system_status": PermissionLevel.CONFIRM_ONCE,
            "dev_agent": PermissionLevel.BLOCKED,
        })
        self.assertTrue(PermissionPolicy().evaluate(status, {}).allowed)
        self.assertTrue(policy.evaluate(status, {}).requires_confirmation)
        self.assertEqual(policy.evaluate(sender, {}).policy, "confirm_always")
        self.assertEqual(policy.evaluate(dev, {}).policy, "blocked")
        self.assertFalse(policy.is_advertised(dev))

    def test_critical_minimum_cannot_be_weakened(self):
        sender = tool("send_message", risk=RiskLevel.EXTERNAL_EFFECT)
        decision = PermissionPolicy({"send_message": PermissionLevel.FREE}).evaluate(sender, {})
        self.assertEqual(decision.policy, "confirm_always")
        self.assertTrue(decision.requires_confirmation)

    def test_file_operations_have_distinct_minimums(self):
        files = tool("file_controller", risk=RiskLevel.SENSITIVE)
        policy = PermissionPolicy()
        self.assertTrue(policy.evaluate(files, {"action": "read"}).allowed)
        for action in ("inspect", "browse", "inspect_folder", "read_folder"):
            with self.subTest(action=action):
                self.assertTrue(policy.evaluate(files, {"action": action}).allowed)
        self.assertTrue(policy.evaluate(files, {"action": "create_folder"}).allowed)
        self.assertTrue(policy.evaluate(files, {"action": "create_file"}).allowed)
        self.assertTrue(policy.evaluate(files, {"action": "copy"}).allowed)
        self.assertEqual(policy.evaluate(files, {"action": "write"}).policy, "confirm_once")
        self.assertEqual(policy.evaluate(files, {"action": "delete"}).policy, "confirm_always")
        self.assertEqual(policy.evaluate(files, {"action": "clear_jarvis_temp"}).policy, "confirm_always")

    def test_operation_preference_applies_without_weakening_minimum(self):
        files = tool("file_controller", risk=RiskLevel.SENSITIVE)
        policy = PermissionPolicy({
            "file_controller:create_folder": PermissionLevel.BLOCKED,
            "file_controller:delete": PermissionLevel.FREE,
        })
        self.assertEqual(policy.evaluate(files, {"action": "create_folder"}).policy, "blocked")
        self.assertEqual(policy.evaluate(files, {"action": "delete"}).policy, "confirm_always")

    def test_direct_ui_actions_and_jarvis_exit_are_free(self):
        policy = PermissionPolicy()
        control = tool("computer_control", risk=RiskLevel.SENSITIVE)
        exit_tool = tool("shutdown_jarvis", risk=RiskLevel.SENSITIVE)
        open_tool = tool("open_app", risk=RiskLevel.LOCAL_CHANGE)
        for definition, args in (
            (control, {"action": "press", "key": "enter"}),
            (control, {"action": "scroll", "amount": 3}),
            (exit_tool, {}),
            (open_tool, {"app_name": "Spotify"}),
        ):
            with self.subTest(tool=definition.name, args=args):
                self.assertTrue(policy.evaluate(definition, args).allowed)

    def test_computer_power_and_code_execution_remain_confirmed(self):
        policy = PermissionPolicy()
        settings = tool("computer_settings", risk=RiskLevel.SENSITIVE)
        code = tool("code_helper", risk=RiskLevel.SENSITIVE)
        self.assertEqual(
            policy.evaluate(settings, {"description": "restart the computer"}).policy,
            "confirm_always",
        )
        self.assertTrue(policy.evaluate(code, {"action": "write"}).allowed)
        self.assertEqual(policy.evaluate(code, {"action": "run"}).policy, "confirm_always")

    def test_memory_reads_are_free_and_forgetting_requires_confirmation(self):
        policy = PermissionPolicy()
        listing = tool("memory_list")
        updating = tool(
            "memory_update", risk=RiskLevel.LOCAL_CHANGE,
            confirmation=ConfirmationPolicy.DEPENDS_ON_ARGUMENTS,
        )
        forgetting = tool(
            "memory_forget", risk=RiskLevel.SENSITIVE,
            confirmation=ConfirmationPolicy.ALWAYS,
        )
        self.assertTrue(policy.evaluate(listing, {}).allowed)
        self.assertTrue(policy.evaluate(updating, {"memory_id": "mem_example"}).requires_confirmation)
        decision = policy.evaluate(forgetting, {"memory_id": "mem_example"})
        self.assertEqual(decision.policy, "confirm_always")
        self.assertTrue(decision.requires_confirmation)

    def test_remote_context_is_more_restrictive(self):
        status = tool("system_status")
        decision = PermissionPolicy().evaluate(status, {}, ExecutionContext(source="remote"))
        self.assertTrue(decision.requires_confirmation)

    def test_simulation_is_structured_and_redacts_content(self):
        sender = tool("send_message", risk=RiskLevel.EXTERNAL_EFFECT)
        args = {"receiver": "Alice", "message_text": "secret", "platform": "Signal"}
        decision = PermissionPolicy().evaluate(sender, args, ExecutionContext(simulate=True))
        preview = build_preview("send_message", args, decision)
        self.assertTrue(decision.simulated)
        self.assertFalse(decision.allowed)
        self.assertEqual(preview["arguments"]["message_text"], "[redacted]")
        self.assertEqual(preview["affected"], "Alice")

    def test_unsupported_simulation_fails_closed(self):
        status = tool("system_status")
        decision = PermissionPolicy().evaluate(status, {}, ExecutionContext(simulate=True))
        self.assertFalse(decision.allowed)
        self.assertFalse(decision.simulated)


class PermissionStoreTests(unittest.TestCase):
    def test_valid_preferences_load_and_round_trip(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "permissions.json"
            store = PermissionStore(path)
            store.save({"dev_agent": PermissionLevel.BLOCKED})
            self.assertEqual(store.load()["dev_agent"], PermissionLevel.BLOCKED)

    def test_operation_preferences_round_trip(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "permissions.json"
            store = PermissionStore(path)
            store.save({"file_controller:create_folder": PermissionLevel.FREE})
            self.assertEqual(
                store.load()["file_controller:create_folder"], PermissionLevel.FREE
            )
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["version"], 2)
            self.assertEqual(
                payload["operations"]["file_controller"]["create_folder"], "free"
            )

    def test_invalid_configuration_returns_safe_defaults(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "permissions.json"
            path.write_text(json.dumps({"version": 999, "tools": {"send_message": "free"}}), encoding="utf-8")
            loaded = PermissionStore(path).load()
            self.assertEqual(loaded["send_message"], PermissionLevel.CONFIRM_ALWAYS)


if __name__ == "__main__":
    unittest.main()
