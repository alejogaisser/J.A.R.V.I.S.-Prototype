from pathlib import Path
import unittest


class ContextWorkspaceRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path("ui.py").read_text(encoding="utf-8")

    def test_camera_device_can_be_selected_and_persisted(self):
        self.assertIn("def _show_camera_selector", self.source)
        self.assertIn('update_settings({"camera_index": int(index)})', self.source)
        self.assertIn("configure_capture(cap, cv2, profile)", self.source)
        self.assertIn("profile.jpeg_quality", self.source)

    def test_face_regions_are_removed_before_hand_contours(self):
        face_pos = self.source.index("detectMultiScale")
        contour_pos = self.source.index("cv2.findContours", face_pos)
        self.assertLess(face_pos, contour_pos)
        self.assertIn("mask[y1:y2, x1:x2] = 0", self.source)

    def test_unstable_rotation_was_removed(self):
        self.assertNotIn("cv2.fitEllipse", self.source)
        self.assertIn('"rotation": 0.0', self.source)

    def test_context_workspace_supports_mouse_and_explicit_hand_mode(self):
        for declaration in (
            "def set_context",
            "def clear_context",
            "def mouseMoveEvent",
            "def wheelEvent",
            'self._camera_mode == "hand"',
            '"gesture": "MOVE"',
        ):
            self.assertIn(declaration, self.source)
        self.assertNotIn("PINZA: ZOOM", self.source)
        self.assertNotIn("PUÑO · CONFIRMAR", self.source)

    def test_normal_mode_skips_hand_processing(self):
        self.assertIn('self._camera_mode == "hand"', self.source)
        self.assertIn("now - self._last_gesture_action >= 0.10", self.source)
        self.assertIn('self._camera_mode = "normal"', self.source)
        self.assertIn("def set_camera_view", self.source)

    def test_chat_and_files_are_distinct_animated_views(self):
        self.assertIn("self._panel_stack = QStackedWidget()", self.source)
        self.assertIn("self._panel_stack.addWidget(chat)", self.source)
        self.assertIn("self._panel_stack.addWidget(files)", self.source)
        self.assertIn("QGraphicsOpacityEffect", self.source)
        self.assertIn("QParallelAnimationGroup", self.source)
        self.assertIn("def _show_panel_view", self.source)

    def test_context_results_are_routed_to_hud(self):
        self.assertIn("self.hud.set_context(title, text, image_path)", self.source)
        self.assertIn("if self._camera_mode == \"hand\" and self.context_active", self.source)

    def test_camera_workspace_supports_multiple_clickable_tabs(self):
        self.assertIn("self._contexts: list[dict] = []", self.source)
        self.assertIn("self._context_tab_rects", self.source)
        self.assertIn("self._load_context(index)", self.source)
        self.assertIn("self._contexts = self._contexts[-5:]", self.source)

    def test_camera_frames_avoid_per_frame_jpeg_round_trip(self):
        self.assertIn("_cam_frame_sig  = pyqtSignal(object)", self.source)
        self.assertIn("QImage.Format.Format_BGR888", self.source)
        self.assertEqual(self.source.count("cv2.imencode("), 1)
        self.assertIn("now - self._last_gesture_action >= 0.10", self.source)

    def test_camera_lifecycle_is_queued_and_single_instance(self):
        self.assertIn("_camera_request_sig = pyqtSignal(bool)", self.source)
        self.assertIn("self._win._camera_request_sig.emit(True)", self.source)
        self.assertIn("self._win._camera_request_sig.emit(False)", self.source)
        self.assertIn("self._cam_lock", self.source)
        self.assertIn("self._cam_generation", self.source)
        self.assertIn("self._cam_thread is threading.current_thread()", self.source)

    def test_memory_button_has_a_reachable_handler(self):
        toggle = self.source[
            self.source.index("    def _toggle_v1_panel"):
            self.source.index("    def _show_panel_view")
        ]
        self.assertIn('if panel == "memory"', toggle)
        self.assertIn("self.show_memory_graph()", toggle)

    def test_visible_interface_copy_is_english(self):
        for spanish in (
            "CONVERSACIÓN", "ARCHIVOS", "Cámara", "Memoria", "INTERRUMPIR",
            "MODO NORMAL", "BUSCANDO MANO", "Pantalla completa", "SISTEMA ACTIVO",
        ):
            self.assertNotIn(spanish, self.source)
        self.assertIn("ALWAYS LISTENING  ·  ACTIVE", self.source)

    def test_window_starts_and_returns_to_full_screen(self):
        constructor = self.source[
            self.source.index("class JarvisUI"):
            self.source.index("    @property", self.source.index("class JarvisUI"))
        ]
        self.assertIn("self._win.showFullScreen()", constructor)
        self.assertNotIn("self._win.showNormal()", constructor)
        self.assertIn("SW_RESTORE = 9", constructor)
        self.assertIn("~Qt.WindowState.WindowMinimized", constructor)
        self.assertIn("Qt.WindowState.WindowFullScreen", constructor)

    def test_backend_starts_after_first_visible_frame(self):
        main = Path("main.py").read_text(encoding="utf-8")
        self.assertIn("ui.start_after_visible(start_runner_after_first_frame)", main)
        self.assertIn("def start_after_visible", self.source)
        self.assertLess(
            main.index('ui = JarvisUI("face.png")'),
            main.index("ui.start_after_visible(start_runner_after_first_frame)"),
        )

    def test_audio_event_loop_metrics_and_camera_load_after_first_paint(self):
        main = Path("main.py").read_text(encoding="utf-8")
        eager_main = main[:main.index("def _load_asyncio_dependency")]
        self.assertNotIn("import asyncio", eager_main)
        self.assertNotIn("import sounddevice", eager_main)
        runner = main[main.index("    def runner()"):
                      main.index("    def start_runner_after_first_frame")]
        self.assertLess(
            runner.index("_load_runtime_dependencies()"),
            runner.index("JarvisLive(ui,"),
        )
        self.assertIn("QTimer.singleShot(250, _metrics.start)", self.source)
        gesture_init = self.source[
            self.source.index("    def __init__(self):", self.source.index("class HandGestureTracker")):
            self.source.index("    def _ensure_face_detector", self.source.index("class HandGestureTracker"))
        ]
        self.assertNotIn("import cv2", gesture_init)
        geo = self.source[
            self.source.index("    def _locate_geo_query"):
            self.source.index("    def _apply_geo_focus")
        ]
        self.assertIn("from actions.open_geo import OpenGeoClient", geo)

    def test_panel_switches_skip_layout_animation_while_speaking(self):
        for method in (
            "def _animate_system_panel", "def _animate_side_panel",
            "def _animate_memory_panel",
        ):
            start = self.source.index(method)
            body = self.source[start:start + 900]
            self.assertIn("if self.hud.speaking:", body)

    def test_rapid_panel_changes_cancel_and_release_old_animations(self):
        self.assertIn("def _discard_animation", self.source)
        self.assertIn('self._discard_animation("_panel_motion")', self.source)
        self.assertIn('self._discard_animation("_memory_animation")', self.source)
        self.assertIn('self._discard_animation("_system_animation")', self.source)
        self.assertIn("if self._panel_motion is not motion:", self.source)
        self.assertIn("motion.deleteLater()", self.source)

    def test_delayed_startup_focus_cannot_override_pet_mode(self):
        self.assertIn('self._surface_mode = "pet" if self._start_in_pet_mode else "main"', self.source)
        foreground = self.source[
            self.source.index("    def _bring_main_window_to_front"):
            self.source.index("    def _open_from_pet")
        ]
        self.assertIn('if self._surface_mode != "main":', foreground)

    def test_all_workspaces_share_the_holographic_surface_language(self):
        self.assertIn("class HolographicSurface(QWidget)", self.source)
        self.assertIn('HolographicSurface("left")', self.source)
        self.assertIn('HolographicSurface("right")', self.source)
        self.assertIn('HolographicSurface("full")', self.source)
        self.assertIn("sweep_y = self._phase", self.source)

    def test_system_metrics_keep_live_graph_history(self):
        metric = self.source[
            self.source.index("class MetricBar"):
            self.source.index("class LogWidget")
        ]
        self.assertIn("self._history: list[float]", metric)
        self.assertIn("graph = QPainterPath()", metric)
        self.assertIn("self._history[-23:]", metric)

    def test_files_memory_and_context_have_distinct_holographic_details(self):
        self.assertIn("scan_y = pad + 8", self.source)
        self.assertIn('for label in ("IMAGE", "DOC", "AUDIO", "CODE")', self.source)
        self.assertIn('for label in ("IDENTITY", "PREFERENCES", "PROJECT", "LONG-TERM")', self.source)
        self.assertIn("chip.setEnabled(False)", self.source)
        self.assertIn("live_scan_y = card.top()", self.source)
        self.assertIn("context_glass = QLinearGradient", self.source)

    def test_camera_workspace_has_visual_reticle_without_changing_capture(self):
        self.assertIn("Full-frame optical reticle", self.source)
        self.assertIn("OPTICAL FEED / ZOOM", self.source)
        self.assertIn("optical_scan = QLinearGradient", self.source)
        self.assertIn("guarded capture thread", self.source)


if __name__ == "__main__":
    unittest.main()
