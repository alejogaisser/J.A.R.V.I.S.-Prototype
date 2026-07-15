"""Official JARVIS entry point for direct and wake-word startup modes."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

try:
    import psutil
except ImportError:  # Direct mode must still work in a minimal installation.
    psutil = None

BASE_DIR = Path(__file__).resolve().parent
MAIN_FILE = BASE_DIR / "main.py"
WAKE_FILE = BASE_DIR / "wake_word.py"
CONFIG_FILE = BASE_DIR / "config" / "wake_word.json"


def _python_executable() -> Path:
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    return pythonw if pythonw.exists() else Path(sys.executable)


def load_config() -> dict:
    defaults = {
        "enabled": True,
        "phrases": ["hey jarvis"],
        "model_path": "models/vosk-model-small-en-us-0.15",
        "min_wake_rms": 180,
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
    if args.enable:
        config["enabled"] = True
    if args.disable:
        config["enabled"] = False
    save_config(config)
    print(f"Wake-word configuration saved to {CONFIG_FILE}")
    return 0


def launch(mode: str) -> int:
    target = WAKE_FILE if mode == "wake" else MAIN_FILE
    if not target.exists():
        raise FileNotFoundError(f"JARVIS entry point not found: {target}")
    if mode == "wake" and not load_config().get("enabled", True):
        print("Wake-word listening is disabled in config/wake_word.json.")
        return 2
    if psutil is not None:
        target_name = target.name.lower()
        for running in psutil.process_iter(["pid", "cmdline"]):
            try:
                if running.info["pid"] == os.getpid():
                    continue
                command = " ".join(str(part) for part in (running.info.get("cmdline") or [])).lower()
                if target_name in command and str(BASE_DIR).lower() in command:
                    print(f"{target.name} is already running (PID {running.info['pid']}).")
                    return 0
            except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
                continue
    process = subprocess.Popen([str(_python_executable()), str(target)], cwd=str(BASE_DIR))
    return process.wait()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Start JARVIS directly or by wake word")
    parser.add_argument("--mode", choices=("direct", "wake"), default="direct")
    parser.add_argument("--configure", action="store_true")
    parser.add_argument("--phrases", help="Comma-separated wake phrases")
    parser.add_argument("--model", help="Vosk model path, relative to the project or absolute")
    parser.add_argument("--sensitivity", type=int, help="Minimum RMS voice level")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--enable", action="store_true")
    group.add_argument("--disable", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.configure:
            return configure(args)
        return launch(args.mode)
    except (OSError, ValueError) as exc:
        print(f"[Launcher] Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
