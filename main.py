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
import re
import threading
import time
import json
import sys
import traceback
from datetime import datetime
from core.clock import local_now, prompt_datetime
from pathlib import Path

import sounddevice as sd
from google import genai
from google.genai import types
from ui import JarvisUI
from core.security import VoiceConfirmationGate, confirmation_request, safe_tool_args
from core.permissions import (
    ExecutionContext, PermissionLevel, PermissionPolicy, PermissionStore, build_preview,
)
from core.tools import ToolExecutor
from core.tools.builtins import SPECIAL_TOOLS, build_builtin_registry
from memory.memory_manager import (
    load_memory, create_memory, list_memories, search_memories,
    update_memory_by_id, forget_memory, restore_memory, format_memory_for_prompt,
)
from memory.script_memory import format_scripts_for_prompt



def _load_action_dependencies() -> None:
    """Load optional/heavy action modules after the UI is already visible."""
    global file_processor, flight_finder, open_app, weather_action
    global send_message, reminder, computer_settings, analyze_visual, screen_process_action
    global youtube_video, desktop_control, browser_control, file_controller
    global code_helper, dev_agent, web_search_action, computer_control
    global game_updater, SystemMonitor, get_system_status, ProactiveEngine
    global math_engine, account_connector, obsidian_connector

    from actions.file_processor import file_processor
    from actions.flight_finder import flight_finder
    from actions.open_app import open_app
    from actions.weather_report import weather_action
    from actions.send_message import send_message
    from actions.reminder import reminder
    from actions.computer_settings import computer_settings
    from actions.screen_processor import analyze_visual, screen_process as screen_process_action
    from actions.youtube_video import youtube_video
    from actions.desktop import desktop_control
    from actions.browser_control import browser_control
    from actions.file_controller import file_controller
    from actions.code_helper import code_helper
    from actions.dev_agent import dev_agent
    from actions.web_search import web_search as web_search_action
    from actions.computer_control import computer_control
    from actions.game_updater import game_updater
    from actions.system_monitor import SystemMonitor, get_system_status
    from actions.proactive import ProactiveEngine
    from actions.math_engine import math_engine
    from actions.account_connector import account_connector
    from actions.obsidian_connector import obsidian_connector


def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


BASE_DIR        = get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"
PROMPT_PATH     = BASE_DIR / "core" / "prompt.txt"
LIVE_MODEL = "models/gemini-3.1-flash-live-preview"
CHANNELS            = 1
SEND_SAMPLE_RATE    = 16000
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE          = 640  # 40 ms at 16 kHz, within Gemini Live guidance

