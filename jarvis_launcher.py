"""Official JARVIS entry point for direct and wake-word startup modes."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

try:
    import psutil
except ImportError:  # Direct mode must still work in a minimal installation.
    psutil = None

BASE_DIR = Path(__file__).resolve().parent
MAIN_FILE = BASE_DIR / "main.py"
WAKE_FILE = BASE_DIR / "wake_word.py"
CONFIG_FILE = BASE_DIR / "config" / "wake_word.json"
SUPERVISED_ENV = "JARVIS_WAKE_SUPERVISED"
WAKE_SUPERVISOR_ENV = "JARVIS_WAKE_SUPERVISOR"


def _python_executable(*, console: bool = False) -> Path:
    if console:
        python = Path(sys.executable)
        if python.name.casefold() == "pythonw.exe":
            visible = python.with_name("python.exe")
            return visible if visible.exists() else python
        return python
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    return pythonw if pythonw.exists() else Path(sys.executable)


def _is_wake_supervisor_command(command: str) -> bool:
    launcher_path = str(Path(__file__).resolve()).casefold()
    normalized = command.casefold()
    return (
        launcher_path in normalized
        and "--mode" in normalized
        and "wake" in normalized
    )


def _terminate_processes(processes: list) -> None:
    for running in processes:
        try:
            running.terminate()
        except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
            continue
    if not processes:
        return
    _gone, alive = psutil.wait_procs(processes, timeout=3)
    for running in alive:
        try:
            running.kill()
        except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
            pass


def stop_wake_detector() -> None:
    """Stop this project's background wake listener before a manual launch."""
    if psutil is None:
        return

    wake_path = str(WAKE_FILE.resolve()).casefold()
    supervisors = []
    detectors = []
    for running in psutil.process_iter(["pid", "cmdline"]):
        try:
            if running.info["pid"] == os.getpid():
                continue
            command = " ".join(
                str(part) for part in (running.info.get("cmdline") or [])
            ).casefold()
            if _is_wake_supervisor_command(command):
                supervisors.append(running)
            elif wake_path in command:
                detectors.append(running)
        except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
            continue

    # Stop the parent first so it cannot relaunch the child while direct mode
    # is trying to release the microphone.
    _terminate_processes(supervisors)
    _terminate_processes(detectors)


def _find_project_process(target: Path):
    """Return a running process for this project's target, if visible."""
    if psutil is None:
        return None
    target_path = str(target.resolve()).casefold()
    for running in psutil.process_iter(["pid", "cmdline"]):
        try:
            if running.info["pid"] == os.getpid():
                continue
            command = " ".join(
                str(part) for part in (running.info.get("cmdline") or [])
            ).casefold()
            if target_path in command:
                return running
        except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
            continue
    return None


def _find_wake_supervisor():
    if psutil is None:
        return None
    for running in psutil.process_iter(["pid", "cmdline"]):
        try:
            if running.info["pid"] == os.getpid():
                continue
            command = " ".join(
                str(part) for part in (running.info.get("cmdline") or [])
            )
            if _is_wake_supervisor_command(command):
                return running
        except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
            continue
    return None


def start_wake_detector() -> bool:
    """Start the hidden, self-healing wake supervisor if none is running."""
    if not load_config().get("enabled", True):
        return False
    if (
        _find_project_process(WAKE_FILE) is not None
        or _find_wake_supervisor() is not None
    ):
        return False

    log_dir = BASE_DIR / "logs"
    log_dir.mkdir(exist_ok=True)
    wake_env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    with (log_dir / "wake_word.log").open("a", encoding="utf-8") as log:
        subprocess.Popen(
            [
                str(_python_executable()), "-u", str(Path(__file__).resolve()),
                "--mode", "wake",
            ],
            cwd=str(BASE_DIR),
            creationflags=creation_flags,
            close_fds=True,
            stdout=log,
            stderr=subprocess.STDOUT,
            env=wake_env,
        )
    return True


def _append_wake_log(message: str) -> None:
    log_dir = BASE_DIR / "logs"
    log_dir.mkdir(exist_ok=True)
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with (log_dir / "wake_word.log").open("a", encoding="utf-8") as log:
        log.write(f"[WakeSupervisor {timestamp}] {message}\n")


