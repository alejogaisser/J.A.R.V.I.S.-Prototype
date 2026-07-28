import hashlib
import os
import platform
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from core.tools import (
    EffectStatus,
    ExecutionStatus,
    RollbackStatus,
    ToolResult,
    VerificationStatus,
)
from core.tools.file_verifier import FileEvidence, capture_file_evidence

try:
    import send2trash
    _SEND2TRASH = True
except ImportError:
    class _MissingSend2Trash:
        @staticmethod
        def send2trash(_value):
            raise RuntimeError("send2trash is not installed")
    send2trash = _MissingSend2Trash()
    _SEND2TRASH = False

_OS = platform.system()  # "Windows" | "Darwin" | "Linux"
_PROJECT_ROOT = Path(__file__).resolve().parent.parent

_SAFE_ROOTS: list[Path] = [
    Path.home(),
]

_PROTECTED_DIR_NAMES = {
    "appdata", ".ssh", ".gnupg", ".aws", ".azure", ".kube", ".docker",
    ".git", ".codex", ".config", "credentials", "certs", "secrets",
}
_PROTECTED_FILE_NAMES = {
    ".env", "api_keys.json", "google_oauth_client.json",
    "microsoft_oauth_client.json", "permissions.json", "long_term.json",
    "credentials.json", "secrets.json", "id_rsa", "id_ed25519",
}
_PROTECTED_SUFFIXES = {".pem", ".key", ".pfx", ".p12", ".kdbx"}


def _is_protected_path(target: Path) -> bool:
    """Immutable deny-list, independent from editable permission preferences."""
    try:
        resolved = target.resolve()
        relative = resolved.relative_to(Path.home().resolve())
    except (OSError, ValueError):
        return True
    if {part.casefold() for part in relative.parts} & _PROTECTED_DIR_NAMES:
        return True
    return (
        resolved.name.casefold() in _PROTECTED_FILE_NAMES
        or resolved.suffix.casefold() in _PROTECTED_SUFFIXES
    )

def _is_safe_path(target: Path) -> bool:
    """Verilen path _SAFE_ROOTS içinde mi? Değilse işlemi reddet."""
    try:
        resolved = target.resolve()
        inside_allowed_root = any(
            resolved == root.resolve() or resolved.is_relative_to(root.resolve())
            for root in _SAFE_ROOTS
        )
        return inside_allowed_root and not _is_protected_path(resolved)
    except Exception:
        return False

def _get_desktop() -> Path:
    from utils.paths import get_desktop
    return get_desktop()


def _get_downloads() -> Path:
    from utils.paths import get_downloads
    return get_downloads()


def _get_documents() -> Path:
    from utils.paths import get_documents
    return get_documents()


def _get_pictures() -> Path:
    from utils.paths import get_pictures
    return get_pictures()


def _get_music() -> Path:
    from utils.paths import get_music
    return get_music()


def _get_videos() -> Path:
    from utils.paths import get_videos
    return get_videos()


def _resolve_path(raw: str) -> Path:
    shortcuts: dict[str, Path] = {
        "desktop":   _get_desktop(),
        "downloads": _get_downloads(),
        "documents": _get_documents(),
        "pictures":  _get_pictures(),
        "music":     _get_music(),
        "videos":    _get_videos(),
        "home":      Path.home(),
        "tmp":       _PROJECT_ROOT / "tmp",
        "jarvis_tmp": _PROJECT_ROOT / "tmp",
        "jarvis temp": _PROJECT_ROOT / "tmp",
    }
    cleaned = str(raw).strip().strip('"').strip("'")
    lower = cleaned.lower()
    if lower in shortcuts:
        return shortcuts[lower]
    # Models commonly return shortcut paths such as "documents/Arduino/Blink".
    # Resolve the shortcut prefix too, otherwise pathlib treats it as relative to
    # JARVIS' installation directory and nested folders appear to be missing.
    normalized = cleaned.replace("\\", "/")
    prefix, separator, remainder = normalized.partition("/")
    if separator and prefix.casefold() in shortcuts:
        return shortcuts[prefix.casefold()] / Path(remainder)
    return Path(cleaned).expanduser()


