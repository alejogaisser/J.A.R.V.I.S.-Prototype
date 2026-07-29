import asyncio
import sys
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import psutil

from actions.dev_agent import _build_project
from core.request_context import InputSource, RequestContext
from core.tools import (
    CancellationToken,
    EffectStatus,
    ExecutionStatus,
    RiskLevel,
    RollbackStatus,
    ToolCancelled,
    ToolDefinition,
    ToolExecutor,
    ToolRegistry,
    VerificationStatus,
)
from core.tools.process_runner import run_cancellable_process

SCHEMA = {"type": "OBJECT", "properties": {}}


class ToolCancellationTests(unittest.TestCase):
    def test_timeout_signals_cooperative_sync_handler_and_waits_for_cleanup(self):
        cleaned = threading.Event()

        def handler(_args, *, cancellation_token):
            try:
                cancellation_token.wait(2)
                cancellation_token.raise_if_cancelled(
                    effect_status=EffectStatus.NOT_APPLIED,
                    rollback_status=RollbackStatus.NOT_NEEDED,
                )
                return "unexpected completion"
            finally:
                cleaned.set()

        definition = ToolDefinition(
            "cooperative",
            "Cooperative",
            SCHEMA,
            handler=handler,
            timeout=0.02,
            cancellable=True,
        )

        result = asyncio.run(
            ToolExecutor(
                ToolRegistry([definition]),
                cancellation_grace=0.5,
            ).execute("cooperative", {})
        )

        self.assertTrue(cleaned.is_set())
        self.assertEqual(result.execution_status, ExecutionStatus.TIMED_OUT)
        self.assertEqual(result.effect_status, EffectStatus.NOT_APPLIED)
        self.assertEqual(
            result.verification_status,
            VerificationStatus.NOT_REQUESTED,
        )
        self.assertEqual(result.rollback_status, RollbackStatus.NOT_NEEDED)
        self.assertIn("cancellation_acknowledged", result.evidence)

    def test_explicit_cancel_by_request_id_returns_cancelled_result(self):
        started = threading.Event()

        def handler(_args, *, cancellation_token):
            started.set()
            cancellation_token.wait(2)
            cancellation_token.raise_if_cancelled(
                effect_status=EffectStatus.NOT_APPLIED,
                rollback_status=RollbackStatus.NOT_NEEDED,
            )
            return "unexpected completion"

        context = RequestContext.create(InputSource.LOCAL)
        executor = ToolExecutor(
            ToolRegistry([
                ToolDefinition(
                    "cooperative",
                    "Cooperative",
                    SCHEMA,
                    handler=handler,
                    timeout=2,
                    cancellable=True,
                )
            ]),
            cancellation_grace=0.5,
        )

        async def scenario():
            task = asyncio.create_task(
                executor.execute("cooperative", {}, context=context)
            )
            await asyncio.to_thread(started.wait, 1)
            self.assertTrue(executor.cancel(context.request_id))
            return await task

        result = asyncio.run(scenario())

        self.assertEqual(result.execution_status, ExecutionStatus.CANCELLED)
        self.assertEqual(result.effect_status, EffectStatus.NOT_APPLIED)
        self.assertEqual(result.request_id, context.request_id)
        self.assertFalse(executor.cancel(context.request_id))

    def test_uncooperative_timeout_keeps_effect_unknown(self):
        finished = threading.Event()

        def handler(_args):
            finished.wait(0.05)
            return "late result"

        definition = ToolDefinition(
            "legacy",
            "Legacy",
            SCHEMA,
            handler=handler,
            risk=RiskLevel.LOCAL_CHANGE,
            timeout=0.005,
            cancellable=True,
        )
        result = asyncio.run(
            ToolExecutor(
                ToolRegistry([definition]),
                cancellation_grace=0.005,
            ).execute("legacy", {})
        )
        finished.set()

        self.assertEqual(result.execution_status, ExecutionStatus.TIMED_OUT)
        self.assertEqual(result.effect_status, EffectStatus.UNKNOWN)
        self.assertIn("cancellation_unacknowledged", result.evidence)

    def test_process_runner_terminates_spawned_process_on_timeout(self):
        with TemporaryDirectory() as directory:
            pid_file = Path(directory) / "pid.txt"
            child_pid_file = Path(directory) / "child-pid.txt"

            def handler(_args, *, cancellation_token: CancellationToken):
                return run_cancellable_process(
                    [
                        sys.executable,
                        "-c",
                        (
                            "import os,sys,time,pathlib,subprocess;"
                            f"pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid()));"
                            "child=subprocess.Popen([sys.executable,'-c',"
                            "'import time;time.sleep(30)']);"
                            f"pathlib.Path({str(child_pid_file)!r}).write_text(str(child.pid));"
                            "time.sleep(30)"
                        ),
                    ],
                    cancellation_token=cancellation_token,
                    cancellation_effect=EffectStatus.PARTIAL,
                    cancellation_rollback=RollbackStatus.AVAILABLE,
                )

            definition = ToolDefinition(
                "process",
                "Process",
                SCHEMA,
                handler=handler,
                timeout=0.2,
                cancellable=True,
            )
            result = asyncio.run(
                ToolExecutor(
                    ToolRegistry([definition]),
                    cancellation_grace=2,
                ).execute("process", {})
            )

            pid = int(pid_file.read_text(encoding="utf-8"))
            child_pid = int(child_pid_file.read_text(encoding="utf-8"))
            self.assertFalse(psutil.pid_exists(pid))
            self.assertFalse(psutil.pid_exists(child_pid))
            self.assertEqual(result.execution_status, ExecutionStatus.TIMED_OUT)
            self.assertEqual(result.effect_status, EffectStatus.PARTIAL)
            self.assertEqual(result.rollback_status, RollbackStatus.AVAILABLE)
            self.assertIn("process_terminated", result.evidence)

    def test_process_runner_internal_timeout_terminates_process(self):
        with TemporaryDirectory() as directory:
            pid_file = Path(directory) / "pid.txt"
            token = CancellationToken()

            with self.assertRaises(TimeoutError):
                run_cancellable_process(
                    [
                        sys.executable,
                        "-c",
                        (
                            "import os,time,pathlib;"
                            f"pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid()));"
                            "time.sleep(30)"
                        ),
                    ],
                    cancellation_token=token,
                    timeout=0.2,
                )

            pid = int(pid_file.read_text(encoding="utf-8"))
            self.assertFalse(psutil.pid_exists(pid))

    def test_dev_agent_checks_cancellation_before_creating_project(self):
        token = CancellationToken()
        token.cancel("requested")

        with self.assertRaises(ToolCancelled) as raised:
            _build_project(
                "do not build",
                "python",
                "cancelled-project",
                1,
                cancellation_token=token,
            )

        self.assertEqual(
            raised.exception.effect_status,
            EffectStatus.NOT_APPLIED,
        )
        self.assertEqual(
            raised.exception.rollback_status,
            RollbackStatus.NOT_NEEDED,
        )


class CancellationTokenTests(unittest.TestCase):
    def test_callbacks_run_once_and_late_registration_runs_immediately(self):
        token = CancellationToken()
        calls = []

        token.add_callback(lambda reason: calls.append(reason))
        self.assertTrue(token.cancel("stop"))
        self.assertFalse(token.cancel("again"))
        token.add_callback(lambda reason: calls.append(reason))

        self.assertEqual(calls, ["stop", "stop"])
        self.assertTrue(token.cancelled)
        self.assertEqual(token.reason, "stop")

    def test_raise_if_cancelled_carries_effect_metadata(self):
        token = CancellationToken()
        token.cancel("timeout")

        with self.assertRaises(ToolCancelled) as raised:
            token.raise_if_cancelled(
                effect_status=EffectStatus.PARTIAL,
                rollback_status=RollbackStatus.AVAILABLE,
                evidence=("checkpoint:write",),
            )

        self.assertEqual(raised.exception.effect_status, EffectStatus.PARTIAL)
        self.assertEqual(
            raised.exception.rollback_status,
            RollbackStatus.AVAILABLE,
        )
        self.assertEqual(raised.exception.evidence, ("checkpoint:write",))


if __name__ == "__main__":
    unittest.main()
