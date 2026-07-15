from __future__ import annotations

from .models import PermissionDecision


_SECRET_FIELDS = {"content", "message_text", "password", "text", "token"}


def build_preview(tool_name: str, arguments: dict, decision: PermissionDecision) -> dict:
    relevant = {
        key: ("[redacted]" if key.lower() in _SECRET_FIELDS else value)
        for key, value in arguments.items()
        if key != "simulate"
    }
    target = (
        arguments.get("receiver") if tool_name == "send_message"
        else arguments.get("name") or arguments.get("path") or "unspecified target"
    )
    return {
        "simulated": True,
        "estimated": True,
        "tool": tool_name,
        "operation": decision.operation,
        "arguments": relevant,
        "affected": str(target),
        "risk_policy": decision.policy,
        "confirmation_required_for_real_execution": decision.requires_confirmation
            or decision.policy in {"confirm_once", "confirm_always"},
        "expected_result": "A real execution would apply the described action to the affected target.",
        "uncertainties": "The final result and external state cannot be verified without execution.",
    }