def _resolve_named_target(path: str, name: str) -> Path:
    """Avoid duplicating a filename when models provide it in both fields."""
    base = _resolve_path(path)
    clean_name = str(name or "").strip().strip('"').strip("'")
    if not clean_name:
        return base
    if base.name.casefold() == Path(clean_name).name.casefold():
        return base
    return base / clean_name

def _format_size(b: int) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} TB"

def _safe_trash(target: Path) -> str:

    if not _SEND2TRASH:
        return (
            "send2trash is not installed. "
            "Run: pip install send2trash — "
            "Permanent deletion is disabled for safety."
        )
    send2trash.send2trash(str(target))
    return f"Moved to Trash: {target.name}"


def list_files(path: str = "desktop", show_hidden: bool = False) -> str:
    try:
        target = _resolve_path(path)
        if not _is_safe_path(target):
            return f"Access denied: {target}"
        if not target.exists():
            return f"Path not found: {target}"
        if not target.is_dir():
            return f"Not a directory: {target}"

        items = []
        for item in sorted(target.iterdir()):
            if not _is_safe_path(item):
                continue
            if not show_hidden and item.name.startswith("."):
                continue
            if item.is_dir():
                items.append(f"📁 {item.name}/")
            else:
                size = _format_size(item.stat().st_size)
                items.append(f"📄 {item.name} ({size})")

        if not items:
            return f"Directory is empty: {target.name}/"

        return f"Contents of {target.name}/ ({len(items)} items):\n" + "\n".join(items)

    except PermissionError:
        return f"Permission denied: {path}"
    except Exception as e:
        return f"Error listing files: {e}"


def create_file(path: str, name: str = "", content: str = "") -> str:
    try:
        target = _resolve_named_target(path, name)
        if not _is_safe_path(target):
            return f"Access denied: {target}"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"Local file created and verified: {target.resolve()}"
    except Exception as e:
        return f"Could not create file: {e}"


def create_folder(path: str, name: str = "") -> str:
    try:
        target = _resolve_named_target(path, name)
        if not _is_safe_path(target):
            return f"Access denied: {target}"
        target.mkdir(parents=True, exist_ok=True)
        return f"Local folder created and verified: {target.resolve()}"
    except Exception as e:
        return f"Could not create folder: {e}"


def delete_file(path: str, name: str = "") -> str:
    try:
        base   = _resolve_path(path)
        target = (base / name) if name else base
        if not _is_safe_path(target):
            return f"Access denied: {target}"
        if not target.exists():
            return f"Not found: {target.name}"

        # Güvenli dizin kontrolü — kritik kullanıcı klasörlerini koru
        protected = {
            _get_desktop(), _get_downloads(), _get_documents(),
            _get_pictures(), _get_music(), _get_videos(), Path.home()
        }
        if target.resolve() in {p.resolve() for p in protected}:
            return f"Protected directory, cannot delete: {target.name}"

        return _safe_trash(target)

    except PermissionError:
        return f"Permission denied: {path}"
    except Exception as e:
        return f"Could not delete: {e}"


def move_file(path: str, name: str = "", destination: str = "") -> str:
    try:
        base   = _resolve_path(path)
        src    = (base / name) if name else base
        dst    = _resolve_path(destination) if destination else None

        if not src.exists():
            return f"Source not found: {src.name}"
        if dst is None:
            return "No destination specified."
        if not _is_safe_path(src):
            return f"Access denied (source): {src}"
        if not _is_safe_path(dst):
            return f"Access denied (destination): {dst}"

        if dst.is_dir():
            dst = dst / src.name

        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        return f"Moved: {src.name} → {dst.parent.name}/"

    except Exception as e:
        return f"Could not move: {e}"