def supervise_wake_detector(
    max_restarts: int | None = None,
    *,
    console: bool = False,
) -> int:
    """Keep the detector alive after Python or native failures."""
    delay = 2.0
    restarts = 0
    while load_config().get("enabled", True):
        started_at = time.monotonic()
        log_dir = BASE_DIR / "logs"
        log_dir.mkdir(exist_ok=True)
        wake_env = {
            **os.environ,
            "PYTHONIOENCODING": "utf-8",
            WAKE_SUPERVISOR_ENV: "1",
        }
        if console:
            wake_env["JARVIS_WAKE_DIAGNOSTICS"] = "1"
        command = [
            str(_python_executable(console=console)), "-u", str(WAKE_FILE)
        ]
        if console:
            # Diagnostic mode deliberately inherits the launcher's console.
            # Tracebacks and native-library messages remain visible in real time.
            process = subprocess.Popen(
                command,
                cwd=str(BASE_DIR),
                env=wake_env,
            )
            return_code = process.wait()
        else:
            with (log_dir / "wake_word.log").open("a", encoding="utf-8") as log:
                process = subprocess.Popen(
                    command,
                    cwd=str(BASE_DIR),
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    env=wake_env,
                )
                return_code = process.wait()

        if return_code == 0:
            return 0

        lifetime = time.monotonic() - started_at
        restarts += 1
        _append_wake_log(
            f"Detector exited with code {return_code} after {lifetime:.1f}s; "
            f"restarting in {delay:.0f}s."
        )
        if max_restarts is not None and restarts >= max_restarts:
            return int(return_code)
        time.sleep(delay)
        delay = 2.0 if lifetime >= 60.0 else min(delay * 2.0, 60.0)
    return 0


def load_config() -> dict:
    defaults = {
        "enabled": True,
        "phrases": ["hey jarvis"],
        "model_path": "models/vosk-model-small-en-us-0.15",
        "min_wake_rms": 45,
        "min_confidence": 0.65,
        "wake_threshold": 0.35,
        "input_device": None,
        "input_device_name": "Intel Smart Sound Technology for Digital Microphones",
    }
    if not CONFIG_FILE.exists():
        return defaults
    try:
        stored = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid wake-word configuration: {exc}") from exc
    if not isinstance(stored, dict):
        raise ValueError("Wake-word configuration must be a JSON object")
    return {**defaults, **stored}


def save_config(config: dict) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(
        json.dumps(config, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def configure(args: argparse.Namespace) -> int:
    config = load_config()
    if args.phrases:
        phrases = [p.strip().lower() for p in args.phrases.split(",") if p.strip()]
        if not phrases:
            raise ValueError("At least one wake phrase is required")
        config["phrases"] = phrases
    if args.model:
        config["model_path"] = args.model
    if args.sensitivity is not None:
        if args.sensitivity < 0:
            raise ValueError("Sensitivity must be zero or greater")
        config["min_wake_rms"] = args.sensitivity
    if args.confidence is not None:
        if not 0 <= args.confidence <= 1:
            raise ValueError("Confidence must be between 0 and 1")
        config["min_confidence"] = args.confidence
    if args.enable:
        config["enabled"] = True
    if args.disable:
        config["enabled"] = False
    save_config(config)
    print(f"Wake-word configuration saved to {CONFIG_FILE}")
    return 0


def launch(mode: str, *, console: bool = False) -> int:
    target = WAKE_FILE if mode == "wake" else MAIN_FILE
    if not target.exists():
        raise FileNotFoundError(f"JARVIS entry point not found: {target}")
    if mode == "wake" and not load_config().get("enabled", True):
        print("Wake-word listening is disabled in config/wake_word.json.")
        return 2
    if mode == "direct":
        stop_wake_detector()
    elif console:
        # A diagnostic launch must replace any hidden supervisor; otherwise the
        # visible CMD would only report "already running" and show no detector
        # output from the process the user is trying to inspect.
        stop_wake_detector()
    running = _find_project_process(target)
    if running is not None:
        print(f"{target.name} is already running (PID {running.pid}).")
        if mode == "direct":
            # Attach supervision even when the user launches the shortcut while
            # an unsupervised main.py is already open.
            try:
                return_code = running.wait()
                return 0 if return_code is None else int(return_code)
            finally:
                start_wake_detector()
        return 0
    if mode == "wake":
        return supervise_wake_detector(console=console)
    main_env = {**os.environ, SUPERVISED_ENV: "1"}
    process = subprocess.Popen(
        [str(_python_executable()), str(target)],
        cwd=str(BASE_DIR),
        env=main_env,
    )
    try:
        return process.wait()
    finally:
        # Restore always-on wake listening after normal exits and native/Python
        # crashes alike. start_wake_detector() is duplicate-safe.
        start_wake_detector()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Start JARVIS directly or by wake word")
    parser.add_argument("--mode", choices=("direct", "wake"), default="direct")
    parser.add_argument("--configure", action="store_true")
    parser.add_argument("--phrases", help="Comma-separated wake phrases")
    parser.add_argument("--model", help="Vosk model path, relative to the project or absolute")
    parser.add_argument("--sensitivity", type=int, help="Minimum RMS voice level")
    parser.add_argument("--confidence", type=float, help="Minimum Vosk phrase confidence (0-1)")
    parser.add_argument(
        "--console",
        action="store_true",
        help="Show wake detector output and tracebacks in the current console",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--enable", action="store_true")
    group.add_argument("--disable", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.configure:
            return configure(args)
        return launch(args.mode, console=args.console)
    except (OSError, ValueError) as exc:
        print(f"[Launcher] Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
