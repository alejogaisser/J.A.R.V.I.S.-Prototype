import copy
import importlib.util
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "check_operational_change_control.py"
SPEC = importlib.util.spec_from_file_location("check_operational_change_control", SCRIPT)
assert SPEC and SPEC.loader
control = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(control)


class OperationalChangeControlTests(unittest.TestCase):
    def setUp(self):
        self.payload = control.load_contract(
            REPO_ROOT / "docs" / "operational_change_control.json"
        )

    def test_contract_covers_all_pdf_controls_and_sequential_phases(self):
        controls, changes = control.validate_contract(self.payload, REPO_ROOT)

        self.assertEqual(controls, 19)
        self.assertEqual(changes, 2)

    def test_missing_control_fails_closed(self):
        payload = copy.deepcopy(self.payload)
        payload["controls"].pop()

        with self.assertRaisesRegex(ValueError, "Operational control mismatch"):
            control.validate_contract(payload, REPO_ROOT)

    def test_missing_completed_phase_record_fails_closed(self):
        payload = copy.deepcopy(self.payload)
        payload["changes"] = [payload["changes"][1]]

        with self.assertRaisesRegex(ValueError, "Completed phases lack"):
            control.validate_contract(payload, REPO_ROOT)

    def test_sensitive_or_external_paths_are_rejected(self):
        sensitive = copy.deepcopy(self.payload)
        sensitive["changes"][0]["files"][0] = "config/api_keys.json"
        external = copy.deepcopy(self.payload)
        external["changes"][0]["files"][0] = "../outside.md"

        with self.assertRaisesRegex(ValueError, "sensitive file"):
            control.validate_contract(sensitive, REPO_ROOT)
        with self.assertRaisesRegex(ValueError, "escapes the repository"):
            control.validate_contract(external, REPO_ROOT)

    def test_completed_phase_rejects_pending_tests_or_obsidian(self):
        pending_test = copy.deepcopy(self.payload)
        pending_test["changes"][0]["tests"][0]["outcome"] = "pending"
        pending_note = copy.deepcopy(self.payload)
        pending_note["changes"][0]["obsidian_note"] = "pending"

        with self.assertRaisesRegex(ValueError, "cannot retain pending"):
            control.validate_contract(pending_test, REPO_ROOT)
        with self.assertRaisesRegex(ValueError, "must record the Obsidian"):
            control.validate_contract(pending_note, REPO_ROOT)

    def test_destructive_change_requires_confirmation_and_preview(self):
        payload = copy.deepcopy(self.payload)
        payload["changes"][0]["destructive"] = True

        with self.assertRaisesRegex(ValueError, "require confirmation"):
            control.validate_contract(payload, REPO_ROOT)

    def test_new_abstraction_requires_an_allowed_benefit(self):
        payload = copy.deepcopy(self.payload)
        payload["changes"][0]["abstraction_benefit"] = "looks_cleaner"

        with self.assertRaisesRegex(ValueError, "invalid abstraction benefit"):
            control.validate_contract(payload, REPO_ROOT)


if __name__ == "__main__":
    unittest.main()
