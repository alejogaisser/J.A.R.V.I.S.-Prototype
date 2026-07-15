import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.temp_files import cleanup_temp_files, temporary_output
from actions.file_controller import clear_jarvis_temp


class TemporaryOutputTests(unittest.TestCase):
    def test_unique_outputs_and_old_file_cleanup(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"JARVIS_TEMP_DIR": directory}):
            first = temporary_output(prefix="grafico")
            second = temporary_output(prefix="grafico")
            self.assertNotEqual(first, second)
            self.assertEqual(first.parent.name, "imagenes")
            first.write_bytes(b"old")
            old = time.time() - 9 * 86400
            os.utime(first, (old, old))
            self.assertEqual(cleanup_temp_files(max_age_days=7), 1)
            self.assertFalse(first.exists())

    def test_explicit_math_output_remains_supported(self):
        source = Path("actions/math_engine.py").read_text(encoding="utf-8")
        self.assertIn('args.get("output_path")', source)
        self.assertIn("temporary_output", source)

    def test_clear_temp_preserves_root(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"JARVIS_TEMP_DIR": directory}):
            root = Path(directory)
            (root / "imagenes").mkdir()
            (root / "imagenes" / "plot.png").write_bytes(b"png")
            with patch("actions.file_controller.send2trash.send2trash", side_effect=lambda value: __import__("shutil").rmtree(value)):
                result = clear_jarvis_temp()
            self.assertTrue(root.exists())
            self.assertEqual(list(root.iterdir()), [])
            self.assertIn("Folder preserved", result)


if __name__ == "__main__":
    unittest.main()
