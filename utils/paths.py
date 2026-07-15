from __future__ import annotations

import os
import platform
from pathlib import Path


def _windows_known_folder(registry_name: str, fallback_name: str) -> Path:
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
        ) as key:
            value, _ = winreg.QueryValueEx(key, registry_name)

        resolved = Path(os.path.expandvars(value)).expanduser()

        if resolved.exists():
            return resolved

    except Exception:
        pass

    onedrive = os.environ.get("OneDrive")

    if onedrive:
        candidate = Path(onedrive) / fallback_name
        if candidate.exists():
            return candidate

    return Path.home() / fallback_name


def get_desktop() -> Path:
    if platform.system() == "Windows":
        return _windows_known_folder("Desktop", "Desktop")

    if platform.system() == "Linux":
        xdg = os.environ.get("XDG_DESKTOP_DIR", "")
        if xdg:
            candidate = Path(os.path.expandvars(xdg)).expanduser()
            if candidate.exists():
                return candidate

    return Path.home() / "Desktop"


def get_documents() -> Path:
    if platform.system() == "Windows":
        return _windows_known_folder("Personal", "Documents")

    return Path.home() / "Documents"


def get_downloads() -> Path:
    if platform.system() == "Windows":
        return _windows_known_folder(
            "{374DE290-123F-4565-9164-39C4925E467B}",
            "Downloads",
        )

    return Path.home() / "Downloads"


def get_pictures() -> Path:
    if platform.system() == "Windows":
        return _windows_known_folder("My Pictures", "Pictures")

    return Path.home() / "Pictures"


def get_music() -> Path:
    if platform.system() == "Windows":
        return _windows_known_folder("My Music", "Music")

    return Path.home() / "Music"


def get_videos() -> Path:
    if platform.system() == "Windows":
        return _windows_known_folder("My Video", "Videos")

    return Path.home() / "Videos"