def copy_file(path: str, name: str = "", destination: str = "") -> str:
    try:
        base = _resolve_path(path)
        src  = (base / name) if name else base
        dst  = _resolve_path(destination) if destination else None

        if not src.exists():
            return f"Source not found: {src.name}"
        if dst is None:
            return "No destination specified."
        if not _is_safe_path(src):
            return f"Access denied (source): {src}"
        if not _is_safe_path(dst):
            return f"Access denied (destination): {dst}"

        if dst.is_dir():
            dst = dst / src.name

        dst.parent.mkdir(parents=True, exist_ok=True)

        if src.is_dir():
            shutil.copytree(str(src), str(dst))
        else:
            shutil.copy2(str(src), str(dst))

        return f"Copied: {src.name} → {dst.parent.name}/"

    except Exception as e:
        return f"Could not copy: {e}"


def _rejected_result(message: str) -> ToolResult:
    return ToolResult(
        False,
        message,
        error_code="precondition_failed",
        execution_status=ExecutionStatus.REJECTED,
        effect_status=EffectStatus.NOT_APPLIED,
        verification_status=VerificationStatus.NOT_REQUESTED,
    )


def _operation_failed_result(
    message: str,
    destination: Path | None = None,
) -> ToolResult:
    observed = bool(destination and destination.exists())
    return ToolResult(
        False,
        message,
        error_code="operation_failed",
        execution_status=ExecutionStatus.FAILED,
        effect_status=EffectStatus.PARTIAL if observed else EffectStatus.UNKNOWN,
        verification_status=VerificationStatus.UNKNOWN,
        rollback_status=(
            RollbackStatus.AVAILABLE if observed else RollbackStatus.UNKNOWN
        ),
    )


def _verification_failed_result(
    operation: str,
    destination: Path,
    *,
    source: Path | None = None,
) -> ToolResult:
    observed = destination.exists()
    rollback = (
        {"action": "trash", "path": str(destination.resolve())}
        if operation in {"create_file", "copy"}
        else {
            "action": "move",
            "source": str(destination.resolve()),
            "destination": str(source.resolve()) if source else "",
        }
    )
    return ToolResult(
        False,
        f"{operation} completed but destination verification failed.",
        data={
            "operation": operation,
            "resolved_path": str(destination.resolve()),
            "rollback": rollback,
        },
        error_code="verification_failed",
        execution_status=ExecutionStatus.SUCCEEDED,
        effect_status=EffectStatus.APPLIED if observed else EffectStatus.UNKNOWN,
        verification_status=VerificationStatus.FAILED,
        rollback_status=(
            RollbackStatus.AVAILABLE if observed else RollbackStatus.UNKNOWN
        ),
    )


def _verified_result(
    operation: str,
    evidence: FileEvidence,
    *,
    source: Path | None = None,
    source_absent: bool = False,
) -> ToolResult:
    destination = Path(evidence.resolved_path)
    if operation in {"create_file", "copy"}:
        rollback = {"action": "trash", "path": evidence.resolved_path}
    else:
        rollback = {
            "action": "move",
            "source": evidence.resolved_path,
            "destination": str(source.resolve()) if source else "",
        }
    tokens = evidence.tokens + (
        (f"source_absent:{str(source_absent).lower()}",)
        if operation == "move"
        else ()
    )
    return ToolResult(
        True,
        f"{operation} applied and verified: {destination}",
        data={
            "operation": operation,
            "resolved_path": evidence.resolved_path,
            "source_path": str(source.resolve()) if source else None,
            "size": evidence.size,
            "sha256": evidence.sha256,
            "rollback": rollback,
        },
        execution_status=ExecutionStatus.SUCCEEDED,
        effect_status=EffectStatus.APPLIED,
        verification_status=VerificationStatus.VERIFIED,
        rollback_status=RollbackStatus.AVAILABLE,
        evidence=tokens,
    )


def _verified_create_file(path: str, name: str, content: str) -> ToolResult:
    target = _resolve_named_target(path, name)
    if not _is_safe_path(target):
        return _rejected_result(f"Access denied: {target}")
    if target.exists():
        return _rejected_result(f"Destination already exists: {target}")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    except Exception as exc:
        return _operation_failed_result(
            f"Could not create file: {exc}",
            target,
        )
    evidence = capture_file_evidence(target)
    expected = hashlib.sha256(content.encode("utf-8")).hexdigest()
    if evidence is None or evidence.sha256 != expected:
        return _verification_failed_result("create_file", target)
    return _verified_result("create_file", evidence)


