from __future__ import annotations

import base64
import hashlib
import hmac
import ast
from pathlib import Path
import unittest

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from core.security import VoiceConfirmationGate, confirmation_request, safe_tool_args
from actions.computer_control import _scale_image_point
from core.model_fallback import generate_with_model_fallback, is_transient_api_error
from dashboard.server import _decrypt_cbc, _derive_keys


class ToolPolicyTests(unittest.TestCase):
    def test_read_only_file_action_does_not_prompt(self):
        self.assertIsNone(confirmation_request("file_controller", {"action": "read"}))

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
    def test_shutdown_waits_for_farewell_playback(self):
        source = Path("main.py").read_text(encoding="utf-8")
        self.assertIn("[SHUTDOWN_SCHEDULED]", source)
        self.assertIn("if self._shutdown_after_turn:", source)
        self.assertIn("self._shutdown_farewell_audio_seen = True", source)
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

    def test_only_escape_interrupts_model_playback(self):
        source = Path("main.py").read_text(encoding="utf-8")
        self.assertIn("types.ActivityHandling.NO_INTERRUPTION", source)
        self.assertIn("and not jarvis_speaking", source)
        self.assertIn('self._flush_playback("ESC")', source)
        self.assertNotIn("types.ActivityHandling.START_OF_ACTIVITY_INTERRUPTS", source)

    def test_realtime_audio_prefers_fresh_mic_frames(self):
        source = Path("main.py").read_text(encoding="utf-8")
        self.assertIn("asyncio.Queue(maxsize=25)", source)
        self.assertIn("self.out_queue.get_nowait()", source)
        self.assertIn("if jarvis_speaking or self._interrupted:", source)

    def test_microphone_stream_recovers_without_reconnecting_session(self):
        tree = ast.parse(Path("main.py").read_text(encoding="utf-8"))
        listen = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "_listen_audio"
        )
        self.assertTrue(any(isinstance(node, ast.While) for node in ast.walk(listen)))
        self.assertIn("Microphone lost; reconnecting", ast.unparse(listen))

    def test_heavy_actions_load_after_ui_construction(self):
        source = Path("main.py").read_text(encoding="utf-8")
        self.assertIn("def _load_action_dependencies()", source)
        self.assertLess(source.index('ui = JarvisUI("face.png")'), source.index("JarvisLive(ui)"))

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
