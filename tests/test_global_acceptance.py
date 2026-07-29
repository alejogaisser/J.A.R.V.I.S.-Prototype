import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "check_global_acceptance.py"
SPEC = importlib.util.spec_from_file_location("check_global_acceptance", SCRIPT)
assert SPEC and SPEC.loader
acceptance = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(acceptance)


class GlobalAcceptanceGateTests(unittest.TestCase):
    def test_matrix_has_all_pdf_criteria_and_valid_evidence(self):
        payload = acceptance.load_matrix(REPO_ROOT / "docs" / "global_acceptance.json")
        counts = acceptance.validate_matrix(payload, REPO_ROOT)

        self.assertEqual(sum(counts.values()), 19)
        self.assertGreater(counts["verified"], 0)
        self.assertGreater(counts["partial"] + counts["manual"], 0)

    def test_integrity_mode_passes_but_strict_completion_fails_closed(self):
        integrity = subprocess.run(
            [sys.executable, str(SCRIPT), "--repo-root", str(REPO_ROOT)],
            capture_output=True,
            text=True,
            check=False,
        )
        strict = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--repo-root",
                str(REPO_ROOT),
                "--require-complete",
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(integrity.returncode, 0, integrity.stderr)
        self.assertEqual(strict.returncode, 2)
        self.assertIn("unresolved criteria remain", strict.stdout)


if __name__ == "__main__":
    unittest.main()
