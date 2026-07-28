from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path

from .models import PermissionLevel


DEFAULT_PREFERENCES = {
    "system_status": PermissionLevel.FREE,
    "send_message": PermissionLevel.CONFIRM_ALWAYS,
    "dev_agent": PermissionLevel.CONFIRM_ALWAYS,
}

_PATH_LOCKS: dict[Path, threading.RLock] = {}
_PATH_LOCKS_GUARD = threading.Lock()


def _lock_for(path: Path) -> threading.RLock:
    resolved = path.resolve(strict=False)
    with _PATH_LOCKS_GUARD:
        return _PATH_LOCKS.setdefault(resolved, threading.RLock())


class PermissionStore:
    """Versioned preferences with atomic publication and safe recovery."""

    VERSION = 2
    READABLE_VERSIONS = frozenset({1, VERSION})

    def __init__(self, path: str | Path = "config/permissions.json") -> None:
        self.path = Path(path)
        self.backup_path = self.path.with_name(f"{self.path.name}.bak")
        self._lock = _lock_for(self.path)

    @classmethod
    def _decode_payload(cls, payload: object) -> dict[str, PermissionLevel]:
        if not isinstance(payload, dict):
            raise TypeError("Permission payload must be an object")
        if payload.get("version") not in cls.READABLE_VERSIONS:
            raise ValueError("Unsupported permission store version")
        tools = payload.get("tools")
        if not isinstance(tools, dict):
            raise TypeError("Permission tools must be an object")

        preferences = dict(DEFAULT_PREFERENCES)
        validated: dict[str, PermissionLevel] = {}
        for name, raw_level in tools.items():
            if not isinstance(name, str):
                raise TypeError("Tool names must be strings")
            validated[name] = PermissionLevel.parse(raw_level)

        operations = payload.get("operations", {})
        if not isinstance(operations, dict):
            raise TypeError("Operation preferences must be an object")
        for tool_name, tool_operations in operations.items():
            if not isinstance(tool_name, str) or not isinstance(tool_operations, dict):
                raise TypeError("Operation preferences must be nested objects")
            for operation, raw_level in tool_operations.items():
                if not isinstance(operation, str):
                    raise TypeError("Operation names must be strings")
                validated[f"{tool_name}:{operation}"] = PermissionLevel.parse(
                    raw_level
                )

        preferences.update(validated)
        return preferences

    @classmethod
    def _read_document(
        cls,
        path: Path,
    ) -> tuple[bytes, dict[str, PermissionLevel]]:
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
        return raw, cls._decode_payload(payload)

    @classmethod
    def _serialize(
        cls,
        preferences: dict[str, PermissionLevel | str],
    ) -> bytes:
        tools: dict[str, str] = {}
        operations: dict[str, dict[str, str]] = {}
        for name, level in preferences.items():
            if not isinstance(name, str):
                raise TypeError("Permission names must be strings")
            parsed = PermissionLevel.parse(level).label
            if ":" in name:
                tool_name, operation = name.split(":", 1)
                if not tool_name or not operation:
                    raise ValueError("Operation preference names cannot be empty")
                operations.setdefault(tool_name, {})[operation] = parsed
            else:
                if not name:
                    raise ValueError("Tool preference names cannot be empty")
                tools[name] = parsed
        payload = {
            "version": cls.VERSION,
            "tools": tools,
            "operations": operations,
        }
        # Validate exactly what will be published before touching the final path.
        cls._decode_payload(payload)
        return (
            json.dumps(payload, indent=2, ensure_ascii=True, sort_keys=True) + "\n"
        ).encode("utf-8")

    @classmethod
    def _atomic_publish(cls, target: Path, content: bytes) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary_path = Path(handle.name)
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())

            # Re-read and validate the durable temporary before publication.
            cls._read_document(temporary_path)
            os.replace(temporary_path, target)
            temporary_path = None
            cls._fsync_directory(target.parent)
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink()
                except FileNotFoundError:
                    pass

    @staticmethod
    def _fsync_directory(directory: Path) -> None:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        try:
            descriptor = os.open(directory, flags)
        except OSError:
            return
        try:
            os.fsync(descriptor)
        except OSError:
            # Windows and some filesystems do not support directory fsync.
            pass
        finally:
            os.close(descriptor)

    def load(self) -> dict[str, PermissionLevel]:
        with self._lock:
            for candidate in (self.path, self.backup_path):
                try:
                    _, preferences = self._read_document(candidate)
                    return preferences
                except (
                    OSError,
                    UnicodeError,
                    ValueError,
                    KeyError,
                    TypeError,
                    json.JSONDecodeError,
                ):
                    continue
        return dict(DEFAULT_PREFERENCES)

    def save(self, preferences: dict[str, PermissionLevel | str]) -> None:
        content = self._serialize(preferences)
        with self._lock:
            # Preserve only a validated primary. Corrupt data must never replace
            # the last known-good backup.
            try:
                current, _ = self._read_document(self.path)
            except (
                OSError,
                UnicodeError,
                ValueError,
                KeyError,
                TypeError,
                json.JSONDecodeError,
            ):
                current = None
            if current is not None:
                self._atomic_publish(self.backup_path, current)
            self._atomic_publish(self.path, content)
