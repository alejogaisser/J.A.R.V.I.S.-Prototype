from __future__ import annotations

import threading
import time
import unittest
from pathlib import Path


class _RecordingUi:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, tuple[object, ...]]] = []
        self.current_file = "C:/tmp/input.txt"
        self.microphone_enabled = True
        self.listen_mode = "always"

    def _record(self, name: str, *args: object):
        self.calls.append((name, threading.get_ident(), args))

    def write_log(self, text: str) -> None:
        self._record("write_log", text)

    def show_study_result(self, artifact, automatic: bool = True) -> str:
        self._record("show_study_result", artifact, automatic)
        return "stored"

    def show_content(self, title: str, text: str) -> None:
        self._record("show_content", title, text)

    def show_memory_graph(self) -> None:
        self._record("show_memory_graph")

    def refresh_memory_graph(self) -> None:
        self._record("refresh_memory_graph")

    def show_geo(self, place=None) -> None:
        self._record("show_geo", place)

    def enter_pet_mode(self, state: str, message: str) -> None:
        self._record("enter_pet_mode", state, message)

    def control_interface(self, action: str, target: str, mode: str = ""):
        self._record("control_interface", action, target, mode)
        return {"workspace": target}


class UiCommandFacadeTests(unittest.TestCase):
    def test_facade_has_an_explicit_command_surface(self):
        from core.ui_boundary import UiCommandFacade

        public = {
            name
            for name in dir(UiCommandFacade)
            if not name.startswith("_")
        }
        self.assertEqual(
            public,
            {
                "control_interface",
                "current_file",
                "enter_pet_mode",
                "listen_mode",
                "microphone_enabled",
                "refresh_memory_graph",
                "show_content",
                "show_geo",
                "show_memory_graph",
                "show_study_result",
                "write_log",
            },
        )

    def test_worker_can_only_enqueue_commands_and_consume_snapshots(self):
        from core.ui_boundary import UiCommandFacade

        ui = _RecordingUi()
        facade = UiCommandFacade(ui)
        worker_id: list[int] = []

        def invoke() -> None:
            worker_id.append(threading.get_ident())
            facade.write_log("hello")
            self.assertEqual(facade.show_study_result({"kind": "math"}), "stored")
            self.assertEqual(facade.current_file, "C:/tmp/input.txt")
            self.assertTrue(facade.microphone_enabled)

        worker = threading.Thread(target=invoke)
        worker.start()
        worker.join(timeout=2)

        self.assertFalse(worker.is_alive())
        self.assertTrue(ui.calls)
        self.assertTrue(all(call[1] == worker_id[0] for call in ui.calls))


class UiThreadBoundaryIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.main = Path("main.py").read_text(encoding="utf-8")
        cls.ui = Path("ui.py").read_text(encoding="utf-8")

    def test_tool_handlers_receive_facade_instead_of_widget_owner(self):
        handlers = self.main[
            self.main.index("        handlers = {"):
            self.main.index("        self.tool_registry =", self.main.index("        handlers = {"))
        ]
        self.assertIn("UiCommandFacade(self.ui)", self.main)
        self.assertNotIn("player=self.ui)", handlers)
        self.assertNotIn("player=self.ui,", handlers)
        self.assertIn("player=self.ui_tools", handlers)
        self.assertIn("self.ui_tools.enter_pet_mode(", handlers)
        self.assertIn("self.ui_tools.control_interface(", handlers)

    def test_phone_notification_is_queued_to_qt(self):
        self.assertIn("_phone_connected_sig = pyqtSignal()", self.ui)
        self.assertIn(
            "self._phone_connected_sig.connect(self.notify_phone_connected)",
            self.ui,
        )
        wrapper = self.ui[
            self.ui.index("    def notify_phone_connected", self.ui.index("class JarvisUI")):
            self.ui.index("    def set_state", self.ui.index("class JarvisUI"))
        ]
        self.assertIn("self._win._phone_connected_sig.emit()", wrapper)
        self.assertNotIn("self._win.notify_phone_connected()", wrapper)

    def test_worker_snapshots_do_not_read_widgets(self):
        current_file = self.ui[
            self.ui.index("    def current_file", self.ui.index("class JarvisUI")):
            self.ui.index("    @property", self.ui.index("    def current_file", self.ui.index("class JarvisUI")))
        ]
        self.assertIn("self._win.tool_snapshot()", current_file)
        self.assertNotIn("_drop_zone", current_file)
        self.assertIn("self._tool_state_lock", self.ui)

    def test_camera_callback_is_read_and_written_under_camera_lock(self):
        start = self.ui.index("    def _cam_loop")
        camera = self.ui[start:self.ui.index("    def set_camera_mode", start)]
        self.assertIn("callback = self._camera_frame_callback", camera)
        self.assertIn("with self._cam_lock:", camera)
        self.assertNotIn("self._camera_frame_callback(buf.tobytes())", camera)

    def test_qt_queued_command_runs_on_application_thread(self):
        try:
            from PyQt6.QtCore import QCoreApplication, QObject, pyqtSignal, pyqtSlot
        except ImportError:
            self.skipTest("PyQt6 is not installed")

        app = QCoreApplication.instance() or QCoreApplication([])
        application_thread = threading.get_ident()
        observed: list[int] = []

        class Bridge(QObject):
            command = pyqtSignal()

            @pyqtSlot()
            def consume(self) -> None:
                observed.append(threading.get_ident())

        bridge = Bridge()
        bridge.command.connect(bridge.consume)
        worker = threading.Thread(target=bridge.command.emit)
        worker.start()
        worker.join(timeout=2)

        deadline = time.monotonic() + 2
        while not observed and time.monotonic() < deadline:
            app.processEvents()

        self.assertEqual(observed, [application_thread])


if __name__ == "__main__":
    unittest.main()
