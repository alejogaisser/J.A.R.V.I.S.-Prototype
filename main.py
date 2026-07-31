from __future__ import annotations

import platform as _platform
import subprocess as _subprocess

# ── Nuclear: force CREATE_NO_WINDOW on EVERY subprocess call on Windows ───────
# This patches Popen itself, so no per-file flag is needed anywhere.
if _platform.system() == "Windows":
    _OrigPopen = _subprocess.Popen

    class _Popen(_OrigPopen):
        def __init__(self, args, **kw):
            kw["creationflags"] = kw.get("creationflags", 0) | _subprocess.CREATE_NO_WINDOW
            kw.pop("startupinfo", None)   # drop any stale/shared STARTUPINFO
            super().__init__(args, **kw)

    _subprocess.Popen = _Popen
# ─────────────────────────────────────────────────────────────────────────────

import asyncio
import logging
import os
import re
import threading
import time
import json
import sys
import traceback
import faulthandler
from dataclasses import replace
from datetime import datetime
from core.clock import local_now, prompt_datetime
from pathlib import Path

import sounddevice as sd
from ui import JarvisUI
from config.settings import get_settings

genai = None
types = None
_LIVE_SDK_LOCK = threading.Lock()


def _load_live_sdk() -> None:
    """Load the heavy Gemini SDK on the core thread after the UI is visible."""
    global genai, types
    if genai is not None and types is not None:
        return
    with _LIVE_SDK_LOCK:
        if genai is not None and types is not None:
            return
        from google import genai as loaded_genai
        from google.genai import types as loaded_types

        genai = loaded_genai
        types = loaded_types


