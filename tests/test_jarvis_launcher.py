import json
import ast
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import jarvis_launcher
import wake_word


class LauncherConfigTests(unittest.TestCase):
    def test_defaults_keep_direct_mode_independent_from_vosk(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wake_word.json"
            with patch.object(jarvis_launcher, "CONFIG_FILE", path):
                config = jarvis_launcher.load_config()
        self.assertTrue(config["enabled"])
        self.assertEqual(config["phrases"], ["hey jarvis"])
        self.assertEqual(config["min_wake_rms"], 110)
        self.assertEqual(config["min_confidence"], 0.65)
        self.assertEqual(config["wake_threshold"], 0.35)

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

    def test_wake_phrase_requires_recognition_confidence(self):
        source = Path("wake_word.py").read_text(encoding="utf-8")
        self.assertIn("def result_confidence", source)
        self.assertIn("confidence >= MIN_WAKE_CONFIDENCE", source)
        self.assertIn("windows_session_available()", source)

    def test_dedicated_hey_jarvis_model_is_primary(self):
        source = Path("wake_word.py").read_text(encoding="utf-8")
        requirements = Path("requirements.txt").read_text(encoding="utf-8")
        self.assertIn("def create_openwakeword_model", source)
        self.assertIn('hey_jarvis_v0.1.onnx', source)
        self.assertIn("listen_for_openwakeword", source)
        self.assertIn("score >= OPENWAKEWORD_THRESHOLD", source)
        self.assertIn('WAKE_PHRASES == ("hey jarvis",)', source)
        self.assertIn("Hey Jarvis detectado", source)
        self.assertNotIn("esperando wake up", source)
        self.assertIn("openwakeword==0.6.0", requirements)

    def test_hey_jarvis_does_not_require_an_extra_tail(self):
        source = Path("wake_word.py").read_text(encoding="utf-8")
        config = Path("config/wake_word.example.json").read_text(encoding="utf-8")
        self.assertIn('WAKE_PHRASES = ("hey jarvis",)', source)
        self.assertIn('"hey jarvis"', config)
        self.assertNotIn('"hey jarvis wake up"', config)

    def test_hidden_wake_failures_are_logged(self):
        source = Path("jarvis_launcher.py").read_text(encoding="utf-8")
        self.assertIn('log_dir / "wake_word.log"', source)
        self.assertIn("stderr=subprocess.STDOUT", source)

    def test_wake_requires_exact_confident_final_words(self):
        source = Path("wake_word.py").read_text(encoding="utf-8")
        self.assertIn("class AdaptiveVoiceGate", source)
        self.assertIn("KaldiRecognizer(model, SAMPLE_RATE)", source)
        self.assertNotIn('json.dumps(list(dict.fromkeys([*WAKE_PHRASES', source)
        self.assertIn("result_matches_wake_phrase(raw_result)", source)
        self.assertIn("return sum(scores) / len(scores) if scores else 0.0", source)
        self.assertIn('field="partial"', source)
        self.assertNotIn("Activación rápida", source)
        partial_branch = source[source.index("            else:", source.index("if recognizer.AcceptWaveform")):]
        self.assertNotIn("return True", partial_branch.split("# ─", 1)[0])

    def test_primary_desktop_shortcut_starts_direct_mode(self):
        source = Path("ui.py").read_text(encoding="utf-8")
        primary = source.index('str(desktop / "J.A.R.V.I.S.lnk")')
        nearby = source[primary:primary + 220]
        self.assertIn("target", nearby)
        self.assertIn('--mode direct', nearby)

    def test_direct_launch_stops_only_the_project_wake_detector(self):
        source = Path("jarvis_launcher.py").read_text(encoding="utf-8")
        stop = source[source.index("def stop_wake_detector"):source.index("def load_config")]
        self.assertIn("WAKE_FILE.resolve()", stop)
        self.assertIn("_terminate_processes(supervisors)", stop)
        self.assertIn("_terminate_processes(detectors)", stop)
        terminate = source[source.index("def _terminate_processes"):source.index("def stop_wake_detector")]
        self.assertIn("running.terminate()", terminate)
        self.assertIn("psutil.wait_procs", terminate)
        launch = source[source.index("def launch"):source.index("def build_parser")]
        self.assertIn('if mode == "direct":', launch)
        self.assertIn("stop_wake_detector()", launch)

    def test_direct_launch_restores_wake_detector_after_main_exits(self):
        child = MagicMock()
        child.wait.return_value = 0
        with (
            patch.object(jarvis_launcher, "psutil", None),
            patch.object(jarvis_launcher, "stop_wake_detector") as stop,
            patch.object(jarvis_launcher.subprocess, "Popen", return_value=child),
            patch.object(jarvis_launcher, "start_wake_detector") as restart,
        ):
            result = jarvis_launcher.launch("direct")
        self.assertEqual(result, 0)
        stop.assert_called_once_with()
        child.wait.assert_called_once_with()
        restart.assert_called_once_with()

    def test_direct_launch_restores_wake_detector_after_main_crashes(self):
        child = MagicMock()
        child.wait.side_effect = RuntimeError("native process wait failed")
        with (
            patch.object(jarvis_launcher, "psutil", None),
            patch.object(jarvis_launcher, "stop_wake_detector"),
            patch.object(jarvis_launcher.subprocess, "Popen", return_value=child),
            patch.object(jarvis_launcher, "start_wake_detector") as restart,
            self.assertRaises(RuntimeError),
        ):
            jarvis_launcher.launch("direct")
        restart.assert_called_once_with()

    def test_direct_main_restores_wake_when_no_supervisor_exists(self):
        source = Path("main.py").read_text(encoding="utf-8")
        entry = source[source.index("def main():"):]
        self.assertIn('wake_supervised = os.environ.get("JARVIS_WAKE_SUPERVISED") == "1"', entry)
        self.assertIn("from jarvis_launcher import stop_wake_detector", entry)
        self.assertIn("stop_wake_detector()", entry)
        self.assertIn("from jarvis_launcher import start_wake_detector", entry)
        self.assertIn("start_wake_detector()", entry)

    def test_main_imports_os_used_by_wake_supervision(self):
        tree = ast.parse(Path("main.py").read_text(encoding="utf-8"))
        imported = {
            alias.name
            for node in tree.body
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        self.assertIn("os", imported)

    def test_wake_supervisor_restarts_detector_after_crash(self):
        crashed = MagicMock()
        crashed.wait.return_value = 3221226505
        stopped = MagicMock()
        stopped.wait.return_value = 0
        with (
            patch.object(jarvis_launcher, "load_config", return_value={"enabled": True}),
            patch.object(
                jarvis_launcher.subprocess, "Popen",
                side_effect=[crashed, stopped],
            ) as popen,
            patch.object(jarvis_launcher, "_append_wake_log") as log,
            patch.object(jarvis_launcher.time, "sleep") as sleep,
            patch.object(jarvis_launcher.time, "monotonic", side_effect=[0.0, 1.0, 3.0]),
        ):
            result = jarvis_launcher.supervise_wake_detector()

        self.assertEqual(result, 0)
        self.assertEqual(popen.call_count, 2)
        sleep.assert_called_once_with(2.0)
        log.assert_called_once()

    def test_start_wake_detector_starts_supervisor_not_raw_child(self):
        with (
            patch.object(jarvis_launcher, "load_config", return_value={"enabled": True}),
            patch.object(jarvis_launcher, "_find_project_process", return_value=None),
            patch.object(jarvis_launcher, "_find_wake_supervisor", return_value=None),
            patch.object(jarvis_launcher.subprocess, "Popen") as popen,
        ):
            self.assertTrue(jarvis_launcher.start_wake_detector())

        command = popen.call_args.args[0]
        self.assertIn(str(Path(jarvis_launcher.__file__).resolve()), command)
        self.assertIn("--mode", command)
        self.assertIn("wake", command)
        self.assertNotIn(str(jarvis_launcher.WAKE_FILE), command)

    def test_mark_l_window_and_shortcut_arguments_are_supported(self):
        wake = Path("wake_word.py").read_text(encoding="utf-8")
        ui = Path("ui.py").read_text(encoding="utf-8")
        self.assertIn('"mark li" not in title', wake)
        self.assertIn("sc.Arguments        = args", ui)
        self.assertNotIn("sc.Arguments        = f'\"{args}\"'", ui)

    def test_invalid_configured_microphone_falls_back(self):
        source = Path("wake_word.py").read_text(encoding="utf-8")
        self.assertIn("def validate_input_device", source)
        self.assertIn("sd.check_input_settings", source)
        self.assertIn("usando el dispositivo predeterminado", source)
        self.assertIn("def resolve_input_device", source)
        self.assertIn("preferred_tokens.issubset", source)

    def test_hidden_windows_wake_bootstrap_is_portable(self):
        source = Path("launch_jarvis_wake.vbs").read_text(encoding="utf-8")
        self.assertIn('%LOCALAPPDATA%', source)
        self.assertIn('jarvis_launcher.py', source)
        self.assertIn('--mode wake', source)
        self.assertIn('"\\pythonw.exe"', source)
        self.assertNotIn('commandPrompt', source)
        self.assertNotIn(' /K ', source)
        self.assertIn('shell.Run command, 0, False', source)
        self.assertIn('WScript.Sleep 8000', source)
        self.assertIn('versions = Array("314", "313", "312"', source)

    def test_console_mode_inherits_output_for_live_diagnostics(self):
        source = Path("jarvis_launcher.py").read_text(encoding="utf-8")
        supervisor = source[
            source.index("def supervise_wake_detector"):
            source.index("def load_config")
        ]
        self.assertIn("if console:", supervisor)
        self.assertIn("_python_executable(console=console)", supervisor)
        console_branch = supervisor[
            supervisor.index("if console:"):
            supervisor.index("else:", supervisor.index("if console:"))
        ]
        self.assertNotIn("stdout=", console_branch)
        self.assertNotIn("stderr=", console_branch)
        launch = source[source.index("def launch"):source.index("def build_parser")]
        self.assertIn("elif console:", launch)
        self.assertIn("stop_wake_detector()", launch)

    def test_wake_launch_starts_non_intrusive_pet_mode(self):
        wake = Path("wake_word.py").read_text(encoding="utf-8")
        launch = wake[wake.index("def launch_jarvis"):wake.index("# PROCESAMIENTO DE VOZ")]
        self.assertIn('[str(executable), "-u", str(MAIN_FILE), "--pet"]', launch)
        self.assertNotIn('[str(executable), str(SPLASH_FILE), str(process.pid)]', launch)
        self.assertNotIn("timeout=15.0", launch)
        self.assertIn("Pet Mode visible", launch)
        self.assertIn('log_dir / "jarvis.log"', launch)
        self.assertIn("stderr=subprocess.STDOUT", launch)

    def test_closing_ui_releases_wake_detector(self):
        source = Path("ui.py").read_text(encoding="utf-8")
        close = source[source.index("    def closeEvent"):source.index("    def _show_camera_frame")]
        self.assertIn("self._cam_stop.set()", close)
        self.assertIn("QApplication.quit()", close)
        self.assertIn("os._exit(0)", close)

    def test_terminated_windows_pid_does_not_block_wake(self):
        source = Path("wake_word.py").read_text(encoding="utf-8")
        self.assertIn("def process_is_active", source)
        self.assertIn("GetExitCodeProcess", source)
        self.assertIn("STILL_ACTIVE = 259", source)
        self.assertIn("and process_is_active(process_id)", source)

    def test_wake_state_is_observable_and_model_resets_after_manual_open(self):
        source = Path("wake_word.py").read_text(encoding="utf-8")
        runtime = Path("core/runtime_state.py").read_text(encoding="utf-8")
        self.assertIn('update_runtime_state("wake_word", "listening"', source)
        self.assertIn('update_runtime_state("wake_word", "paused"', source)
        self.assertIn("model.reset()", source)
        self.assertIn("os.replace(temporary_path, target)", runtime)
        self.assertIn("os.fsync(handle.fileno())", runtime)

    def test_console_diagnostics_show_audio_text_scores_and_thresholds(self):
        launcher = Path("jarvis_launcher.py").read_text(encoding="utf-8")
        wake = Path("wake_word.py").read_text(encoding="utf-8")
        self.assertIn('wake_env["JARVIS_WAKE_DIAGNOSTICS"] = "1"', launcher)
        self.assertIn("Vosk parcial=", wake)
        self.assertIn("Vosk final=", wake)
        self.assertIn("score={score:.3f}", wake)
        self.assertIn("mínimo={OPENWAKEWORD_THRESHOLD:.3f}", wake)
        self.assertIn("dinámico={voice_gate.threshold:.0f}", wake)
        self.assertIn("Candidato rechazado:", wake)
        self.assertIn("Hey Jarvis detectado — APROBADO", wake)
        self.assertIn("reset_detector_state(model", wake)

    def test_detector_reset_clears_neural_state_and_stale_audio(self):
        model = MagicMock()
        with patch.object(wake_word, "clear_audio_queue") as clear:
            wake_word.reset_detector_state(model, "test")
        model.reset.assert_called_once_with()
        clear.assert_called_once_with()

    def test_delayed_neural_score_uses_recent_real_voice(self):
        recent_voice = wake_word.RecentVoiceWindow(duration=1.5)

        self.assertTrue(recent_voice.observe(True, now=100.0))
        # Reproduces the real log: OpenWakeWord emitted 0.951 after the spoken
        # block, when the current 80 ms frame had already returned to silence.
        self.assertTrue(recent_voice.observe(False, now=100.8))
        with patch.object(wake_word, "OPENWAKEWORD_THRESHOLD", 0.35):
            self.assertTrue(wake_word.openwakeword_candidate_approved(
                has_recent_voice=True,
                score=0.951,
                session_available=True,
            ))
        self.assertFalse(recent_voice.observe(False, now=101.6))

    def test_delayed_score_still_requires_threshold_and_unlocked_windows(self):
        with patch.object(wake_word, "OPENWAKEWORD_THRESHOLD", 0.35):
            self.assertFalse(wake_word.openwakeword_candidate_approved(
                has_recent_voice=True,
                score=0.349,
                session_available=True,
            ))
            self.assertFalse(wake_word.openwakeword_candidate_approved(
                has_recent_voice=True,
                score=0.951,
                session_available=False,
            ))


if __name__ == "__main__":
    unittest.main()
