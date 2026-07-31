from __future__ import annotations

import base64
import hashlib
import hmac
import ast
from pathlib import Path
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from core.security import VoiceConfirmationGate, confirmation_request, safe_tool_args
from actions.computer_control import _scale_image_point
from actions.file_controller import create_file, file_controller, open_file, read_file, write_file
from core.model_fallback import generate_with_model_fallback, is_transient_api_error
from dashboard.server import _decrypt_cbc, _derive_keys


class ToolPolicyTests(unittest.TestCase):
    def test_read_only_file_action_does_not_prompt(self):
        for action in ("read", "inspect", "browse", "inspect_folder", "read_folder"):
            with self.subTest(action=action):
                self.assertIsNone(confirmation_request("file_controller", {"action": action}))

    def test_destructive_and_external_actions_prompt(self):
        cases = [
            ("file_controller", {"action": "delete", "path": "documents"}),
            ("send_message", {"receiver": "Test", "platform": "Signal"}),
            ("computer_settings", {"description": "restart the computer"}),
            ("code_helper", {"action": "run", "file_path": "script.py"}),
            ("dev_agent", {"description": "build an app"}),
            ("game_updater", {"action": "install", "game_name": "Test"}),
        ]
        for tool_name, args in cases:
            with self.subTest(tool_name=tool_name, args=args):
                self.assertIsNotNone(confirmation_request(tool_name, args))

    def test_sensitive_log_values_are_redacted(self):
        safe = safe_tool_args({"message_text": "secret", "receiver": "Alice"})
        self.assertEqual(safe["message_text"], "[redacted]")
        self.assertEqual(safe["receiver"], "Alice")

    def test_windows_launcher_does_not_use_shell_true(self):
        tree = ast.parse(Path("actions/open_app.py").read_text(encoding="utf-8"))
        launcher = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "_launch_windows"
        )
        for call in (node for node in ast.walk(launcher) if isinstance(node, ast.Call)):
            for keyword in call.keywords:
                self.assertFalse(
                    keyword.arg == "shell"
                    and isinstance(keyword.value, ast.Constant)
                    and keyword.value.value is True
                )

    def test_main_run_does_not_start_dashboard(self):
        tree = ast.parse(Path("main.py").read_text(encoding="utf-8"))
        run_method = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "run"
        )
        serve_calls = [
            node for node in ast.walk(run_method)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "serve"
        ]
        self.assertEqual(serve_calls, [])

    def test_confirmation_ui_popup_was_removed(self):
        source = Path("ui.py").read_text(encoding="utf-8")
        self.assertNotIn("QMessageBox", source)
        self.assertNotIn("def confirm_action", source)


class VoiceConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.now = [100.0]
        self.gate = VoiceConfirmationGate(
            ttl_seconds=60,
            clock=lambda: self.now[0],
        )
        self.args = {"action": "delete", "path": "documents", "name": "old.txt"}

    def _stage(self, args=None):
        return self.gate.authorize_or_stage(
            "file_controller",
            args or self.args,
            "Approve file-system change?",
            "Action: delete",
        )

    def test_spoken_yes_authorizes_exactly_one_matching_action(self):
        self.assertFalse(self._stage())

    def test_natural_spoken_yes_is_accepted(self):
        for phrase in ("Sí, claro", "si dale", "Yes, go ahead", "confirmo la acción"):
            with self.subTest(phrase=phrase):
                self.gate.clear()
                self.assertFalse(self._stage())
                self.assertEqual(self.gate.observe(phrase), "approved")

    def test_approval_phrase_with_denial_is_not_accepted(self):
        self.assertFalse(self._stage())
        self.assertIsNone(self.gate.observe("sí pero no lo hagas"))
        self.assertEqual(self.gate.observe("Sí, por favor"), "approved")
        self.assertTrue(self._stage())
        self.assertFalse(self._stage())

    def test_approval_does_not_authorize_a_different_action(self):
        self.assertFalse(self._stage())
        self.assertEqual(self.gate.observe("yes"), "approved")
        other = {"action": "delete", "path": "documents", "name": "other.txt"}
        self.assertFalse(self._stage(other))

    def test_spoken_no_cancels_the_pending_action(self):
        self.assertFalse(self._stage())
        self.assertEqual(self.gate.observe("no gracias"), "denied")
        self.assertFalse(self.gate.has_pending)
        self.assertFalse(self._stage())

    def test_approval_expires(self):
        self.assertFalse(self._stage())
        self.now[0] += 61
        self.assertIsNone(self.gate.observe("yes"))
        self.assertFalse(self.gate.has_pending)


