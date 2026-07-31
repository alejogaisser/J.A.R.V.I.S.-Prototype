from __future__ import annotations

import ctypes
import json
import math
import os
import platform
import queue
import re
import subprocess
import sys
import threading
import time
import unicodedata
from collections.abc import Callable
from pathlib import Path
from ctypes import wintypes
from typing import Any

import numpy as np
import psutil
import sounddevice as sd
from vosk import KaldiRecognizer, Model as VoskModel, SetLogLevel
from jarvis_launcher import load_config
from core.runtime_state import update_runtime_state

try:
    from openwakeword.model import Model as OpenWakeWordModel
except ImportError:
    OpenWakeWordModel = None


# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURACIÓN
# ─────────────────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent
MAIN_FILE = BASE_DIR / "main.py"
SPLASH_FILE = BASE_DIR / "startup_splash.py"

MODEL_PATH = (
    BASE_DIR
    / "models"
    / "vosk-model-small-en-us-0.15"
)
OPENWAKEWORD_DIR = BASE_DIR / "models" / "openwakeword"
OPENWAKEWORD_MODEL_PATH = OPENWAKEWORD_DIR / "hey_jarvis_v0.1.onnx"
OPENWAKEWORD_MELSPEC_PATH = OPENWAKEWORD_DIR / "melspectrogram.onnx"
OPENWAKEWORD_EMBEDDING_PATH = OPENWAKEWORD_DIR / "embedding_model.onnx"

SAMPLE_RATE = 16_000
BLOCK_SIZE = 4_000
OPENWAKEWORD_BLOCK_SIZE = 1_280
MIN_WAKE_RMS = 45
INPUT_DEVICE = None
MIN_WAKE_CONFIDENCE = 0.65
OPENWAKEWORD_THRESHOLD = 0.35
WAKE_AUDIO_WINDOW = 3.0
OPENWAKEWORD_FOLLOWUP_THRESHOLD = 0.05
NOISE_MULTIPLIER = 2.8
DIAGNOSTIC_INTERVAL = 0.5
DIAGNOSTICS_ENABLED = os.environ.get("JARVIS_WAKE_DIAGNOSTICS") == "1"
STREAM_STALL_TIMEOUT = 2.0
MIC_RETRY_DELAY = 1.0
STATUS_HEARTBEAT_INTERVAL = 15.0
VOSK_FOLLOWUP_WINDOW = 4.0

WAKE_PHRASES = ("hey jarvis",)
VOSK_WAKE_ALIASES = (
    "hey service",
    "hey harvest",
    "hey travis",
    "hey charles",
)

# Oculta los mensajes internos de Vosk.
SetLogLevel(-1)

_audio_queue: queue.Queue[bytes] = queue.Queue(maxsize=30)
_instance_mutex = None
_diagnostic_last_print = 0.0
_audio_last_callback = 0.0


class AudioStreamStalled(RuntimeError):
    """Raised when PortAudio stays open but stops delivering microphone data."""


class AsyncVoskFallback:
    """Load the heavier Vosk fallback without delaying OpenWakeWord readiness."""

    def __init__(
        self,
        model_path: Path,
        model_factory: Callable[[str], Any] = VoskModel,
    ) -> None:
        self._model_path = Path(model_path)
        self._model_factory = model_factory
        self._model: Any | None = None
        self._error: Exception | None = None
        self._ready = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> "AsyncVoskFallback":
        """Start one daemon loader and return immediately."""
        if self._thread is not None:
            return self
        self._thread = threading.Thread(
            target=self._load,
            name="jarvis-vosk-fallback-loader",
            daemon=True,
        )
        self._thread.start()
        return self

    def _load(self) -> None:
        started_at = time.monotonic()
        try:
            self._model = self._model_factory(str(self._model_path))
            elapsed = time.monotonic() - started_at
            print_wake_diagnostic(
                f"Respaldo Vosk listo en {elapsed:.2f}s.",
                force=True,
            )
        except Exception as exc:
            # OpenWakeWord remains fully operational when the optional fallback
            # cannot load. Preserve the failure for a sanitized diagnostic.
            self._error = exc
            print(
                "[WakeWord] El respaldo Vosk no pudo cargarse; "
                f"OpenWakeWord continúa activo ({type(exc).__name__})."
            )
        finally:
            self._ready.set()

    def model_if_ready(self) -> Any | None:
        """Return the model only after loading completed successfully."""
        return self._model if self._ready.is_set() and self._error is None else None

    def wait(self, timeout: float | None = None) -> bool:
        """Wait for tests or diagnostics without exposing the loader thread."""
        return self._ready.wait(timeout)


