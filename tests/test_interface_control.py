from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from main import TOOL_DECLARATIONS
from ui import JarvisUI, MainWindow
from ui_mk2.study import StudyWorkspace

ROOT = Path(__file__).resolve().parents[1]


class _CompletingSignal:
    def __init__(self, *, result=None, error=None):
        self.result = result
        self.error = error
        self.request = None

    def emit(self, request):
        self.request = request
        if self.error:
            request["error"] = self.error
        else:
            request["result"] = self.result
        request["event"].set()


class _FakeWindow:
    def __init__(self, signal):
        self._interface_sig = signal


class _FakeStudyWindow:
    def __init__(self, signal, *, visible=True, minimized=False):
        self._study_sig = signal
        self._visible = visible
        self._minimized = minimized

    def isVisible(self):
        return self._visible

    def isMinimized(self):
        return self._minimized


class _RecordingSignal:
    def __init__(self):
        self.calls = []

    def emit(self, *args):
        self.calls.append(args)


class _DispatchSurface:
    _execute_interface_request = MainWindow._execute_interface_request

    def __init__(self):
        self._main_mode_sig = _RecordingSignal()
        self.opened = []

    def show_geo_workspace(self):
        self.opened.append("geo")


def _bare_ui(signal):
    ui = JarvisUI.__new__(JarvisUI)
    ui._surface_mode = "main"
    ui._win = _FakeWindow(signal)
    return ui


def test_interface_tool_exposes_every_visible_workspace():
    declaration = next(
        item for item in TOOL_DECLARATIONS if item["name"] == "interface_control"
    )
    target_help = declaration["parameters"]["properties"]["target"]["description"]
    for target in (
        "pet", "app", "core", "chat", "files", "camera", "study", "memory",
        "geo", "context", "system", "live_map", "fullscreen", "listening",
        "content", "interrupt",
    ):
        assert target in target_help


def test_control_interface_waits_for_and_returns_verified_qt_result():
    signal = _CompletingSignal(result="Geographic workspace opened.")
    ui = _bare_ui(signal)

    result = ui.control_interface("open", "geo")

    assert result == "Geographic workspace opened."
    assert signal.request["action"] == "open"
    assert signal.request["target"] == "geo"
    assert isinstance(signal.request["event"], threading.Event)


def test_control_interface_propagates_dispatch_failure():
    ui = _bare_ui(_CompletingSignal(error="Interface command failed: camera unavailable"))

    with pytest.raises(RuntimeError, match="camera unavailable"):
        ui.control_interface("open", "camera")


def test_workspace_order_from_pet_restores_app_then_opens_requested_view():
    surface = _DispatchSurface()
    request = {
        "action": "open",
        "target": "geo",
        "surface_mode": "pet",
        "event": threading.Event(),
    }

    surface._execute_interface_request(request)

    assert len(surface._main_mode_sig.calls) == 1
    assert surface.opened == ["geo"]
    assert request["result"] == "Geographic workspace opened."
    assert request["event"].is_set()


def test_interface_status_reports_camera_and_real_microphone_state():
    surface = SimpleNamespace(
        _hud_cam_stack=SimpleNamespace(currentIndex=lambda: 0),
        hud=SimpleNamespace(camera_active=True, context_active=False),
        _active_v1_panel=None,
        _right_panel=SimpleNamespace(isVisible=lambda: False),
        _system_open=False,
        _camera_mode="normal",
        _listen_mode="toggle",
        _talk_enabled=False,
        isFullScreen=lambda: True,
    )

    status = MainWindow._interface_status(surface, "main")

    assert status["workspace"] == "camera"
    assert status["microphone_enabled"] is False


def test_study_auto_opens_only_when_main_app_is_already_visible():
    visible_signal = _CompletingSignal(result="Study workspace opened with the latest result.")
    ui = JarvisUI.__new__(JarvisUI)
    ui._surface_mode = "main"
    ui._win = _FakeStudyWindow(visible_signal)
    ui.show_study_result({"title": "Result"}, automatic=True)
    assert visible_signal.request["automatic"] is True
    assert visible_signal.request["surface_mode"] == "main"

    pet_signal = _CompletingSignal(result="Study result stored without opening the application.")
    ui._surface_mode = "pet"
    ui._win = _FakeStudyWindow(pet_signal, visible=False)
    ui.show_study_result({"title": "Queued"}, automatic=True)
    assert pet_signal.request["automatic"] is True
    assert pet_signal.request["surface_mode"] == "pet"


def test_study_workspace_defers_render_until_web_page_is_ready():
    rendered = []
    pending = SimpleNamespace(setText=lambda value: None)
    workspace = SimpleNamespace(
        latest_artifact=None,
        _page_ready=False,
        pending=pending,
        _render_latest=lambda: rendered.append("rendered"),
    )

    StudyWorkspace.set_artifact(workspace, {"title": "Deferred"})
    assert workspace.latest_artifact == {"title": "Deferred"}
    assert rendered == []

    workspace._page_ready = True
    StudyWorkspace.set_artifact(workspace, {"title": "Ready"})
    assert rendered == ["rendered"]


def test_internal_workspace_opening_verifies_the_stack_postcondition():
    stack = SimpleNamespace(
        setCurrentIndex=lambda _index: None,
        currentIndex=lambda: 0,
    )
    surface = SimpleNamespace(
        hud=SimpleNamespace(camera_active=False),
        _content_panel=SimpleNamespace(isVisible=lambda: False),
        _right_panel=SimpleNamespace(isVisible=lambda: False),
        _active_v1_panel=None,
        _hud_cam_stack=stack,
        _set_v1_button_state=lambda _header: None,
        _set_header_tab=lambda _header: None,
    )

    with pytest.raises(RuntimeError, match="study workspace did not become active"):
        MainWindow._show_central_workspace(surface, 4, "study")


def test_prompt_routes_jarvis_ui_orders_without_mouse_simulation():
    prompt = (ROOT / "core" / "prompt.txt").read_text(encoding="utf-8")
    assert "Use interface_control for every request" in prompt
    assert "Never use computer_control or visual_mouse for JARVIS's own controls" in prompt
    assert "Opening Camera only displays the stream" in prompt