class AudioVisionRegressionTests(unittest.TestCase):
    def test_live_microphone_policy_prioritizes_clear_speech(self):
        source = Path("main.py").read_text(encoding="utf-8")
        self.assertIn("LIVE MICROPHONE TURN POLICY", source)
        self.assertIn("silence_duration_ms=1500", source.replace(" ", ""))
        self.assertIn("Prioritize hearing and answering the user", source)
        self.assertIn("ask the user once, briefly and naturally, to repeat it", source)
        self.assertIn("never announce that such noise was ignored", source)
        self.assertIn("START_SENSITIVITY_HIGH", source)
        self.assertIn("prefix_padding_ms=500", source)

    def test_close_app_matches_spoken_alias_title_and_process(self):
        from actions.computer_settings import _window_candidate_score

        self.assertGreater(
            _window_candidate_score("la calculadora", "Calculator", "CalculatorApp.exe"),
            0,
        )
        self.assertGreater(
            _window_candidate_score("spotify", "Song title", "Spotify.exe"),
            0,
        )
        self.assertGreater(
            _window_candidate_score("bloc de notas", "untitled - Notepad", "Notepad.exe"),
            0,
        )
        self.assertEqual(
            _window_candidate_score("spotify", "Calculator", "CalculatorApp.exe"),
            0,
        )

    def test_voice_interruption_preserves_the_new_user_turn(self):
        tree = ast.parse(Path("main.py").read_text(encoding="utf-8"))
        receive = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "_receive_audio"
        )
        vad_interrupt = next(
            node for node in ast.walk(receive)
            if isinstance(node, ast.If)
            and ast.unparse(node.test) == "sc.interrupted"
        )
        body = ast.unparse(vad_interrupt)
        self.assertIn("await self._flush_playback('VAD')", body)
        self.assertNotIn("self._interrupted = True", body)

    def test_enter_releases_command_focus_without_changing_toggle(self):
        source = Path("ui.py").read_text(encoding="utf-8")
        self.assertIn("self._input.clearFocus()", source)
        send_body = source[source.index("    def _send(self):"):source.index("    def _apply_state", source.index("    def _send(self):"))]
        self.assertNotIn("_toggle_talk", send_body)

    def test_windows_window_uses_jarvis_taskbar_identity_and_icon(self):
        source = Path("ui.py").read_text(encoding="utf-8")
        self.assertIn("SetCurrentProcessExplicitAppUserModelID", source)
        self.assertIn('CONFIG_DIR / "jarvis.ico"', source)
        self.assertIn("self.setWindowIcon(QIcon(str(icon_path)))", source)

    def test_escape_signals_model_and_flushes_local_playback(self):
        source = Path("main.py").read_text(encoding="utf-8")
        self.assertIn("_interrupt_model_turn", source)
        self.assertIn("[USER_INTERRUPT]", source)
        self.assertIn("types.ActivityHandling.START_OF_ACTIVITY_INTERRUPTS", source)

    def test_camera_frames_continue_until_explicit_close(self):
        source = Path("main.py").read_text(encoding="utf-8")
        ui = Path("ui.py").read_text(encoding="utf-8")
        self.assertIn("set_camera_frame_callback(self._stream_camera_frame)", source)
        self.assertIn("def _stream_camera_frame", source)
        self.assertIn("async def _send_camera_frame", source)
        self.assertIn("video=types.Blob", source)
        self.assertNotIn("screen_process_action", source)
        self.assertIn("now - self._last_camera_ai_frame >= 1.0", ui)

    def test_camera_uses_one_audio_session(self):
        source = Path("main.py").read_text(encoding="utf-8")
        camera_branch = source[source.index('if angle == "camera"'):source.index('else:', source.index('if angle == "camera"'))]
        self.assertIn('analyze_visual(user_text, "camera")', camera_branch)
        self.assertIn("self.ui.start_camera_stream()", camera_branch)
        self.assertNotIn("screen_process_action", camera_branch)

    def test_shutdown_waits_for_farewell_playback(self):
        source = Path("main.py").read_text(encoding="utf-8")
        self.assertIn("[SHUTDOWN_SCHEDULED]", source)
        self.assertIn("self._runtime.lifecycle.request_shutdown(", source)
        self.assertIn(
            "self._runtime.lifecycle.observe_farewell_audio()",
            source,
        )
        self.assertIn(
            "self._runtime.lifecycle.observe_playback_drained()",
            source,
        )
        self.assertIn("_shutdown_fallback_timeout", source)
        self.assertIn("self._finish_shutdown_after_audio()", source)
        self.assertNotIn('self.speak("Goodbye, sir.")', source)
    def test_vision_uses_fallback_model_after_503(self):
        calls = []

        class Models:
            def generate_content(self, model, contents):
                calls.append(model)
                if len(calls) == 1:
                    raise RuntimeError("503 UNAVAILABLE: high demand")
                return "fallback response"

        client = type("Client", (), {"models": Models()})()
        response, model = generate_with_model_fallback(
            client, ["image", "prompt"], ("gemini-3.5-flash", "gemini-3.1-flash-lite")
        )
        self.assertEqual(response, "fallback response")
        self.assertEqual(model, "gemini-3.1-flash-lite")
        self.assertEqual(calls, ["gemini-3.5-flash", "gemini-3.1-flash-lite"])

    def test_vision_replaces_retired_configured_fallback(self):
        vision_source = Path("actions/screen_processor.py").read_text(encoding="utf-8")
        self.assertIn('_RETIRED_VISION_MODELS = {"gemini-2.5-flash"}', vision_source)
        self.assertIn("if model in _RETIRED_VISION_MODELS else model", vision_source)

    def test_vision_does_not_hide_permanent_api_errors(self):
        self.assertFalse(is_transient_api_error(RuntimeError("403 PERMISSION_DENIED")))

    def test_briefing_phase_2_waits_for_phase_1_playback(self):
        source = Path("main.py").read_text(encoding="utf-8")
        self.assertIn("await asyncio.wait_for(phase1_done.wait(), timeout=30.0)", source)
        self.assertIn("self._briefing_phase1_done.set()", source)
        self.assertNotIn("await asyncio.sleep(3.0)", source)
        briefing = source[
            source.index("    async def _send_startup_briefing"):
            source.index("    async def _briefing_news_phase")
        ]
        self.assertIn("await asyncio.sleep(0)", briefing)
        self.assertLess(
            briefing.index("await asyncio.wait_for(phase1_done.wait()"),
            briefing.index("self._briefing_sent = True"),
        )
        self.assertIn("if not self._briefing_phase1_played:", briefing)
        self.assertIn("self._briefing_inflight = False", briefing)

        flush = source[
            source.index("    async def _flush_playback"):
            source.index("    def speak(", source.index("    async def _flush_playback"))
        ]
        self.assertIn("self._briefing_phase1_played = False", flush)

        playback = source[
            source.index("    async def _play_audio"):
            source.index("    def _finish_shutdown_after_audio")
        ]
        self.assertIn("self._briefing_phase1_played = True", playback)

    def test_gemini_sdk_loads_after_ui_module_and_off_the_qt_startup_path(self):
        source = Path("main.py").read_text(encoding="utf-8")
        self.assertNotIn("from google import genai\n", source[:source.index("class JarvisLive")])
        self.assertIn("def _load_live_sdk()", source)
        init = source[
            source.index("class JarvisLive"):
            source.index("    def _open_memory_graph")
        ]
        self.assertIn("search_provider: GroundedSearchProvider | None = None", init)
        self.assertIn("runtime_events: EventBus | None = None", init)
        self.assertIn("_load_live_sdk()", init)

    def test_only_escape_interrupts_model_playback(self):
        source = Path("main.py").read_text(encoding="utf-8")
        self.assertIn("types.ActivityHandling.START_OF_ACTIVITY_INTERRUPTS", source)
        self.assertIn("and not jarvis_speaking", source)
        self.assertIn('self._flush_playback("ESC")', source)
        self.assertNotIn("types.ActivityHandling.NO_INTERRUPTION", source)

    def test_realtime_audio_prefers_fresh_mic_frames(self):
        source = Path("main.py").read_text(encoding="utf-8")
        self.assertIn("asyncio.Queue(maxsize=25)", source)
        self.assertIn("self.out_queue.get_nowait()", source)
        self.assertIn(
            "if jarvis_speaking or self._runtime.audio.interrupted:",
            source,
        )

    def test_microphone_stream_recovers_without_reconnecting_session(self):
        tree = ast.parse(Path("main.py").read_text(encoding="utf-8"))
        listen = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "_listen_audio"
        )
        self.assertTrue(any(isinstance(node, ast.While) for node in ast.walk(listen)))
        self.assertIn("Microphone lost; reconnecting", ast.unparse(listen))

    def test_idle_microphone_ends_only_audio_stream_and_preserves_session(self):
        source = Path("main.py").read_text(encoding="utf-8")
        reset = source[source.index("    async def _close_idle_audio_stream"):source.index(
            "    async def _receive_audio"
        )]
        self.assertIn("audio_stream_end=True", reset)
        self.assertIn('self.ui.set_state("SLEEPING")', reset)
        self.assertNotIn("self.session = None", reset)
        self.assertIn("microphone callback stalled", source)

    def test_heavy_actions_load_after_ui_construction(self):
        source = Path("main.py").read_text(encoding="utf-8")
        self.assertIn("def _load_action_dependencies()", source)
        self.assertLess(
            source.index('ui = JarvisUI("face.png")'),
            source.index("JarvisLive(ui,"),
        )

    def test_escape_uses_thread_safe_playback_flush(self):
        tree = ast.parse(Path("main.py").read_text(encoding="utf-8"))
        interrupt = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "interrupt"
        )
        attrs = {
            node.attr for node in ast.walk(interrupt) if isinstance(node, ast.Attribute)
        }
        self.assertIn("call_soon_threadsafe", attrs)
        self.assertNotIn("get_nowait", attrs)

    def test_escape_has_bounded_microphone_recovery(self):
        source = Path("main.py").read_text(encoding="utf-8")
        interrupt = source[source.index("    async def _interrupt_model_turn"):source.index(
            "    def _reset_output_stream"
        )]
        self.assertIn("await asyncio.sleep(0.75)", interrupt)
        self.assertIn("self._release_interrupt(serial)", interrupt)
        self.assertIn(
            "self._runtime.audio.release_interrupt(serial)",
            interrupt,
        )

    def test_listening_defaults_on_and_escape_works_outside_jarvis(self):
        source = Path("ui.py").read_text(encoding="utf-8")
        self.assertIn('self._listen_mode       = "always"', source)
        self.assertIn("Qt.ShortcutContext.ApplicationShortcut", source)
        self.assertIn("GetAsyncKeyState(0x1B)", source)
        self.assertIn("and self.hud.speaking", source)

    def test_dpi_coordinate_scaling(self):
        self.assertEqual(
            _scale_image_point(1920, 1080, (3840, 2160), (2560, 1440)),
            (1280, 720),
        )
        self.assertIsNone(_scale_image_point(4000, 10, (3840, 2160), (2560, 1440)))

    def test_screen_analysis_is_atomic_and_visual_mouse_is_declared(self):
        main_source = Path("main.py").read_text(encoding="utf-8")
        vision_source = Path("actions/screen_processor.py").read_text(encoding="utf-8")
        self.assertIn('"name": "visual_mouse"', main_source)
        self.assertIn("analyze_visual(user_text, angle)", main_source)
        self.assertNotIn("_pending_vision", main_source)
        self.assertIn('_DEFAULT_VISION_MODEL = "gemini-3.5-flash"', vision_source)
        self.assertIn('_DEFAULT_VISION_FALLBACK_MODEL = "gemini-3.1-flash-lite"', vision_source)


