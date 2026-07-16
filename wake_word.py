from __future__ import annotations

import ctypes
import json
import math
import os
import platform
import queue
import subprocess
import sys
import time
from pathlib import Path
from ctypes import wintypes

import psutil
import sounddevice as sd
from vosk import KaldiRecognizer, Model, SetLogLevel
from jarvis_launcher import load_config


# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURACIÓN
# ─────────────────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent
MAIN_FILE = BASE_DIR / "main.py"

MODEL_PATH = (
    BASE_DIR
    / "models"
    / "vosk-model-small-en-us-0.15"
)

SAMPLE_RATE = 16_000
BLOCK_SIZE = 4_000
MIN_WAKE_RMS = 180
MIN_WAKE_CONFIDENCE = 0.82
WAKE_AUDIO_WINDOW = 1.5

WAKE_PHRASES = ("hey jarvis",)

# Oculta los mensajes internos de Vosk.
SetLogLevel(-1)

_audio_queue: queue.Queue[bytes] = queue.Queue(maxsize=30)
_instance_mutex = None


def apply_wake_config() -> None:
    """Load user-selectable phrases, model and voice threshold."""
    global MODEL_PATH, MIN_WAKE_RMS, MIN_WAKE_CONFIDENCE, WAKE_PHRASES
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
    MIN_WAKE_CONFIDENCE = float(config.get("min_confidence", MIN_WAKE_CONFIDENCE))
    WAKE_PHRASES = normalized


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

            if expected_main in command or relative_main:
                return int(process_id)

        except (
            psutil.NoSuchProcess,
            psutil.AccessDenied,
            psutil.ZombieProcess,
        ):
            continue

    return None


def jarvis_is_running() -> bool:
    """Indica si main.py ya está ejecutándose."""
    return get_running_jarvis_pid() is not None


def wait_until_jarvis_closes() -> None:
    """Espera hasta que no quede ninguna instancia de main.py."""
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

            if "mark xlviii" not in title:
                return True

            main_window.append(int(hwnd))
            return False

        callback_reference = EnumWindowsProc(callback)
        user32.EnumWindows(callback_reference, 0)

        if main_window:
            hwnd = main_window[0]

            user32.AllowSetForegroundWindow(-1)
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

    creation_flags = 0

    if sys.platform == "win32":
        creation_flags = subprocess.CREATE_NO_WINDOW

    process = subprocess.Popen(
        [str(executable), str(MAIN_FILE)],
        cwd=str(BASE_DIR),
        creationflags=creation_flags,
        close_fds=True,
    )

    print(f"[WakeWord] Estado: En sesión. PID: {process.pid}")

    # Espera a que PyQt cree la ventana y la trae al frente.
    bring_process_window_to_front(
        process_id=process.pid,
        timeout=15.0,
    )

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
    """Average confidence for the exact recognized phrase; zero if unavailable."""
    try:
        words = json.loads(payload).get("result", [])
        scores = [float(word.get("conf", 0.0)) for word in words if "conf" in word]
        return sum(scores) / len(scores) if scores else 0.0
    except (TypeError, ValueError, json.JSONDecodeError):
        return 0.0


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


def listen_for_wake_word(model: Model) -> bool:
    """
    Abre el micrófono y espera hasta detectar Hey Jarvis.

    Al devolver True, el stream ya está cerrado y el micrófono
    queda libre para que main.py pueda utilizarlo.
    """
    recognizer = KaldiRecognizer(
        model,
        SAMPLE_RATE,
        json.dumps(list(dict.fromkeys([*WAKE_PHRASES, "jarvis", "[unk]"]))),
    )
    recognizer.SetWords(True)

    clear_audio_queue()
    recent_voice_until = 0.0

    print(f"[WakeWord] Estado: Dormido. Escuchando: {', '.join(WAKE_PHRASES)}")

    with sd.RawInputStream(
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

            # Registrar si hubo voz real recientemente. Un micrófono muteado
            # suele entregar ceros o un nivel extremadamente bajo.
            if audio_rms(audio_data) >= MIN_WAKE_RMS:
                recent_voice_until = time.monotonic() + WAKE_AUDIO_WINDOW

            if recognizer.AcceptWaveform(audio_data):
                raw_result = recognizer.Result()
                text = extract_text(
                    raw_result,
                    field="text",
                )
                confidence = result_confidence(raw_result)

                if text:
                    print(f"[WakeWord] Escuchado: {text}")

                # No abrir con resultados parciales. Exigir:
                # 1) frase completa exacta;
                # 2) audio con voz real en los últimos segundos.
                if (
                    time.monotonic() <= recent_voice_until
                    and contains_wake_phrase(text)
                    and confidence >= MIN_WAKE_CONFIDENCE
                    and windows_session_available()
                ):
                    clear_audio_queue()
                    return True


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

    if not MODEL_PATH.exists():
        raise FileNotFoundError(
            "No se encontró el modelo de Vosk.\n"
            f"Ruta esperada:\n{MODEL_PATH}\n\n"
            "Revisá que la carpeta del modelo tenga exactamente ese nombre."
        )

    print("[WakeWord] Cargando modelo de Vosk...")

    model = Model(str(MODEL_PATH))

    print("[WakeWord] Modelo cargado correctamente.")

    while True:
        try:
            if jarvis_is_running():
                print("[WakeWord] Estado: En sesión. Detector pausado y micrófono liberado.")
                wait_until_jarvis_closes()
                print("[WakeWord] JARVIS se cerró. Reactivando la palabra de inicio...")
                clear_audio_queue()
                time.sleep(1)
                continue

            detected = listen_for_wake_word(model)

            if detected:
                print("[WakeWord] Estado: Activando. Frase detectada.")

                # listen_for_wake_word ya cerró RawInputStream,
                # por lo que el micrófono está libre.
                launch_jarvis()

                clear_audio_queue()
                time.sleep(1)

        except KeyboardInterrupt:
            print("\n[WakeWord] Detector detenido.")
            break

        except sd.PortAudioError as error:
            print(f"[WakeWord] Error de micrófono: {error}")
            print("[WakeWord] Reintentando en 3 segundos...")
            time.sleep(3)

        except Exception as error:
            print(
                f"[WakeWord] Error inesperado: "
                f"{type(error).__name__}: {error}"
            )
            print("[WakeWord] Reintentando en 3 segundos...")
            time.sleep(3)


if __name__ == "__main__":
    main()
