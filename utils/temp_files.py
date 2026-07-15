from __future__ import annotations

import os
import time
import uuid
from pathlib import Path

from utils.paths import get_documents

RETENTION_DAYS = 7


def jarvis_temp_root() -> Path:
    override = os.environ.get("JARVIS_TEMP_DIR", "").strip()
    root = Path(override).expanduser() if override else get_documents() / "Jarvis temporales"
    return root.resolve()


def cleanup_temp_files(max_age_days: int = RETENTION_DAYS) -> int:
    root = jarvis_temp_root()
    if not root.exists():
        return 0
    cutoff = time.time() - max(0, max_age_days) * 86400
    removed = 0
    for path in root.rglob("*"):
        try:
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            continue
    for directory in sorted((p for p in root.rglob("*") if p.is_dir()), reverse=True):
        try:
            directory.rmdir()
        except OSError:
            pass
    return removed


def temporary_output(*, suffix: str = ".png", prefix: str = "jarvis", category: str = "imagenes") -> Path:
    cleanup_temp_files()
    folder = jarvis_temp_root() / category
    folder.mkdir(parents=True, exist_ok=True)
    safe_suffix = suffix if suffix.startswith(".") else f".{suffix}"
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return folder / f"{prefix}-{stamp}-{uuid.uuid4().hex[:8]}{safe_suffix}"
