"""Central safety policy for model-triggered desktop actions."""

from __future__ import annotations

import json
import re
import time
import unicodedata
from collections.abc import Callable


_SENSITIVE_LOG_FIELDS = {"code", "content", "message_text", "password", "text"}


def safe_tool_args(args: dict) -> dict:
    """Keep credentials and user content out of terminal logs."""
    return {
        key: "[redacted]" if key.lower() in _SENSITIVE_LOG_FIELDS else value
        for key, value in args.items()
    }


def confirmation_request(tool_name: str, args: dict) -> tuple[str, str] | None:
    """Return the local approval prompt required for a privileged tool call."""
    raw_action = args.get("action") or args.get("description") or ""
    action = str(raw_action).lower().strip().replace("-", "_")

    if tool_name == "send_message":
        receiver = str(args.get("receiver", "unknown recipient"))[:80]
        platform_name = str(args.get("platform", "messaging app"))[:40]
        return "Send this message?", f"Recipient: {receiver}\nPlatform: {platform_name}"

    if tool_name == "file_controller" and action in {
        "delete", "move", "rename", "write", "organize_desktop", "clear_jarvis_temp"
    }:
        target = (
            "Jarvis temporales (contents only; folder preserved)"
            if action == "clear_jarvis_temp"
            else str(args.get("name") or args.get("path") or "unspecified path")[:240]
        )
        return "Approve file-system change?", f"Action: {action}\nTarget: {target}"

    if tool_name == "obsidian_connector" and action in {"create", "write", "append"}:
        target = str(args.get("path") or "unspecified note")[:240]
        return "Approve Obsidian note change?", f"Action: {action}\nNote: {target}"

    if tool_name == "computer_settings" and any(
        keyword in action
        for keyword in ("shutdown", "shut_down", "restart", "reboot", "toggle_wifi")
    ):
        return "Approve system change?", f"Action: {action}"

    if tool_name == "desktop_control" and action in {"clean", "organize", "task"}:
        return "Approve desktop changes?", f"Action: {action}"

    if tool_name == "code_helper" and action in {
        "write", "edit", "run", "build", "optimize", "screen_debug", "auto"
    }:
        target = str(args.get("file_path") or args.get("output_path") or "new code")[:240]
        return "Approve code modification or execution?", f"Action: {action}\nTarget: {target}"

    if tool_name == "dev_agent":
        return (
            "Allow the developer agent to run?",
            "It may create files, install packages, and execute code.",
        )

    if tool_name == "game_updater" and (
        action in {"update", "install", "schedule", "cancel_schedule"}
        or bool(args.get("shutdown_when_done"))
    ):
        game = str(args.get("game_name") or "selected games")[:120]
        return "Approve game-management action?", f"Action: {action}\nGame: {game}"

    return None


def _normalize_confirmation(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = re.sub(r"[^a-zA-Z0-9 ]+", " ", normalized.lower())
    return " ".join(normalized.split())


class VoiceConfirmationGate:
    """Authorize exactly one staged action after an explicit spoken response."""

    _APPROVE = {
        "yes", "yes please", "confirm", "i confirm", "do it", "go ahead",
        "proceed", "approved", "si", "si por favor", "confirmo", "hacelo",
        "hazlo", "dale", "adelante", "procede", "aprobado",
    }
    _DENY = {
        "no", "no thanks", "cancel", "cancel it", "do not", "dont",
        "stop", "deny", "no gracias", "cancela", "cancelar", "no lo hagas",
        "detente", "rechazo",
    }

    def __init__(
        self,
        ttl_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._pending: dict | None = None

    @staticmethod
    def _fingerprint(tool_name: str, args: dict) -> str:
        payload = json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)
        return f"{tool_name}:{payload}"

    def _expire_if_needed(self) -> None:
        if self._pending and self._pending["expires_at"] <= self._clock():
            self._pending = None

    def authorize_or_stage(
        self,
        tool_name: str,
        args: dict,
        title: str,
        detail: str,
    ) -> bool:
        """Return True only for the matching action after explicit approval."""
        self._expire_if_needed()
        fingerprint = self._fingerprint(tool_name, args)
        if (
            self._pending
            and self._pending["fingerprint"] == fingerprint
            and self._pending["approved"]
        ):
            self._pending = None
            return True

        self._pending = {
            "fingerprint": fingerprint,
            "title": title,
            "detail": detail,
            "approved": False,
            "expires_at": self._clock() + self._ttl_seconds,
        }
        return False

    def observe(self, text: str) -> str | None:
        """Return approved/denied only for an exact, unambiguous response."""
        self._expire_if_needed()
        if not self._pending:
            return None
        normalized = _normalize_confirmation(text)
        words = set(normalized.split())
        denial_words = {"no", "cancel", "cancela", "cancelar", "rechazo", "deny", "stop"}
        approval_prefixes = (
            "si ", "yes ", "confirmo ", "confirm ", "dale ", "claro ",
            "correcto ", "aprobado ", "approved ", "go ahead ",
        )
        if normalized in self._APPROVE or (
            normalized.startswith(approval_prefixes) and not words.intersection(denial_words)
        ):
            self._pending["approved"] = True
            return "approved"
        if normalized in self._DENY:
            self._pending = None
            return "denied"
        return None

    def clear(self) -> None:
        self._pending = None

    @property
    def has_pending(self) -> bool:
        self._expire_if_needed()
        return self._pending is not None
