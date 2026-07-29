import copy
import importlib.util
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "check_audit_closure.py"
SPEC = importlib.util.spec_from_file_location("check_audit_closure", SCRIPT)
assert SPEC and SPEC.loader
closure = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(closure)


class AuditClosureTests(unittest.TestCase):
    def setUp(self):
        self.payload = closure.load_closure(REPO_ROOT / "docs" / "audit_closure.json")

    def test_closure_covers_sources_limits_and_open_global_criteria(self):
        sources, limits, unresolved = closure.validate_closure(
            self.payload,
            REPO_ROOT,
        )

        self.assertEqual(sources, 8)
        self.assertEqual(limits, 5)
        self.assertEqual(unresolved, 13)

    def test_missing_source_group_or_limit_fails_closed(self):
        missing_source = copy.deepcopy(self.payload)
        missing_source["source_groups"].pop()
        missing_limit = copy.deepcopy(self.payload)
        missing_limit["limits"].pop()

        with self.assertRaisesRegex(ValueError, "source groups mismatch"):
            closure.validate_closure(missing_source, REPO_ROOT)
        with self.assertRaisesRegex(ValueError, "limits mismatch"):
            closure.validate_closure(missing_limit, REPO_ROOT)

    def test_external_or_missing_source_path_is_rejected(self):
        external = copy.deepcopy(self.payload)
        external["source_groups"][0]["paths"][0] = "../outside.py"
        missing = copy.deepcopy(self.payload)
        missing["source_groups"][0]["paths"][0] = "missing.py"

        with self.assertRaisesRegex(ValueError, "escapes the repository"):
            closure.validate_closure(external, REPO_ROOT)
        with self.assertRaisesRegex(ValueError, "missing path"):
            closure.validate_closure(missing, REPO_ROOT)

    def test_unresolved_global_criteria_forbid_verified_complete(self):
        payload = copy.deepcopy(self.payload)
        payload["closure_status"] = "verified_complete"

        with self.assertRaisesRegex(ValueError, "forbid verified_complete"):
            closure.validate_closure(payload, REPO_ROOT)

    def test_stale_global_summary_is_rejected(self):
        payload = copy.deepcopy(self.payload)
        payload["global_acceptance"]["verified"] += 1

        with self.assertRaisesRegex(ValueError, "summary is stale"):
            closure.validate_closure(payload, REPO_ROOT)


if __name__ == "__main__":
    unittest.main()
