from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

CONFIG_FILE = Path(__file__).resolve().parents[1] / "config" / "obsidian.json"
EXCLUDED_DIRS = {".obsidian", ".git", ".trash", ".jarvis-backups"}


class ObsidianError(RuntimeError):
    pass


def _settings() -> tuple[Path, str]:
    if not CONFIG_FILE.exists():
        raise ObsidianError("Obsidian config is missing: config/obsidian.json")
    data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    root = Path(str(data.get("vault_path", ""))).expanduser().resolve()
    if not root.is_dir() or not (root / ".obsidian").is_dir():
        raise ObsidianError(f"Configured path is not an Obsidian vault: {root}")
    return root, str(data.get("vault_name") or root.name)


def _note_path(relative: str, *, may_create: bool = False) -> tuple[Path, Path]:
    configured_root, _ = _settings()
    root = configured_root.resolve(strict=True)
    clean = str(relative or "").strip().replace("\\", "/")
    if not clean:
        raise ObsidianError("A note path is required.")
    candidate = Path(clean)
    if candidate.anchor or candidate.is_absolute():
        raise ObsidianError("The note must stay inside the configured vault.")
    if not clean.lower().endswith(".md"):
        clean += ".md"
    target = (root / clean).resolve(strict=False)
    try:
        relative_parts = target.relative_to(root).parts
    except ValueError:
        raise ObsidianError(
            "The note must stay inside the configured vault."
        ) from None
    if any(part.lower() in EXCLUDED_DIRS or part.startswith(".") for part in relative_parts):
        raise ObsidianError("Hidden and internal Obsidian folders are protected.")
    if not may_create and not target.is_file():
        raise ObsidianError(f"Note not found: {clean}")
    return root, target


def _notes(root: Path):
    for path in root.rglob("*.md"):
        relative = path.relative_to(root)
        if any(part.lower() in EXCLUDED_DIRS or part.startswith(".") for part in relative.parts):
            continue
        yield path


def _search(query: str, limit: int) -> list[dict]:
    root, _ = _settings()
    terms = [term.casefold() for term in str(query).split() if term]
    results = []
    for path in _notes(root):
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        haystack = f"{path.stem}\n{content}".casefold()
        if terms and not all(term in haystack for term in terms):
            continue
        first_match = 0
        if terms:
            positions = [haystack.find(term) for term in terms if haystack.find(term) >= 0]
            first_match = min(positions) if positions else 0
        start = max(0, first_match - 120)
        snippet = " ".join(content[start:start + 360].split())
        results.append({
            "path": path.relative_to(root).as_posix(),
            "title": path.stem,
            "modified": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="minutes"),
            "snippet": snippet,
        })
        if len(results) >= max(1, min(limit, 30)):
            break
    return results


def _backup(root: Path, target: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    relative = target.relative_to(root)
    backup = (
        root
        / ".jarvis-backups"
        / relative.parent
        / f"{relative.stem}-{stamp}.md"
    ).resolve(strict=False)
    try:
        backup.relative_to(root)
    except ValueError as exc:
        raise ObsidianError("The backup must stay inside the configured vault.") from exc
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target, backup)
    return backup


def obsidian_connector(parameters: dict | None = None, player=None) -> str:
    args = dict(parameters or {})
    action = str(args.get("action", "status")).lower().strip()
    if player:
        player.write_log(f"[obsidian] {action}")
    try:
        configured_root, vault_name = _settings()
        root = configured_root.resolve(strict=True)
        if action == "status":
            return json.dumps({"connected": True, "vault": vault_name, "path": str(root)}, ensure_ascii=False)
        if action == "search":
            return json.dumps(_search(str(args.get("query", "")), int(args.get("limit", 10))), ensure_ascii=False)
        if action == "read":
            _, target = _note_path(str(args.get("path", "")))
            content = target.read_text(encoding="utf-8", errors="replace")
            limit = max(500, min(int(args.get("max_chars", 12000)), 30000))
            if len(content) > limit:
                content = content[:limit] + f"\n\n[Truncated: {len(content)} total characters]"
            return json.dumps({"path": target.relative_to(root).as_posix(), "content": content}, ensure_ascii=False)
        if action == "open":
            _, target = _note_path(str(args.get("path", "")))
            relative = target.relative_to(root).with_suffix("").as_posix()
            os.startfile(f"obsidian://open?vault={quote(vault_name)}&file={quote(relative)}")
            return f"Opened in Obsidian: {target.relative_to(root)}"
        if action in {"create", "write", "append"}:
            _, target = _note_path(str(args.get("path", "")), may_create=True)
            content = str(args.get("content", ""))
            existed = target.exists()
            backup = _backup(root, target) if existed else None
            target.parent.mkdir(parents=True, exist_ok=True)
            if action == "append":
                with target.open("a", encoding="utf-8") as stream:
                    if target.stat().st_size and content and not content.startswith("\n"):
                        stream.write("\n")
                    stream.write(content)
            else:
                target.write_text(content, encoding="utf-8")
            result = f"{'Updated' if existed else 'Created'} Obsidian note: {target.relative_to(root)}"
            if backup:
                result += f" (backup: {backup.relative_to(root)})"
            return result
        raise ObsidianError(f"Unknown Obsidian action: {action}")
    except Exception as exc:
        return f"Obsidian error ({action}): {exc}"
