"""Build the trusted registry from Gemini declarations and local adapters."""

from __future__ import annotations

from collections.abc import Mapping

from .definitions import ConfirmationPolicy, RiskLevel, ToolDefinition
from .registry import ToolRegistry


SPECIAL_TOOLS = {
    "save_memory", "screen_process", "visual_mouse", "close_camera", "shutdown_jarvis"
}

RISK = {
    "send_message": RiskLevel.EXTERNAL_EFFECT,
    "reminder": RiskLevel.EXTERNAL_EFFECT,
    "open_app": RiskLevel.LOCAL_CHANGE,
    "computer_settings": RiskLevel.SENSITIVE,
    "file_controller": RiskLevel.SENSITIVE,
    "desktop_control": RiskLevel.SENSITIVE,
    "code_helper": RiskLevel.SENSITIVE,
    "dev_agent": RiskLevel.SENSITIVE,
    "computer_control": RiskLevel.SENSITIVE,
    "game_updater": RiskLevel.EXTERNAL_EFFECT,
    "shutdown_jarvis": RiskLevel.SENSITIVE,
    "save_memory": RiskLevel.LOCAL_CHANGE,
    "memory_update": RiskLevel.LOCAL_CHANGE,
    "memory_forget": RiskLevel.SENSITIVE,
    "memory_restore": RiskLevel.LOCAL_CHANGE,
    "obsidian_connector": RiskLevel.SENSITIVE,
}

CONFIRMATION = {
    name: ConfirmationPolicy.DEPENDS_ON_ARGUMENTS
    for name in {
        "send_message", "file_controller", "computer_settings", "desktop_control",
        "code_helper", "dev_agent", "game_updater",
        "obsidian_connector",
    }
}
CONFIRMATION["memory_forget"] = ConfirmationPolicy.ALWAYS
CONFIRMATION["memory_update"] = ConfirmationPolicy.DEPENDS_ON_ARGUMENTS
CONFIRMATION["memory_restore"] = ConfirmationPolicy.DEPENDS_ON_ARGUMENTS

DEFAULT_RESULTS = {
    "open_app": "Opened application.",
    "weather_report": "Weather delivered.",
    "send_message": "Message sent.",
    "reminder": "Reminder set.",
}


def build_builtin_registry(
    declarations: list[dict], handlers: Mapping[str, object]
) -> ToolRegistry:
    registry = ToolRegistry()
    for declaration in declarations:
        name = declaration["name"]
        special = name in SPECIAL_TOOLS
        registry.register(ToolDefinition(
            name=name,
            description=declaration.get("description", ""),
            parameters=declaration.get("parameters", {"type": "OBJECT", "properties": {}}),
            handler=None if special else handlers.get(name),
            risk=RISK.get(name, RiskLevel.READ_ONLY),
            confirmation=CONFIRMATION.get(name, ConfirmationPolicy.NEVER),
            platforms=frozenset({"windows"}),
            timeout=120.0 if name in {"dev_agent", "code_helper", "game_updater"} else 30.0,
            cancellable=name not in SPECIAL_TOOLS,
            background=False,
            special=special,
            default_result=DEFAULT_RESULTS.get(name, "Done."),
        ))
    return registry