def _verified_copy_file(
    source_path: str,
    name: str,
    destination_path: str,
) -> ToolResult | str:
    base = _resolve_path(source_path)
    source = (base / name) if name else base
    if source.is_dir():
        return copy_file(source_path, name=name, destination=destination_path)
    destination = _resolve_path(destination_path) if destination_path else None
    if not source.exists() or not source.is_file():
        return _rejected_result(f"Source file not found: {source}")
    if destination is None:
        return _rejected_result("No destination specified.")
    if destination.is_dir():
        destination = destination / source.name
    if not _is_safe_path(source) or not _is_safe_path(destination):
        return _rejected_result("Access denied for source or destination.")
    if destination.exists():
        return _rejected_result(f"Destination already exists: {destination}")
    source_evidence = capture_file_evidence(source)
    if source_evidence is None:
        return _rejected_result(f"Could not inspect source file: {source}")
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(source), str(destination))
    except Exception as exc:
        return _operation_failed_result(f"Could not copy: {exc}", destination)
    destination_evidence = capture_file_evidence(destination)
    if not source_evidence.matches(destination_evidence):
        return _verification_failed_result(
            "copy",
            destination,
            source=source,
        )
    return _verified_result("copy", destination_evidence, source=source)


def _verified_move_file(
    source_path: str,
    name: str,
    destination_path: str,
) -> ToolResult | str:
    base = _resolve_path(source_path)
    source = (base / name) if name else base
    if source.is_dir():
        return move_file(source_path, name=name, destination=destination_path)
    destination = _resolve_path(destination_path) if destination_path else None
    if not source.exists() or not source.is_file():
        return _rejected_result(f"Source file not found: {source}")
    if destination is None:
        return _rejected_result("No destination specified.")
    if destination.is_dir():
        destination = destination / source.name
    if not _is_safe_path(source) or not _is_safe_path(destination):
        return _rejected_result("Access denied for source or destination.")
    if destination.exists():
        return _rejected_result(f"Destination already exists: {destination}")
    source_evidence = capture_file_evidence(source)
    if source_evidence is None:
        return _rejected_result(f"Could not inspect source file: {source}")
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))
    except Exception as exc:
        return _operation_failed_result(f"Could not move: {exc}", destination)
    destination_evidence = capture_file_evidence(destination)
    source_absent = not source.exists()
    if (
        not source_evidence.matches(destination_evidence)
        or not source_absent
    ):
        return _verification_failed_result(
            "move",
            destination,
            source=source,
        )
    return _verified_result(
        "move",
        destination_evidence,
        source=source,
        source_absent=True,
    )


def rename_file(path: str, name: str = "", new_name: str = "") -> str:
    try:
        base     = _resolve_path(path)
        target   = (base / name) if name else base
        if not _is_safe_path(target):
            return f"Access denied: {target}"
        if not target.exists():
            return f"Not found: {target.name}"
        if not new_name:
            return "No new name provided."

        new_path = target.parent / new_name
        if new_path.exists():
            return f"A file named '{new_name}' already exists here."

        target.rename(new_path)
        return f"Renamed: {target.name} → {new_name}"

    except Exception as e:
        return f"Could not rename: {e}"


def read_file(path: str, name: str = "", max_chars: int = 4000) -> str:
    try:
        base   = _resolve_path(path)
        target = (base / name) if name else base
        if not _is_safe_path(target):
            return f"Access denied: {target}"
        if not target.exists():
            return f"File not found: {target.name}"
        if target.is_dir():
            return inspect_folder(str(target), max_chars=max_chars)
        if not target.is_file():
            return f"Not a file: {target.name}"

        content = target.read_text(encoding="utf-8", errors="ignore")
        if len(content) > max_chars:
            content = content[:max_chars] + f"\n\n[Truncated — {len(content)} total chars]"
        return content

    except Exception as e:
        return f"Could not read file: {e}"