class FileAndDesktopRegressionTests(unittest.TestCase):
    def test_inspect_folder_discovers_and_reads_nested_arduino_sketch(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory, patch(
            "actions.file_controller._is_protected_path", return_value=False
        ):
            project = Path(directory) / "Robot" / "src"
            project.mkdir(parents=True)
            (project / "Robot.ino").write_text("void setup() {}", encoding="utf-8")
            result = file_controller({"action": "inspect", "path": str(Path(directory) / "Robot")})
            self.assertIn("src\\Robot.ino", result)
            self.assertIn("void setup() {}", result)

    def test_nested_shortcut_path_resolves_below_known_folder(self):
        from actions.file_controller import _resolve_path
        with patch("actions.file_controller._get_documents", return_value=Path("C:/Users/Test/Documents")):
            resolved = _resolve_path("documents/Arduino/Robot/Robot.ino")
        self.assertEqual(resolved, Path("C:/Users/Test/Documents/Arduino/Robot/Robot.ino"))

    def test_read_folder_inspects_project_instead_of_rejecting_it(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory, patch(
            "actions.file_controller._is_protected_path", return_value=False
        ):
            (Path(directory) / "Blink.ino").write_text("void loop() {}", encoding="utf-8")
            self.assertIn("void loop() {}", read_file(directory))

    def test_create_folder_accepts_common_model_aliases(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory, patch(
            "actions.file_controller._is_protected_path", return_value=False
        ):
            result = file_controller({
                "action": "mkdir", "path": directory, "folder_name": "Nueva carpeta"
            })
            self.assertIn("Local folder created and verified", result)
            self.assertTrue((Path(directory) / "Nueva carpeta").is_dir())

    def test_file_create_write_read_and_open_pipeline(self):
        import tempfile
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory, patch(
            "actions.file_controller._is_protected_path", return_value=False
        ):
            path = Path(directory)
            self.assertIn("Local file created and verified", create_file(str(path), "qa.txt", "one"))
            self.assertIn("Written to", write_file(str(path), "qa.txt", "two"))
            self.assertEqual(read_file(str(path), "qa.txt"), "two")
            with patch("actions.file_controller.os.startfile") as startfile:
                self.assertIn("Opened", open_file(str(path), "qa.txt"))
                startfile.assert_called_once()

    def test_tmp_alias_resolves_to_the_project_temp_folder(self):
        from actions.file_controller import _resolve_path

        expected = Path("tmp").resolve()
        self.assertEqual(_resolve_path("tmp").resolve(), expected)
        self.assertEqual(_resolve_path("jarvis_tmp").resolve(), expected)

    def test_create_file_does_not_duplicate_name_present_in_path(self):
        import tempfile
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as directory, patch(
            "actions.file_controller._is_protected_path", return_value=False
        ):
            target = Path(directory) / "same.txt"
            result = create_file(str(target), "same.txt", "verified")
            self.assertEqual(target.read_text(encoding="utf-8"), "verified")
            self.assertFalse((target / "same.txt").exists())
            self.assertIn(str(target.resolve()), result)

    def test_remote_drive_folder_names_block_local_write_fallback(self):
        source = Path("main.py").read_text(encoding="utf-8")
        self.assertIn("self._remote_drive_folders", source)
        self.assertIn('"error": "wrong_storage_provider"', source)
        self.assertIn("Blocked local write", source)

    def test_power_actions_require_central_confirmation_but_accept_preapproval(self):
        source = Path("main.py").read_text(encoding="utf-8")
        settings = Path("actions/computer_settings.py").read_text(encoding="utf-8")
        self.assertIn('args["confirmed"] = "yes"', source)
        self.assertIn('if confirmed not in ("yes", "true", "1", "confirm")', settings)
        self.assertIn("result.returncode != 0", settings)

    def test_spoken_confirmation_is_short(self):
        source = Path("main.py").read_text(encoding="utf-8")
        self.assertIn('question = "Confirm action?"', source)
        self.assertNotIn('question = "Confirm action? Yes or no."', source)
        self.assertIn("[VOICE_CONFIRMATION_REQUIRED] Say exactly", source)
        self.assertNotIn("The application will execute the action automatically", source)

    def test_visual_mouse_prefers_uia_before_image_grounding(self):
        source = Path("actions/computer_control.py").read_text(encoding="utf-8")
        self.assertIn("native = _uia_find(description)", source)
        self.assertIn('Desktop(backend="uia")', source)

    def test_sensitive_paths_are_immutably_denied(self):
        from actions.file_controller import _is_safe_path
        home = Path.home()
        for path in (
            home / "AppData" / "Local" / "secret.txt",
            home / ".ssh" / "id_rsa",
            home / "Documents" / ".env",
            home / "Documents" / "api_keys.json",
            home / "Documents" / "certificate.pfx",
        ):
            with self.subTest(path=path):
                self.assertFalse(_is_safe_path(path))

    def test_permission_manager_is_declared_and_protected(self):
        main_source = Path("main.py").read_text(encoding="utf-8")
        self.assertIn('"name": "permission_manager"', main_source)
        self.assertIn("immutable minimum", main_source)
        self.assertIn('question = "Confirm action?"', main_source)


class DashboardCryptoTests(unittest.TestCase):
    def _encrypt(self, session_key: str, plaintext: str) -> tuple[bytes, bytes, str]:
        aes_key, mac_key = _derive_keys(session_key)
        iv = bytes(range(16))
        padder = padding.PKCS7(128).padder()
        padded = padder.update(plaintext.encode("utf-8")) + padder.finalize()
        enc = Cipher(algorithms.AES(aes_key), modes.CBC(iv)).encryptor()
        ciphertext = enc.update(padded) + enc.finalize()
        tag = hmac.new(mac_key, iv + ciphertext, hashlib.sha256).digest()
        payload = base64.b64encode(iv + ciphertext + tag).decode("ascii")
        return aes_key, mac_key, payload

    def test_authenticated_payload_decrypts(self):
        aes_key, mac_key, payload = self._encrypt("ABCDEFG234", "hello")
        self.assertEqual(_decrypt_cbc(aes_key, mac_key, payload), "hello")

    def test_tampered_payload_is_rejected(self):
        aes_key, mac_key, payload = self._encrypt("ABCDEFG234", "hello")
        raw = bytearray(base64.b64decode(payload))
        raw[20] ^= 1
        tampered = base64.b64encode(raw).decode("ascii")
        with self.assertRaises(ValueError):
            _decrypt_cbc(aes_key, mac_key, tampered)


if __name__ == "__main__":
    unittest.main()