def apply_wake_config() -> None:
    """Load user-selectable phrases, model and voice threshold."""
    global MODEL_PATH, MIN_WAKE_RMS, MIN_WAKE_CONFIDENCE, WAKE_PHRASES, INPUT_DEVICE
    global OPENWAKEWORD_THRESHOLD
    config = load_config()
    phrases = config.get("phrases", ["hey jarvis"])
    if not isinstance(phrases, list) or not all(isinstance(p, str) for p in phrases):
        raise ValueError("'phrases' must be a list of strings")
    normalized = tuple(" ".join(p.lower().split()) for p in phrases if p.strip())
    if not normalized:
        raise ValueError("At least one wake phrase is required")
    model_path = Path(str(config.get("model_path", MODEL_PATH)))
    MODEL_PATH = model_path if model_path.is_absolute() else BASE_DIR / model_path
    MIN_WAKE_RMS = int(config.get("min_wake_rms", MIN_WAKE_RMS))
    configured_device = config.get("input_device")
    INPUT_DEVICE = resolve_input_device(
        int(configured_device) if configured_device is not None else None,
        str(config.get("input_device_name", "")).strip(),
    )
    MIN_WAKE_CONFIDENCE = float(config.get("min_confidence", MIN_WAKE_CONFIDENCE))
    OPENWAKEWORD_THRESHOLD = float(
        config.get("wake_threshold", OPENWAKEWORD_THRESHOLD)
    )
    if not 0 <= OPENWAKEWORD_THRESHOLD <= 1:
        raise ValueError("'wake_threshold' must be between 0 and 1")
    WAKE_PHRASES = normalized


def _device_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", normalized.casefold()).split())


def validate_input_device(device: int | None) -> int | None:
    """Return an input index only when it supports Vosk's exact PCM format."""
    if device is None:
        return None
    try:
        info = sd.query_devices(device, "input")
        if int(info.get("max_input_channels", 0)) < 1:
            raise ValueError("device has no input channels")
        sd.check_input_settings(
            device=device, channels=1, dtype="int16", samplerate=SAMPLE_RATE
        )
        return device
    except Exception as exc:
        print(
            f"[WakeWord] Micrófono configurado {device} no disponible ({exc}); "
            "usando el dispositivo predeterminado."
        )
        return None


def resolve_input_device(device: int | None, preferred_name: str = "") -> int | None:
    """Resolve a stable microphone name before considering a volatile index."""
    preferred = _device_key(preferred_name)
    if preferred:
        preferred_tokens = set(preferred.split())
        for index, info in enumerate(sd.query_devices()):
            name = _device_key(str(info.get("name", "")))
            if int(info.get("max_input_channels", 0)) < 1:
                continue
            if not preferred_tokens.issubset(set(name.split())):
                continue
            valid = validate_input_device(index)
            if valid is not None:
                print(f"[WakeWord] Micrófono seleccionado: {info['name']} (ID {valid})")
                return valid
    return validate_input_device(device)


def acquire_single_instance() -> bool:
    """Prevent two wake detectors from competing for the microphone."""
    global _instance_mutex
    if sys.platform != "win32":
        return True
    kernel32 = ctypes.windll.kernel32
    _instance_mutex = kernel32.CreateMutexW(None, False, "Local\\JARVISWakeWordDetector")
    return bool(_instance_mutex) and kernel32.GetLastError() != 183


# ─────────────────────────────────────────────────────────────────────────────
# AUDIO
# ─────────────────────────────────────────────────────────────────────────────

def audio_callback(indata, frames, time_info, status) -> None:
    """
    Recibe audio del micrófono y lo coloca en una cola.

    Si la cola está llena, descarta el bloque para evitar acumulación.
    """
    global _audio_last_callback
    _audio_last_callback = time.monotonic()

    if status:
        print(f"[WakeWord] Advertencia de audio: {status}")

    try:
        _audio_queue.put_nowait(bytes(indata))
    except queue.Full:
        pass


def clear_audio_queue() -> None:
    """Elimina cualquier audio viejo almacenado en la cola."""
    while True:
        try:
            _audio_queue.get_nowait()
        except queue.Empty:
            break


def print_wake_diagnostic(message: str, *, force: bool = False) -> None:
    """Print throttled live detector telemetry only in visible console mode."""
    global _diagnostic_last_print
    if not DIAGNOSTICS_ENABLED:
        return
    now = time.monotonic()
    if not force and now - _diagnostic_last_print < DIAGNOSTIC_INTERVAL:
        return
    _diagnostic_last_print = now
    print(f"[WakeDiag] {message}", flush=True)


def reset_detector_state(model, reason: str) -> None:
    """Clear audio and neural state before listening after a JARVIS session."""
    reset = getattr(model, "reset", None)
    if callable(reset):
        reset()
    clear_audio_queue()
    print_wake_diagnostic(f"Detector reiniciado: {reason}.", force=True)


# ─────────────────────────────────────────────────────────────────────────────
# DETECCIÓN DE PROCESOS
# ─────────────────────────────────────────────────────────────────────────────