_CODE_SUFFIXES = {
    ".ino", ".pde", ".h", ".hpp", ".hh", ".c", ".cpp", ".cc", ".cxx",
    ".py", ".js", ".ts", ".java", ".cs", ".go", ".rs", ".sh", ".html",
    ".css", ".json", ".yaml", ".yml", ".toml", ".txt", ".md",
}


def inspect_folder(path: str, max_files: int = 30, max_chars: int = 12000) -> str:
    """Return a bounded project tree plus readable source contents.

    This lets the model inspect an Arduino sketch or other small code project when
    the user supplies its folder rather than the exact source-file path.
    """
    try:
        root = _resolve_path(path)
        if not _is_safe_path(root):
            return f"Access denied: {root}"
        if not root.exists():
            return f"Path not found: {root}"
        if not root.is_dir():
            return read_file(str(root), max_chars=max_chars)

        files = []
        for item in _safe_walk_files(root, max_dirs=500):
            if item.is_file():
                files.append(item)
                if len(files) >= max_files:
                    break

        if not files:
            return f"Directory is empty or has no accessible files: {root}"

        tree = [str(item.relative_to(root)) for item in files]
        sections = [f"Project folder: {root}", "Files:", *[f"- {entry}" for entry in tree]]
        remaining = max_chars - len("\n".join(sections))
        readable = [item for item in files if item.suffix.casefold() in _CODE_SUFFIXES]

        for item in readable:
            if remaining <= 100:
                break
            try:
                content = item.read_text(encoding="utf-8", errors="ignore")
            except OSError as exc:
                content = f"[Could not read: {exc}]"
            header = f"\n--- {item.relative_to(root)} ---\n"
            excerpt = content[:max(0, remaining - len(header))]
            sections.append(header + excerpt)
            remaining -= len(header) + len(excerpt)

        if len(files) >= max_files:
            sections.append(f"\n[Limited to the first {max_files} accessible files]")
        if readable and remaining <= 100:
            sections.append(f"\n[Source contents truncated at {max_chars} characters]")
        return "\n".join(sections)
    except Exception as e:
        return f"Could not inspect folder: {e}"


def open_file(path: str, name: str = "") -> str:
    """Open a user file with its default application."""
    try:
        base = _resolve_path(path)
        target = (base / name) if name else base
        if not _is_safe_path(target):
            return f"Access denied: {target}"
        if not target.exists():
            return f"File not found: {target.name}"
        if _OS == "Windows":
            os.startfile(str(target))
        elif _OS == "Darwin":
            subprocess.run(["open", str(target)], check=True)
        else:
            subprocess.run(["xdg-open", str(target)], check=True)
        return f"Opened: {target.name}"
    except Exception as e:
        return f"Could not open file: {e}"


def write_file(path: str, name: str = "", content: str = "",
               append: bool = False) -> str:
    try:
        base   = _resolve_path(path)
        target = (base / name) if name else base
        if not _is_safe_path(target):
            return f"Access denied: {target}"
        target.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if append else "w"
        with open(target, mode, encoding="utf-8") as f:
            f.write(content)
        action = "Appended to" if append else "Written to"
        return f"{action}: {target.name}"
    except Exception as e:
        return f"Could not write file: {e}"


def _safe_walk_files(root: Path, max_dirs: int = 500):
    visited = 0
    for current, directories, filenames in os.walk(root):
        current_path = Path(current)
        directories[:] = [d for d in directories if _is_safe_path(current_path / d)]
        visited += len(directories)
        if visited > max_dirs:
            directories[:] = []
        for filename in filenames:
            item = current_path / filename
            if _is_safe_path(item):
                yield item


def find_files(name: str = "", extension: str = "",
               path: str = "home", max_results: int = 20) -> str:
    try:
        search_path = _resolve_path(path)
        if not _is_safe_path(search_path):
            return f"Access denied: {search_path}"
        if not search_path.exists():
            return f"Search path not found: {path}"

        results    = []
        dir_count  = 0
        max_dirs   = 500  # performans + güvenlik limiti

        for item in _safe_walk_files(search_path, max_dirs=max_dirs):
            if item.is_dir():
                dir_count += 1
                if dir_count > max_dirs:
                    break
                continue
            if not item.is_file():
                continue
            if extension and item.suffix.lower() != extension.lower():
                continue
            if name and name.lower() not in item.name.lower():
                continue
            size = _format_size(item.stat().st_size)
            results.append(f"📄 {item.name} ({size}) — {item.parent}")
            if len(results) >= max_results:
                break

        if not results:
            query = name or extension or "files"
            return f"No {query} found in {search_path.name}/"

        return f"Found {len(results)} file(s):\n" + "\n".join(results)

    except Exception as e:
        return f"Search error: {e}"


