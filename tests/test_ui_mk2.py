from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

from ui_mk2.state import VisualState, VisualStateController, normalize_state


class Mk2StateTests(unittest.TestCase):
    def test_runtime_aliases_map_to_six_visual_states(self):
        self.assertEqual(normalize_state("SLEEPING"), VisualState.DORMANT)
        self.assertEqual(normalize_state("PROCESSING"), VisualState.EXECUTING)
        self.assertEqual(normalize_state("SPEAKING"), VisualState.SPEAKING)
        self.assertEqual(normalize_state("unexpected"), VisualState.DORMANT)

    def test_dormant_has_no_ambient_rotation(self):
        controller = VisualStateController("DORMANT")
        self.assertEqual(controller.spec.ring_speed, 0.0)

    def test_state_transition_is_interpolated(self):
        controller = VisualStateController("DORMANT")
        controller.set_state("LISTENING")
        self.assertEqual(controller.progress, 0.0)
        controller.advance(controller.duration / 2)
        self.assertAlmostEqual(controller.progress, 0.5)


class Mk2IntegrationTests(unittest.TestCase):
    def test_wake_word_opens_base_app_and_pet_remains_explicit(self):
        wake = Path("wake_word.py").read_text(encoding="utf-8")
        self.assertIn('[str(executable), "-u", str(MAIN_FILE)]', wake)
        self.assertNotIn('[str(executable), "-u", str(MAIN_FILE), "--pet"]', wake)
        self.assertIn("def enter_pet_mode", Path("ui.py").read_text(encoding="utf-8"))

    def test_pet_is_a_compact_text_free_movable_orb(self):
        pet = Path("ui_mk2/pet.py").read_text(encoding="utf-8")
        ui = Path("ui.py").read_text(encoding="utf-8")
        self.assertIn("SIZE = 136", pet)
        self.assertIn("QConicalGradient", pet)
        self.assertIn("from .tokens import Palette, color", pet)
        self.assertIn("painter.drawArc", pet)
        self.assertIn("def mouseMoveEvent", pet)
        self.assertIn('self._settings.setValue("pet/position"', pet)
        self.assertNotIn("drawText", pet)
        self.assertIn("widget in {self._win, self._pet}", ui)

    def test_main_app_handoff_hides_pet(self):
        ui = Path("ui.py").read_text(encoding="utf-8")
        handoff = ui[ui.index("    def _open_from_pet"):ui.index("    def enter_pet_mode")]
        self.assertIn("self._pet.hide_pet()", handoff)
        self.assertIn("self._bring_main_window_to_front()", handoff)

    def test_pet_releases_pointer_capture_before_returning_to_app(self):
        pet = Path("ui_mk2/pet.py").read_text(encoding="utf-8")
        reset = pet[
            pet.index("    def _reset_pointer_interaction"):
            pet.index("    def set_state")
        ]
        double_click = pet[
            pet.index("    def mouseDoubleClickEvent"):
            pet.index("    def closeEvent")
        ]
        self.assertIn("self._drag_origin = None", reset)
        self.assertIn("if QWidget.mouseGrabber() is self:", reset)
        self.assertIn("self.releaseMouse()", reset)
        self.assertIn("self._reset_pointer_interaction()", double_click)
        self.assertLess(
            double_click.index("self._reset_pointer_interaction()"),
            double_click.index("self.open_requested.emit()"),
        )

    def test_pet_round_trip_keeps_real_navigation_buttons_alive(self):
        script = """
from PyQt6 import sip
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from ui import JarvisUI

ui = JarvisUI("face.png")
app = ui._app
app.processEvents()
chat = ui._win._v1_chat_btn
files = ui._win._v1_files_btn
QTest.mouseClick(ui._win._v1_pet_btn, Qt.MouseButton.LeftButton)
app.processEvents()
assert ui._surface_mode == "pet"
assert not ui._win._v1_pet_btn.isChecked()
QTest.mouseDClick(ui._pet, Qt.MouseButton.LeftButton)
QTest.qWait(30)
app.processEvents()
assert ui._surface_mode == "main"
assert ui._win._v1_chat_btn is chat and not sip.isdeleted(chat)
assert ui._win._v1_files_btn is files and not sip.isdeleted(files)
QTest.mouseClick(chat, Qt.MouseButton.LeftButton)
QTest.qWait(300)
app.processEvents()
assert ui._win._active_v1_panel == "chat"
assert ui._win._right_panel.isVisible()
assert ui._win._right_panel.maximumWidth() > 0
QTest.mouseClick(files, Qt.MouseButton.LeftButton)
QTest.qWait(300)
app.processEvents()
assert ui._win._active_v1_panel == "files"
assert ui._win._right_panel.isVisible()
"""
        env = dict(os.environ)
        env["QT_QPA_PLATFORM"] = "offscreen"
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parents[1],
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        self.assertEqual(
            completed.returncode,
            0,
            msg=f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}",
        )

    def test_top_navigation_is_interactive_and_routes_real_workspaces(self):
        ui = Path("ui.py").read_text(encoding="utf-8")
        header = ui[ui.index("    def _build_header"):ui.index("    def _build_control_bar")]
        self.assertIn("tab = QPushButton(label)", header)
        self.assertIn("def _select_header_view", header)
        self.assertIn("self.hud.show_context_workspace()", header)
        self.assertIn("self._animate_system_panel", header)
        self.assertIn("self.hud.show_core()", header)

    def test_futuristic_roadmap_modules_are_visible_but_inert(self):
        ui = Path("ui.py").read_text(encoding="utf-8")
        module = ui[ui.index("class FutureModuleButton"):ui.index("class HudCanvas")]
        self.assertIn("self.setEnabled(False)", module)
        self.assertNotIn("clicked.connect", module)
        self.assertIn('FutureModuleButton("AUTOMATIONS"', ui)
        self.assertIn('FutureModuleButton("COMMS HUB"', ui)
        self.assertIn('FutureModuleButton("ROBOTICS"', ui)
        self.assertIn('FutureModuleButton("SMART HOME"', ui)

    def test_operational_field_has_animated_depth_and_live_telemetry(self):
        ui = Path("ui.py").read_text(encoding="utf-8")
        field = ui[ui.index("    def _draw_operational_field"):ui.index("    def _draw_core_stage")]
        self.assertIn("VOICE CHANNEL", field)
        self.assertIn("MEMORY MATRIX", field)
        self.assertIn("sweep = (self._tick * 2.2)", field)
        self.assertIn("QLinearGradient", field)
        self.assertIn("graph = QPainterPath()", field)

    def test_core_is_a_multilayer_holographic_reactor(self):
        core = Path("ui_mk2/core.py").read_text(encoding="utf-8")
        self.assertIn("def _draw_segmented_housing", core)
        self.assertIn("count = 28", core)
        self.assertIn("def _draw_micro_ticks", core)
        self.assertIn("for index in range(96)", core)
        self.assertIn("def _draw_data_orbits", core)
        self.assertIn("Latitude/longitude traces", core)
        self.assertIn("Deterministic plasma filaments", core)
        self.assertIn("Multi-pass energy torus", core)

    def test_only_the_inner_nucleus_is_static(self):
        core = Path("ui_mk2/core.py").read_text(encoding="utf-8")
        iris = core[core.index("    def _draw_iris"):core.index("    def _draw_state_signature")]
        outer = core[core.index("    def _draw_data_orbits"):core.index("    def _draw_iris")]
        self.assertIn("STATIC_NUCLEUS_TIME = 0.0", core)
        self.assertIn("nucleus_time = self.STATIC_NUCLEUS_TIME", iris)
        self.assertNotIn("self.time_seconds", iris)
        self.assertIn("QPicture()", iris)
        self.assertIn("self._iris_cache.play(painter)", iris)
        self.assertIn("self.phase", outer)
        self.assertIn("self.time_seconds", outer)

    def test_pet_mode_is_reachable_by_button_and_thread_safe_signal(self):
        ui = Path("ui.py").read_text(encoding="utf-8")
        self.assertIn('_button("pet", "Pet Mode", self._request_pet_mode)', ui)
        self.assertIn("self._v1_pet_btn.setCheckable(False)", ui)
        self.assertIn("_pet_mode_sig = pyqtSignal(str, str)", ui)
        self.assertIn("self._win._pet_mode_sig.connect(self._apply_pet_mode)", ui)
        enter = ui[ui.index("    def enter_pet_mode"):ui.index("    def exit_pet_mode")]
        self.assertIn("self._win._pet_mode_sig.emit(state, message)", enter)
        self.assertIn("def _apply_pet_mode", enter)
        self.assertIn("self._win.hide()", enter)
        self.assertIn("self._pet.show_pet(state, message)", enter)
        self.assertIn("self._win.stop_camera_stream()", enter)

    def test_camera_sessions_are_generation_guarded(self):
        ui = Path("ui.py").read_text(encoding="utf-8")
        camera = ui[ui.index("    def start_camera_stream"):ui.index("    def set_camera_frame_callback")]
        self.assertIn("self._cam_lock", camera)
        self.assertIn("self._cam_generation", camera)
        self.assertIn("self._cam_thread is threading.current_thread()", camera)
        self.assertIn("cap.release()", camera)
        self.assertIn("self._cam_stream_sig.emit(False)", camera)

    def test_pet_mode_has_a_dedicated_voice_tool(self):
        main = Path("main.py").read_text(encoding="utf-8")
        prompt = Path("core/prompt.txt").read_text(encoding="utf-8")
        builtins = Path("core/tools/builtins.py").read_text(encoding="utf-8")
        self.assertIn('"name": "pet_mode"', main)
        self.assertIn('"pet_mode": lambda args: self.ui_tools.enter_pet_mode(', main)
        self.assertIn('"pet_mode": RiskLevel.LOCAL_CHANGE', builtins)
        self.assertIn("call pet_mode immediately", prompt)


if __name__ == "__main__":
    unittest.main()