def get_running_jarvis_pid() -> int | None:
    """
    Devuelve el PID de main.py si JARVIS ya está ejecutándose.

    Devuelve None cuando no encuentra ninguna instancia.
    """
    current_pid = os.getpid()

    for process in psutil.process_iter(["pid", "cmdline", "cwd"]):
        try:
            process_id = process.info["pid"]

            if process_id == current_pid:
                continue

            command_parts = [
                str(part).strip('"')
                for part in (process.info.get("cmdline") or [])
            ]
            command = " ".join(command_parts).lower()
            expected_main = str(MAIN_FILE.resolve()).lower()
            cwd = process.info.get("cwd")
            relative_main = (
                any(part.lower() == "main.py" for part in command_parts)
                and cwd
                and Path(cwd).resolve() == BASE_DIR
            )

            if (expected_main in command or relative_main) and process_is_active(process_id):
                return int(process_id)

        except (
            psutil.NoSuchProcess,
            psutil.AccessDenied,
            psutil.ZombieProcess,
        ):
            continue

    return None


def process_is_active(process_id: int) -> bool:
    """Reject terminated Windows PIDs that remain visible through an open handle."""
    if sys.platform != "win32":
        try:
            process = psutil.Process(process_id)
            return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION, False, process_id
    )
    if not handle:
        return False
    try:
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return False
        return exit_code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def jarvis_is_running() -> bool:
    """Indica si main.py ya está ejecutándose."""
    return get_running_jarvis_pid() is not None


def wait_until_jarvis_closes() -> None:
    """Espera hasta que no quede ninguna instancia de main.py."""
    update_runtime_state("wake_word", "paused", reason="jarvis_on")
    while jarvis_is_running():
        time.sleep(1)


# ─────────────────────────────────────────────────────────────────────────────
# VENTANA DE JARVIS
# ─────────────────────────────────────────────────────────────────────────────

def bring_process_window_to_front(
    process_id: int,
    timeout: float = 20.0,
) -> bool:
    """
    Encuentra únicamente la ventana principal de JARVIS y la lleva al frente.
    Ignora ventanas auxiliares, ocultas o vacías de Qt.
    """
    if sys.platform != "win32":
        return False

    user32 = ctypes.windll.user32

    SW_RESTORE = 9

    HWND_TOPMOST = -1
    HWND_NOTOPMOST = -2

    SWP_NOMOVE = 0x0002
    SWP_NOSIZE = 0x0001
    SWP_SHOWWINDOW = 0x0040

    def get_related_pids(root_pid: int) -> set[int]:
        pids = {root_pid}

        try:
            root_process = psutil.Process(root_pid)

            for child in root_process.children(recursive=True):
                pids.add(child.pid)

        except (
            psutil.NoSuchProcess,
            psutil.AccessDenied,
        ):
            pass

        return pids

    EnumWindowsProc = ctypes.WINFUNCTYPE(
        ctypes.c_bool,
        ctypes.c_void_p,
        ctypes.c_void_p,
    )

    deadline = time.time() + timeout

    while time.time() < deadline:
        related_pids = get_related_pids(process_id)
        main_window: list[int] = []

        def callback(hwnd, _lparam):
            if not user32.IsWindow(hwnd):
                return True

            window_pid = ctypes.c_ulong()

            user32.GetWindowThreadProcessId(
                hwnd,
                ctypes.byref(window_pid),
            )

            if window_pid.value not in related_pids:
                return True

            # Leer el título de la ventana.
            title_length = user32.GetWindowTextLengthW(hwnd)

            if title_length <= 0:
                return True

            title_buffer = ctypes.create_unicode_buffer(title_length + 1)
            user32.GetWindowTextW(
                hwnd,
                title_buffer,
                title_length + 1,
            )

            title = title_buffer.value.strip().lower()

            # Seleccionar únicamente la ventana principal real.
            if "j.a.r.v.i.s" not in title:
                return True

            if "mark li" not in title and "mark xlviii" not in title:
                return True

            main_window.append(int(hwnd))
            return False

        callback_reference = EnumWindowsProc(callback)
        user32.EnumWindows(callback_reference, 0)

        if main_window:
            hwnd = main_window[0]

            user32.AllowSetForegroundWindow(-1)
            # SW_RESTORE is required when Windows has only kept the app's
            # taskbar button; SW_SHOW does not clear the minimized state.
            user32.ShowWindowAsync(hwnd, SW_RESTORE)

            user32.SetWindowPos(
                hwnd,
                HWND_TOPMOST,
                0,
                0,
                0,
                0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW,
            )

            user32.SetWindowPos(
                hwnd,
                HWND_NOTOPMOST,
                0,
                0,
                0,
                0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW,
            )

            # Simular Alt para que Windows permita darle foco.
            user32.keybd_event(0x12, 0, 0, 0)
            user32.SetForegroundWindow(hwnd)
            user32.BringWindowToTop(hwnd)
            user32.SetFocus(hwnd)
            user32.keybd_event(0x12, 0, 0x0002, 0)

            print("[WakeWord] Ventana principal de JARVIS mostrada.")
            return True

        time.sleep(0.25)

    print("[WakeWord] No se encontró la ventana principal de JARVIS.")
    return False