def get_largest_files(path: str = "downloads", count: int = 10) -> str:
    count = min(count, 50)  # maksimum 50
    try:
        search_path = _resolve_path(path)
        if not _is_safe_path(search_path):
            return f"Access denied: {search_path}"
        if not search_path.exists():
            return f"Path not found: {path}"

        files = []
        for item in _safe_walk_files(search_path):
            if item.is_file():
                try:
                    files.append((item.stat().st_size, item))
                except Exception:
                    continue

        files.sort(reverse=True)
        top = files[:count]

        if not top:
            return "No files found."

        lines = [f"Top {len(top)} largest files in {search_path.name}/:"]
        for size, f in top:
            lines.append(f"  {_format_size(size):>10}  {f.name}  ({f.parent})")

        return "\n".join(lines)

    except Exception as e:
        return f"Error: {e}"


def get_disk_usage(path: str = "home") -> str:
    try:
        target = _resolve_path(path)
        usage  = shutil.disk_usage(target)
        pct    = usage.used / usage.total * 100
        return (
            f"Disk usage ({target}):\n"
            f"  Total : {_format_size(usage.total)}\n"
            f"  Used  : {_format_size(usage.used)} ({pct:.1f}%)\n"
            f"  Free  : {_format_size(usage.free)}"
        )
    except Exception as e:
        return f"Could not get disk usage: {e}"


