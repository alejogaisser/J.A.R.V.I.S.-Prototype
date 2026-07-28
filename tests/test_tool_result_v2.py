import asyncio
import json
import unittest

from core.request_context import InputSource, RequestContext
from core.tools import (
    EffectStatus,
    ExecutionStatus,
    RiskLevel,
    RollbackStatus,
    ToolDefinition,
    ToolExecutor,
    ToolRegistry,
    ToolResult,
    VerificationStatus,
    normalize_tool_output,
)


SCHEMA = {"type": "OBJECT", "properties": {}}


class ToolResultV2Tests(unittest.TestCase):
    def test_v2_round_trip_preserves_structured_states(self):
        result = ToolResult(
            True,
            "created",
            data={"path": "artifact.txt"},
            request_id="request-1",
            execution_status=ExecutionStatus.SUCCEEDED,
            effect_status=EffectStatus.APPLIED,
            verification_status=VerificationStatus.VERIFIED,
            rollback_status=RollbackStatus.AVAILABLE,
            duration_ms=12.5,
            evidence=("artifact_exists",),
        )

        payload = result.to_dict()
        json.dumps(payload)
        restored = ToolResult.from_dict(payload)

        self.assertEqual(payload["schema_version"], 2)
        self.assertEqual(payload["execution_status"], "succeeded")
        self.assertEqual(payload["effect_status"], "applied")
        self.assertEqual(payload["verification_status"], "verified")
        self.assertEqual(payload["rollback_status"], "available")
        self.assertEqual(restored, result)

    def test_malformed_serialized_result_is_rejected(self):
        with self.assertRaises(TypeError):
            ToolResult.from_dict(
                {
                    "schema_version": 2,
                    "success": "yes",
                    "message": "invalid",
                }
            )

    def test_negative_duration_is_rejected(self):
        with self.assertRaises(ValueError):
            ToolResult(True, "ok", duration_ms=-0.1)

    def test_conflicting_success_and_execution_status_is_rejected(self):
        with self.assertRaises(ValueError):
            ToolResult(
                True,
                "not actually successful",
                execution_status=ExecutionStatus.FAILED,
            )

    def test_read_only_legacy_success_has_no_effect(self):
        result = normalize_tool_output(
            "status",
            "ok",
            "Done.",
            risk=RiskLevel.READ_ONLY,
        )

        self.assertEqual(result.execution_status, ExecutionStatus.SUCCEEDED)
        self.assertEqual(result.effect_status, EffectStatus.NONE)
        self.assertEqual(
            result.verification_status,
            VerificationStatus.NOT_REQUESTED,
        )

    def test_effectful_legacy_success_does_not_invent_applied_effect(self):
        result = normalize_tool_output(
            "writer",
            "Done.",
            "Done.",
            risk=RiskLevel.LOCAL_CHANGE,
        )

        self.assertTrue(result.success)
        self.assertEqual(result.effect_status, EffectStatus.UNKNOWN)
        self.assertEqual(
            result.verification_status,
            VerificationStatus.NOT_REQUESTED,
        )
        self.assertEqual(result.evidence, ())

    def test_serialized_v2_mapping_is_not_downgraded_to_legacy(self):
        original = ToolResult(
            False,
            "verification failed",
            error_code="not_verified",
            execution_status=ExecutionStatus.SUCCEEDED,
            effect_status=EffectStatus.APPLIED,
            verification_status=VerificationStatus.FAILED,
            rollback_status=RollbackStatus.AVAILABLE,
            evidence=("destination_missing",),
        )

        restored = normalize_tool_output(
            "writer",
            original.to_dict(),
            "Done.",
            risk=RiskLevel.LOCAL_CHANGE,
        )

        self.assertEqual(restored, original)

    def test_timeout_reports_unknown_effect_and_measured_duration(self):
        async def slow(_args):
            await asyncio.sleep(0.05)

        definition = ToolDefinition(
            "slow",
            "Slow",
            SCHEMA,
            handler=slow,
            risk=RiskLevel.LOCAL_CHANGE,
            timeout=0.001,
        )
        context = RequestContext.create(InputSource.LOCAL)

        result = asyncio.run(
            ToolExecutor(ToolRegistry([definition])).execute(
                "slow",
                {},
                context=context,
            )
        )

        self.assertFalse(result.success)
        self.assertEqual(result.execution_status, ExecutionStatus.TIMED_OUT)
        self.assertEqual(result.effect_status, EffectStatus.UNKNOWN)
        self.assertEqual(result.verification_status, VerificationStatus.UNKNOWN)
        self.assertGreaterEqual(result.duration_ms, 0)
        self.assertEqual(result.request_id, context.request_id)

    def test_validation_rejection_cannot_have_applied_an_effect(self):
        definition = ToolDefinition(
            "needs_value",
            "Needs value",
            {
                "type": "OBJECT",
                "properties": {"value": {"type": "STRING"}},
                "required": ["value"],
            },
            handler=lambda _args: "ok",
            risk=RiskLevel.LOCAL_CHANGE,
        )

        result = asyncio.run(
            ToolExecutor(ToolRegistry([definition])).execute(
                "needs_value",
                {},
            )
        )

        self.assertEqual(result.execution_status, ExecutionStatus.REJECTED)
        self.assertEqual(result.effect_status, EffectStatus.NOT_APPLIED)
        self.assertEqual(
            result.verification_status,
            VerificationStatus.NOT_REQUESTED,
        )

    def test_handler_v2_result_keeps_effect_and_verification_evidence(self):
        handler_result = ToolResult(
            True,
            "written and verified",
            execution_status=ExecutionStatus.SUCCEEDED,
            effect_status=EffectStatus.APPLIED,
            verification_status=VerificationStatus.VERIFIED,
            rollback_status=RollbackStatus.AVAILABLE,
            evidence=("sha256:example",),
        )
        definition = ToolDefinition(
            "writer",
            "Writer",
            SCHEMA,
            handler=lambda _args: handler_result,
            risk=RiskLevel.LOCAL_CHANGE,
        )

        result = asyncio.run(
            ToolExecutor(ToolRegistry([definition])).execute("writer", {})
        )

        self.assertEqual(result.effect_status, EffectStatus.APPLIED)
        self.assertEqual(
            result.verification_status,
            VerificationStatus.VERIFIED,
        )
        self.assertEqual(result.evidence, ("sha256:example",))
        self.assertGreaterEqual(result.duration_ms, 0)


if __name__ == "__main__":
    unittest.main()