# ─────────────────────────────────────────────────────────────────────────────
# APERTURA DE JARVIS
# ─────────────────────────────────────────────────────────────────────────────

def launch_jarvis() -> None:
    """
    Abre JARVIS, muestra su ventana al frente y espera hasta que se cierre.

    Mientras JARVIS está abierto, Vosk deja libre el micrófono.
    Cuando JARVIS se cierra, vuelve a activarse el detector.
    """
    running_pid = get_running_jarvis_pid()

    if running_pid is not None:
        print("[WakeWord] JARVIS ya está abierto.")
        bring_process_window_to_front(running_pid)

        print("[WakeWord] Esperando a que se cierre...")
        wait_until_jarvis_closes()
        return

    pythonw = Path(sys.executable).with_name("pythonw.exe")

    if pythonw.exists():
        executable = pythonw
    else:
        executable = Path(sys.executable)

    print("[WakeWord] Estado: Abriendo. Iniciando JARVIS...")
    update_runtime_state("wake_word", "paused", reason="launching_jarvis")

    creation_flags = 0

    if sys.platform == "win32":
        creation_flags = subprocess.CREATE_NO_WINDOW

    log_dir = BASE_DIR / "logs"
    log_dir.mkdir(exist_ok=True)
    with (log_dir / "jarvis.log").open("a", encoding="utf-8") as jarvis_log:
        main_env = {**os.environ, "JARVIS_WAKE_SUPERVISED": "1"}
        process = subprocess.Popen(
            [str(executable), "-u", str(MAIN_FILE)],
            cwd=str(BASE_DIR),
            creationflags=creation_flags,
            close_fds=True,
            stdout=jarvis_log,
            stderr=subprocess.STDOUT,
            env=main_env,
        )

    print(f"[WakeWord] Estado: En sesión. PID: {process.pid}")

    # Wake startup now follows the same base surface as a direct launch. Pet
    # Mode remains an explicit in-session transition owned by JarvisUI.
    print("[WakeWord] Abriendo la interfaz base en pantalla completa...")
    bring_process_window_to_front(process.pid, timeout=12.0)

    print("[WakeWord] Esperando a que se cierre...")

    # El detector queda pausado hasta que JARVIS termine.
    return_code = process.wait()

    if return_code:
        print(f"[WakeWord] Estado: Error. JARVIS terminó con código {return_code}.")
    else:
        print("[WakeWord] JARVIS se cerró correctamente.")
    print("[WakeWord] Reactivando la palabra de inicio...")


# ─────────────────────────────────────────────────────────────────────────────
# PROCESAMIENTO DE VOZ
# ─────────────────────────────────────────────────────────────────────────────

def extract_text(
    result_json: str,
    field: str = "text",
) -> str:
    """Extrae texto de una respuesta JSON de Vosk."""
    try:
        data = json.loads(result_json)
        return str(data.get(field, "")).lower().strip()

    except (json.JSONDecodeError, TypeError):
        return ""


def contains_wake_phrase(text: str) -> bool:
    """Acepta únicamente la frase completa, no coincidencias parciales."""
    normalized = " ".join(text.lower().strip().split())
    return normalized in WAKE_PHRASES


def result_confidence(payload: str) -> float:
    """Average confidence; exact final words still guard against false wakes."""
    try:
        words = json.loads(payload).get("result", [])
        scores = [float(word.get("conf", 0.0)) for word in words if "conf" in word]
        return sum(scores) / len(scores) if scores else 0.0
    except (TypeError, ValueError, json.JSONDecodeError):
        return 0.0


def result_words(payload: str) -> tuple[str, ...]:
    """Return Vosk's final word sequence, excluding inferred/plain text."""
    try:
        words = json.loads(payload).get("result", [])
        return tuple(str(item.get("word", "")).lower().strip() for item in words)
    except (TypeError, json.JSONDecodeError):
        return ()


def result_matches_wake_phrase(payload: str) -> bool:
    """Require the final word tokens to equal one configured phrase exactly."""
    recognized = result_words(payload)
    expected = {tuple(phrase.split()) for phrase in WAKE_PHRASES}
    return bool(recognized) and recognized in expected


def result_matches_vosk_wake_alias(payload: str) -> bool:
    """Match only a full two-word acoustic proxy for the OOV word ``Jarvis``."""
    recognized = result_words(payload)
    expected = {tuple(phrase.split()) for phrase in VOSK_WAKE_ALIASES}
    return bool(recognized) and recognized in expected


