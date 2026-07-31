import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UPSTREAM_COMMIT_URL = (
    "https://github.com/FatihMakes/Mark-L/commit/d178f6b"
)


class PublicReleaseMetadataTests(unittest.TestCase):
    """Keep publication metadata explicit and free of credential-like examples."""

    def test_google_oauth_example_uses_obvious_placeholders(self):
        config = json.loads(
            (ROOT / "config" / "google_oauth_client.example.json").read_text(
                encoding="utf-8"
            )
        )["installed"]

        self.assertEqual(
            config["client_id"],
            "YOUR_CLIENT_ID.apps.googleusercontent.com",
        )
        self.assertEqual(config["client_secret"], "YOUR_CLIENT_SECRET")
        self.assertEqual(config["project_id"], "YOUR_GOOGLE_CLOUD_PROJECT_ID")

    def test_generated_output_directory_is_ignored(self):
        ignored_entries = {
            line.strip()
            for line in (ROOT / ".gitignore").read_text(
                encoding="utf-8"
            ).splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        self.assertIn("/output/", ignored_entries)

    def test_upstream_attribution_is_precise_and_consistent(self):
        for relative_path in (
            "LICENSE.md",
            "NOTICE.md",
            "THIRD_PARTY_NOTICES.md",
            "readme.md",
        ):
            with self.subTest(path=relative_path):
                content = (ROOT / relative_path).read_text(encoding="utf-8")
                self.assertIn("FatihMakes", content)
                self.assertIn(UPSTREAM_COMMIT_URL, content)
                self.assertIn("non-commercial", content.casefold())

    def test_non_affiliation_disclaimer_is_visible(self):
        for relative_path in ("LICENSE.md", "NOTICE.md", "readme.md"):
            with self.subTest(path=relative_path):
                content = (ROOT / relative_path).read_text(encoding="utf-8")
                self.assertIn("Marvel", content)
                self.assertIn("The Walt Disney Company", content)
                self.assertIn("not affiliated", content.casefold())

    def test_current_maintainer_identity_preserves_previous_alias(self):
        for relative_path in ("LICENSE.md", "NOTICE.md", "readme.md"):
            with self.subTest(path=relative_path):
                content = (ROOT / relative_path).read_text(encoding="utf-8")
                self.assertIn("Alejo Gaisser", content)
                self.assertIn("https://github.com/alejogaisser", content)
                self.assertIn("@AlejoGaisser07", content)

    def test_bundled_wake_models_remain_documented(self):
        notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
        for filename in (
            "embedding_model.onnx",
            "melspectrogram.onnx",
            "hey_jarvis_v0.1.onnx",
        ):
            self.assertIn(filename, notices)
        self.assertIn("CC BY-NC-SA 4.0", notices)


if __name__ == "__main__":
    unittest.main()
