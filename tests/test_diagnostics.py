import tempfile
import unittest
from pathlib import Path

from core.diagnostics import CrashReporter, redact_diagnostic_text


class DiagnosticsTests(unittest.TestCase):
    def test_redacts_common_secret_shapes(self):
        text = (
            "api_key=super-secret token: abc123 "
            "url=https://example.test/?access_token=visible"
        )
        redacted = redact_diagnostic_text(text)

        self.assertNotIn("super-secret", redacted)
        self.assertNotIn("abc123", redacted)
        self.assertNotIn("visible", redacted)
        self.assertGreaterEqual(redacted.count("[REDACTED]"), 3)

    def test_records_sanitized_exception(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "crash.log"
            reporter = CrashReporter(path)
            try:
                raise RuntimeError("authorization=private-value")
            except RuntimeError as exc:
                reporter.record_exception("test worker", exc)

            content = path.read_text(encoding="utf-8")
            self.assertIn("test worker", content)
            self.assertIn("RuntimeError", content)
            self.assertNotIn("private-value", content)


if __name__ == "__main__":
    unittest.main()