def _get_api_key() -> str:
    with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["gemini_api_key"]


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
        "description": "Builds complete multi-file projects from scratch: plans, writes files, installs deps, opens VSCode, runs and fixes errors.",
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
            "If a conflict is returned, ask whether to replace the old memory. "
            "Values must be in English regardless of the conversation language."
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
                "expires_at": {"type": "STRING", "description": "Optional ISO-8601 expiry with timezone for temporary memories"},
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
        "name": "account_connector",
        "description": (
            "Connect, disconnect, inspect, search, read, or download from an authorized "
            "personal account. Supports Gmail, Google Calendar and Google Drive. Read/search/download "
            "are direct after OAuth; never request or store the user's password."
        ),
        "parameters": {"type": "OBJECT", "properties": {
            "provider": {"type": "STRING", "description": "gmail|outlook|google_calendar|google_drive"},
            "action": {"type": "STRING", "description": "connect|disconnect|status|search|read|download"},
            "query": {"type": "STRING", "description": "Provider-specific search text or Gmail query"},
            "limit": {"type": "INTEGER"}, "item_id": {"type": "STRING"},
            "attachment": {"type": "STRING"}, "destination": {"type": "STRING"}
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

    def __init__(self, ui: JarvisUI):
        _load_action_dependencies()
        self.ui             = ui
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
        self._vision_last_time     = 0.0     # monotonic time of last screen_process call (cooldown guard)
        self._vision_busy          = False   # True while a vision capture/inject cycle is in flight
        self._interrupted          = False   # True while draining audio after user interrupt
        self.ui.on_text_command   = self._on_text_command
        self.ui.on_remote_clicked = self._make_remote_key
        self.ui.on_interrupt      = self.interrupt
        self._turn_done_event: asyncio.Event | None = None
        self._briefing_phase1_done: asyncio.Event | None = None
        self._dashboard     = None
        self._dashboard_factory = None
        self._dashboard_tasks_started = False
        self._briefing_sent    = False          # morning briefing fires once per process
        self._sys_monitor      = SystemMonitor()  # persistent cooldown state
        self._proactive        = ProactiveEngine()
        self._last_user_speech = time.monotonic()  # updated on every user utterance
        self._confirmation_gate = VoiceConfirmationGate(ttl_seconds=60)
        self._pending_confirmation_fc = None
        self._confirmation_execution_scheduled = False
        self._shutdown_after_turn = False
        self._shutdown_started = False
        self._shutdown_farewell_audio_seen = False
        handlers = {
            "open_app": lambda args: open_app(parameters=args, response=None, player=self.ui)
                or f"Opened {args.get('app_name')}.",
            "weather_report": lambda args: weather_action(parameters=args, player=self.ui),
            "browser_control": lambda args: browser_control(parameters=args, player=self.ui),
            "file_controller": lambda args: file_controller(parameters=args, player=self.ui),
            "send_message": lambda args: send_message(
                parameters=args, response=None, player=self.ui, session_memory=None
            ) or f"Message sent to {args.get('receiver')}.",
            "reminder": lambda args: reminder(parameters=args, response=None, player=self.ui),
            "youtube_video": lambda args: youtube_video(parameters=args, response=None, player=self.ui),
            "computer_settings": lambda args: computer_settings(
                parameters=args, response=None, player=self.ui
            ),
            "desktop_control": lambda args: desktop_control(parameters=args, player=self.ui),
            "code_helper": lambda args: code_helper(
                parameters=args, player=self.ui, speak=self.speak
            ),
            "dev_agent": lambda args: dev_agent(parameters=args, player=self.ui, speak=self.speak),
            "web_search": lambda args: web_search_action(parameters=args, player=self.ui),
            "file_processor": self._run_file_processor,
            "computer_control": lambda args: computer_control(parameters=args, player=self.ui),
            "game_updater": lambda args: game_updater(
                parameters=args, player=self.ui, speak=self.speak
            ),
            "flight_finder": lambda args: flight_finder(parameters=args, player=self.ui),
            "system_status": lambda args: str(get_system_status()),
            "memory_list": lambda args: list_memories(args.get("category"), args.get("status", "active")),
            "memory_search": lambda args: search_memories(args.get("query", ""), args.get("category")),
            "memory_update": lambda args: update_memory_by_id(
                args["memory_id"], **{k: args[k] for k in ("value", "expires_at") if k in args}
            ),
            "memory_forget": lambda args: forget_memory(args["memory_id"]),
            "memory_restore": lambda args: restore_memory(args["memory_id"]),
            "math_engine": lambda args: math_engine(parameters=args, player=self.ui),
            "account_connector": lambda args: account_connector(parameters=args, player=self.ui),
            "obsidian_connector": lambda args: obsidian_connector(parameters=args, player=self.ui),
        }
        self.tool_registry = build_builtin_registry(TOOL_DECLARATIONS, handlers)
        self.permission_store = PermissionStore()
        self.permission_policy = PermissionPolicy(self.permission_store.load())
        self.tool_executor = ToolExecutor(self.tool_registry)

    def _run_file_processor(self, args: dict):
        args = dict(args)
        if not args.get("file_path") and self.ui.current_file:
            args["file_path"] = self.ui.current_file
        return file_processor(parameters=args, player=self.ui, speak=self.speak)

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
            self._dashboard = self._dashboard_factory()
            self._dashboard.set_connect_callback(self._on_phone_connected)
        self._dashboard_tasks_started = True
        asyncio.create_task(self._dashboard.serve())
        asyncio.create_task(self._process_dashboard_commands())
        await asyncio.sleep(0)

    def _on_text_command(self, text: str):
        if not self._loop or not self.session:
            return
        if self._handle_confirmation_text(text):
            return
        asyncio.run_coroutine_threadsafe(
            self.session.send_realtime_input(text=text),
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
            self._pending_confirmation_fc = None
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
        self._pending_confirmation_fc = None
        try:
            if fc is None:
                return
            self._confirmation_gate.clear()
            response = await self._execute_tool(fc, preapproved=True)
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
        self._interrupted = True
        self._interrupted_at = time.monotonic()
        self.set_speaking(False)
        self.ui.write_log("SYS: Interrupted — listening...")
        if self._loop:
            self._loop.call_soon_threadsafe(
                lambda: asyncio.create_task(self._interrupt_model_turn())
            )

    async def _interrupt_model_turn(self) -> None:
        """Send explicit user activity so Gemini stops generating, then stay silent."""
        await self._flush_playback("ESC")
        if not self.session:
            return
        try:
            await self.session.send_realtime_input(
                text="[USER_INTERRUPT] Stop the current response now. Do not reply to this marker."
            )
        except Exception as exc:
            # Local playback is already stopped; retain a useful diagnostic if the
            # active Live API version cannot accept manual activity signals.
            self.ui.write_log(f"AUDIO: Model cancellation signal failed: {exc}")

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
                    start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_LOW,
                    end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_LOW,
                    prefix_padding_ms=80,
                    silence_duration_ms=350,
                ),
            ),
            session_resumption=types.SessionResumptionConfig(),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name="Charon"
                    )
                )
            ),
        )

    async def _execute_tool(self, fc, preapproved: bool = False) -> types.FunctionResponse:
        name = fc.name
        args = dict(fc.args or {})

        if name in {"file_processor", "code_helper", "dev_agent", "desktop_control", "computer_control"}:
            from actions.file_controller import _is_protected_path
            for field in ("path", "file_path", "output_path", "destination"):
                raw_path = args.get(field)
                if not raw_path or str(raw_path).lower() in {
                    "desktop", "documents", "downloads", "pictures", "music", "videos", "home"
                }:
                    continue
                if _is_protected_path(Path(str(raw_path)).expanduser()):
                    return types.FunctionResponse(
                        id=fc.id,
                        name=name,
                        response={
                            "result": "Access denied: protected system, credential, or private path.",
                            "error": "protected_path",
                        },
                    )

        print(f"[JARVIS] 🔧 {name}  {safe_tool_args(args)}")
        self.ui.set_state("THINKING")

        if name == "shutdown_jarvis" and self._pending_confirmation_fc is not None:
            self._pending_confirmation_fc = None
            self._confirmation_gate.clear()
            self._confirmation_execution_scheduled = False
            self.ui.write_log("SECURITY: Pending confirmation cancelled by shutdown.")

        if self._pending_confirmation_fc is not None and not preapproved:
            return types.FunctionResponse(
                id=fc.id, name=name,
                response={"result": (
                    "[VOICE_CONFIRMATION_ALREADY_PENDING] Wait for the user's yes or no. "
                    "Do not call this or another tool again."
                )},
            )

        if name == "save_memory":
            category = args.get("category", "notes")
            key      = args.get("key", "")
            value    = args.get("value", "")
            saved = {"result": "invalid", "error": "missing key/value"}
            if key and value:
                saved = create_memory(
                    category, key, value, expires_at=args.get("expires_at"), replace=False
                )
                print(f"[Memory] save_memory: {category}/{key} = [redacted] ({saved['result']})")
            if self.ui.microphone_enabled:
                self.ui.set_state("LISTENING")
            return types.FunctionResponse(
                id=fc.id, name=name,
                response={"result": saved, "silent": saved.get("result") != "conflict"}
            )

        loop   = asyncio.get_event_loop()
        result = "Done."

        try:
            definition = self.tool_registry.validate_for_execution(name)
            self.tool_registry.validate_arguments(definition, args)
        except (KeyError, PermissionError, RuntimeError, TypeError, ValueError) as exc:
            return types.FunctionResponse(
                id=fc.id, name=name,
                response={"result": str(exc), "error": "unavailable"},
            )

        decision = self.permission_policy.evaluate(
            definition,
            args,
            ExecutionContext(source="local", simulate=bool(args.get("simulate", False))),
        )
        print(
            f"[SECURITY] {name}/{decision.operation}: {decision.policy} "
            f"simulated={decision.simulated}"
        )
        if decision.simulated:
            preview = build_preview(name, args, decision)
            if self.ui.microphone_enabled:
                self.ui.set_state("LISTENING")
            return types.FunctionResponse(id=fc.id, name=name, response={"result": preview})
        if not decision.allowed and not decision.requires_confirmation:
            if self.ui.microphone_enabled:
                self.ui.set_state("LISTENING")
            return types.FunctionResponse(
                id=fc.id, name=name,
                response={"result": decision.reason, "error": "blocked"},
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
                self.ui.write_log(f"SECURITY DETAIL: {detail.replace(chr(10), ' | ')}")
                question = "Confirm action? Yes or no."
                self.ui.write_log(f"SECURITY: Awaiting spoken approval for {name}.")
                if self.ui.microphone_enabled:
                    self.ui.set_state("LISTENING")
                return types.FunctionResponse(
                    id=fc.id, name=name,
                    response={
                        "result": (
                            "[VOICE_CONFIRMATION_REQUIRED] Ask the user aloud exactly: "
                            f"'{question}' Then wait. The application will execute the "
                            "action automatically after an explicit approval; do not call "
                            "this or any other tool while waiting."
                        )
                    }
                )
            if name == "computer_settings":
                args["confirmed"] = "yes"
        elif decision.requires_confirmation and preapproved:
            self.ui.write_log(f"SECURITY: Executing preapproved action {name} once.")
            if name == "computer_settings":
                args["confirmed"] = "yes"

        try:
            if name not in SPECIAL_TOOLS:
                execution = await self.tool_executor.execute(name, args)
                result = execution.message
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
                r = await loop.run_in_executor(None, lambda: weather_action(parameters=args, player=self.ui))
                result = r or "Weather delivered."

            elif name == "browser_control":
                r = await loop.run_in_executor(None, lambda: browser_control(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "file_controller":
                r = await loop.run_in_executor(None, lambda: file_controller(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "send_message":
                r = await loop.run_in_executor(None, lambda: send_message(parameters=args, response=None, player=self.ui, session_memory=None))
                result = r or f"Message sent to {args.get('receiver')}."

            elif name == "reminder":
                r = await loop.run_in_executor(None, lambda: reminder(parameters=args, response=None, player=self.ui))
                result = r or "Reminder set."

            elif name == "youtube_video":
                r = await loop.run_in_executor(None, lambda: youtube_video(parameters=args, response=None, player=self.ui))
                result = r or "Done."

            elif name == "screen_process":
                _now = time.monotonic()
                _cooldown = 4.0  # seconds — covers echo window after speaking ends
                if self._vision_busy or (_now - self._vision_last_time) < _cooldown:
                    _wait = max(0, _cooldown - (_now - self._vision_last_time))
                    print(f"[Vision] ⏳ Cooldown active ({_wait:.1f}s remaining) — ignoring duplicate call")
                    result = "Vision is still processing the previous request. I will not call this again."
                else:
                    self._vision_busy      = True
                    self._vision_last_time = _now
                    angle = args.get("angle", "screen").lower()
                    user_text = args.get("text", "What do you see?")
                    try:
                        if angle == "camera":
                            started = await loop.run_in_executor(
                                None,
                                lambda: screen_process_action(
                                    {"text": user_text, "angle": angle}, player=self.ui
                                ),
                            )
                            result = (
                                "Live camera analysis started and will remain active until closed."
                                if started else "Could not start live camera analysis."
                            )
                        else:
                            result = await loop.run_in_executor(
                                None, lambda: analyze_visual(user_text, angle)
                            )
                    finally:
                        self._vision_busy = False

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
                    None, lambda: computer_control(parameters=mouse_args, player=self.ui)
                )
                result = r or "Visual mouse action completed."

            elif name == "close_camera":
                self.ui.stop_camera_stream()
                result = "Camera closed."

            elif name == "permission_manager":
                result = self._manage_permission(args)

            elif name == "computer_settings":
                r = await loop.run_in_executor(None, lambda: computer_settings(parameters=args, response=None, player=self.ui))
                result = r or "Done."

            elif name == "desktop_control":
                r = await loop.run_in_executor(None, lambda: desktop_control(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "code_helper":
                r = await loop.run_in_executor(None, lambda: code_helper(parameters=args, player=self.ui, speak=self.speak))
                result = r or "Done."

            elif name == "dev_agent":
                r = await loop.run_in_executor(None, lambda: dev_agent(parameters=args, player=self.ui, speak=self.speak))
                result = r or "Done."

            elif name == "web_search":
                r = await loop.run_in_executor(None, lambda: web_search_action(parameters=args, player=self.ui))
                result = r or "Done."
                # Mirror results to the on-screen content panel
                _mode = args.get("mode", "search")
                if r and not r.startswith("No results") and not r.startswith("Search failed"):
                    _query = args.get("query") or ", ".join(args.get("items", []))
                    _label = f"{_mode.upper()} — {_query[:38]}" if _query else _mode.upper()
                    self.ui.show_content(_label, r)
            elif name == "file_processor":
                if not args.get("file_path") and self.ui.current_file:
                    args["file_path"] = self.ui.current_file
                r = await loop.run_in_executor(
                    None,
                    lambda: file_processor(parameters=args, player=self.ui, speak=self.speak)
                )
                result = r or "Done."

            elif name == "computer_control":
                r = await loop.run_in_executor(None, lambda: computer_control(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "game_updater":
                r = await loop.run_in_executor(None, lambda: game_updater(parameters=args, player=self.ui, speak=self.speak))
                result = r or "Done."

            elif name == "flight_finder":
                r = await loop.run_in_executor(None, lambda: flight_finder(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "system_status":
                r = await loop.run_in_executor(None, get_system_status)
                result = str(r)

            elif name == "shutdown_jarvis":
                self.ui.write_log("SYS: Shutdown requested.")
                self._shutdown_after_turn = True
                self._shutdown_farewell_audio_seen = False
                asyncio.create_task(self._shutdown_fallback_timeout())
                result = (
                    "[SHUTDOWN_SCHEDULED] Say one brief, natural goodbye in the user's "
                    "language now. Do not call another tool. JARVIS will close only after "
                    "the farewell audio finishes playing."
                )

            else:
                result = f"Unknown tool: {name}"

        except Exception as e:
            result = f"Tool '{name}' failed: {e}"
            traceback.print_exc()
            self.speak_error(name, e)

        if self.ui.microphone_enabled:
            self.ui.set_state("LISTENING")

        print(f"[JARVIS] 📤 {name} → {str(result)[:80]}")
        return types.FunctionResponse(
            id=fc.id, name=name,
            response={"result": result}
        )

    async def _send_realtime(self):
        while True:
            msg = await self.out_queue.get()
            with self._speaking_lock:
                jarvis_speaking = self._is_speaking
            if jarvis_speaking or self._interrupted:
                continue
            await self.session.send_realtime_input(audio=msg)

    async def _listen_audio(self):
        print("[JARVIS] 🎤 Mic started")
        loop = asyncio.get_event_loop()

        def _enqueue_audio(blob: types.Blob) -> None:
            try:
                self.out_queue.put_nowait(blob)
            except asyncio.QueueFull:
                # Preserve the most recent speech instead of a stale backlog.
                try:
                    self.out_queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    self.out_queue.put_nowait(blob)
                except asyncio.QueueFull:
                    pass

        def callback(indata, frames, time_info, status):
            # Do not feed the speakers (or ambient noise) back into Gemini while
            # JARVIS is talking. Listening resumes when playback ends or ESC calls
            # set_speaking(False).
            with self._speaking_lock:
                jarvis_speaking = self._is_speaking
            if (
                self.ui.microphone_enabled
                and not self._phone_active
                and not jarvis_speaking
            ):
                data = indata.tobytes()
                loop.call_soon_threadsafe(
                    _enqueue_audio,
                    types.Blob(
                        data=data,
                        mime_type=f"audio/pcm;rate={SEND_SAMPLE_RATE}",
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
                    while True:
                        await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                print(f"[JARVIS] ❌ Mic: {e}; retrying in 1 second")
                self.ui.write_log("AUDIO: Microphone lost; reconnecting...")
                await asyncio.sleep(1)

    async def _receive_audio(self):
        print("[JARVIS] 👂 Recv started")
        out_buf, in_buf = [], []

        try:
            while True:
                async for response in self.session.receive():

                    if response.data:
                        # Stale frames captured just before playback can otherwise
                        # reach Gemini as a false interruption of its next phrase.
                        self.set_speaking(True)
                        while self.out_queue and not self.out_queue.empty():
                            try:
                                self.out_queue.get_nowait()
                            except asyncio.QueueEmpty:
                                break
                        if self._shutdown_after_turn:
                            self._shutdown_farewell_audio_seen = True
                        if self._interrupted:
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
                            self._interrupted = True
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
                            if self._turn_done_event:
                                self._turn_done_event.set()

                            # If this turn_complete ends an interrupted response, clear the
                            # flag and skip all further processing for that turn.
                            if self._interrupted:
                                self._interrupted = False
                                self._interrupted_at = 0.0
                                in_buf  = []
                                out_buf = []
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
                            self._briefing_phase1_done.set()
                        if self._shutdown_after_turn and self._shutdown_farewell_audio_seen:
                            self._finish_shutdown_after_audio()
                    continue
                self.set_speaking(True)
                try:
                    generation = self._playback_generation

                    def _write_current_chunk() -> None:
                        with self._output_stream_lock:
                            if generation != self._playback_generation or self._interrupted:
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
        if self._shutdown_started:
            return
        self._shutdown_started = True
        self._shutdown_after_turn = False
        self.ui.write_log("SYS: Farewell complete. Shutting down JARVIS.")

        def _exit_after_device_flush():
            import os
            time.sleep(0.25)
            os._exit(0)

        threading.Thread(target=_exit_after_device_flush, daemon=True).start()

    async def _shutdown_fallback_timeout(self) -> None:
        """Guarantee an explicit shutdown even if Gemini produces no farewell audio."""
        await asyncio.sleep(12)
        if self._shutdown_after_turn and not self._shutdown_started:
            self.ui.write_log("SYS: Farewell audio timed out; completing shutdown.")
            self._finish_shutdown_after_audio()

    # ── Morning briefing ────────────────────────────────────────────────────────

    async def _send_startup_briefing(self) -> None:
            """
            Two-phase briefing:
          Phase 1: immediate greeting.
          Phase 2: fetch news in background.
        """
            await asyncio.sleep(0.3)

            if not self.session:
                return

            memory = load_memory()
            identity = memory.get("identity", {})

            def _val(key: str) -> str:
                entry = identity.get(key, {})

                if isinstance(entry, dict):
                    return str(entry.get("value", "")).strip()

                return str(entry).strip()

            lang = _val("language")
            name = _val("name")

            now = local_now()
            time_str = now.strftime("%H:%M")
            date_str = now.strftime("%A, %B %d, %Y")

            lang_clause = f" Respond in {lang}." if lang else ""
            name_clause = f" Address the user as {name}." if name else ""

            p1 = (
            f"Greet the user, state that the authoritative local date and time are "
            f"{date_str} at {time_str} in Buenos Aires, and say you are "
            f"fetching today's news headlines now. "
            f"One short sentence only. Do not call any tools."
            f"{lang_clause}{name_clause}"
        )

            phase1_done = asyncio.Event()
            self._briefing_phase1_done = phase1_done

            await self.session.send_realtime_input(
                text=p1
        )

            self.ui.write_log(
            "SYS: Briefing phase 1 (greeting) sent."
        )

            try:
                await asyncio.wait_for(phase1_done.wait(), timeout=30.0)
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
                    self.out_queue.put_nowait(chunk)
                except asyncio.QueueFull:
                    pass

    def _on_phone_connected(self) -> None:
        self.ui.write_log("SYS: Phone connected via Remote Dashboard.")
        self.ui.notify_phone_connected()

    # ── dashboard command relay ─────────────────────────────────────────────

    async def _process_dashboard_commands(self) -> None:
        while True:
            try:
                text = await asyncio.wait_for(
                    self._dashboard._command_queue.get(), timeout=0.5
                )
                if not text:
                    continue
                if self._handle_confirmation_text(text):
                    self.ui.write_log(f"[Web]: {text}")
                    continue
                # Wait up to 8s for session to become ready after a wake
                for _ in range(80):
                    if self.session:
                        break
                    await asyncio.sleep(0.1)
                if self.session:
                    await self.session.send_realtime_input(text=text)
                    self.ui.write_log(f"[Web]: {text}")
                else:
                    print(f"[Dashboard] Dropped command (no session): {text}")
            except asyncio.TimeoutError:
                pass
            except Exception as e:
                print(f"[Dashboard] Command error: {e}")
                await asyncio.sleep(0.5)

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
                    self.audio_in_queue   = asyncio.Queue()
                    self.out_queue        = asyncio.Queue(maxsize=25)
                    self._turn_done_event = asyncio.Event()

                    # Reset transient state that must not carry over from a previous session
                    self._vision_busy          = False
                    self._vision_last_time     = 0.0
                    self._interrupted          = False

                    print("[JARVIS] Connected.")
                    self.ui.set_state("LISTENING")
                    self.ui.write_log("SYS: JARVIS online.")

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
                    if not self._briefing_sent:
                        self._briefing_sent = True
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
                self.session = None

            self.set_speaking(False)
            self.ui.set_state("SLEEPING")

            if self._dashboard:
                await self._dashboard.broadcast({"type": "status", "state": "sleeping"})

            delay = getattr(self, "_conn_backoff", 3)
            print(f"[JARVIS] Reconnecting in {delay}s...")
            await asyncio.sleep(delay)

def main():
    ui = JarvisUI("face.png")

    def runner():
        ui.wait_for_api_key()
        jarvis = JarvisLive(ui)
        try:
            asyncio.run(jarvis.run())
        except KeyboardInterrupt:
            print("\n🔴 Shutting down...")

    threading.Thread(target=runner, daemon=True).start()
    ui.root.mainloop()

if __name__ == "__main__":
    main()
