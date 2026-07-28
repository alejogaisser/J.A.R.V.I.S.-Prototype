import hashlib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from actions.file_controller import file_controller
from core.tools import (
    EffectStatus,
    ExecutionStatus,
    RollbackStatus,
    ToolResult,
    VerificationStatus,
)


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class FileVerificationPilotTests(unittest.TestCase):
    def setUp(self):
        self._safe_path = patch(
            "actions.file_controller._is_safe_path",
            return_value=True,
        )
        self._safe_path.start()
        self.addCleanup(self._safe_path.stop)

    def test_create_file_returns_verified_v2_result(self):
        with TemporaryDirectory() as directory:
            target = Path(directory) / "created.txt"

            result = file_controller(
                {
                    "action": "create_file",
                    "path": str(target),
                    "content": "verified content",
                }
            )

            self.assertIsInstance(result, ToolResult)
            self.assertTrue(result.success)
            self.assertEqual(result.execution_status, ExecutionStatus.SUCCEEDED)
            self.assertEqual(result.effect_status, EffectStatus.APPLIED)
            self.assertEqual(
                result.verification_status,
                VerificationStatus.VERIFIED,
            )
            self.assertEqual(result.rollback_status, RollbackStatus.AVAILABLE)
            self.assertEqual(
                result.data["resolved_path"],
                str(target.resolve()),
            )
            self.assertEqual(
                result.data["sha256"],
                digest(b"verified content"),
            )
            self.assertIn("sha256:" + digest(b"verified content"), result.evidence)
            self.assertEqual(target.read_text(encoding="utf-8"), "verified content")

    def test_create_file_conflict_does_not_overwrite_existing_content(self):
        with TemporaryDirectory() as directory:
            target = Path(directory) / "existing.txt"
            target.write_text("original", encoding="utf-8")

            result = file_controller(
                {
                    "action": "create_file",
                    "path": str(target),
                    "content": "replacement",
                }
            )

            self.assertIsInstance(result, ToolResult)
            self.assertFalse(result.success)
            self.assertEqual(result.execution_status, ExecutionStatus.REJECTED)
            self.assertEqual(result.effect_status, EffectStatus.NOT_APPLIED)
            self.assertEqual(target.read_text(encoding="utf-8"), "original")

    def test_copy_file_verifies_destination_and_preserves_source(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.txt"
            destination = root / "destination"
            source.write_bytes(b"copy evidence")
            destination.mkdir()

            result = file_controller(
                {
                    "action": "copy",
                    "path": str(source),
                    "destination": str(destination),
                }
            )
            copied = destination / source.name

            self.assertIsInstance(result, ToolResult)
            self.assertTrue(result.success)
            self.assertEqual(result.effect_status, EffectStatus.APPLIED)
            self.assertEqual(
                result.verification_status,
                VerificationStatus.VERIFIED,
            )
            self.assertEqual(result.rollback_status, RollbackStatus.AVAILABLE)
            self.assertEqual(result.data["resolved_path"], str(copied.resolve()))
            self.assertEqual(result.data["sha256"], digest(b"copy evidence"))
            self.assertTrue(source.exists())
            self.assertEqual(copied.read_bytes(), b"copy evidence")
            self.assertEqual(
                result.data["rollback"],
                {"action": "trash", "path": str(copied.resolve())},
            )

    def test_move_file_verifies_destination_and_source_absence(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.txt"
            destination = root / "destination"
            source.write_bytes(b"move evidence")
            destination.mkdir()

            result = file_controller(
                {
                    "action": "move",
                    "path": str(source),
                    "destination": str(destination),
                }
            )
            moved = destination / source.name

            self.assertIsInstance(result, ToolResult)
            self.assertTrue(result.success)
            self.assertEqual(
                result.verification_status,
                VerificationStatus.VERIFIED,
            )
            self.assertFalse(source.exists())
            self.assertEqual(moved.read_bytes(), b"move evidence")
            self.assertIn("source_absent:true", result.evidence)
            self.assertEqual(
                result.data["rollback"],
                {
                    "action": "move",
                    "source": str(moved.resolve()),
                    "destination": str(source.resolve()),
                },
            )

    def test_destination_conflict_is_rejected_for_copy_and_move(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.txt"
            destination = root / "destination.txt"
            source.write_text("source", encoding="utf-8")
            destination.write_text("destination", encoding="utf-8")

            for action in ("copy", "move"):
                with self.subTest(action=action):
                    result = file_controller(
                        {
                            "action": action,
                            "path": str(source),
                            "destination": str(destination),
                        }
                    )
                    self.assertIsInstance(result, ToolResult)
                    self.assertEqual(
                        result.execution_status,
                        ExecutionStatus.REJECTED,
                    )
                    self.assertEqual(
                        result.effect_status,
                        EffectStatus.NOT_APPLIED,
                    )
                    self.assertEqual(
                        destination.read_text(encoding="utf-8"),
                        "destination",
                    )
                    self.assertTrue(source.exists())

    def test_unobserved_destination_is_not_reported_as_verified(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.txt"
            destination = root / "destination.txt"
            source.write_text("source", encoding="utf-8")

            from core.tools.file_verifier import capture_file_evidence

            source_evidence = capture_file_evidence(source)
            with patch(
                "actions.file_controller.capture_file_evidence",
                side_effect=[source_evidence, None],
            ):
                result = file_controller(
                    {
                        "action": "copy",
                        "path": str(source),
                        "destination": str(destination),
                    }
                )

            self.assertIsInstance(result, ToolResult)
            self.assertFalse(result.success)
            self.assertEqual(result.execution_status, ExecutionStatus.SUCCEEDED)
            self.assertEqual(result.effect_status, EffectStatus.APPLIED)
            self.assertEqual(
                result.verification_status,
                VerificationStatus.FAILED,
            )
            self.assertNotIn("verified", result.message.casefold())

    def test_directory_copy_remains_on_legacy_adapter_during_pilot(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            destination = root / "destination"
            source.mkdir()
            (source / "item.txt").write_text("item", encoding="utf-8")

            result = file_controller(
                {
                    "action": "copy",
                    "path": str(source),
                    "destination": str(destination),
                }
            )

            self.assertIsInstance(result, str)
            self.assertTrue((destination / "item.txt").exists())


if __name__ == "__main__":
    unittest.main()
