"""Cancellable subprocess execution with bounded process-tree cleanup."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Sequence

import psutil

from .cancellation import CancellationToken, ToolCancelled
from .definitions import EffectStatus, RollbackStatus


def terminate_process_tree(
    process: subprocess.Popen,
    *,
    grace_seconds: float = 0.5,
) -> None:
    """Terminate only the process tree rooted at the child created by us."""
    if process.poll() is not None:
        return
    try:
        parent = psutil.Process(process.pid)
        targets = parent.children(recursive=True)
        targets.append(parent)
        for target in reversed(targets):
            try:
                target.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        _gone, alive = psutil.wait_procs(targets, timeout=grace_seconds)
        for target in alive:
            try:
                target.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        psutil.wait_procs(alive, timeout=grace_seconds)
    except psutil.NoSuchProcess:
        pass
    finally:
        try:
            process.wait(timeout=grace_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=grace_seconds)


def run_cancellable_process(
    args: Sequence[str],
    *,
    cancellation_token: CancellationToken,
    timeout: float | None = None,
    cwd: str | Path | None = None,
    text: bool = True,
    encoding: str = "utf-8",
    errors: str = "replace",
    cancellation_effect: EffectStatus = EffectStatus.UNKNOWN,
    cancellation_rollback: RollbackStatus = RollbackStatus.UNKNOWN,
) -> subprocess.CompletedProcess:
    """Run a child, polling cancellation and always reaping it before return."""
    if cancellation_token.cancelled:
        cancellation_token.raise_if_cancelled(
            effect_status=EffectStatus.NOT_APPLIED,
            rollback_status=RollbackStatus.NOT_NEEDED,
        )

    process = subprocess.Popen(
        list(args),
        cwd=str(cwd) if cwd is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=text,
        encoding=encoding if text else None,
        errors=errors if text else None,
    )
    started_at = time.monotonic()
    while True:
        if cancellation_token.cancelled:
            terminate_process_tree(process)
            raise ToolCancelled(
                f"Process terminated: {cancellation_token.reason or 'cancelled'}.",
                effect_status=cancellation_effect,
                rollback_status=cancellation_rollback,
                evidence=("process_terminated", f"pid:{process.pid}"),
            )
        elapsed = time.monotonic() - started_at
        if timeout is not None and elapsed >= timeout:
            terminate_process_tree(process)
            raise TimeoutError(
                f"Process timed out after {timeout:g} seconds and was terminated."
            )
        interval = 0.05
        if timeout is not None:
            interval = max(0.001, min(interval, timeout - elapsed))
        try:
            stdout, stderr = process.communicate(timeout=interval)
            return subprocess.CompletedProcess(
                list(args),
                process.returncode,
                stdout,
                stderr,
            )
        except subprocess.TimeoutExpired:
            continue