def windows_session_available() -> bool:
    """Do not wake while Windows is locked (common when a laptop lid is closed)."""
    if platform.system() != "Windows":
        return True
    try:
        import ctypes
        desktop = ctypes.windll.user32.OpenInputDesktop(0, False, 0x0100)
        if not desktop:
            return False
        ctypes.windll.user32.CloseDesktop(desktop)
        return True
    except Exception:
        return False


def audio_rms(audio_data: bytes) -> float:
    """Calcula el nivel RMS de un bloque PCM int16 sin dependencias extra."""
    if len(audio_data) < 2:
        return 0.0

    sample_count = len(audio_data) // 2
    total = 0

    for index in range(0, sample_count * 2, 2):
        sample = int.from_bytes(
            audio_data[index:index + 2],
            byteorder="little",
            signed=True,
        )
        total += sample * sample

    return math.sqrt(total / sample_count)


class AdaptiveVoiceGate:
    """Separate sustained voice-like audio from the current ambient floor."""

    def __init__(self, absolute_floor: float) -> None:
        self.absolute_floor = float(absolute_floor)
        self.noise_floor = max(1.0, self.absolute_floor / NOISE_MULTIPLIER)
        self.voiced_blocks = 0

    @property
    def threshold(self) -> float:
        return max(self.absolute_floor, self.noise_floor * NOISE_MULTIPLIER)

    def observe(self, rms: float, recognizer_has_speech: bool) -> bool:
        # Learn only from audio below the absolute voice floor.  The previous
        # threshold-relative rule could absorb a sustained spoken phrase into the
        # noise floor before OpenWakeWord emitted a score, making the detector
        # progressively deaf after startup.
        if not recognizer_has_speech and rms < self.absolute_floor:
            self.noise_floor = (self.noise_floor * 0.97) + (rms * 0.03)

        voiced = rms >= self.threshold
        self.voiced_blocks = self.voiced_blocks + 1 if voiced else 0
        return voiced

    def reset_voice_run(self) -> None:
        self.voiced_blocks = 0


class RecentVoiceWindow:
    """Bridge the short delay between spoken audio and neural wake scores."""

    def __init__(self, duration: float = WAKE_AUDIO_WINDOW) -> None:
        self.duration = float(duration)
        self.last_voice_at: float | None = None

    def observe(self, has_voice: bool, *, now: float | None = None) -> bool:
        observed_at = time.monotonic() if now is None else now
        if has_voice:
            self.last_voice_at = observed_at
        return (
            self.last_voice_at is not None
            and observed_at - self.last_voice_at <= self.duration
        )


class VoskWakeSequence:
    """Recognize ``hey`` followed by Jarvis when Jarvis is out-of-vocabulary."""

    def __init__(self, duration: float = VOSK_FOLLOWUP_WINDOW) -> None:
        self.duration = float(duration)
        self.armed_until = 0.0

    def neural_followup(
        self,
        score: float,
        has_recent_voice: bool,
        session_available: bool,
        *,
        now: float | None = None,
    ) -> bool:
        """Combine a confident Vosk ``hey`` with a weak Jarvis neural score."""
        observed_at = time.monotonic() if now is None else now
        approved = (
            observed_at <= self.armed_until
            and score >= OPENWAKEWORD_FOLLOWUP_THRESHOLD
            and has_recent_voice
            and session_available
        )
        if approved or observed_at > self.armed_until:
            self.armed_until = 0.0
        return approved

    def observe(
        self,
        text: str,
        confidence: float,
        has_recent_voice: bool,
        session_available: bool,
        *,
        now: float | None = None,
    ) -> bool:
        observed_at = time.monotonic() if now is None else now
        eligible = (
            confidence >= MIN_WAKE_CONFIDENCE
            and has_recent_voice
            and session_available
        )
        if text == "hey" and eligible:
            self.armed_until = observed_at + self.duration
            return False
        approved = (
            text == "[unk]"
            and eligible
            and observed_at <= self.armed_until
        )
        self.armed_until = 0.0
        return approved


def openwakeword_candidate_approved(
    *,
    has_recent_voice: bool,
    score: float,
    session_available: bool,
) -> bool:
    """Apply the three independent wake guards without frame-level coupling."""
    return (
        has_recent_voice
        and score >= OPENWAKEWORD_THRESHOLD
        and session_available
    )


def create_openwakeword_model():
    """Load the dedicated Hey Jarvis detector and its local ONNX features."""
    if OpenWakeWordModel is None:
        return None
    required = (
        OPENWAKEWORD_MODEL_PATH,
        OPENWAKEWORD_MELSPEC_PATH,
        OPENWAKEWORD_EMBEDDING_PATH,
    )

    if not all(path.exists() for path in required):
        return None
    return OpenWakeWordModel(
        wakeword_models=[str(OPENWAKEWORD_MODEL_PATH)],
        inference_framework="onnx",
        melspec_model_path=str(OPENWAKEWORD_MELSPEC_PATH),
        embedding_model_path=str(OPENWAKEWORD_EMBEDDING_PATH),
    )


