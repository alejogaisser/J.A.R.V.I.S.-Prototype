"""Crash reporting that is safe to call from any JARVIS thread."""

from __future__ import annotations

import re
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path
from types import TracebackType

_SECRET_PATTERNS = (
    re.compile(r"AIza[0-9A-Za-z_-]{20,}"),
    re.compile(
        r"\b(?:"
        r"gh[pousr]_[0-9A-Za-z]{36,255}|"
        r"github_pat_[0-9A-Za-z_]{20,255}|"
        r"sk-(?:(?:proj|svcacct)-)?[0-9A-Za-z_-]{20,}|"
        r"(?:AKIA|ASIA)[0-9A-Z]{16}|"
        r"xox[baprs]-[0-9A-Za-z-]{20,}"
        r")\b"
    ),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(
        r"(?i)\b(api[_ -]?key|access[_ -]?token|authorization|secret|token)"
        r"(\s*[:=]\s*)([^\s,;]+)"
    ),
    re.compile(r"(?i)([?&](?:key|token|access_token)=)[^&\s]+"),
)


def redact_diagnostic_text(text: str) -> str:
    """Remove common credential shapes before a traceback reaches disk."""
    redacted = _SECRET_PATTERNS[0].sub("[REDACTED_API_KEY]", text)
    redacted = _SECRET_PATTERNS[1].sub("[REDACTED_CREDENTIAL]", redacted)
    redacted = _SECRET_PATTERNS[2].sub("[REDACTED_PRIVATE_KEY]", redacted)
    redacted = _SECRET_PATTERNS[3].sub(r"\1\2[REDACTED]", redacted)
    return _SECRET_PATTERNS[4].sub(r"\1[REDACTED]", redacted)


class CrashReporter:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._installed = False
        self._previous_sys_hook = sys.excepthook
        self._previous_thread_hook = threading.excepthook

    def record(
        self,
        context: str,
        exc_type: type[BaseException],
        exc_value: BaseException,
        exc_traceback: TracebackType | None,
    ) -> None:
        formatted = "".join(traceback.format_exception(
            exc_type, exc_value, exc_traceback
        ))
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        entry = redact_diagnostic_text(
            f"\n[{timestamp}] Unhandled exception in {context}\n{formatted}"
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(entry)

    def record_exception(self, context: str, exc: BaseException) -> None:
        self.record(context, type(exc), exc, exc.__traceback__)

    def install(self) -> None:
        if self._installed:
            return
        self._installed = True

        def sys_hook(
            exc_type: type[BaseException],
            exc_value: BaseException,
            exc_traceback: TracebackType | None,
        ) -> None:
            self.record("main thread", exc_type, exc_value, exc_traceback)
            self._previous_sys_hook(exc_type, exc_value, exc_traceback)

        def thread_hook(args: threading.ExceptHookArgs) -> None:
            name = args.thread.name if args.thread else "background thread"
            if args.exc_value is not None:
                self.record(name, args.exc_type, args.exc_value, args.exc_traceback)
            self._previous_thread_hook(args)

        sys.excepthook = sys_hook
        threading.excepthook = thread_hook
