from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from config.settings import (
    SettingsError,
    get_settings,
    refresh_settings,
)


class SettingsTests(unittest.TestCase):
    def test_missing_file_uses_platform_default_without_a_secret(self):
        with TemporaryDirectory() as temp:
            settings = get_settings(Path(temp) / "missing.json")

        self.assertEqual(settings.gemini_api_key, "")
        self.assertIn(settings.os_system, {"windows", "mac", "linux"})

    def test_malformed_json_fails_with_stable_error(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "config.json"
            path.write_text("{", encoding="utf-8")

            with self.assertRaisesRegex(SettingsError, "valid JSON"):
                get_settings(path)

    def test_invalid_field_types_fail_at_load(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "config.json"
            path.write_text(
                json.dumps({"gemini_api_key": 123, "os_system": "windows"}),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(SettingsError, "gemini_api_key"):
                get_settings(path)

    def test_settings_are_cached_until_explicit_refresh(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "config.json"
            path.write_text(
                json.dumps({"gemini_api_key": "first", "os_system": "windows"}),
                encoding="utf-8",
            )
            first = get_settings(path)
            path.write_text(
                json.dumps({"gemini_api_key": "second", "os_system": "linux"}),
                encoding="utf-8",
            )

            self.assertIs(get_settings(path), first)
            refreshed = refresh_settings(path)

        self.assertEqual(refreshed.gemini_api_key, "second")
        self.assertEqual(refreshed.os_system, "linux")

    def test_secret_is_excluded_from_repr(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "config.json"
            path.write_text(
                json.dumps({"gemini_api_key": "do-not-print", "os_system": "windows"}),
                encoding="utf-8",
            )
            settings = get_settings(path)

        self.assertNotIn("do-not-print", repr(settings))

    def test_nested_extras_are_immutable_but_legacy_view_is_mutable(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "config.json"
            path.write_text(
                json.dumps({
                    "os_system": "windows",
                    "models": {"fallback": ["one", "two"]},
                }),
                encoding="utf-8",
            )
            settings = get_settings(path)

        with self.assertRaises(TypeError):
            settings.extras["models"]["fallback"] = ("changed",)
        self.assertEqual(
            settings.as_legacy_dict()["models"]["fallback"],
            ["one", "two"],
        )

    def test_missing_required_key_has_a_stable_error(self):
        with TemporaryDirectory() as temp:
            settings = get_settings(Path(temp) / "missing.json")

        with self.assertRaisesRegex(SettingsError, "gemini_api_key"):
            settings.require_gemini_api_key()

    def test_main_uses_settings_owner_instead_of_reading_config_json(self):
        source = Path("main.py").read_text(encoding="utf-8")
        self.assertIn("get_settings().require_gemini_api_key()", source)
        self.assertNotIn('API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"', source)


if __name__ == "__main__":
    unittest.main()
