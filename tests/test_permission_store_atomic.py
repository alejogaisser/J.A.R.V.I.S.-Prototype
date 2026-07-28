import json
import os
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from core.permissions import PermissionLevel, PermissionStore


class AtomicPermissionStoreTests(unittest.TestCase):
    def test_local_primary_and_backup_are_ignored_by_git(self):
        ignored = Path(".gitignore").read_text(encoding="utf-8")

        self.assertIn("config/permissions.json\n", ignored)
        self.assertIn("config/permissions.json.bak\n", ignored)

    def test_save_uses_same_directory_replace_and_fsync(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "permissions.json"
            store = PermissionStore(path)

            with (
                patch("core.permissions.store.os.replace", wraps=os.replace) as replace,
                patch("core.permissions.store.os.fsync", wraps=os.fsync) as fsync,
            ):
                store.save({"dev_agent": PermissionLevel.BLOCKED})

            source, destination = replace.call_args_list[-1].args
            self.assertEqual(Path(source).parent, path.parent)
            self.assertEqual(Path(destination), path)
            self.assertTrue(fsync.called)

    def test_replace_failure_preserves_previous_primary_and_cleans_temp(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "permissions.json"
            store = PermissionStore(path)
            store.save({"dev_agent": PermissionLevel.CONFIRM_ALWAYS})
            original = path.read_bytes()
            real_replace = os.replace

            def fail_primary(source, destination):
                if Path(destination) == path:
                    raise OSError("simulated power loss before publish")
                return real_replace(source, destination)

            with patch("core.permissions.store.os.replace", side_effect=fail_primary):
                with self.assertRaises(OSError):
                    store.save({"dev_agent": PermissionLevel.BLOCKED})

            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(path.parent.glob(f".{path.name}.*.tmp")), [])

    def test_write_failure_preserves_previous_primary_and_cleans_temp(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "permissions.json"
            store = PermissionStore(path)
            store.save({"dev_agent": PermissionLevel.CONFIRM_ALWAYS})
            original = path.read_bytes()

            with patch(
                "core.permissions.store.os.fsync",
                side_effect=OSError("simulated disk error"),
            ):
                with self.assertRaises(OSError):
                    store.save({"dev_agent": PermissionLevel.BLOCKED})

            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(path.parent.glob(f".{path.name}.*.tmp")), [])

    def test_corrupt_primary_recovers_last_valid_backup(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "permissions.json"
            store = PermissionStore(path)
            store.save({"dev_agent": PermissionLevel.CONFIRM_ALWAYS})
            store.save({"dev_agent": PermissionLevel.BLOCKED})
            path.write_text("{partial", encoding="utf-8")

            loaded = store.load()

            self.assertEqual(
                loaded["dev_agent"],
                PermissionLevel.CONFIRM_ALWAYS,
            )

    def test_corrupt_primary_and_backup_fail_closed(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "permissions.json"
            store = PermissionStore(path)
            path.write_text("{partial", encoding="utf-8")
            store.backup_path.write_text("{also partial", encoding="utf-8")

            loaded = store.load()

            self.assertEqual(
                loaded["send_message"],
                PermissionLevel.CONFIRM_ALWAYS,
            )
            self.assertEqual(
                loaded["dev_agent"],
                PermissionLevel.CONFIRM_ALWAYS,
            )

    def test_unknown_version_does_not_override_safe_defaults(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "permissions.json"
            path.write_text(
                json.dumps(
                    {"version": 999, "tools": {"send_message": "free"}}
                ),
                encoding="utf-8",
            )

            loaded = PermissionStore(path).load()

            self.assertEqual(
                loaded["send_message"],
                PermissionLevel.CONFIRM_ALWAYS,
            )

    def test_version_one_remains_readable(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "permissions.json"
            path.write_text(
                json.dumps(
                    {"version": 1, "tools": {"dev_agent": "blocked"}}
                ),
                encoding="utf-8",
            )

            loaded = PermissionStore(path).load()

            self.assertEqual(loaded["dev_agent"], PermissionLevel.BLOCKED)

    def test_invalid_preferences_are_rejected_before_publication(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "permissions.json"
            store = PermissionStore(path)
            store.save({"dev_agent": PermissionLevel.CONFIRM_ALWAYS})
            original = path.read_bytes()

            with self.assertRaises(KeyError):
                store.save({"dev_agent": "not_a_permission"})

            self.assertEqual(path.read_bytes(), original)

    def test_corrupt_primary_does_not_overwrite_last_valid_backup(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "permissions.json"
            store = PermissionStore(path)
            store.save({"dev_agent": PermissionLevel.CONFIRM_ALWAYS})
            store.save({"dev_agent": PermissionLevel.BLOCKED})
            valid_backup = store.backup_path.read_bytes()
            path.write_text("{partial", encoding="utf-8")

            store.save({"dev_agent": PermissionLevel.FREE})

            self.assertEqual(store.backup_path.read_bytes(), valid_backup)
            self.assertEqual(store.load()["dev_agent"], PermissionLevel.FREE)

    def test_concurrent_store_instances_leave_one_complete_document(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "permissions.json"
            barrier = threading.Barrier(8)
            errors = []

            def writer(index):
                try:
                    barrier.wait()
                    PermissionStore(path).save(
                        {
                            "dev_agent": (
                                PermissionLevel.BLOCKED
                                if index % 2
                                else PermissionLevel.CONFIRM_ALWAYS
                            )
                        }
                    )
                except Exception as exc:
                    errors.append(exc)

            threads = [
                threading.Thread(target=writer, args=(index,))
                for index in range(8)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=5)

            self.assertEqual(errors, [])
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["version"], PermissionStore.VERSION)
            self.assertIn(
                payload["tools"]["dev_agent"],
                {"blocked", "confirm_always"},
            )
            self.assertEqual(list(path.parent.glob(f".{path.name}.*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