def listen_for_openwakeword(
    model,
    fallback_vosk_model: VoskModel | AsyncVoskFallback | None = None,
) -> bool:
    """Activate through OpenWakeWord, with exact Vosk recognition as fallback."""
    global _audio_last_callback
    clear_audio_queue()
    voice_gate = AdaptiveVoiceGate(MIN_WAKE_RMS)
    recent_voice = RecentVoiceWindow()
    fallback_recognizer = None
    fallback_partial = ""
    fallback_sequence = VoskWakeSequence()
    def ensure_fallback_recognizer() -> None:
        nonlocal fallback_recognizer
        if fallback_recognizer is not None:
            return
        resolved_model = (
            fallback_vosk_model.model_if_ready()
            if isinstance(fallback_vosk_model, AsyncVoskFallback)
            else fallback_vosk_model
        )
        if resolved_model is None:
            return
        # A tiny wake-only grammar avoids accent-driven substitutions such as
        # "east" for "hey".  ``[unk]`` is essential: unrelated speech can still
        # be rejected instead of being forced into the configured phrase.
        fallback_grammar = json.dumps(
            ["hey", *WAKE_PHRASES, *VOSK_WAKE_ALIASES, "[unk]"],
            ensure_ascii=False,
        )
        fallback_recognizer = KaldiRecognizer(
            resolved_model,
            SAMPLE_RATE,
            fallback_grammar,
        )
        fallback_recognizer.SetWords(True)

    ensure_fallback_recognizer()
    print("[WakeWord] Estado: Dormido. Frase requerida: Hey Jarvis")
    print_wake_diagnostic(
        "OpenWakeWord decide la activación; Vosk sólo transcribe para diagnóstico. "
        f"Score mínimo={OPENWAKEWORD_THRESHOLD:.3f}, "
        f"RMS absoluto mínimo={MIN_WAKE_RMS}.",
        force=True,
    )
    update_runtime_state("wake_word", "listening", phrase="Hey Jarvis")
    _audio_last_callback = time.monotonic()
    last_status_heartbeat = _audio_last_callback

    with sd.RawInputStream(
        device=INPUT_DEVICE,
        samplerate=SAMPLE_RATE,
        blocksize=OPENWAKEWORD_BLOCK_SIZE,
        dtype="int16",
        channels=1,
        callback=audio_callback,
    ):
        while True:
            try:
                audio_data = _audio_queue.get(timeout=0.5)
            except queue.Empty:
                if jarvis_is_running():
                    model.reset()
                    return False
                if time.monotonic() - _audio_last_callback >= STREAM_STALL_TIMEOUT:
                    raise AudioStreamStalled(
                        "el micrófono dejó de entregar audio"
                    )
                continue

            if jarvis_is_running():
                model.reset()
                clear_audio_queue()
                return False

            # OpenWakeWord starts immediately. Attach Vosk only when its
            # background load finishes; no audio stream restart is required.
            ensure_fallback_recognizer()
            samples = np.frombuffer(audio_data, dtype=np.int16)
            predictions = model.predict(samples)
            score = max((float(value) for value in predictions.values()), default=0.0)
            rms = audio_rms(audio_data)
            has_voice = voice_gate.observe(rms, score > 0.05)
            has_recent_voice = recent_voice.observe(has_voice)
            session_available = windows_session_available()

            vosk_approved = False
            if fallback_recognizer is not None:
                if fallback_recognizer.AcceptWaveform(audio_data):
                    fallback_result = fallback_recognizer.Result()
                    fallback_text = extract_text(fallback_result, field="text")
                    fallback_confidence = result_confidence(fallback_result)
                    if fallback_text:
                        print_wake_diagnostic(
                            f"Vosk final='{fallback_text}' "
                            f"confianza={fallback_confidence:.3f} "
                            f"(referencia mínima fallback={MIN_WAKE_CONFIDENCE:.3f}).",
                            force=True,
                        )
                    vosk_approved = (
                        has_recent_voice
                        and (
                            (
                                contains_wake_phrase(fallback_text)
                                and result_matches_wake_phrase(fallback_result)
                            )
                            or result_matches_vosk_wake_alias(fallback_result)
                        )
                        and fallback_confidence >= MIN_WAKE_CONFIDENCE
                        and session_available
                    )
                    if fallback_text:
                        vosk_approved = vosk_approved or fallback_sequence.observe(
                            fallback_text,
                            fallback_confidence,
                            has_recent_voice,
                            session_available,
                        )
                    fallback_partial = ""
                else:
                    partial = extract_text(
                        fallback_recognizer.PartialResult(), field="partial"
                    )
                    if partial and partial != fallback_partial:
                        fallback_partial = partial
                        print_wake_diagnostic(
                            f"Vosk parcial='{partial}'.",
                            force=True,
                        )

            now = time.monotonic()
            if now - last_status_heartbeat >= STATUS_HEARTBEAT_INTERVAL:
                update_runtime_state(
                    "wake_word",
                    "listening",
                    phrase="Hey Jarvis",
                    rms=round(rms),
                    input_device=INPUT_DEVICE,
                )
                last_status_heartbeat = now

            print_wake_diagnostic(
                f"RMS={rms:.0f} (mínimo={MIN_WAKE_RMS}, "
                f"dinámico={voice_gate.threshold:.0f}) | "
                f"score={score:.3f} (mínimo={OPENWAKEWORD_THRESHOLD:.3f}) | "
                f"voz={'SÍ' if has_voice else 'NO'} | "
                f"voz reciente={'SÍ' if has_recent_voice else 'NO'} | "
                f"sesión Windows={'SÍ' if session_available else 'NO'}"
            )

            if openwakeword_candidate_approved(
                has_recent_voice=has_recent_voice,
                score=score,
                session_available=session_available,
            ):
                print(
                    f"[WakeWord] Hey Jarvis detectado — APROBADO: "
                    f"score={score:.3f}/"
                    f"{OPENWAKEWORD_THRESHOLD:.3f}, RMS={rms:.0f}/"
                    f"{voice_gate.threshold:.0f}, voz reciente=SÍ."
                )
                model.reset()
                clear_audio_queue()
                return True
            if fallback_sequence.neural_followup(
                score,
                has_recent_voice,
                session_available,
            ):
                print(
                    "[WakeWord] Hey Jarvis detectado — APROBADO por "
                    "confirmación híbrida."
                )
                model.reset()
                clear_audio_queue()
                return True
            if vosk_approved:
                print(
                    "[WakeWord] Hey Jarvis detectado — APROBADO por respaldo Vosk."
                )
                model.reset()
                clear_audio_queue()
                return True
            if score >= 0.05:
                reasons = []
                if not has_recent_voice:
                    reasons.append(
                        f"sin voz en los últimos {WAKE_AUDIO_WINDOW:.1f}s "
                        f"(RMS actual {rms:.0f})"
                    )
                if score < OPENWAKEWORD_THRESHOLD:
                    reasons.append(
                        f"score {score:.3f} < {OPENWAKEWORD_THRESHOLD:.3f}"
                    )
                if not session_available:
                    reasons.append("sesión de Windows bloqueada")
                print_wake_diagnostic(
                    "Candidato rechazado: " + ", ".join(reasons),
                )