def _configure_console_encoding() -> None:
    """Keep diagnostic output from crashing audio tasks on legacy consoles."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass


_configure_console_encoding()

_CRASH_LOG_DIR = Path(__file__).resolve().parent / "logs"
_CRASH_LOG_DIR.mkdir(exist_ok=True)
_CRASH_LOG_HANDLE = (_CRASH_LOG_DIR / "jarvis_crash.log").open(
    "a", encoding="utf-8", buffering=1
)
faulthandler.enable(_CRASH_LOG_HANDLE, all_threads=True)
from core.diagnostics import CrashReporter
from core.security import VoiceConfirmationGate, confirmation_request, safe_tool_args
from services.runtime import RuntimeServices
from core.events import DashboardConnected, EventBus, RuntimeEvent
from core.runtime_state import update_runtime_state
from core.request_audit import RequestAuditSink
from core.request_context import RequestContext
from core.structured_logging import StructuredRuntimeLog
from core.ui_boundary import UiCommandFacade
from core.providers import GroundedSearchProvider
from core.providers.google import GoogleGroundedSearchProvider
from core.permissions import (
    ExecutionContext, InputSource, PermissionLevel, PermissionPolicy, PermissionStore,
    build_preview,
)
from core.tools import (
    EffectStatus,
    ExecutionStatus,
    ToolExecutor,
    ToolResult,
    VerificationStatus,
    normalize_tool_output,
)
from core.tools.builtins import SPECIAL_TOOLS, build_builtin_registry
from memory.memory_manager import (
    load_memory, create_memory, list_memories, search_memories,
    update_memory_by_id, forget_memory, restore_memory, format_memory_for_prompt,
    format_language_instruction, get_response_language,
)
from memory.script_memory import format_scripts_for_prompt


_CRASH_REPORTER = CrashReporter(_CRASH_LOG_DIR / "jarvis_crash.log")
_CRASH_REPORTER.install()



def _load_action_dependencies() -> None:
    """Load optional/heavy action modules after the UI is already visible."""
    global file_processor, flight_finder, open_app, weather_action
    global send_message, reminder, computer_settings, analyze_visual
    global youtube_video, desktop_control, browser_control, file_controller
    global code_helper, dev_agent, web_search_action, computer_control
    global game_updater, SystemMonitor, get_system_status, ProactiveEngine
    global math_engine, study_engine, account_connector, obsidian_connector, open_geo
    global configure_browser_worker_events, shutdown_browser_workers
    global configure_vision_worker_events, shutdown_vision_worker

    from actions.file_processor import file_processor
    from actions.flight_finder import flight_finder
    from actions.open_app import open_app
    from actions.weather_report import weather_action
    from actions.send_message import send_message
    from actions.reminder import reminder
    from actions.computer_settings import computer_settings
    from actions.screen_processor import (
        analyze_visual,
        configure_vision_worker_events,
        shutdown_vision_worker,
    )
    from actions.youtube_video import youtube_video
    from actions.desktop import desktop_control
    from actions.browser_control import (
        browser_control,
        configure_browser_worker_events,
        shutdown_browser_workers,
    )
    from actions.file_controller import file_controller
    from actions.code_helper import code_helper
    from actions.dev_agent import dev_agent
    from actions.web_search import web_search as web_search_action
    from actions.computer_control import computer_control
    from actions.game_updater import game_updater
    from actions.system_monitor import SystemMonitor, get_system_status
    from actions.proactive import ProactiveEngine
    from actions.math_engine import math_engine
    from actions.study_engine import study_engine
    from actions.account_connector import account_connector
    from actions.obsidian_connector import obsidian_connector
    from actions.open_geo import open_geo


def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


BASE_DIR        = get_base_dir()
PROMPT_PATH     = BASE_DIR / "core" / "prompt.txt"
LIVE_MODEL = "models/gemini-3.1-flash-live-preview"
CHANNELS            = 1
SEND_SAMPLE_RATE    = 16000
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE          = 640  # 40 ms at 16 kHz, within Gemini Live guidance

def _get_api_key() -> str:
    return get_settings().require_gemini_api_key()


def _load_system_prompt() -> str:
    try:
        return PROMPT_PATH.read_text(encoding="utf-8")
    except Exception:
        return (
            "You are JARVIS, Tony Stark's AI assistant. "
            "Be concise, direct, and always use the provided tools to complete tasks. "
            "Never simulate or guess results — always call the appropriate tool."
        )

_CTRL_RE = re.compile(r"<ctrl\d+>", re.IGNORECASE)

def _clean_transcript(text: str) -> str:    
    text = _CTRL_RE.sub("", text)
    text = re.sub(r"[\x00-\x08\x0b-\x1f]", "", text)
    return text.strip()


TOOL_DECLARATIONS = [
    {
        "name": "open_app",
        "description": (
            "Opens any application on the computer. "
            "Use this whenever the user asks to open, launch, or start any app, "
            "website, or program. Always call this tool — never just say you opened it."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "app_name": {
                    "type": "STRING",
                    "description": "Exact name of the application (e.g. 'WhatsApp', 'Chrome', 'Spotify')"
                }
            },
            "required": ["app_name"]
        }
    },
    {
        "name": "web_search",
        "description": (
            "Searches the web. Use for ANY question about current facts, events, prices, "
            "or topics — always prefer this over guessing. "
            "Modes: 'search' (default), 'news' (latest headlines on a topic), "
            "'research' (deep comprehensive answer), 'price' (product cost lookup), "
            "'compare' (side-by-side comparison of items)."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query":  {"type": "STRING", "description": "Search query or topic"},
                "mode":   {"type": "STRING", "description": "search | news | research | price | compare"},
                "items":  {"type": "ARRAY",  "items": {"type": "STRING"}, "description": "Items to compare (compare mode)"},
                "aspect": {"type": "STRING", "description": "Comparison aspect: price | specs | reviews | features"},
            },
            "required": ["query"]
        }
    },
    {
        "name": "system_status",
        "description": (
            "Returns real-time system metrics: CPU usage, RAM, GPU load, CPU temperature, "
            "uptime, and process count. Use when the user asks about computer performance, "
            "temperature, memory, or resource usage."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {},
        }
    },
    {
        "name": "weather_report",
        "description": "Gives the weather report to user",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "city": {"type": "STRING", "description": "City name"}
            },
            "required": ["city"]
        }
    },
    {
        "name": "send_message",
        "description": "Sends a text message via WhatsApp, Telegram, or other messaging platform.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "receiver":     {"type": "STRING", "description": "Recipient contact name"},
                "message_text": {"type": "STRING", "description": "The message to send"},
                "platform":     {"type": "STRING", "description": "Platform: WhatsApp, Telegram, etc."}
                ,"simulate":     {"type": "BOOLEAN", "description": "Return a preview without sending"}
            },
            "required": ["receiver", "message_text", "platform"]
        }
    },
    {
        "name": "reminder",
        "description": "Sets a timed reminder using Task Scheduler.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "date":    {"type": "STRING", "description": "Date in YYYY-MM-DD format"},
                "time":    {"type": "STRING", "description": "Time in HH:MM format (24h)"},
                "message": {"type": "STRING", "description": "Reminder message text"}
            },
            "required": ["date", "time", "message"]
        }
    },
    {
        "name": "youtube_video",
        "description": (
            "Controls YouTube. Use for: playing videos, summarizing a video's content, "
            "getting video info, or showing trending videos."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "play | summarize | get_info | trending (default: play)"},
                "query":  {"type": "STRING", "description": "Search query for play action"},
                "save":   {"type": "BOOLEAN", "description": "Save summary to Notepad (summarize only)"},
                "region": {"type": "STRING", "description": "Country code for trending e.g. TR, US"},
                "url":    {"type": "STRING", "description": "Video URL for get_info action"},
            },
            "required": []
        }
    },
    {
        "name": "screen_process",
        "description": (
            "Captures the screen or webcam image and lets you analyze it. "
            "MUST be called when user asks what is on screen, what you see, "
            "look at camera, analyze my screen, etc. "
            "You have NO visual ability without this tool. "
            "After the image is captured it is sent directly to you — describe what you see and answer the user's question. "
            "When using camera: the live view stays open until user says close it or calls close_camera."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "angle": {"type": "STRING", "description": "'screen' to capture display, 'camera' for webcam. Default: 'screen'"},
                "text":  {"type": "STRING", "description": "The question or instruction about the captured image"}
            },
            "required": ["text"]
        }
    },
    {
        "name": "close_camera",
        "description": (
            "Closes the live camera view shown on screen. "
            "Call when user says: close camera, stop camera, turn off camera, "
            "kamerayı kapat, kapat, creepy, etc."
        ),
        "parameters": {"type": "OBJECT", "properties": {}, "required": []}
    },
    {
        "name": "camera_control",
        "description": (
            "Controls the live camera workspace. Switch to hand mode only when explicitly "
            "requested. Hand mode only moves visible content; zoom is always voice-controlled."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "mode": {"type": "STRING", "description": "normal | hand"},
                "zoom": {"type": "NUMBER", "description": "Camera zoom from 1.0 to 4.0"},
                "pan_x": {"type": "NUMBER", "description": "Horizontal focus from -1 (left) to 1 (right)"},
                "pan_y": {"type": "NUMBER", "description": "Vertical focus from -1 (up) to 1 (down)"}
            },
            "required": []
        }
    },
    {
        "name": "pet_mode",
        "description": (
            "Moves the JARVIS application into its desktop Pet Mode while keeping the same "
            "voice session alive. Call immediately when the user asks to activate Pet Mode, "
            "switch to the pet, minimize JARVIS to the pet, 'pasá a modo pet', or equivalent. "
            "Do not use generic window minimization for this request."
        ),
        "parameters": {"type": "OBJECT", "properties": {}, "required": []}
    },
    {
        "name": "interface_control",
        "description": (
            "Controls JARVIS's own application interface through the same internal actions as its buttons. "
            "Use for every voice request to open, close, toggle, or navigate JARVIS UI: Pet Mode or main app, "
            "Core, Chat, Files, Camera, Memory, Geo, Context, System telemetry, results, fullscreen, listening mode, "
            "live map, holographic globe, or interrupt. Examples: 'pasa a pet mode', 'volvé a la app', "
            "'abrí tu mapa', 'mostrá el chat', 'cerrá la cámara'. Opening Camera only displays the live stream; "
            "use screen_process separately only when the user asks JARVIS to inspect or analyze what it sees."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "open | close | toggle | status | set"
                },
                "target": {
                    "type": "STRING",
                    "description": (
                        "status | pet | app | core | chat | files | camera | study | memory | geo | context | system | "
                        "live_map | fullscreen | listening | content | interrupt"
                    )
                },
                "mode": {
                    "type": "STRING",
                    "description": "Optional: live | holographic for live_map; always | toggle for listening"
                },
            },
            "required": ["action", "target"]
        }
    },
    {
        "name": "visual_mouse",
        "description": (
            "Locates a visible UI element from a fresh screenshot, moves the mouse to it, "
            "and optionally clicks it. MUST be used whenever the user asks to move the "
            "pointer to, click, double-click, or right-click something identified by its "
            "visible name or appearance. Do not use screen_process for mouse actions."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "move | click | double_click | right_click"
                },
                "description": {
                    "type": "STRING",
                    "description": "Precise visible element to locate, including nearby text if helpful"
                },
            },
            "required": ["action", "description"]
        }
    },
    {
        "name": "computer_settings",
        "description": (
            "Controls the computer: volume, brightness, window management, keyboard shortcuts, "
            "typing text on screen, closing apps, fullscreen, dark mode, WiFi, restart, shutdown, "
            "scrolling, tab management, zoom, screenshots, lock screen, refresh/reload page. "
            "Use for ANY single computer control command."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "The action to perform"},
                "description": {"type": "STRING", "description": "Natural language description of what to do"},
                "value":       {"type": "STRING", "description": "Optional value: volume level, text to type, or keys such as ctrl+shift+s"},
                "keys":        {"type": "STRING", "description": "Keyboard combination for action=hotkey"},
                "target_title": {"type": "STRING", "description": "Optional window title to target for minimize, maximize, close, or hotkey"}
            },
            "required": []
        }
    },
    {
        "name": "browser_control",
        "description": (
            "Controls any web browser. Use for: opening websites, searching the web, "
            "clicking elements, filling forms, scrolling, screenshots, navigation, any web-based task. "
            "Always pass the 'browser' parameter when the user specifies a browser (e.g. 'open in Edge', "
            "'use Firefox', 'open Chrome'). Multiple browsers can run simultaneously."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "go_to | search | click | type | scroll | fill_form | smart_click | smart_type | get_text | get_url | press | new_tab | close_tab | screenshot | back | forward | reload | switch | list_browsers | close | close_all"},
                "browser":     {"type": "STRING", "description": "Target browser: chrome | edge | firefox | opera | operagx | brave | vivaldi | safari. Omit to use the currently active browser."},
                "url":         {"type": "STRING", "description": "URL for go_to / new_tab action"},
                "query":       {"type": "STRING", "description": "Search query for search action"},
                "engine":      {"type": "STRING", "description": "Search engine: google | bing | duckduckgo | yandex (default: google)"},
                "selector":    {"type": "STRING", "description": "CSS selector for click/type"},
                "text":        {"type": "STRING", "description": "Text to click or type"},
                "description": {"type": "STRING", "description": "Element description for smart_click/smart_type"},
                "direction":   {"type": "STRING", "description": "up | down for scroll"},
                "amount":      {"type": "INTEGER", "description": "Scroll amount in pixels (default: 500)"},
                "key":         {"type": "STRING", "description": "Key name for press action (e.g. Enter, Escape, F5)"},
                "path":        {"type": "STRING", "description": "Save path for screenshot"},
                "incognito":   {"type": "BOOLEAN", "description": "Open in private/incognito mode"},
                "clear_first": {"type": "BOOLEAN", "description": "Clear field before typing (default: true)"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "file_controller",
        "description": "Manages files and folders. Use inspect on a project folder to discover nested files and read source code, including Arduino .ino sketches.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "list | inspect | create_file | create_folder | delete | move | copy | rename | read | open | write | find | largest | disk_usage | organize_desktop | info | clear_jarvis_temp. Use inspect for a folder containing a code project; read also inspects when path points to a folder."},
                "path":        {"type": "STRING", "description": "File/folder path or shortcut: desktop, downloads, documents, home"},
                "destination": {"type": "STRING", "description": "Destination path for move/copy"},
                "new_name":    {"type": "STRING", "description": "New name for rename"},
                "content":     {"type": "STRING", "description": "Content for create_file/write"},
                "name":        {"type": "STRING", "description": "File or folder name for create, read, open, write, rename, delete, or search"},
                "folder_name": {"type": "STRING", "description": "Folder name; accepted as an alias of name for create_folder"},
                "file_name":   {"type": "STRING", "description": "File name; accepted as an alias of name"},
                "extension":   {"type": "STRING", "description": "File extension to search (e.g. .pdf)"},
                "count":       {"type": "INTEGER", "description": "Number of results for largest"},
                "max_files":   {"type": "INTEGER", "description": "Maximum files returned by inspect (default 30, maximum 100)"},
                "max_chars":   {"type": "INTEGER", "description": "Maximum source characters returned by inspect/read"},
                "simulate":    {"type": "BOOLEAN", "description": "Return a preview without changing files"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "desktop_control",
        "description": "Controls the desktop: wallpaper, organize, clean, list, stats.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "wallpaper | wallpaper_url | organize | clean | list | stats | task"},
                "path":   {"type": "STRING", "description": "Image path for wallpaper"},
                "url":    {"type": "STRING", "description": "Image URL for wallpaper_url"},
                "mode":   {"type": "STRING", "description": "by_type or by_date for organize"},
                "task":   {"type": "STRING", "description": "Natural language desktop task"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "code_helper",
        "description": (
            "Creates persistent scripts and automations, or writes, edits, explains, runs, "
            "and builds code files. MUST be used when the user asks to create a script, "
            "command, shortcut, workflow, macro, or named routine such as 'open daily'. "
            "Use action='write' and routine_name to create it; never substitute keyboard presses."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "write | edit | explain | run | build | auto (default: auto)"},
                "description": {"type": "STRING", "description": "What the code should do or what change to make"},
                "language":    {"type": "STRING", "description": "Programming language (default: python)"},
                "output_path": {"type": "STRING", "description": "Where to save the file"},
                "routine_name": {"type": "STRING", "description": "Short spoken name for a reusable script, e.g. open daily"},
                "file_path":   {"type": "STRING", "description": "Path to existing file for edit/explain/run/build"},
                "code":        {"type": "STRING", "description": "Raw code string for explain"},
                "args":        {"type": "STRING", "description": "CLI arguments for run/build"},
                "timeout":     {"type": "INTEGER", "description": "Execution timeout in seconds (default: 30)"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "dev_agent",
        "description": (
            "Creates a contained multi-file project preview in a new isolated "
            "workspace. It does not install dependencies or execute generated code."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "description":  {"type": "STRING", "description": "What the project should do"},
                "language":     {"type": "STRING", "description": "Programming language (default: python)"},
                "project_name": {"type": "STRING", "description": "Optional project folder name"},
                "timeout":      {"type": "INTEGER", "description": "Run timeout in seconds (default: 30)"},
            },
            "required": ["description"]
        }
    },
    {
        "name": "computer_control",
        "description": (
            "Immediate one-time computer control: type, click, hotkeys, scroll, move mouse, "
            "screenshots, and visible elements. It MUST NOT create scripts, commands, "
            "shortcuts, macros, named routines, or persistent automations; use code_helper "
            "for those. Use press only when the user explicitly asks to press a key now."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "type | smart_type | click | double_click | right_click | hotkey | press | scroll | move | copy | paste | screenshot | wait | clear_field | focus_window | screen_find | screen_click | random_data | user_data"},
                "text":        {"type": "STRING", "description": "Text to type or paste"},
                "x":           {"type": "INTEGER", "description": "X coordinate"},
                "y":           {"type": "INTEGER", "description": "Y coordinate"},
                "keys":        {"type": "STRING", "description": "Key combination e.g. 'ctrl+c'"},
                "key":         {"type": "STRING", "description": "Single key e.g. 'enter'"},
                "direction":   {"type": "STRING", "description": "up | down | left | right"},
                "amount":      {"type": "INTEGER", "description": "Scroll amount (default: 3)"},
                "seconds":     {"type": "NUMBER",  "description": "Seconds to wait"},
                "title":       {"type": "STRING",  "description": "Window title for focus_window"},
                "description": {"type": "STRING",  "description": "Element description for screen_find/screen_click"},
                "type":        {"type": "STRING",  "description": "Data type for random_data"},
                "field":       {"type": "STRING",  "description": "Field for user_data: name|email|city"},
                "clear_first": {"type": "BOOLEAN", "description": "Clear field before typing (default: true)"},
                "path":        {"type": "STRING",  "description": "Save path for screenshot"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "game_updater",
        "description": (
            "THE ONLY tool for ANY Steam or Epic Games request. "
            "Use for: installing, downloading, updating games, listing installed games, "
            "checking download status, scheduling updates. "
            "ALWAYS call directly for any Steam/Epic/game request. "
            "NEVER use browser_control or web_search for Steam/Epic."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":    {"type": "STRING",  "description": "update | install | list | download_status | schedule | cancel_schedule | schedule_status (default: update)"},
                "platform":  {"type": "STRING",  "description": "steam | epic | both (default: both)"},
                "game_name": {"type": "STRING",  "description": "Game name (partial match supported)"},
                "app_id":    {"type": "STRING",  "description": "Steam AppID for install (optional)"},
                "hour":      {"type": "INTEGER", "description": "Hour for scheduled update 0-23 (default: 3)"},
                "minute":    {"type": "INTEGER", "description": "Minute for scheduled update 0-59 (default: 0)"},
                "shutdown_when_done": {"type": "BOOLEAN", "description": "Shut down PC when download finishes"},
            },
            "required": []
        }
    },
    {
        "name": "flight_finder",
        "description": "Searches Google Flights and speaks the best options.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "origin":      {"type": "STRING",  "description": "Departure city or airport code"},
                "destination": {"type": "STRING",  "description": "Arrival city or airport code"},
                "date":        {"type": "STRING",  "description": "Departure date (any format)"},
                "return_date": {"type": "STRING",  "description": "Return date for round trips"},
                "passengers":  {"type": "INTEGER", "description": "Number of passengers (default: 1)"},
                "cabin":       {"type": "STRING",  "description": "economy | premium | business | first"},
                "save":        {"type": "BOOLEAN", "description": "Save results to Notepad"},
            },
            "required": ["origin", "destination", "date"]
        }
    },
    {
        "name": "shutdown_jarvis",
        "description": (
            "Shuts down the assistant completely. "
            "Call this when the user expresses intent to end the conversation, "
            "close the assistant, say goodbye, or stop Jarvis. "
            "The user can say this in ANY language."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {},
        }
    },
    {
    "name": "file_processor",
    "description": (
        "Processes any file that the user has uploaded or dropped onto the interface. "
        "Use this when the user refers to an uploaded file and wants an action on it. "
        "Supports: images (describe/ocr/resize/compress/convert), "
        "PDFs (summarize/extract_text/to_word), "
        "Word docs & text files (summarize/fix/reformat/translate), "
        "CSV/Excel (analyze/stats/filter/sort/convert), "
        "JSON/XML (validate/format/analyze), "
        "code files (explain/review/fix/optimize/run/document/test), "
        "audio (transcribe/trim/convert/info), "
        "video (trim/extract_audio/extract_frame/compress/transcribe/info), "
        "archives (list/extract), "
        "presentations (summarize/extract_text). "
        "ALWAYS call this tool when a file has been uploaded and the user gives a command about it. "
        "If the user's command is ambiguous, pick the most logical action for that file type."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "file_path": {
                "type": "STRING",
                "description": "Full path to the uploaded file. Leave empty to use the currently uploaded file."
            },
            "action": {
                "type": "STRING",
                "description": (
                    "What to do with the file. Examples by type:\n"
                    "image: describe | ocr | resize | compress | convert | info\n"
                    "pdf: summarize | extract_text | to_word | info\n"
                    "docx/txt: summarize | fix | reformat | translate_hint | word_count | to_bullet\n"
                    "csv/excel: analyze | stats | filter | sort | convert | info\n"
                    "json: validate | format | analyze | to_csv\n"
                    "code: explain | review | fix | optimize | run | document | test\n"
                    "audio: transcribe | trim | convert | info\n"
                    "video: trim | extract_audio | extract_frame | compress | transcribe | info | convert\n"
                    "archive: list | extract\n"
                    "pptx: summarize | extract_text | analyze"
                )
            },
            "instruction": {
                "type": "STRING",
                "description": "Free-form instruction if action doesn't cover it. E.g. 'translate this to Turkish', 'find all email addresses'"
            },
            "format": {
                "type": "STRING",
                "description": "Target format for conversion. E.g. 'mp3', 'pdf', 'csv', 'png'"
            },
            "width":     {"type": "INTEGER", "description": "Target width for image resize"},
            "height":    {"type": "INTEGER", "description": "Target height for image resize"},
            "scale":     {"type": "NUMBER",  "description": "Scale factor for image resize (e.g. 0.5)"},
            "quality":   {"type": "INTEGER", "description": "Quality 1-100 for image/video compress"},
            "start":     {"type": "STRING",  "description": "Start time for trim: seconds or HH:MM:SS"},
            "end":       {"type": "STRING",  "description": "End time for trim: seconds or HH:MM:SS"},
            "timestamp": {"type": "STRING",  "description": "Timestamp for video frame extraction HH:MM:SS"},
            "column":    {"type": "STRING",  "description": "Column name for CSV filter/sort"},
            "value":     {"type": "STRING",  "description": "Filter value for CSV filter"},
            "condition": {"type": "STRING",  "description": "Filter condition: equals|contains|gt|lt"},
            "ascending": {"type": "BOOLEAN", "description": "Sort order for CSV sort (default: true)"},
            "save":      {"type": "BOOLEAN", "description": "Save result to file (default: true)"},
            "destination": {"type": "STRING", "description": "Output folder for archive extract"},
        },
        "required": []
    }
},
    {
        "name": "save_memory",
        "description": (
            "Save an important personal fact about the user to long-term memory. "
            "Use it when the user explicitly asks, or for a clear, normal, durable fact. "
            "Never store an inference or sensitive/private data silently. "
            "Do NOT call for: weather, reminders, searches, or one-time commands. "
            "Do NOT announce that you are saving — just call it silently. "
            "If the user explicitly changes a known fact, set replace_existing=true. "
            "Otherwise, if a conflict is returned, ask whether to replace the old memory. "
            "Values must be in English regardless of the conversation language. "
            "A dated task, promise, appointment, or one-time plan MUST use category='temporary' "
            "and expires_at set to its relevant local date/time. Recurring facts such as birthdays "
            "and anniversaries MUST remain durable without expires_at."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "category": {
                    "type": "STRING",
                    "description": (
                        "identity — name, age, birthday, city, job, language, nationality | "
                        "preferences — favorite food/color/music/film/game/sport, hobbies | "
                        "projects — active projects, goals, things being built | "
                        "relationships — friends, family, partner, colleagues | "
                        "wishes — future plans, things to buy, travel dreams | "
                        "notes — habits, schedule, anything else worth remembering"
                    )
                },
                "key":   {"type": "STRING", "description": "Short snake_case key (e.g. name, favorite_food, sister_name)"},
                "value": {"type": "STRING", "description": "Concise value in English (e.g. Fatih, pizza, older sister)"},
                "contexts": {
                    "type": "ARRAY", "items": {"type": "STRING"},
                    "description": "Optional short topic nuclei explicitly stated by the user. Never infer or invent an unstated context."
                },
                "expires_at": {"type": "STRING", "description": "Required ISO-8601 local expiry for dated one-time commitments; omit for durable or annually recurring facts"},
                "replace_existing": {"type": "BOOLEAN", "description": "True only when the user explicitly changes or corrects this fact"},
            },
            "required": ["category", "key", "value"]
        }
    },
    {
        "name": "memory_list",
        "description": "List the user's active, expired, or forgotten memories. Sensitive values are redacted.",
        "parameters": {"type": "OBJECT", "properties": {
            "category": {"type": "STRING"},
            "status": {"type": "STRING", "description": "active, expired, or forgotten"}
        }, "required": []}
    },
    {
        "name": "memory_search",
        "description": "Search active user memories by text and optional category.",
        "parameters": {"type": "OBJECT", "properties": {
            "query": {"type": "STRING"}, "category": {"type": "STRING"}
        }, "required": ["query"]}
    },
    {
        "name": "memory_update",
        "description": "Correct a memory by its exact memory_id, optionally changing its expiry.",
        "parameters": {"type": "OBJECT", "properties": {
            "memory_id": {"type": "STRING"}, "value": {"type": "STRING"},
            "expires_at": {"type": "STRING", "description": "ISO-8601 date/time with timezone"}
        }, "required": ["memory_id"]}
    },
    {
        "name": "memory_forget",
        "description": "Soft-delete one exact memory after user confirmation; it immediately leaves the prompt.",
        "parameters": {"type": "OBJECT", "properties": {
            "memory_id": {"type": "STRING"}
        }, "required": ["memory_id"]}
    },
    {
        "name": "memory_restore",
        "description": "Restore a previously forgotten memory by its exact memory_id.",
        "parameters": {"type": "OBJECT", "properties": {
            "memory_id": {"type": "STRING"}
        }, "required": ["memory_id"]}
    },
    {
        "name": "memory_graph",
        "description": "Open or refresh the interactive local knowledge graph combining Obsidian notes, links, tags, and redacted JARVIS memory.",
        "parameters": {"type": "OBJECT", "properties": {
            "action": {"type": "STRING", "description": "open|refresh"}
        }, "required": []}
    },
    {
        "name": "geo_map",
        "description": (
            "Open the holographic live map or use zero-key open services to focus a real place, "
            "calculate a route, or inspect current weather. Distinguishes cities from provinces/states "
            "and countries, and accepts regional qualifiers. No billing account or API key is required."
        ),
        "parameters": {"type": "OBJECT", "properties": {
            "action": {"type": "STRING", "description": "open|status|focus|route|weather"},
            "query": {"type": "STRING", "description": "Place to focus"},
            "place_type": {"type": "STRING", "description": "Optional city|province|country disambiguation"},
            "country_code": {"type": "STRING", "description": "Optional ISO country code, e.g. AR"},
            "location": {"type": "STRING", "description": "Weather location"},
            "origin": {"type": "STRING"}, "destination": {"type": "STRING"},
            "travel_mode": {"type": "STRING", "description": "DRIVE (current zero-key routing mode)"}
        }, "required": ["action"]}
    },
    {
        "name": "math_engine",
        "description": (
            "Local exact and numeric mathematics. Use for simplification, equations, "
            "derivatives, integrals, limits, matrices, step-by-step Gaussian elimination, "
            "and exportable 2D/3D plots. Report whether the result is exact or numeric."
        ),
        "parameters": {"type": "OBJECT", "properties": {
            "action": {"type": "STRING", "description": "simplify|solve|derivative|integral|limit|numeric|matrix|gauss|plot2d|plot3d"},
            "expression": {"type": "STRING"}, "rhs": {"type": "STRING"},
            "variable": {"type": "STRING"}, "order": {"type": "INTEGER"},
            "lower": {"type": "STRING"}, "upper": {"type": "STRING"},
            "point": {"type": "STRING"}, "direction": {"type": "STRING"},
            "precision": {"type": "INTEGER"},
            "matrix": {"type": "STRING", "description": "Matrix as JSON rows, e.g. [[1,2],[3,4]]"},
            "matrix_operation": {"type": "STRING", "description": "determinant|inverse|rank|eigenvalues|eigenvectors|transpose|rref"},
            "min": {"type": "NUMBER"}, "max": {"type": "NUMBER"},
            "output_path": {"type": "STRING"}
        }, "required": ["action"]}
    },
    {
        "name": "study_engine",
        "description": (
            "Creates and displays verified artifacts in JARVIS Study. Prefer this for exercises, functions, "
            "calculus, matrices, 2D/3D models, free-body diagrams, molecules, interactive anatomy/organ "
            "schematics, chemistry, physics, medicine, or a structured "
            "science explanation. If the main app is visible Study opens automatically; in Pet Mode or while "
            "minimized the result is stored without opening the app. For a photographed exercise, first use "
            "screen_process once to transcribe it, then call Study with the structured expression/data."
        ),
        "parameters": {"type": "OBJECT", "properties": {
            "action": {"type": "STRING", "description": "status|open|present|simplify|solve|derivative|integral|limit|numeric|matrix|gauss|plot2d|plot3d|free_body|molecule|anatomy|geogebra|wolfram"},
            "subject": {"type": "STRING"}, "title": {"type": "STRING"},
            "problem": {"type": "STRING"}, "query": {"type": "STRING"},
            "result": {"type": "STRING"}, "steps": {"type": "ARRAY", "items": {"type": "STRING"}},
            "note": {"type": "STRING"}, "expression": {"type": "STRING"},
            "rhs": {"type": "STRING"}, "variable": {"type": "STRING"},
            "order": {"type": "INTEGER"}, "lower": {"type": "STRING"}, "upper": {"type": "STRING"},
            "point": {"type": "STRING"}, "direction": {"type": "STRING"}, "precision": {"type": "INTEGER"},
            "matrix": {"type": "STRING"}, "matrix_operation": {"type": "STRING"},
            "min": {"type": "NUMBER"}, "max": {"type": "NUMBER"},
            "forces": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
                "label": {"type": "STRING"}, "magnitude": {"type": "NUMBER"}, "angle_deg": {"type": "NUMBER"}
            }}},
            "smiles": {"type": "STRING"},
            "organ": {"type": "STRING", "description": "Organ for an interactive educational anatomy schematic"}
        }, "required": ["action"]}
    },
    {
        "name": "account_connector",
        "description": (
            "Connect, disconnect, inspect, search, read, download, or create items in an authorized "
            "personal account. Supports Gmail, Google Calendar and Google Drive, including native "
            "Google Docs, Sheets and Slides content. Read/search/download "
            "are direct after OAuth; Google Drive also supports find_folder, list_children, and "
            "verified file/folder and Workspace writes. Use read_workspace_file for native content; "
            "use create/append_document, create_spreadsheet, write/append_sheet, or "
            "create_presentation/append_slide for native writes. For any Google Drive request, use only this tool: "
            "never use file_controller, browser vision, or screen_process to claim a Drive change. "
            "Never claim a write succeeded unless the tool result starts with 'Verified'. Never request "
            "or store the user's password."
        ),
        "parameters": {"type": "OBJECT", "properties": {
            "provider": {"type": "STRING", "description": "gmail|outlook|google_calendar|google_drive"},
            "action": {"type": "STRING", "description": "connect|disconnect|status|search|find_folder|list_children|read|read_workspace_file|download|create_file|create_folder|create_document|append_document|create_spreadsheet|write_sheet|append_sheet|create_presentation|append_slide"},
            "query": {"type": "STRING", "description": "Provider-specific search text or Gmail query"},
            "limit": {"type": "INTEGER"}, "item_id": {"type": "STRING"},
            "attachment": {"type": "STRING"}, "destination": {"type": "STRING"},
            "name": {"type": "STRING", "description": "Name for create_file or create_folder"},
            "content": {"type": "STRING", "description": "UTF-8 text content for create_file"},
            "parent_id": {"type": "STRING", "description": "Google Drive folder ID returned by search/read"},
            "mime_type": {"type": "STRING", "description": "Optional MIME type for create_file"},
            "range": {"type": "STRING", "description": "A1 range for reading or writing Google Sheets"},
            "values": {"type": "ARRAY", "items": {"type": "ARRAY", "items": {"type": "STRING"}}, "description": "Rows of scalar values for Google Sheets"},
            "title": {"type": "STRING", "description": "Title text for a new Google Slides page"},
            "body": {"type": "STRING", "description": "Body text for a new Google Slides page"},
            "max_chars": {"type": "INTEGER", "description": "Maximum native text returned, up to 50000"}
        }, "required": ["provider", "action"]}
    },
    {
        "name": "obsidian_connector",
        "description": (
            "Search, read, open, create, or update Markdown notes in the configured local "
            "Obsidian vault. Use this for personal notes and academic material. Search/read/open "
            "are read-only; create/write/append require confirmation and preserve a backup."
        ),
        "parameters": {"type": "OBJECT", "properties": {
            "action": {"type": "STRING", "description": "status|search|read|open|create|write|append"},
            "query": {"type": "STRING"},
            "path": {"type": "STRING", "description": "Vault-relative Markdown path"},
            "content": {"type": "STRING"},
            "limit": {"type": "INTEGER"},
            "max_chars": {"type": "INTEGER"}
        }, "required": ["action"]}
    },
    {
        "name": "permission_manager",
        "description": (
            "Reports or changes the confirmation state of a specific JARVIS tool/action. "
            "Use when the user asks whether an action needs confirmation, or explicitly "
            "asks to change it. Hard security minimums can never be weakened."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "status | set"},
                "tool_name": {"type": "STRING", "description": "Tool such as file_controller"},
                "operation": {"type": "STRING", "description": "Specific action such as create_folder or delete"},
                "level": {"type": "STRING", "description": "free | confirm_once | confirm_always | blocked"},
            },
            "required": ["action", "tool_name"],
        },
    },
]

# --- Plugin system ---


class JarvisLive:

    def __init__(
        self,
        ui: JarvisUI,
        search_provider: GroundedSearchProvider | None = None,
        runtime_events: EventBus | None = None,
    ):
        _load_live_sdk()
        _load_action_dependencies()
        self.ui             = ui
        self.ui_tools       = UiCommandFacade(self.ui)
        self.search_provider = search_provider or GoogleGroundedSearchProvider.from_api_key(
            _get_api_key(),
            log=self.ui_tools.write_log,
        )
        self._events        = runtime_events or EventBus()
        self._event_subscription = self._events.subscribe(
            self._on_runtime_event
        )
        configure_browser_worker_events(self._events)
        configure_vision_worker_events(self._events)
        self._runtime       = RuntimeServices(events=self._events)
        self.session              = None
        self.audio_in_queue       = None
        self.out_queue            = None
        self._loop                = None
        self._is_speaking         = False
        self._speaking_lock       = threading.Lock()
        self._output_stream_lock  = threading.Lock()
        self._output_stream       = None
        self._playback_generation = 0
        self._phone_active        = False   # True while phone mic is streaming; pauses PC mic
        self._remote_drive_folders: set[str] = set()
        self.ui.on_text_command   = self._on_text_command
        self.ui.on_remote_clicked = self._make_remote_key
        self.ui.on_interrupt      = self.interrupt
        self._turn_done_event: asyncio.Event | None = None
        self._briefing_phase1_done: asyncio.Event | None = None
        self._briefing_phase1_played = False
        self._dashboard     = None
        self._dashboard_factory = None
        self._dashboard_tasks_started = False
        self._briefing_sent    = False          # morning briefing fires once per process
        self._briefing_inflight = False
        self._sys_monitor      = SystemMonitor()  # persistent cooldown state
        self._proactive        = ProactiveEngine()
        self._last_user_speech = time.monotonic()  # updated on every user utterance
        self._confirmation_gate = VoiceConfirmationGate(ttl_seconds=60)
        self._pending_confirmation_fc = None
        self._pending_confirmation_source: InputSource | None = None
        self._pending_confirmation_context: RequestContext | None = None
        self._confirmation_execution_scheduled = False
        self._active_input_source = self._default_source()
        self._input_source_locked = False
        handlers = {
            "open_app": lambda args: open_app(parameters=args, response=None, player=self.ui_tools),
            "weather_report": lambda args: weather_action(parameters=args, player=self.ui_tools),
            "browser_control": lambda args: browser_control(parameters=args, player=self.ui_tools),
            "file_controller": lambda args: file_controller(parameters=args, player=self.ui_tools),
            "send_message": lambda args: send_message(
                parameters=args, response=None, player=self.ui_tools, session_memory=None
            ),
            "reminder": lambda args: reminder(parameters=args, response=None, player=self.ui_tools),
            "youtube_video": lambda args: youtube_video(parameters=args, response=None, player=self.ui_tools),
            "computer_settings": lambda args: computer_settings(
                parameters=args, response=None, player=self.ui_tools
            ),
            "desktop_control": lambda args: desktop_control(parameters=args, player=self.ui_tools),
            "code_helper": lambda args: code_helper(
                parameters=args, player=self.ui_tools, speak=self.speak
            ),
            "dev_agent": lambda args, cancellation_token=None: dev_agent(
                parameters=args,
                player=self.ui_tools,
                speak=self.speak,
                cancellation_token=cancellation_token,
            ),
            "web_search": lambda args: web_search_action(
                parameters=args,
                player=self.ui_tools,
                provider=self.search_provider,
            ),
            "file_processor": self._run_file_processor,
            "computer_control": lambda args: computer_control(parameters=args, player=self.ui_tools),
            "game_updater": lambda args: game_updater(
                parameters=args, player=self.ui_tools, speak=self.speak
            ),
            "flight_finder": lambda args: flight_finder(parameters=args, player=self.ui_tools),
            "system_status": lambda args: str(get_system_status()),
            "memory_list": lambda args: list_memories(args.get("category"), args.get("status", "active")),
            "memory_search": lambda args: search_memories(args.get("query", ""), args.get("category")),
            "memory_update": lambda args: update_memory_by_id(
                args["memory_id"], **{k: args[k] for k in ("value", "expires_at") if k in args}
            ),
            "memory_forget": lambda args: forget_memory(args["memory_id"]),
            "memory_restore": lambda args: restore_memory(args["memory_id"]),
            "memory_graph": self._open_memory_graph,
            "geo_map": self._run_geo_map,
            "math_engine": lambda args: study_engine(parameters=args, player=self.ui_tools),
            "study_engine": lambda args: study_engine(parameters=args, player=self.ui_tools),
            "account_connector": lambda args: account_connector(parameters=args, player=self.ui_tools),
            "obsidian_connector": lambda args: obsidian_connector(parameters=args, player=self.ui_tools),
            "pet_mode": lambda args: self.ui_tools.enter_pet_mode(
                "LISTENING", "Pet Mode active."
            ) or "Pet Mode activated; the voice session remains active.",
            "interface_control": lambda args: self.ui_tools.control_interface(
                args.get("action", "open"),
                args.get("target", "status"),
                args.get("mode", ""),
            ),
        }
        self.tool_registry = build_builtin_registry(TOOL_DECLARATIONS, handlers)
        self.permission_store = PermissionStore()
        self.permission_policy = PermissionPolicy(self.permission_store.load())
        self.request_audit = RequestAuditSink()
        self.tool_executor = ToolExecutor(
            self.tool_registry,
            audit_sink=self.request_audit,
        )

    def _open_memory_graph(self, _args: dict):
        self.ui_tools.show_memory_graph()
        return "Interactive local memory graph opened and reindexed."

    def _run_geo_map(self, args: dict):
        action = str(args.get("action", "open")).lower()
        if action == "open":
            self.ui_tools.show_geo()
            return "Holographic geographic workspace opened in local mode."
        result = open_geo(args)
        if action in {"focus", "place"}:
            self.ui_tools.show_geo(result)
        elif action == "route":
            route_view = dict(result.get("destination") or {})
            route_view["path"] = result.get("path", [])
            self.ui_tools.show_geo(route_view)
            distance = float(result.get("distance_meters", 0)) / 1000
            self.ui_tools.show_content(
                "ROUTE / OPEN DATA",
                f"{result['origin'].get('name')}  →  {result['destination'].get('name')}\n"
                f"DISTANCE  {distance:.1f} km\nDURATION  {result.get('duration', 'N/A')}\n"
                f"MODE      {result.get('travel_mode', 'DRIVE')}",
            )
        elif action == "weather":
            self.ui_tools.show_geo(result.get("place"))
            self.ui_tools.show_content(
                "WEATHER / OPEN-METEO",
                json.dumps(result, ensure_ascii=False, indent=2)[:4000],
            )
        return result

    def _run_file_processor(self, args: dict):
        args = dict(args)
        if not args.get("file_path") and self.ui_tools.current_file:
            args["file_path"] = self.ui_tools.current_file
        return file_processor(parameters=args, player=self.ui_tools, speak=self.speak)

    def _manage_permission(self, args: dict) -> str:
        action = str(args.get("action", "status")).lower().strip()
        tool_name = str(args.get("tool_name", "")).strip()
        operation = str(args.get("operation", "default")).lower().strip().replace(" ", "_")
        try:
            definition = self.tool_registry.get(tool_name)
        except KeyError:
            return f"Unknown tool: {tool_name}"
        probe = {"action": operation}
        if action in {"status", "get", "query"}:
            info = self.permission_policy.describe(definition, probe)
            return (
                f"{tool_name}/{operation}: effective={info['effective']}, "
                f"configured={info['configured']}, immutable minimum={info['minimum']}."
            )
        if action not in {"set", "change", "update"}:
            return "Permission action must be status or set."
        if operation == "default":
            return "Specify the exact operation whose permission should change."
        try:
            requested = PermissionLevel.parse(args.get("level", ""))
        except (KeyError, ValueError):
            return "Level must be free, confirm_once, confirm_always, or blocked."
        minimum = self.permission_policy.minimum(definition, operation)
        if requested < minimum:
            return (
                f"Denied: {tool_name}/{operation} has immutable minimum "
                f"{minimum.label}; it cannot be reduced to {requested.label}."
            )
        preferences = self.permission_store.load()
        preferences[f"{tool_name}:{operation}"] = requested
        self.permission_store.save(preferences)
        self.permission_policy = PermissionPolicy(self.permission_store.load())
        return f"Permission updated: {tool_name}/{operation} is now {requested.label}."

    def _make_remote_key(self):
        """Called from Qt main thread when user presses Remote Control."""
        if self._dashboard_factory is None or not self._loop:
            self.ui.write_log(
                "SYS: Dashboard unavailable. "
                "Run: pip install fastapi \"uvicorn[standard]\" cryptography"
            )
            return None
        try:
            future = asyncio.run_coroutine_threadsafe(
                self._enable_dashboard(), self._loop
            )
            future.result(timeout=5)
        except Exception as exc:
            self.ui.write_log(f"SYS: Dashboard could not start: {exc}")
            return None
        key    = self._dashboard.new_key()
        url    = self._dashboard.get_url()
        manual = self._dashboard.get_manual_url()
        return url, key, f"{url}/auto-login?key={key}", manual

    async def _enable_dashboard(self) -> None:
        """Start LAN services only after explicit local user action."""
        if self._dashboard_tasks_started:
            return
        if self._dashboard is None:
            self._dashboard = self._dashboard_factory(events=self._events)
        self._dashboard_tasks_started = True
        asyncio.create_task(self._dashboard.serve())
        asyncio.create_task(self._process_dashboard_commands())
        await asyncio.sleep(0)

    @staticmethod
    def _default_source() -> InputSource:
        if os.environ.get("JARVIS_WAKE_SUPERVISED") == "1":
            return InputSource.WAKE
        return InputSource.LOCAL

    def _set_input_source(self, source: InputSource, *, lock: bool = False) -> None:
        current = getattr(self, "_active_input_source", self._default_source())
        locked = getattr(self, "_input_source_locked", False)
        if locked and current != source:
            # A remote ingress can raise trust requirements, but no later local
            # frame may downgrade a turn that already contains remote input.
            if current.is_remote or not source.is_remote:
                return
        self._active_input_source = source
        self._input_source_locked = lock or locked

    def _reset_input_source(self) -> None:
        self._active_input_source = self._default_source()
        self._input_source_locked = False

    def _audit_request(
        self,
        context: RequestContext,
        event: str,
        tool: str,
        **metadata,
    ) -> None:
        sink = getattr(self, "request_audit", None)
        if sink is None:
            return
        try:
            sink.record(context, event, tool, **metadata)
        except Exception:
            # Audit is intentionally best effort and cannot block a tool response.
            pass

    def _function_response(
        self,
        fc,
        context: RequestContext,
        response: dict,
        *,
        completed: bool = False,
        outcome: str | None = None,
        duration_ms: float | None = None,
    ) -> types.FunctionResponse:
        # Production loads the SDK in __init__. Keep this boundary resilient
        # for isolated adapters/tests that intentionally construct via __new__.
        if types is None:
            _load_live_sdk()
        payload = dict(response)
        payload["request_id"] = context.request_id
        response_outcome = outcome or (
            "error" if payload.get("error") else "success"
        )
        if completed:
            self._audit_request(
                context,
                "completed",
                fc.name,
                outcome=response_outcome,
                error_code=payload.get("error"),
                duration_ms=duration_ms,
            )
        self._audit_request(
            context,
            "response",
            fc.name,
            outcome=response_outcome,
            error_code=payload.get("error"),
        )
        return types.FunctionResponse(
            id=fc.id,
            name=fc.name,
            response=payload,
        )

    async def _send_text_input(self, text: str, source: InputSource) -> None:
        self._set_input_source(source, lock=True)
        await self.session.send_realtime_input(text=text)

    def _on_text_command(self, text: str):
        if not self._loop or not self.session:
            return
        if self._handle_confirmation_text(text):
            return
        asyncio.run_coroutine_threadsafe(
            self._send_text_input(text, InputSource.UI),
            self._loop
        )

    def _handle_confirmation_text(self, text: str) -> bool:
        """Observe an explicit voice/text yes or no for the pending action."""
        decision = self._confirmation_gate.observe(text)
        if decision == "approved":
            if self._pending_confirmation_fc and not self._confirmation_execution_scheduled:
                self._confirmation_execution_scheduled = True
                self.ui.write_log("SECURITY: Spoken approval received.")
                self._loop.call_soon_threadsafe(
                    lambda: asyncio.create_task(self._execute_confirmed_pending())
                )
            return True
        if decision == "denied":
            pending_fc = self._pending_confirmation_fc
            pending_context = getattr(self, "_pending_confirmation_context", None)
            self._pending_confirmation_fc = None
            self._pending_confirmation_source = None
            self._pending_confirmation_context = None
            if pending_fc is not None and pending_context is not None:
                self._audit_request(
                    pending_context,
                    "confirmation",
                    pending_fc.name,
                    outcome="denied",
                )
                self._audit_request(
                    pending_context,
                    "completed",
                    pending_fc.name,
                    outcome="denied",
                )
            self.ui.write_log("SECURITY: Spoken confirmation denied.")
            if self._loop and self.session:
                asyncio.run_coroutine_threadsafe(
                    self.session.send_realtime_input(
                        text=(
                            "[CONFIRMATION_DENIED] The user denied the pending action. "
                            "Acknowledge briefly and do not call the tool."
                        )
                    ),
                    self._loop,
                )
            return True
        return False

    async def _execute_confirmed_pending(self) -> None:
        """Execute the staged action after the user's explicit spoken approval."""
        fc = self._pending_confirmation_fc
        source = self._pending_confirmation_source
        context = getattr(self, "_pending_confirmation_context", None)
        self._pending_confirmation_fc = None
        self._pending_confirmation_source = None
        self._pending_confirmation_context = None
        try:
            if fc is None:
                return
            self._confirmation_gate.clear()
            response = await self._execute_tool(
                fc,
                preapproved=True,
                source=source,
                request_context=context,
            )
            payload = getattr(response, "response", {}) or {}
            result = payload.get("result", "Done.") if isinstance(payload, dict) else str(payload)
            if self.session:
                await self.session.send_realtime_input(
                    text=(
                        "[CONFIRMED_ACTION_RESULT] The approved action has now executed. "
                        f"Result: {str(result)[:800]}. Tell the user briefly."
                    )
                )
        finally:
            self._confirmation_execution_scheduled = False

    def set_speaking(self, value: bool):
        with self._speaking_lock:
            self._is_speaking = value
        if value:
            self.ui.set_state("SPEAKING")
        elif self.ui.microphone_enabled:
            self.ui.set_state("LISTENING")

    def interrupt(self) -> None:
        """Thread-safe ESC handler: cancel the model turn and local playback."""
        serial = self._runtime.audio.begin_interrupt()
        self.set_speaking(False)
        self.ui.write_log("SYS: Interrupted — listening...")
        if self._loop:
            self._loop.call_soon_threadsafe(
                lambda: asyncio.create_task(self._interrupt_model_turn(serial))
            )

    async def _interrupt_model_turn(self, serial: int) -> None:
        """Cancel one model turn and always restore the microphone afterwards."""
        await self._flush_playback("ESC")
        if not self.session:
            self._release_interrupt(serial)
            return
        try:
            await self.session.send_realtime_input(
                text="[USER_INTERRUPT] Stop the current response now. Do not reply to this marker."
            )
        except Exception as exc:
            # Local playback is already stopped; retain a useful diagnostic if the
            # active Live API version cannot accept manual activity signals.
            self.ui.write_log(f"AUDIO: Model cancellation signal failed: {exc}")
        finally:
            # A missing turn_complete used to leave _send_realtime dropping
            # microphone frames forever after ESC.
            await asyncio.sleep(0.75)
            self._release_interrupt(serial)

    def _release_interrupt(self, serial: int) -> None:
        """Clear only the interrupt generation that requested this recovery."""
        if not self._runtime.audio.release_interrupt(serial):
            return
        if self.ui.microphone_enabled:
            self.ui.set_state("LISTENING")

    def _reset_output_stream(self) -> None:
        """Drop bytes already buffered by the audio device without killing the task."""
        with self._output_stream_lock:
            stream = self._output_stream
            if stream is None:
                return
            try:
                stream.abort(ignore_errors=True)
                stream.start()
            except Exception as exc:
                print(f"[JARVIS] ⚠️ Output reset failed: {exc}")

    async def _flush_playback(self, reason: str) -> None:
        """Run queue/device mutations on the asyncio thread."""
        self._playback_generation += 1
        drained = 0
        q = self.audio_in_queue
        if q:
            while True:
                try:
                    q.get_nowait()
                    drained += 1
                except asyncio.QueueEmpty:
                    break
        if self._turn_done_event:
            self._turn_done_event.clear()
        await asyncio.to_thread(self._reset_output_stream)
        self.set_speaking(False)
        if self._briefing_phase1_done:
            # Release the waiter without reporting discarded audio as played.
            self._briefing_phase1_played = False
            self._briefing_phase1_done.set()
        print(f"[JARVIS] ✋ {reason} interruption — {drained} queued chunks discarded")

    def speak(self, text: str):
        if not self._loop or not self.session:
            return
        asyncio.run_coroutine_threadsafe(
            self.session.send_realtime_input(text=text),
            self._loop
        )

    def speak_error(self, tool_name: str, error: str):
        short = str(error)[:120]
        self.ui.write_log(f"ERR: {tool_name} — {short}")
        self.speak(f"Sir, {tool_name} encountered an error. {short}")

    def _build_config(self) -> types.LiveConnectConfig:
        memory     = load_memory()
        mem_str    = format_memory_for_prompt(memory)
        scripts_str = format_scripts_for_prompt()
        sys_prompt = _load_system_prompt()

        time_str = prompt_datetime()
        time_ctx = (
            f"[CURRENT DATE & TIME]\n"
            f"Right now it is: {time_str}\n"
            f"Authoritative timezone: America/Buenos_Aires (UTC-03:00).\n"
            f"Never infer the date from UTC or save a conflicting date in memory.\n"
            f"Use this to calculate exact times for reminders.\n\n"
        )

        parts = [time_ctx]
        if mem_str:
            parts.append(mem_str)
        if scripts_str:
            parts.append(scripts_str)
        parts.append(sys_prompt)
        parts.append(
            """LIVE MICROPHONE TURN POLICY (highest priority):
Prioritize hearing and answering the user. Do not require the user to say JARVIS, and do not discard a clear intelligible request merely because it is short or might be part of nearby conversation. Short replies such as yes, no, stop, cancel, or a requested value are valid whenever their meaning is clear from the current exchange.
Ignore only audio that contains no intelligible speech, such as steady room noise, microphone hiss, a fan, or an isolated bump; never announce that such noise was ignored. If speech is audible but the actual request is clipped, incomplete, or unintelligible, ask the user once, briefly and naturally, to repeat it instead of remaining silent or guessing the missing words. Emergency interruption words such as stop, cancel, silence, or shut up must always be honored immediately."""
        )
        # Keep this last so general prompt text cannot override the explicit
        # response-language preference.
        parts.append(format_language_instruction(memory))

        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            output_audio_transcription={},
            input_audio_transcription={},
            system_instruction="\n".join(parts),
            tools=[{"function_declarations": self.tool_registry.declarations(
                predicate=self.permission_policy.is_advertised
            )}],
            realtime_input_config=types.RealtimeInputConfig(
                # Microphone frames are suppressed during playback, so ambient sound
                # cannot barge in. Explicit ESC text activity still cancels the turn.
                activity_handling=types.ActivityHandling.START_OF_ACTIVITY_INTERRUPTS,
                automatic_activity_detection=types.AutomaticActivityDetection(
                    disabled=False,
                    start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_HIGH,
                    end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_LOW,
                    # Retain quiet initial consonants without delaying detection.
                    prefix_padding_ms=500,
                    # Allow natural hesitations without handing the turn to JARVIS.
                    silence_duration_ms=1500,
                ),
            ),
            session_resumption=types.SessionResumptionConfig(
                handle=self._runtime.session.resumption.resumption_handle,
            ),
            context_window_compression=types.ContextWindowCompressionConfig(
                sliding_window=types.SlidingWindow(),
            ),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name="Charon"
                    )
                )
            ),
        )

    async def _execute_tool(
        self,
        fc,
        preapproved: bool = False,
        source: InputSource | None = None,
        request_context: RequestContext | None = None,
    ) -> types.FunctionResponse:
        name = fc.name
        args = dict(fc.args or {})
        if request_context is None:
            execution_source = source or getattr(
                self,
                "_active_input_source",
                self._default_source(),
            )
            request_context = RequestContext.create(
                execution_source,
                tool_call_id=str(fc.id),
            )
            self._audit_request(request_context, "requested", name)
        else:
            execution_source = request_context.source
        request_started_at = time.monotonic()

        if name in {"file_processor", "code_helper", "dev_agent", "desktop_control", "computer_control"}:
            from actions.file_controller import _is_protected_path
            for field in ("path", "file_path", "output_path", "destination"):
                raw_path = args.get(field)
                if not raw_path or str(raw_path).lower() in {
                    "desktop", "documents", "downloads", "pictures", "music", "videos", "home"
                }:
                    continue
                if _is_protected_path(Path(str(raw_path)).expanduser()):
                    return self._function_response(
                        fc,
                        request_context,
                        {
                            "result": "Access denied: protected system, credential, or private path.",
                            "error": "protected_path",
                        },
                        completed=True,
                        outcome="blocked",
                        duration_ms=(time.monotonic() - request_started_at) * 1000,
                    )

        print(f"[JARVIS] 🔧 {name}  {safe_tool_args(args)}")
        self.ui.set_state("THINKING")

        if name == "shutdown_jarvis" and self._pending_confirmation_fc is not None:
            cancelled_fc = self._pending_confirmation_fc
            cancelled_context = getattr(self, "_pending_confirmation_context", None)
            self._pending_confirmation_fc = None
            self._pending_confirmation_source = None
            self._pending_confirmation_context = None
            if cancelled_context is not None:
                self._audit_request(
                    cancelled_context,
                    "confirmation",
                    cancelled_fc.name,
                    outcome="cancelled",
                )
                self._audit_request(
                    cancelled_context,
                    "completed",
                    cancelled_fc.name,
                    outcome="cancelled",
                )
            self._confirmation_gate.clear()
            self._confirmation_execution_scheduled = False
            self.ui.write_log("SECURITY: Pending confirmation cancelled by shutdown.")

        if self._pending_confirmation_fc is not None and not preapproved:
            return self._function_response(
                fc,
                request_context,
                {"result": (
                    "[VOICE_CONFIRMATION_ALREADY_PENDING] Wait for the user's yes or no. "
                    "Do not call this or another tool again."
                )},
                completed=True,
                outcome="blocked",
                duration_ms=(time.monotonic() - request_started_at) * 1000,
            )

        loop   = asyncio.get_event_loop()
        result = "Done."
        result_success = True
        result_error = None
        result_contract: ToolResult | None = None

        try:
            definition = self.tool_registry.validate_for_execution(name)
            self.tool_registry.validate_arguments(definition, args)
        except (KeyError, PermissionError, RuntimeError, TypeError, ValueError) as exc:
            return self._function_response(
                fc,
                request_context,
                {"result": str(exc), "error": "unavailable"},
                completed=True,
                duration_ms=(time.monotonic() - request_started_at) * 1000,
            )

        decision = self.permission_policy.evaluate(
            definition,
            args,
            ExecutionContext(
                source=execution_source,
                simulate=bool(args.get("simulate", False)),
                request_id=request_context.request_id,
            ),
        )
        self._audit_request(
            request_context,
            "policy",
            name,
            operation=decision.operation,
            policy=decision.policy,
            outcome=(
                "confirmation_required"
                if decision.requires_confirmation
                else "allowed" if decision.allowed else "blocked"
            ),
        )
        print(
            f"[SECURITY] {name}/{decision.operation}: {decision.policy} "
            f"simulated={decision.simulated}"
        )
        if decision.simulated:
            preview = build_preview(name, args, decision)
            self._audit_request(
                request_context,
                "confirmation",
                name,
                outcome="not_applicable",
            )
            if self.ui.microphone_enabled:
                self.ui.set_state("LISTENING")
            return self._function_response(
                fc,
                request_context,
                {"result": preview},
                completed=True,
                outcome="simulated",
                duration_ms=(time.monotonic() - request_started_at) * 1000,
            )
        if not decision.allowed and not decision.requires_confirmation:
            self._audit_request(
                request_context,
                "confirmation",
                name,
                outcome="not_applicable",
            )
            if self.ui.microphone_enabled:
                self.ui.set_state("LISTENING")
            return self._function_response(
                fc,
                request_context,
                {"result": decision.reason, "error": "blocked"},
                completed=True,
                outcome="blocked",
                duration_ms=(time.monotonic() - request_started_at) * 1000,
            )

        approval = confirmation_request(name, args)
        if decision.requires_confirmation and not preapproved:
            if approval is None:
                approval = (
                    "Approve this action?",
                    f"Tool: {name}. Operation: {decision.operation}.",
                )
            title, detail = approval
            approved = self._confirmation_gate.authorize_or_stage(
                name, args, title, detail
            )
            if not approved:
                self._pending_confirmation_fc = fc
                self._pending_confirmation_source = execution_source
                self._pending_confirmation_context = request_context
                self._audit_request(
                    request_context,
                    "confirmation",
                    name,
                    outcome="requested",
                )
                self.ui.write_log(f"SECURITY DETAIL: {detail.replace(chr(10), ' | ')}")
                question = "Confirm action?"
                self.ui.write_log(f"SECURITY: Awaiting spoken approval for {name}.")
                if self.ui.microphone_enabled:
                    self.ui.set_state("LISTENING")
                return self._function_response(
                    fc,
                    request_context,
                    {
                        "result": f'[VOICE_CONFIRMATION_REQUIRED] Say exactly "{question}" Then wait.'
                    },
                    outcome="confirmation_required",
                )
            if name == "computer_settings":
                args["confirmed"] = "yes"
        elif decision.requires_confirmation and preapproved:
            self._audit_request(
                request_context,
                "confirmation",
                name,
                outcome="approved",
            )
            self.ui.write_log(f"SECURITY: Executing preapproved action {name} once.")
            if name == "computer_settings":
                args["confirmed"] = "yes"
        else:
            self._audit_request(
                request_context,
                "confirmation",
                name,
                outcome="not_required",
            )

        try:
            if name == "file_controller" and str(args.get("action", "")).lower() in {
                "create_file", "create_folder", "new_file", "new_folder", "mkdir",
            }:
                local_path = str(args.get("path") or args.get("name") or "")
                first_part = local_path.replace("\\", "/").strip("/").split("/", 1)[0]
                if first_part.casefold() in self._remote_drive_folders:
                    result = (
                        f"Blocked local write: {first_part!r} was identified as a Google Drive "
                        "folder in this session. Use account_connector with find_folder and then "
                        "create_file/create_folder using its parent_id. No file was created."
                    )
                    self._audit_request(request_context, "started", name)
                    return self._function_response(
                        fc,
                        request_context,
                        {"result": result, "error": "wrong_storage_provider"},
                        completed=True,
                        outcome="blocked",
                        duration_ms=(time.monotonic() - request_started_at) * 1000,
                    )
            if name in SPECIAL_TOOLS:
                self._audit_request(request_context, "started", name)

            if name not in SPECIAL_TOOLS:
                execution = await self.tool_executor.execute(
                    name,
                    args,
                    context=request_context,
                )
                result = execution.message
                result_success = execution.success
                result_error = execution.error_code
                result_contract = execution
                if name == "account_connector" and execution.success:
                    provider = str(args.get("provider", "")).casefold()
                    action = str(args.get("action", "")).casefold()
                    if provider in {"drive", "google_drive"} and action in {
                        "search", "find_folder", "read",
                    }:
                        try:
                            payload = json.loads(str(execution.data))
                            items = payload if isinstance(payload, list) else [payload]
                            for item in items:
                                if (
                                    isinstance(item, dict)
                                    and item.get("mimeType") == "application/vnd.google-apps.folder"
                                    and item.get("name")
                                ):
                                    self._remote_drive_folders.add(
                                        str(item["name"]).casefold()
                                    )
                        except (TypeError, json.JSONDecodeError):
                            pass
                if not execution.success and execution.error_code == "exception":
                    self.speak_error(name, RuntimeError(result))
                if name == "web_search" and execution.success:
                    raw_result = execution.data
                    mode = args.get("mode", "search")
                    if (
                        raw_result
                        and not raw_result.startswith("No results")
                        and not raw_result.startswith("Search failed")
                    ):
                        query = args.get("query") or ", ".join(args.get("items", []))
                        label = f"{mode.upper()} — {query[:38]}" if query else mode.upper()
                        self.ui.show_content(label, raw_result)

            elif name == "weather_report":
                r = await loop.run_in_executor(None, lambda: weather_action(parameters=args, player=self.ui_tools))
                result = r or "Weather delivered."

            elif name == "browser_control":
                r = await loop.run_in_executor(None, lambda: browser_control(parameters=args, player=self.ui_tools))
                result = r or "Done."

            elif name == "file_controller":
                r = await loop.run_in_executor(None, lambda: file_controller(parameters=args, player=self.ui_tools))
                result = r or "Done."

            elif name == "send_message":
                r = await loop.run_in_executor(None, lambda: send_message(parameters=args, response=None, player=self.ui_tools, session_memory=None))
                result = r or f"Message sent to {args.get('receiver')}."

            elif name == "reminder":
                r = await loop.run_in_executor(None, lambda: reminder(parameters=args, response=None, player=self.ui_tools))
                result = r or "Reminder set."

            elif name == "youtube_video":
                r = await loop.run_in_executor(None, lambda: youtube_video(parameters=args, response=None, player=self.ui_tools))
                result = r or "Done."

            elif name == "screen_process":
                _now = time.monotonic()
                _cooldown = 4.0  # seconds — covers echo window after speaking ends
                if not self._runtime.vision.try_begin_analysis(
                    now=_now,
                    cooldown=_cooldown,
                    request_id=request_context.request_id,
                ):
                    _wait = self._runtime.vision.cooldown_remaining(
                        now=_now,
                        cooldown=_cooldown,
                    )
                    print(f"[Vision] ⏳ Cooldown active ({_wait:.1f}s remaining) — ignoring duplicate call")
                    result = "Vision is still processing the previous request. I will not call this again."
                else:
                    angle = args.get("angle", "screen").lower()
                    user_text = args.get("text", "What do you see?")
                    try:
                        if angle == "camera":
                            analysis = await loop.run_in_executor(
                                None, lambda: analyze_visual(user_text, "camera")
                            )
                            self.ui.set_camera_frame_callback(self._stream_camera_frame)
                            self.ui.start_camera_stream()
                            result = (
                                f"Live camera attached to this primary voice session. {analysis}"
                            )
                        else:
                            result = await loop.run_in_executor(
                                None, lambda: analyze_visual(user_text, angle)
                            )
                    finally:
                        self._runtime.vision.finish_analysis()

            elif name == "visual_mouse":
                mouse_action = {
                    "move": "screen_move",
                    "click": "screen_click",
                    "double_click": "screen_double_click",
                    "right_click": "screen_right_click",
                }.get(str(args.get("action", "click")).lower(), "screen_click")
                mouse_args = {
                    "action": mouse_action,
                    "description": args.get("description", ""),
                }
                r = await loop.run_in_executor(
                    None, lambda: computer_control(parameters=mouse_args, player=self.ui_tools)
                )
                result = r or "Visual mouse action completed."

            elif name == "close_camera":
                self.ui.stop_camera_stream()
                self._runtime.vision.finish_camera_frame()
                result = "Camera closed."

            elif name == "camera_control":
                mode = str(args.get("mode", "normal")).lower()
                if mode not in {"normal", "hand"}:
                    mode = "normal"
                zoom = max(1.0, min(4.0, float(args.get("zoom", 1.0))))
                pan_x = max(-1.0, min(1.0, float(args.get("pan_x", 0.0))))
                pan_y = max(-1.0, min(1.0, float(args.get("pan_y", 0.0))))
                self.ui.set_camera_mode(mode)
                self.ui.set_camera_view(zoom, pan_x, pan_y)
                result = f"Camera set to {mode} mode; zoom {zoom:.1f}."

            elif name == "permission_manager":
                result = self._manage_permission(args)

            elif name == "save_memory":
                category = args.get("category", "notes")
                key = args.get("key", "")
                value = args.get("value", "")
                saved = {"result": "invalid", "error": "missing key/value"}
                if key and value:
                    saved = create_memory(
                        category,
                        key,
                        value,
                        expires_at=args.get("expires_at"),
                        replace=bool(args.get("replace_existing", False)),
                        contexts=args.get("contexts"),
                    )
                    if saved.get("result") in {"created", "updated", "unchanged"}:
                        self.ui.refresh_memory_graph()
                    print(
                        f"[Memory] save_memory: {category}/{key} = "
                        f"[redacted] ({saved['result']})"
                    )
                result = saved

            elif name == "computer_settings":
                r = await loop.run_in_executor(None, lambda: computer_settings(parameters=args, response=None, player=self.ui_tools))
                result = r or "Done."

            elif name == "desktop_control":
                r = await loop.run_in_executor(None, lambda: desktop_control(parameters=args, player=self.ui_tools))
                result = r or "Done."

            elif name == "code_helper":
                r = await loop.run_in_executor(None, lambda: code_helper(parameters=args, player=self.ui_tools, speak=self.speak))
                result = r or "Done."

            elif name == "dev_agent":
                r = await loop.run_in_executor(None, lambda: dev_agent(parameters=args, player=self.ui_tools, speak=self.speak))
                result = r or "Done."

            elif name == "web_search":
                r = await loop.run_in_executor(
                    None,
                    lambda: web_search_action(
                        parameters=args,
                        player=self.ui_tools,
                        provider=self.search_provider,
                    ),
                )
                result = r or "Done."
                # Mirror results to the on-screen content panel
                _mode = args.get("mode", "search")
                if r and not r.startswith("No results") and not r.startswith("Search failed"):
                    _query = args.get("query") or ", ".join(args.get("items", []))
                    _label = f"{_mode.upper()} — {_query[:38]}" if _query else _mode.upper()
                    self.ui.show_content(_label, r)
            elif name == "file_processor":
                if not args.get("file_path") and self.ui_tools.current_file:
                    args["file_path"] = self.ui_tools.current_file
                r = await loop.run_in_executor(
                    None,
                    lambda: file_processor(parameters=args, player=self.ui_tools, speak=self.speak)
                )
                result = r or "Done."

            elif name == "computer_control":
                r = await loop.run_in_executor(None, lambda: computer_control(parameters=args, player=self.ui_tools))
                result = r or "Done."

            elif name == "game_updater":
                r = await loop.run_in_executor(None, lambda: game_updater(parameters=args, player=self.ui_tools, speak=self.speak))
                result = r or "Done."

            elif name == "flight_finder":
                r = await loop.run_in_executor(None, lambda: flight_finder(parameters=args, player=self.ui_tools))
                result = r or "Done."

            elif name == "system_status":
                r = await loop.run_in_executor(None, get_system_status)
                result = str(r)

            elif name == "shutdown_jarvis":
                self.ui.write_log("SYS: Shutdown requested.")
                if self._runtime.lifecycle.request_shutdown(
                    request_id=request_context.request_id,
                ):
                    asyncio.create_task(self._shutdown_fallback_timeout())
                result = (
                    "[SHUTDOWN_SCHEDULED] Say one brief, natural goodbye in the user's "
                    "language now. Do not call another tool. JARVIS will close only after "
                    "the farewell audio finishes playing."
                )

            else:
                result = f"Unknown tool: {name}"
                result_success = False
                result_error = "unknown_tool"

        except Exception as e:
            result = f"Tool '{name}' failed: {e}"
            result_success = False
            result_error = "exception"
            traceback.print_exc()
            self.speak_error(name, e)

        if name in SPECIAL_TOOLS:
            if result_success:
                normalized = normalize_tool_output(
                    name,
                    result,
                    "Done.",
                    risk=definition.risk,
                )
            else:
                normalized = ToolResult(
                    False,
                    str(result),
                    error_code=result_error,
                    execution_status=ExecutionStatus.FAILED,
                    effect_status=EffectStatus.UNKNOWN,
                    verification_status=VerificationStatus.UNKNOWN,
                )
            result_contract = replace(
                normalized,
                request_id=request_context.request_id,
                duration_ms=(time.monotonic() - request_started_at) * 1000,
            )
            result = result_contract.message
            result_success = result_contract.success
            result_error = result_contract.error_code
            self._audit_request(
                request_context,
                "completed",
                name,
                outcome="success" if result_success else "error",
                error_code=result_error,
                duration_ms=result_contract.duration_ms,
                execution_status=result_contract.execution_status.value,
                effect_status=result_contract.effect_status.value,
                verification_status=result_contract.verification_status.value,
                rollback_status=result_contract.rollback_status.value,
            )

        if self.ui.microphone_enabled:
            self.ui.set_state("LISTENING")

        print(f"[JARVIS] 📤 {name} → {str(result)[:80]}")
        return self._function_response(
            fc,
            request_context,
            {
                "result": result,
                "success": result_success,
                "error": result_error,
                "tool_result": (
                    result_contract.to_dict(include_data=False)
                    if result_contract is not None
                    else None
                ),
            },
            outcome="success" if result_success else "error",
        )

    def _stream_camera_frame(self, image_bytes: bytes) -> None:
        """Attach camera video to the same Live session that owns voice and playback."""
        if not self._loop or not self.session or not image_bytes:
            return

        def _schedule() -> None:
            frame_generation = (
                self._runtime.vision.try_queue_camera_frame()
            )
            if frame_generation is None:
                return
            asyncio.create_task(
                self._send_camera_frame(image_bytes, frame_generation)
            )

        self._loop.call_soon_threadsafe(_schedule)

    async def _send_camera_frame(
        self,
        image_bytes: bytes,
        generation: int,
    ) -> None:
        try:
            if self.session:
                await self.session.send_realtime_input(
                    video=types.Blob(data=image_bytes, mime_type="image/jpeg")
                )
        except Exception as exc:
            print(f"[Camera] Primary-session frame failed: {exc}")
        finally:
            self._runtime.vision.finish_camera_frame(generation)

    async def _send_realtime(self):
        while True:
            msg = await self.out_queue.get()
            source, audio = msg
            self._set_input_source(source)
            with self._speaking_lock:
                jarvis_speaking = self._is_speaking
            if jarvis_speaking or self._runtime.audio.interrupted:
                continue
            await self.session.send_realtime_input(audio=audio)

    async def _listen_audio(self):
        print("[JARVIS] 🎤 Mic started")
        loop = asyncio.get_event_loop()

        def _apply_audio_transition(transition: str) -> None:
            if transition == "sleep":
                asyncio.create_task(self._close_idle_audio_stream())
            elif transition == "wake":
                self.ui.set_state("LISTENING")
                self.ui.write_log(
                    "AUDIO: Voice detected; listening stream reinitialized."
                )

        def _enqueue_audio(item: tuple[InputSource, types.Blob]) -> None:
            try:
                self.out_queue.put_nowait(item)
            except asyncio.QueueFull:
                # Preserve the most recent speech instead of a stale backlog.
                try:
                    self.out_queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    self.out_queue.put_nowait(item)
                except asyncio.QueueFull:
                    pass

        def callback(indata, frames, time_info, status):
            # Do not feed the speakers (or ambient noise) back into Gemini while
            # JARVIS is talking. Listening resumes when playback ends or ESC calls
            # set_speaking(False).
            with self._speaking_lock:
                jarvis_speaking = self._is_speaking
            self._runtime.audio.mark_microphone_callback()
            mic_active = (
                self.ui.microphone_enabled
                and not self._phone_active
                and not jarvis_speaking
            )
            data = indata.tobytes()
            transition = self._runtime.audio.watchdog.observe_pcm(
                data,
                active=mic_active,
            )
            if transition in {"sleep", "wake"}:
                loop.call_soon_threadsafe(_apply_audio_transition, transition)
            if mic_active and transition not in {"sleep", "sleeping"}:
                loop.call_soon_threadsafe(
                    _enqueue_audio,
                    (
                        self._default_source(),
                        types.Blob(
                            data=data,
                            mime_type=f"audio/pcm;rate={SEND_SAMPLE_RATE}",
                        ),
                    ),
                )

        while True:
            try:
                with sd.InputStream(
                    samplerate=SEND_SAMPLE_RATE,
                    channels=CHANNELS,
                    dtype="int16",
                    blocksize=CHUNK_SIZE,
                    callback=callback,
                ):
                    print("[JARVIS] 🎤 Mic stream open")
                    self._runtime.audio.mark_microphone_callback()
                    while True:
                        await asyncio.sleep(0.1)
                        # Some Windows drivers stop invoking the callback after a
                        # hardware mute without raising a PortAudio exception.
                        # Reopening only the local stream is safe and keeps the
                        # active Live conversation untouched.
                        if self._runtime.audio.microphone_stalled(
                            threshold=2.0
                        ):
                            raise RuntimeError("microphone callback stalled")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                print(f"[JARVIS] ❌ Mic: {e}; retrying in 1 second")
                self.ui.write_log("AUDIO: Microphone lost; reconnecting...")
                self._runtime.audio.mark_microphone_recovery()
                await asyncio.sleep(1)

    async def _close_idle_audio_stream(self) -> None:
        """End a muted/idle input stream while preserving the Live session."""
        if not self.session or not self.ui.microphone_enabled:
            return
        try:
            await self.session.send_realtime_input(audio_stream_end=True)
            self.ui.set_state("SLEEPING")
            self.ui.write_log(
                "AUDIO: No voice for 12 seconds; sleeping until voice returns."
            )
        except Exception as exc:
            # The regular session reconnect loop remains the fallback for a
            # transport that disappears while the microphone is being reset.
            self._runtime.audio.watchdog.reset()
            print(f"[JARVIS] Audio stream reset failed: {exc}")

    async def _receive_audio(self):
        print("[JARVIS] 👂 Recv started")
        out_buf, in_buf = [], []

        try:
            while True:
                async for response in self.session.receive():
                    turn_completed = False

                    update = getattr(response, "session_resumption_update", None)
                    # Checkpoints are internal session bookkeeping. Keep the
                    # resumable handle current without leaking routine protocol
                    # traffic into the user's conversation log.
                    self._runtime.session.resumption.observe_resumption_update(
                        update
                    )
                    go_away = getattr(response, "go_away", None)
                    if go_away:
                        remaining = getattr(go_away, "time_left", None)
                        detail = f" ({remaining} remaining)" if remaining else ""
                        self.ui.write_log(
                            f"NET: Server requested a graceful reconnect{detail}."
                        )

                    if response.data:
                        # Stale frames captured just before playback can otherwise
                        # reach Gemini as a false interruption of its next phrase.
                        self.set_speaking(True)
                        while self.out_queue and not self.out_queue.empty():
                            try:
                                self.out_queue.get_nowait()
                            except asyncio.QueueEmpty:
                                break
                        if self._runtime.lifecycle.shutdown_requested:
                            self._runtime.lifecycle.observe_farewell_audio()
                        if self._runtime.audio.interrupted:
                            pass  # discard: interrupted
                        else:
                            if self._turn_done_event and self._turn_done_event.is_set():
                                self._turn_done_event.clear()
                            # Split into ~50 ms chunks so interrupt() stops audio within 50 ms
                            # (24000 Hz × 2 bytes/sample × 0.05 s = 2400 bytes per slice)
                            _audio_data = response.data
                            _SLICE = 2400
                            for _i in range(0, len(_audio_data), _SLICE):
                                self.audio_in_queue.put_nowait(_audio_data[_i : _i + _SLICE])

                    if response.server_content:
                        sc = response.server_content

                        if sc.interrupted:
                            # A server VAD interruption means the user spoke over
                            # JARVIS. Stop playback, but keep the new user turn alive;
                            # AudioService.interrupted is reserved for explicit ESC cancellation.
                            await self._flush_playback("VAD")

                        if sc.output_transcription and sc.output_transcription.text:
                            txt = _clean_transcript(sc.output_transcription.text)
                            if txt and txt != (out_buf[-1] if out_buf else ""):
                                out_buf.append(txt)

                        if sc.input_transcription and sc.input_transcription.text:
                            txt = _clean_transcript(sc.input_transcription.text)
                            if txt:
                                in_buf.append(txt)
                                self._last_user_speech = time.monotonic()
                                self._handle_confirmation_text(txt)

                        if sc.turn_complete:
                            turn_completed = True
                            if self._turn_done_event:
                                self._turn_done_event.set()

                            # If this turn_complete ends an interrupted response, clear the
                            # flag and skip all further processing for that turn.
                            if self._runtime.audio.interrupted:
                                self._release_interrupt(
                                    self._runtime.audio.interrupt_generation
                                )
                                in_buf  = []
                                out_buf = []
                                self._reset_input_source()
                                continue

                            full_in = " ".join(in_buf).strip()
                            if full_in:
                                self._handle_confirmation_text(full_in)
                                self.ui.write_log(f"You: {full_in}")
                                if self._dashboard:
                                    asyncio.create_task(self._dashboard.broadcast({
                                        "type": "log", "speaker": "user",
                                        "text": full_in,
                                        "ts": local_now().isoformat(),
                                    }))
                            in_buf = []

                            full_out = " ".join(out_buf).strip()
                            if full_out:
                                self.ui.write_log(f"Jarvis: {full_out}")
                                if self._dashboard:
                                    asyncio.create_task(self._dashboard.broadcast({
                                        "type": "log", "speaker": "jarvis",
                                        "text": full_out,
                                        "ts": local_now().isoformat(),
                                    }))
                            out_buf = []

                    if response.tool_call:
                        fn_responses = []
                        for fc in response.tool_call.function_calls:
                            print(f"[JARVIS] 📞 {fc.name}")
                            fr = await self._execute_tool(fc)
                            fn_responses.append(fr)
                        await self.session.send_tool_response(
                            function_responses=fn_responses
                        )
                    if turn_completed:
                        self._reset_input_source()
        except Exception as e:
            print(f"[JARVIS] ❌ Recv: {e}")
            traceback.print_exc()
            raise

    async def _play_audio(self):
        print("[JARVIS] 🔊 Play started")

        stream = sd.RawOutputStream(
            samplerate=RECEIVE_SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            blocksize=CHUNK_SIZE,
        )
        stream.start()
        self._output_stream = stream

        try:
            while True:
                try:
                    chunk = await asyncio.wait_for(
                        self.audio_in_queue.get(),
                        timeout=0.1
                    )
                except asyncio.TimeoutError:
                    if (
                        self._turn_done_event
                        and self._turn_done_event.is_set()
                        and self.audio_in_queue.empty()
                    ):
                        self.set_speaking(False)
                        self._turn_done_event.clear()
                        if self._briefing_phase1_done:
                            self._briefing_phase1_played = True
                            self._briefing_phase1_done.set()
                        if self._runtime.lifecycle.shutdown_requested:
                            self._runtime.lifecycle.observe_playback_drained()
                            if self._runtime.lifecycle.ready_to_finish():
                                self._finish_shutdown_after_audio()
                    continue
                self.set_speaking(True)
                try:
                    generation = self._playback_generation

                    def _write_current_chunk() -> None:
                        with self._output_stream_lock:
                            if (
                                generation != self._playback_generation
                                or self._runtime.audio.interrupted
                            ):
                                return
                            stream.write(chunk)

                    await asyncio.to_thread(_write_current_chunk)
                except (RuntimeError, asyncio.CancelledError):
                    break   # executor shutting down — exit cleanly
        except Exception as e:
            print(f"[JARVIS] ❌ Play: {e}")
            raise
        finally:
            self.set_speaking(False)
            with self._output_stream_lock:
                self._output_stream = None
                stream.stop(ignore_errors=True)
                stream.close(ignore_errors=True)

    def _finish_shutdown_after_audio(self) -> None:
        """Exit once, only after Gemini's farewell has drained from playback."""
        if not self._runtime.lifecycle.begin_finish():
            return
        update_runtime_state("jarvis", "off", reason="voice_shutdown")
        self.ui.write_log("SYS: Farewell complete. Shutting down JARVIS.")

        def _exit_after_device_flush():
            import os
            time.sleep(0.25)
            os._exit(0)

        threading.Thread(target=_exit_after_device_flush, daemon=True).start()

    async def _shutdown_fallback_timeout(self) -> None:
        """Guarantee an explicit shutdown even if Gemini produces no farewell audio."""
        await asyncio.sleep(12)
        if self._runtime.lifecycle.ready_to_finish():
            self.ui.write_log("SYS: Farewell audio timed out; completing shutdown.")
            self._finish_shutdown_after_audio()

    # ── Morning briefing ────────────────────────────────────────────────────────

    async def _send_startup_briefing(self) -> None:
        """Send the greeting once it is actually playable, retrying after disconnects."""
        try:
            # Yield once so receive/playback tasks are running before the model
            # can answer. This replaces the arbitrary 300 ms startup delay.
            await asyncio.sleep(0)
            session = self.session
            if session is None:
                return

            memory = load_memory()
            identity = memory.get("identity", {})

            def _val(key: str) -> str:
                entry = identity.get(key, {})
                if isinstance(entry, dict):
                    return str(entry.get("value", "")).strip()
                return str(entry).strip()

            lang = get_response_language(memory)
            name = _val("name")
            now = local_now()
            time_str = now.strftime("%H:%M")
            date_str = now.strftime("%A, %B %d, %Y")
            lang_clause = f" Respond in {lang}." if lang else ""
            name_clause = f" Address the user as {name}." if name else ""
            prompt = (
                "Greet the user, state that the authoritative local date and time are "
                f"{date_str} at {time_str} in Buenos Aires, and say you are "
                "fetching today's news headlines now. One short sentence only. "
                f"Do not call any tools.{lang_clause}{name_clause}"
            )

            phase1_done = asyncio.Event()
            self._briefing_phase1_played = False
            self._briefing_phase1_done = phase1_done
            await session.send_realtime_input(text=prompt)
            self.ui.write_log("SYS: Briefing phase 1 (greeting) sent.")

            try:
                await asyncio.wait_for(phase1_done.wait(), timeout=30.0)
                if not self._briefing_phase1_played:
                    self.ui.write_log(
                        "SYS: Briefing greeting interrupted; retrying after reconnect."
                    )
                    return
                # Mark completion only after playback. If the session drops
                # earlier, the next connection schedules the greeting again.
                self._briefing_sent = True
                await self._briefing_news_phase(lang)
            except asyncio.TimeoutError:
                self.ui.write_log(
                    "SYS: Briefing phase 1 playback timeout; phase 2 skipped."
                )
            except Exception as error:
                print(f"[Briefing] Phase 2 error: {error}")
                self.ui.write_log(
                    f"SYS: Briefing news phase failed: {error}"
                )
            finally:
                if self._briefing_phase1_done is phase1_done:
                    self._briefing_phase1_done = None
        finally:
            self._briefing_inflight = False

    async def _briefing_news_phase(self, lang: str) -> None:
        """
        Sends the news phase after the initial greeting.
        """
        lang_str = f" Respond in {lang}." if lang else ""

        if not self.session:
            return

        today = local_now().strftime("%Y-%m-%d")
        p2 = (
            "[BRIEFING] Call web_search with mode='news' and "
            f"query='top world news {today}' to find news published or materially "
            "updated within the last 24 hours. Reject older or undated stories, "
            "even if they rank highly, and use article dates to verify recency. "
            "After the search, say one specific news event from the results "
            "in one sentence, then say the full list is displayed on screen."
            f"{lang_str}"
        )

        await self.session.send_realtime_input(
            text=p2
        )

        self.ui.write_log(
            "SYS: Briefing phase 2 (news) sent."
        )

    # ── System monitor ──────────────────────────────────────────────────────────

    async def _run_system_monitor(self) -> None:
        """Background task: voice alerts when metrics exceed thresholds."""
        while True:
            await asyncio.sleep(10)
            alert = await asyncio.to_thread(self._sys_monitor.check)
            if alert and self.session:
                try:
                    await self.session.send_realtime_input(text=alert)
                except Exception as e:
                    print(f"[Monitor] ⚠️ Could not send alert: {e}")

    # ── Proactive mode ──────────────────────────────────────────────────────────

    async def _run_proactive_mode(self) -> None:
        """
        Background task: periodically checks if the user has been silent long enough,
        then hands time + memory context to Gemini so it can decide what (if anything)
        to say proactively. No hardcoded rules — Gemini makes the call.
        """
        while True:
            await asyncio.sleep(60)   # evaluate once per minute

            if not self.session:
                continue

            with self._speaking_lock:
                speaking = self._is_speaking
            if speaking:
                continue

            if not self._proactive.should_trigger(self._last_user_speech):
                continue

            self._proactive.mark_triggered()

            try:
                memory = await asyncio.to_thread(load_memory)
                prompt = self._proactive.build_prompt(memory)
                await self.session.send_realtime_input(text=prompt)
                self.ui.write_log("SYS: Proactive check-in.")
            except Exception as e:
                print(f"[Proactive] ⚠️ {e}")

    # ── Phone audio relay ────────────────────────────────────────────────────────

    async def _relay_phone_audio(self) -> None:
        """Forward phone mic PCM chunks from dashboard queue into the Gemini Live session."""
        q = self._dashboard._phone_audio_queue
        while True:
            try:
                chunk = await asyncio.wait_for(q.get(), timeout=1.0)
            except asyncio.TimeoutError:
                # No audio for 1 s → phone mic inactive, give PC mic back
                self._phone_active = False
                continue
            self._phone_active = True   # phone is streaming — silence PC mic
            with self._speaking_lock:
                speaking = self._is_speaking
            if not speaking and self.ui.microphone_enabled:
                try:
                    self.out_queue.put_nowait((InputSource.DASHBOARD_AUDIO, chunk))
                except asyncio.QueueFull:
                    pass

    def _on_phone_connected(self) -> None:
        self.ui.write_log("SYS: Phone connected via Remote Dashboard.")
        self.ui.notify_phone_connected()

    def _on_runtime_event(self, event: RuntimeEvent) -> None:
        if isinstance(event, DashboardConnected):
            self._on_phone_connected()

    # ── dashboard command relay ─────────────────────────────────────────────

    async def _process_dashboard_commands(self) -> None:
        while True:
            try:
                text = await asyncio.wait_for(
                    self._dashboard._command_queue.get(), timeout=0.5
                )
                if not text:
                    continue
                await self._forward_dashboard_command(text)
            except asyncio.TimeoutError:
                pass
            except Exception as e:
                print(f"[Dashboard] Command error: {e}")
                await asyncio.sleep(0.5)

    async def _forward_dashboard_command(self, text: str) -> None:
        if self._handle_confirmation_text(text):
            self.ui.write_log(f"[Web]: {text}")
            return
        # Wait up to 8s for session to become ready after a wake.
        for _ in range(80):
            if self.session:
                break
            await asyncio.sleep(0.1)
        if self.session:
            await self._send_text_input(text, InputSource.DASHBOARD_TEXT)
            self.ui.write_log(f"[Web]: {text}")
        else:
            print(f"[Dashboard] Dropped command (no session): {text}")

    # ── main loop ───────────────────────────────────────────────────────────

    async def run(self):
        self._loop = asyncio.get_event_loop()

        # Prepare the optional dashboard without opening a socket.  The server
        # starts only after the local Remote Control button is pressed.
        try:
            from dashboard.server import DashboardServer
            self._dashboard_factory = DashboardServer
        except Exception as e:
            print(f"[Dashboard] Disabled: {e}")
            self._dashboard = None
            self._dashboard_factory = None

        while True:
            try:
                print("[JARVIS] Connecting...")
                self.ui.set_state("THINKING")
                config = self._build_config()

                # Fresh client on every reconnect — avoids stale HTTP session state
                client = genai.Client(
                    api_key=_get_api_key(),
                    http_options={"api_version": "v1beta"}
                )

                async with (
                    client.aio.live.connect(model=LIVE_MODEL, config=config) as session,
                    asyncio.TaskGroup() as tg,
                ):
                    self.session          = session
                    connection_outcome = self._runtime.on_transport_connected(
                        session
                    )
                    self.audio_in_queue   = asyncio.Queue()
                    self.out_queue        = asyncio.Queue(maxsize=25)
                    self._turn_done_event = asyncio.Event()

                    # Reset transient state that must not carry over from a previous session
                    self._reset_input_source()

                    print("[JARVIS] Connected.")
                    self.ui.set_state("LISTENING")
                    if connection_outcome == "online":
                        self.ui.write_log("SYS: JARVIS online.")
                    else:
                        self.ui.write_log("NET: Live session restored.")

                    if self._dashboard:
                        await self._dashboard.broadcast({"type": "status", "state": "active"})

                    tg.create_task(self._send_realtime())
                    tg.create_task(self._listen_audio())
                    tg.create_task(self._receive_audio())
                    tg.create_task(self._play_audio())
                    tg.create_task(self._run_system_monitor())
                    tg.create_task(self._run_proactive_mode())
                    if self._dashboard:
                        tg.create_task(self._relay_phone_audio())

                    # Morning briefing — fires once per process launch
                    if not self._briefing_sent and not self._briefing_inflight:
                        self._briefing_inflight = True
                        tg.create_task(self._send_startup_briefing())

            except KeyboardInterrupt:
                raise
            except SystemExit:
                raise
            except BaseException as e:
                # Catches both Exception and BaseExceptionGroup (Python 3.11+
                # TaskGroup raises BaseExceptionGroup when tasks are cancelled
                # externally, which `except Exception` would miss, letting the
                # exception escape the while-loop and causing asyncio.run() to
                # start shutdown — resulting in "executor after shutdown" errors).
                err_str = str(e)
                print(f"[JARVIS] Error ({type(e).__name__}): {e}")
                traceback.print_exc()

                # Invalid API key — stop hammering the API, prompt re-configuration
                if "API key not valid" in err_str or "1007" in err_str:
                    self.ui.write_log("ERR: API key invalid — please re-enter your key.")
                    self.ui.set_state("SLEEPING")
                    self.ui.prompt_reconfig()
                    while not self.ui._win._ready:
                        await asyncio.sleep(1)
                    self.search_provider = GoogleGroundedSearchProvider.from_api_key(
                        _get_api_key(),
                        log=self.ui_tools.write_log,
                    )
                    print("[JARVIS] New API key saved — reconnecting...")
                    _conn_backoff = 3
                    continue

                # Network / timeout errors — log clearly and back off
                is_net_err = any(k in err_str for k in (
                    "TimeoutError", "timed out", "getaddrinfo", "CancelledError",
                    "ConnectionRefusedError", "OSError", "Cannot connect",
                ))
                if is_net_err:
                    _conn_backoff = min(getattr(self, "_conn_backoff", 3) * 2, 60)
                    self._conn_backoff = _conn_backoff
                    self.ui.write_log(
                        f"NET: Bağlantı kurulamadı — {_conn_backoff}s sonra tekrar deneniyor. "
                        "(VPN gerekiyor olabilir)"
                    )
                else:
                    self._conn_backoff = 3
            finally:
                self._runtime.on_transport_disconnected(self.session)
                self.session = None

            await self._flush_playback("live session reconnect")
            self.set_speaking(False)
            self.ui.set_state("SLEEPING")

            if self._dashboard:
                await self._dashboard.broadcast({"type": "status", "state": "sleeping"})

            delay = getattr(self, "_conn_backoff", 3)
            print(f"[JARVIS] Reconnecting in {delay}s...")
            await asyncio.sleep(delay)

