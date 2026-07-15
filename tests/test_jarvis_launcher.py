import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import jarvis_launcher


class LauncherConfigTests(unittest.TestCase):
    def test_defaults_keep_direct_mode_independent_from_vosk(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wake_word.json"
            with patch.object(jarvis_launcher, "CONFIG_FILE", path):
                config = jarvis_launcher.load_config()
        self.assertTrue(config["enabled"])
        self.assertEqual(config["phrases"], ["hey jarvis"])

    def test_stored_config_overrides_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wake_word.json"
            path.write_text(json.dumps({"phrases": ["jarvis", "oye jarvis"]}), encoding="utf-8")
            with patch.object(jarvis_launcher, "CONFIG_FILE", path):
                config = jarvis_launcher.load_config()
        self.assertEqual(config["phrases"], ["jarvis", "oye jarvis"])
        self.assertIn("model_path", config)

    def test_direct_is_the_safe_default(self):
        args = jarvis_launcher.build_parser().parse_args([])
        self.assertEqual(args.mode, "direct")


if __name__ == "__main__":
    unittest.main()
