from __future__ import annotations

from core.tools.definitions import ConfirmationPolicy, RiskLevel, ToolDefinition

from .models import ExecutionContext, PermissionDecision, PermissionLevel


_READ_FILE_ACTIONS = {
    "list", "read", "inspect", "browse", "inspect_folder", "read_folder",
    "open", "find", "largest", "disk_usage", "info",
}
_REVERSIBLE_FILE_ACTIONS = {
    "create_file", "create_folder", "copy",
    "create", "new_file", "new_folder", "mkdir", "make_directory",
}
_ALWAYS_FILE_ACTIONS = {"delete", "clear_jarvis_temp"}
_CHANGE_FILE_ACTIONS = {
    "move", "rename", "write", "organize_desktop"
}
_FREE_TOOLS = {
    "browser_control", "close_camera", "flight_finder", "open_app", "reminder",
    "screen_process", "shutdown_jarvis", "system_status", "visual_mouse",
    "weather_report", "web_search", "youtube_video",
    "math_engine", "account_connector",
}
_FREE_COMPUTER_ACTIONS = {
    "type", "smart_type", "click", "left_click", "double_click", "right_click",
    "move", "drag", "hotkey", "press", "scroll", "copy", "paste", "screenshot",
    "screen_find", "screen_click", "screen_move", "screen_double_click",
    "screen_right_click", "wait", "clear_field", "focus_window", "random_data",
    "user_data",
}
_POWER_ACTION_WORDS = {"shutdown", "shut_down", "restart", "reboot", "poweroff"}


class PermissionPolicy:
    def __init__(self, preferences: dict[str, PermissionLevel] | None = None) -> None:
        self.preferences = preferences or {}

    @staticmethod
    def operation(tool_name: str, arguments: dict) -> str:
        raw = arguments.get("action") or arguments.get("description") or "default"
        return str(raw).lower().strip().replace("-", "_")

    @staticmethod
    def minimum(tool: ToolDefinition, operation: str) -> PermissionLevel:
        if tool.name in _FREE_TOOLS:
            return PermissionLevel.FREE
        if tool.name == "send_message":
            return PermissionLevel.CONFIRM_ALWAYS
        if tool.name == "computer_control":
            return (
                PermissionLevel.FREE
                if operation in _FREE_COMPUTER_ACTIONS
                else PermissionLevel.CONFIRM_ONCE
            )
        if tool.name == "computer_settings":
            if any(word in operation for word in _POWER_ACTION_WORDS):
                return PermissionLevel.CONFIRM_ALWAYS
            return PermissionLevel.FREE
        if tool.name == "code_helper":
            if operation in {"explain", "write", "edit"}:
                return PermissionLevel.FREE
            return PermissionLevel.CONFIRM_ALWAYS
        if tool.name == "file_controller":
            if operation in _READ_FILE_ACTIONS:
                return PermissionLevel.FREE
            if operation in _REVERSIBLE_FILE_ACTIONS:
                return PermissionLevel.FREE
            if operation in _ALWAYS_FILE_ACTIONS:
                return PermissionLevel.CONFIRM_ALWAYS
            if operation in _CHANGE_FILE_ACTIONS:
                return PermissionLevel.CONFIRM_ONCE
            return PermissionLevel.CONFIRM_ALWAYS
        if tool.name == "obsidian_connector":
            if operation in {"status", "search", "read", "open"}:
                return PermissionLevel.FREE
            if operation in {"create", "write", "append"}:
                return PermissionLevel.CONFIRM_ONCE
            return PermissionLevel.CONFIRM_ALWAYS
        if tool.name == "permission_manager":
            return (
                PermissionLevel.FREE
                if operation in {"status", "get", "query"}
                else PermissionLevel.CONFIRM_ALWAYS
            )
        if tool.confirmation == ConfirmationPolicy.ALWAYS:
            return PermissionLevel.CONFIRM_ALWAYS
        if tool.confirmation == ConfirmationPolicy.DEPENDS_ON_ARGUMENTS:
            return PermissionLevel.CONFIRM_ONCE
        if tool.risk in {RiskLevel.SENSITIVE, RiskLevel.EXTERNAL_EFFECT}:
            return PermissionLevel.CONFIRM_ONCE
        return PermissionLevel.FREE

    def effective_level(self, tool: ToolDefinition, arguments: dict, context: ExecutionContext) -> PermissionLevel:
        operation = self.operation(tool.name, arguments)
        minimum = self.minimum(tool, operation)
        if tool.name == "code_helper" and operation == "run":
            from memory.script_memory import is_registered_script
            if is_registered_script(arguments.get("routine_name", "")):
                minimum = PermissionLevel.FREE
        configured = self.preferences.get(
            f"{tool.name}:{operation}",
            self.preferences.get(tool.name, PermissionLevel.FREE),
        )
        level = max(minimum, configured)
        if context.source != "local" and level < PermissionLevel.CONFIRM_ONCE:
            level = PermissionLevel.CONFIRM_ONCE
        return level

    def describe(self, tool: ToolDefinition, arguments: dict) -> dict:
        operation = self.operation(tool.name, arguments)
        minimum = self.minimum(tool, operation)
        configured = self.preferences.get(
            f"{tool.name}:{operation}",
            self.preferences.get(tool.name, PermissionLevel.FREE),
        )
        effective = max(minimum, configured)
        return {
            "tool": tool.name,
            "action": operation,
            "configured": configured.label,
            "minimum": minimum.label,
            "effective": effective.label,
            "editable": effective != PermissionLevel.BLOCKED or minimum != PermissionLevel.BLOCKED,
        }

    def evaluate(self, tool: ToolDefinition, arguments: dict, context: ExecutionContext | None = None) -> PermissionDecision:
        context = context or ExecutionContext()
        operation = self.operation(tool.name, arguments)
        level = self.effective_level(tool, arguments, context)
        can_preview = tool.name == "send_message" or tool.name == "file_controller"
        if context.simulate:
            if can_preview:
                return PermissionDecision(False, False, True, level.label, "Simulation requested; the real handler will not run.", operation)
            return PermissionDecision(False, False, False, level.label, "This tool does not support side-effect-free simulation.", operation)
        if level == PermissionLevel.BLOCKED:
            return PermissionDecision(False, False, False, level.label, "The tool is blocked by the active permission policy.", operation)
        requires = level in {PermissionLevel.CONFIRM_ONCE, PermissionLevel.CONFIRM_ALWAYS}
        return PermissionDecision(not requires, requires, False, level.label, "Effective policy combines the immutable minimum, user preference, and execution context.", operation)

    def is_advertised(self, tool: ToolDefinition, source: str = "local") -> bool:
        return self.effective_level(tool, {}, ExecutionContext(source=source)) != PermissionLevel.BLOCKED