def organize_desktop() -> str:
    type_map = {
        "Images":    {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg", ".ico", ".heic"},
        "Documents": {".pdf", ".doc", ".docx", ".txt", ".xls", ".xlsx",
                      ".ppt", ".pptx", ".csv", ".odt", ".ods", ".odp"},
        "Videos":    {".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm", ".m4v"},
        "Music":     {".mp3", ".wav", ".flac", ".aac", ".ogg", ".wma", ".m4a"},
        "Archives":  {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"},
        "Code":      {".py", ".js", ".ts", ".html", ".css", ".json", ".xml",
                      ".cpp", ".java", ".cs", ".go", ".rs", ".sh"},
    }

    desktop = _get_desktop()
    moved, skipped = [], []

    try:
        for item in desktop.iterdir():
            # Klasörlere, gizli dosyalara ve organize klasörlerine dokunma
            if item.is_dir() or item.name.startswith("."):
                continue
            if item.name in {k for k in type_map}:
                continue

            ext        = item.suffix.lower()
            target_dir = desktop / "Others"
            for folder, exts in type_map.items():
                if ext in exts:
                    target_dir = desktop / folder
                    break

            target_dir.mkdir(exist_ok=True)
            new_path = target_dir / item.name

            if new_path.exists():
                skipped.append(item.name)
                continue

            shutil.move(str(item), str(new_path))
            moved.append(f"{item.name} → {target_dir.name}/")

        result = f"Desktop organized: {len(moved)} files moved."
        if moved:
            preview = moved[:8]
            result += "\n" + "\n".join(preview)
            if len(moved) > 8:
                result += f"\n... and {len(moved) - 8} more."
        if skipped:
            result += f"\n{len(skipped)} file(s) skipped (name conflict)."
        return result

    except Exception as e:
        return f"Could not organize desktop: {e}"


def get_file_info(path: str, name: str = "") -> str:
    try:
        base   = _resolve_path(path)
        target = (base / name) if name else base
        if not _is_safe_path(target):
            return f"Access denied: {target}"
        if not target.exists():
            return f"Not found: {target.name}"

        stat = target.stat()
        info = {
            "Name":      target.name,
            "Type":      "Folder" if target.is_dir() else "File",
            "Size":      _format_size(stat.st_size),
            "Location":  str(target.parent),
            "Created":   datetime.fromtimestamp(stat.st_ctime).strftime("%Y-%m-%d %H:%M"),
            "Modified":  datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
            "Extension": target.suffix or "—",
        }
        return "\n".join(f"  {k}: {v}" for k, v in info.items())

    except Exception as e:
        return f"Could not get file info: {e}"

def clear_jarvis_temp() -> str:
    """Empty Jarvis' temporary folder without deleting the folder itself."""
    from utils.temp_files import jarvis_temp_root

    root = jarvis_temp_root()
    root.mkdir(parents=True, exist_ok=True)
    entries = list(root.iterdir())
    if not entries:
        return f"Jarvis temporary folder is already empty: {root}"
    if not _SEND2TRASH:
        return "send2trash is required to empty temporary files safely."
    moved = 0
    for entry in entries:
        try:
            send2trash.send2trash(str(entry))
            moved += 1
        except OSError:
            continue
    return f"Emptied Jarvis temporary folder: {moved} item(s) moved to Trash. Folder preserved: {root}"


def file_controller(
    parameters: dict = None,
    response=None,
    player=None,
    session_memory=None,
) -> str | ToolResult:
    params = parameters or {}
    action = params.get("action", "").lower().strip().replace("-", "_").replace(" ", "_")
    action = {
        "mkdir": "create_folder",
        "new_folder": "create_folder",
        "make_folder": "create_folder",
        "make_directory": "create_folder",
        "create_directory": "create_folder",
        "new_directory": "create_folder",
        "new_file": "create_file",
        "make_file": "create_file",
        "edit": "write",
        "edit_file": "write",
        "open_file": "open",
        "browse": "inspect",
        "inspect_folder": "inspect",
        "read_folder": "inspect",
    }.get(action, action)
    path   = params.get("path", "desktop")
    name   = (
        params.get("name")
        or params.get("folder_name")
        or params.get("file_name")
        or (params.get("new_name") if action in {"create_folder", "create_file"} else "")
        or ""
    )

    if player:
        player.write_log(f"[file] {action} {name or path}")

    try:
        if action == "list":
            return list_files(path)

        elif action == "create_file":
            return _verified_create_file(
                path,
                name=name,
                content=params.get("content", ""),
            )

        elif action == "create_folder":
            return create_folder(path, name=name)

        elif action == "delete":
            return delete_file(path, name=name)

        elif action == "move":
            return _verified_move_file(
                path,
                name=name,
                destination_path=params.get("destination", ""),
            )

        elif action == "copy":
            return _verified_copy_file(
                path,
                name=name,
                destination_path=params.get("destination", ""),
            )

        elif action == "rename":
            return rename_file(path, name=name, new_name=params.get("new_name", ""))

        elif action == "read":
            return read_file(
                path,
                name=name,
                max_chars=min(max(int(params.get("max_chars", 4000)), 1000), 50000),
            )

        elif action == "inspect":
            target = str(_resolve_path(path) / name) if name else path
            return inspect_folder(
                target,
                max_files=min(max(int(params.get("max_files", 30)), 1), 100),
                max_chars=min(max(int(params.get("max_chars", 12000)), 1000), 50000),
            )

        elif action == "open":
            return open_file(path, name=name)

        elif action == "write":
            return write_file(
                path, name=name,
                content=params.get("content", ""),
                append=params.get("append", False)
            )

        elif action == "find":
            return find_files(
                name=name or params.get("name", ""),
                extension=params.get("extension", ""),
                path=path,
                max_results=min(int(params.get("max_results", 20)), 50),
            )

        elif action == "largest":
            return get_largest_files(
                path=path,
                count=int(params.get("count", 10)),
            )

        elif action == "disk_usage":
            return get_disk_usage(path)

        elif action == "organize_desktop":
            return organize_desktop()

        elif action == "info":
            return get_file_info(path, name=name)

        elif action == "clear_jarvis_temp":
            return clear_jarvis_temp()

        else:
            return f"Unknown action: '{action}'"

    except Exception as e:
        return f"File controller error ({action}): {e}"
