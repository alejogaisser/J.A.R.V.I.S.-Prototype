"""Side-effect-free evidence capture for the file-controller pilot."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class FileEvidence:
    resolved_path: str
    size: int
    sha256: str

    @property
    def tokens(self) -> tuple[str, ...]:
        return (
            f"path:{self.resolved_path}",
            f"size:{self.size}",
            f"sha256:{self.sha256}",
        )

    def matches(self, other: "FileEvidence | None") -> bool:
        return (
            other is not None
            and self.size == other.size
            and self.sha256 == other.sha256
        )


def capture_file_evidence(path: str | Path) -> FileEvidence | None:
    """Capture a regular file after resolving its final filesystem location."""
    try:
        target = Path(path).resolve(strict=True)
        if not target.is_file():
            return None
        digest = hashlib.sha256()
        with target.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return FileEvidence(
            resolved_path=str(target),
            size=target.stat().st_size,
            sha256=digest.hexdigest(),
        )
    except OSError:
        return None