def main():
    runtime_log = StructuredRuntimeLog()
    runtime_events = EventBus()
    runtime_log_subscription = runtime_events.subscribe(
        runtime_log.record_runtime_event
    )
    wake_supervised = os.environ.get("JARVIS_WAKE_SUPERVISED") == "1"
    if not wake_supervised:
        # Direct execution of main.py must obey the same microphone lifecycle
        # as the official launcher: pause wake listening while JARVIS is open.
        try:
            from jarvis_launcher import stop_wake_detector
            stop_wake_detector()
        except Exception as exc:
            print(f"[JARVIS] Could not pause wake detector: {exc}")

    start_in_pet_mode = "--pet" in sys.argv[1:]
    runtime_log.record(
        "application_started",
        component="main",
        metadata={
            "surface": "pet" if start_in_pet_mode else "main",
            "wake_supervised": wake_supervised,
        },
    )
    update_runtime_state(
        "jarvis", "on", surface="pet" if start_in_pet_mode else "main"
    )
    if start_in_pet_mode:
        ui = JarvisUI("face.png", start_in_pet_mode=True)
    else:
        ui = JarvisUI("face.png")

    def runner():
        ui.wait_for_api_key()
        jarvis = JarvisLive(ui, runtime_events=runtime_events)
        try:
            asyncio.run(jarvis.run())
        except KeyboardInterrupt:
            print("\n🔴 Shutting down...")

        except SystemExit:
            return
        except BaseException as exc:
            _CRASH_REPORTER.record_exception("JARVIS core runner", exc)
            runtime_log.record(
                "runner_failed",
                level=logging.ERROR,
                component="main",
                message=f"{type(exc).__name__}: {exc}",
                metadata={"error_code": type(exc).__name__},
            )
            print(f"[JARVIS] Core stopped unexpectedly: {exc}")
            try:
                ui.write_log(
                    "ERR: JARVIS core stopped unexpectedly. "
                    "A sanitized crash report was saved."
                )
                ui.set_state("ERROR")
            except Exception:
                pass

    def start_runner_after_first_frame() -> None:
        threading.Thread(
            target=runner,
            name="jarvis-core",
            daemon=True,
        ).start()

    ui.start_after_visible(start_runner_after_first_frame)
    try:
        ui.root.mainloop()
    finally:
        for worker_name, shutdown_name in (
            ("browser", "shutdown_browser_workers"),
            ("vision", "shutdown_vision_worker"),
        ):
            shutdown = globals().get(shutdown_name)
            if not callable(shutdown):
                continue
            try:
                shutdown()
            except Exception as exc:
                runtime_log.record(
                    "worker_cleanup_failed",
                    level=logging.ERROR,
                    component="workers",
                    metadata={
                        "worker": worker_name,
                        "error_code": type(exc).__name__,
                    },
                )
        update_runtime_state("jarvis", "off", reason="application_exit")
        runtime_log.record(
            "application_stopped",
            component="main",
            metadata={"reason": "application_exit"},
        )
        runtime_log_subscription.close()
        runtime_log.close()
        # Normal entry points supervise this process themselves.  If main.py
        # was executed directly, restore the always-on wake listener here too.
        if not wake_supervised:
            try:
                from jarvis_launcher import start_wake_detector
                start_wake_detector()
            except Exception as exc:
                print(f"[JARVIS] Could not restore wake detector: {exc}")

if __name__ == "__main__":
    main()