def listen_for_wake_word(model: VoskModel) -> bool:
    """
    Abre el micrófono y espera hasta detectar Hey Jarvis.

    Al devolver True, el stream ya está cerrado y el micrófono
    queda libre para que main.py pueda utilizarlo.
    """
    # Unrestricted decoding handles accents far better than a tiny closed
    # grammar, which otherwise collapses valid speech into repeated [unk].
    recognizer = KaldiRecognizer(model, SAMPLE_RATE)
    recognizer.SetWords(True)

    clear_audio_queue()
    recent_voice_until = 0.0
    voice_gate = AdaptiveVoiceGate(MIN_WAKE_RMS)

    print(f"[WakeWord] Estado: Dormido. Escuchando: {', '.join(WAKE_PHRASES)}")
    print_wake_diagnostic(
        f"Fallback Vosk: confianza mínima={MIN_WAKE_CONFIDENCE:.3f}, "
        f"RMS absoluto mínimo={MIN_WAKE_RMS}.",
        force=True,
    )
    update_runtime_state("wake_word", "listening", phrases=list(WAKE_PHRASES))

    with sd.RawInputStream(
        device=INPUT_DEVICE,
        samplerate=SAMPLE_RATE,
        blocksize=BLOCK_SIZE,
        dtype="int16",
        channels=1,
        callback=audio_callback,
    ):
        while True:
            try:
                audio_data = _audio_queue.get(timeout=0.5)
            except queue.Empty:
                if jarvis_is_running():
                    print("[WakeWord] JARVIS se abrió manualmente; liberando el micrófono.")
                    return False
                continue

            if jarvis_is_running():
                print("[WakeWord] JARVIS se abrió manualmente; liberando el micrófono.")
                clear_audio_queue()
                return False

            if recognizer.AcceptWaveform(audio_data):
                raw_result = recognizer.Result()
                text = extract_text(
                    raw_result,
                    field="text",
                )
                confidence = result_confidence(raw_result)
                rms = audio_rms(audio_data)
                has_voice = voice_gate.observe(rms, bool(text))
                if has_voice:
                    recent_voice_until = time.monotonic() + WAKE_AUDIO_WINDOW

                if text:
                    exact_text = contains_wake_phrase(text)
                    exact_words = result_matches_wake_phrase(raw_result)
                    recent_voice = time.monotonic() <= recent_voice_until
                    session_available = windows_session_available()
                    approved = (
                        recent_voice
                        and exact_text
                        and exact_words
                        and confidence >= MIN_WAKE_CONFIDENCE
                        and session_available
                    )
                    print(
                        f"[WakeWord] Vosk final='{text}' | "
                        f"confianza={confidence:.3f}/{MIN_WAKE_CONFIDENCE:.3f} | "
                        f"RMS={rms:.0f}/{voice_gate.threshold:.0f} | "
                        f"frase exacta={'SÍ' if exact_text and exact_words else 'NO'} | "
                        f"resultado={'APROBADO' if approved else 'RECHAZADO'}"
                    )

                # No abrir con resultados parciales. Exigir:
                # 1) frase completa exacta;
                # 2) audio con voz real en los últimos segundos.
                if (
                    time.monotonic() <= recent_voice_until
                    and contains_wake_phrase(text)
                    and result_matches_wake_phrase(raw_result)
                    and confidence >= MIN_WAKE_CONFIDENCE
                    and windows_session_available()
                ):
                    clear_audio_queue()
                    return True

                # A rejected final hypothesis must not leave old noise queued for
                # the next recognition attempt.
                clear_audio_queue()
                voice_gate.reset_voice_run()
            else:
                # Partials are useful only to distinguish speech from the ambient
                # floor. They can never activate JARVIS: provisional Vosk text is
                # deliberately unstable around television, music and random noise.
                partial_text = extract_text(recognizer.PartialResult(), field="partial")
                rms = audio_rms(audio_data)
                if voice_gate.observe(rms, bool(partial_text)):
                    recent_voice_until = time.monotonic() + WAKE_AUDIO_WINDOW
                if partial_text:
                    print_wake_diagnostic(
                        f"Vosk parcial='{partial_text}' | RMS={rms:.0f} "
                        f"(mínimo dinámico={voice_gate.threshold:.0f}).",
                        force=True,
                    )


