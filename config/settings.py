"""Validated, immutable process settings with explicit refresh semantics."""

from __future__ import annotations

import json
import os
import platform
import sys
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping


class SettingsError(RuntimeError):
    """Configuration is missing required data or cannot be validated."""


def _freeze_json(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({
            str(key): _freeze_json(item)
            for key, item in value.items()
        })
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def default_settings_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "config" / "api_keys.json"
    return Path(__file__).resolve().parent / "api_keys.json"


def _platform_os() -> str:
    return {"Windows": "windows", "Darwin": "mac", "Linux": "linux"}.get(
        platform.system(),
        "linux",
    )


@dataclass(frozen=True, slots=True)
class AppSettings:
    gemini_api_key: str = field(default="", repr=False)
    os_system: str = "linux"
    extras: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({}),
        repr=False,
    )

    def require_gemini_api_key(self) -> str:
        if not self.gemini_api_key:
            raise SettingsError("gemini_api_key is missing from local configuration.")
        return self.gemini_api_key

    def as_legacy_dict(self) -> dict[str, Any]:
        return {
            **_thaw_json(self.extras),
            "gemini_api_key": self.gemini_api_key,
            "os_system": self.os_system,
        }


def _settings_from_raw(raw: object) -> AppSettings:
    if not isinstance(raw, dict):
        raise SettingsError("Settings root must be a JSON object.")

    api_key = raw.get("gemini_api_key", "")
    os_system = raw.get("os_system", _platform_os())
    if not isinstance(api_key, str):
        raise SettingsError("gemini_api_key must be a string.")
    if not isinstance(os_system, str):
        raise SettingsError("os_system must be a string.")
    normalized_os = os_system.strip().lower() or _platform_os()
    if normalized_os not in {"windows", "mac", "linux"}:
        raise SettingsError("os_system must be windows, mac, or linux.")

    extras = _freeze_json({
        key: value
        for key, value in raw.items()
        if key not in {"gemini_api_key", "os_system"}
    })
    return AppSettings(
        gemini_api_key=api_key.strip(),
        os_system=normalized_os,
        extras=extras,
    )


def load_settings(path: Path | None = None) -> AppSettings:
    resolved = (path or default_settings_path()).resolve()
    try:
        raw = json.loads(resolved.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raw = {}
    except json.JSONDecodeError as exc:
        raise SettingsError("Settings file must contain valid JSON.") from exc
    except OSError as exc:
        raise SettingsError("Settings file could not be read.") from exc
    return _settings_from_raw(raw)


_CACHE: dict[Path, AppSettings] = {}
_CACHE_LOCK = threading.RLock()


def get_settings(path: Path | None = None) -> AppSettings:
    resolved = (path or default_settings_path()).resolve()
    with _CACHE_LOCK:
        settings = _CACHE.get(resolved)
        if settings is None:
            settings = load_settings(resolved)
            _CACHE[resolved] = settings
        return settings


def refresh_settings(path: Path | None = None) -> AppSettings:
    resolved = (path or default_settings_path()).resolve()
    settings = load_settings(resolved)
    with _CACHE_LOCK:
        _CACHE[resolved] = settings
    return settings


def update_settings(
    values: Mapping[str, Any],
    path: Path | None = None,
) -> AppSettings:
    """Atomically merge validated values into the process settings document."""
    resolved = (path or default_settings_path()).resolve()
    if not isinstance(values, Mapping):
        raise SettingsError("Settings update must be a mapping.")

    with _CACHE_LOCK:
        merged = get_settings(resolved).as_legacy_dict()
        merged.update({str(key): _thaw_json(value) for key, value in values.items()})
        settings = _settings_from_raw(merged)
        try:
            payload = json.dumps(
                settings.as_legacy_dict(),
                indent=2,
                ensure_ascii=False,
            )
        except (TypeError, ValueError) as exc:
            raise SettingsError("Settings values must be JSON serializable.") from exc
        resolved.parent.mkdir(parents=True, exist_ok=True)
        temp_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=resolved.parent,
                prefix=f".{resolved.name}.",
                suffix=".tmp",
                delete=False,
            ) as temp_file:
                temp_name = temp_file.name
                temp_file.write(payload)
                temp_file.write("\n")
                temp_file.flush()
                os.fsync(temp_file.fileno())
            os.replace(temp_name, resolved)
        except OSError as exc:
            if temp_name is not None:
                try:
                    Path(temp_name).unlink(missing_ok=True)
                except OSError:
                    pass
            raise SettingsError("Settings file could not be written.") from exc

        _CACHE[resolved] = settings
        return settings