# ─────────────────────────────────────────────────────────────────────────────
# PROGRAMA PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    if not acquire_single_instance():
        print("[WakeWord] Ya existe un detector en ejecución.")
        return

    apply_wake_config()

    if not MAIN_FILE.exists():
        raise FileNotFoundError(
            "No se encontró main.py.\n"
            f"Ruta esperada:\n{MAIN_FILE}"
        )

    wake_model = create_openwakeword_model()
    if wake_model is not None and WAKE_PHRASES == ("hey jarvis",):
        model = wake_model
        fallback_vosk_model = None
        if MODEL_PATH.exists():
            if DIAGNOSTICS_ENABLED:
                print("[WakeDiag] Preparando Vosk en segundo plano...")
            fallback_vosk_model = AsyncVoskFallback(MODEL_PATH).start()
        listen = lambda active_model: listen_for_openwakeword(
            active_model, fallback_vosk_model
        )
        print("[WakeWord] Detector local Hey Jarvis cargado.")
    else:
        if not MODEL_PATH.exists():
            raise FileNotFoundError(
                "No se encontró el modelo Vosk para la frase personalizada.\n"
                f"Ruta esperada: {MODEL_PATH}"
            )
        print("[WakeWord] OpenWakeWord no disponible; usando Vosk como respaldo.")
        model = VoskModel(str(MODEL_PATH))
        listen = listen_for_wake_word

    while True:
        try:
            if jarvis_is_running():
                print("[WakeWord] Estado: En sesión. Detector pausado y micrófono liberado.")
                wait_until_jarvis_closes()
                print("[WakeWord] JARVIS se cerró. Reactivando la palabra de inicio...")
                update_runtime_state("wake_word", "restarting", reason="jarvis_closed")
                reset_detector_state(model, "JARVIS se cerró")
                time.sleep(1)
                continue

            detected = listen(model)

            if detected:
                print("[WakeWord] Estado: Activando. Frase detectada.")

                # listen_for_wake_word ya cerró RawInputStream,
                # por lo que el micrófono está libre.
                launch_jarvis()

                reset_detector_state(model, "regreso de la sesión")
                time.sleep(1)

        except KeyboardInterrupt:
            print("\n[WakeWord] Detector detenido.")
            break

        except (sd.PortAudioError, AudioStreamStalled) as error:
            print(f"[WakeWord] Error de micrófono: {error}")
            print(f"[WakeWord] Reintentando en {MIC_RETRY_DELAY:.0f} segundo...")
            update_runtime_state("wake_word", "retrying", error="microphone")
            apply_wake_config()
            reset_detector_state(model, "recuperación del micrófono")
            time.sleep(MIC_RETRY_DELAY)

        except Exception as error:
            print(
                f"[WakeWord] Error inesperado: "
                f"{type(error).__name__}: {error}"
            )
            print("[WakeWord] Reintentando en 3 segundos...")
            update_runtime_state(
                "wake_word", "retrying", error=type(error).__name__
            )
            time.sleep(3)


if __name__ == "__main__":
    main()
