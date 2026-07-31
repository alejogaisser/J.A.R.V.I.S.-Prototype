from __future__ import annotations

import math
import os
import platform
import ctypes
import random
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil
from utils.camera import configure_capture, profile_from_config
from ui_mk2.core import CoreRenderer
from ui_mk2.pet import PetOverlayWindow
from ui_mk2.tokens import Palette, Motion, app_stylesheet, body_font, display_font, mono_font
from ui_mk2.web_workspaces import GeoWorkspace
from ui_mk2.memory_workspace import MemoryGraphWorkspace
from ui_mk2.study import StudyWorkspace
from core.runtime_state import update_runtime_state
from config.settings import get_settings, update_settings

if platform.system() == "Windows":
    _WIN_HIDE: dict = {"creationflags": subprocess.CREATE_NO_WINDOW}
else:
    _WIN_HIDE: dict = {}

from PyQt6.QtCore import (
    QEasingCurve, QMimeData, QObject, QPointF, QRectF, QSize, Qt,
    QParallelAnimationGroup, QPropertyAnimation,
    QTimer, QUrl, pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush, QColor, QDragEnterEvent, QDropEvent, QFont, QFontDatabase,
    QIcon, QImage, QKeySequence, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
    QRadialGradient, QShortcut,
)
from PyQt6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QGraphicsOpacityEffect, QMainWindow, QMenu, QPushButton, QScrollArea, QSizePolicy, QSplitter,
    QStackedWidget, QTextEdit, QVBoxLayout, QWidget, QProgressBar,
)

def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent

BASE_DIR   = _base_dir()
CONFIG_DIR = BASE_DIR / "config"

_DEFAULT_W, _DEFAULT_H = 980, 700
_MIN_W,     _MIN_H     = 820, 580
_LEFT_W  = 228
_RIGHT_W = 388

_OS = platform.system()  # "Windows" | "Darwin" | "Linux"


class C:
    BG        = Palette.VOID
    PANEL     = Palette.SURFACE
    PANEL2    = Palette.SURFACE_RAISED
    BORDER    = Palette.LINE
    BORDER_B  = Palette.LINE_STRONG
    BORDER_A  = Palette.LINE_STRONG
    PRI       = Palette.CYAN
    PRI_DIM   = Palette.CYAN_MUTED
    PRI_GHO   = "#082A36"
    ACC       = Palette.CYAN_BRIGHT
    ACC2      = Palette.WARNING
    GREEN     = Palette.SUCCESS
    GREEN_D   = "#2CB99A"
    RED       = Palette.ERROR
    MUTED_C   = Palette.ERROR
    TEXT      = Palette.TEXT
    TEXT_DIM  = Palette.TEXT_DIM
    TEXT_MED  = Palette.TEXT_MEDIUM
    WHITE     = Palette.TEXT
    DARK      = Palette.VOID_DEEP
    BAR_BG    = Palette.SURFACE_RAISED


def qcol(h: str, a: int = 255) -> QColor:
    c = QColor(h); c.setAlpha(a); return c


# ── Windows GPU via NVML DLL (no subprocess, no console window) ──────────────
_nvml_lib: object = None   # cached ctypes DLL
_nvml_ok:  object = None   # None=untested, True=works, False=unavailable


def _nvml_gpu_windows() -> float:
    """Return NVIDIA GPU utilisation % using nvml.dll directly — zero subprocess."""
    global _nvml_lib, _nvml_ok
    if _nvml_ok is False:
        return -1.0
    try:
        import ctypes

        class _Util(ctypes.Structure):
            _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]

        if _nvml_lib is None:
            for dll_name in ("nvml", r"C:\Windows\System32\nvml.dll"):
                try:
                    lib = ctypes.WinDLL(dll_name)
                    lib.nvmlInit_v2()
                    _nvml_lib = lib
                    break
                except Exception:
                    continue

        if _nvml_lib is None:
            import pynvml  # type: ignore
            pynvml.nvmlInit()
            h = pynvml.nvmlDeviceGetHandleByIndex(0)
            _nvml_ok = True
            return float(pynvml.nvmlDeviceGetUtilizationRates(h).gpu)

        dev = ctypes.c_void_p()
        _nvml_lib.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(dev))
        util = _Util()
        _nvml_lib.nvmlDeviceGetUtilizationRates(dev, ctypes.byref(util))
        _nvml_ok = True
        return float(util.gpu)
    except Exception:
        _nvml_ok = False
        return -1.0


class _SysMetrics:
    def __init__(self):
        self.cpu  = 0.0
        self.mem  = 0.0
        self.net  = 0.0   
        self.gpu  = -1.0  
        self.tmp  = -1.0  
        self._lock = threading.Lock()
        self._last_net = psutil.net_io_counters()
        self._last_net_t = time.time()
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start hardware polling once, after the first UI frame is visible."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._running = True
            self._thread = threading.Thread(
                target=self._loop,
                daemon=True,
                name="jarvis-system-metrics",
            )
            self._thread.start()

    def _loop(self):
        while self._running:
            try:
                self._update()
            except Exception:
                pass
            time.sleep(1.5)

    def _update(self):
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory().percent

        nc  = psutil.net_io_counters()
        now = time.time()
        dt  = now - self._last_net_t
        if dt > 0:
            sent = (nc.bytes_sent - self._last_net.bytes_sent) / dt
            recv = (nc.bytes_recv - self._last_net.bytes_recv) / dt
            net  = (sent + recv) / (1024 * 1024)
        else:
            net = 0.0
        self._last_net   = nc
        self._last_net_t = now

        gpu = self._get_gpu()

        tmp = self._get_temp()

        with self._lock:
            self.cpu = cpu
            self.mem = mem
            self.net = net
            self.gpu = gpu
            self.tmp = tmp

    def _get_gpu(self) -> float:
        # pynvml — subprocess-free, works on all platforms if installed
        try:
            import pynvml  # type: ignore
            pynvml.nvmlInit()
            h = pynvml.nvmlDeviceGetHandleByIndex(0)
            return float(pynvml.nvmlDeviceGetUtilizationRates(h).gpu)
        except Exception:
            pass

        # Windows: nvml.dll via ctypes (already cached in _nvml_gpu_windows)
        if _OS == "Windows":
            return _nvml_gpu_windows()

        # Linux / macOS: libnvidia-ml shared lib via ctypes
        try:
            import ctypes
            _lib = "libnvidia-ml.so.1" if _OS == "Linux" else "libnvidia-ml.dylib"

            class _Util(ctypes.Structure):
                _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]

            nv = ctypes.CDLL(_lib)
            nv.nvmlInit_v2()
            dev = ctypes.c_void_p()
            nv.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(dev))
            u = _Util()
            nv.nvmlDeviceGetUtilizationRates(dev, ctypes.byref(u))
            return float(u.gpu)
        except Exception:
            pass

        return -1.0   # N/A — zero subprocess on all platforms

    def _get_temp(self) -> float:
        # psutil — works on Linux; occasionally Windows with driver support
        try:
            temps = psutil.sensors_temperatures()
            for name in ["coretemp", "k10temp", "cpu_thermal", "acpitz",
                         "cpu-thermal", "zenpower", "it8688"]:
                if name in temps and temps[name]:
                    return temps[name][0].current
            for entries in temps.values():
                if entries:
                    return entries[0].current
        except Exception:
            pass

        # Windows: wmi module (pure Python COM, zero subprocess)
        if _OS == "Windows":
            try:
                import wmi  # type: ignore
                w = wmi.WMI(namespace="root/wmi")
                tz = w.MSAcpi_ThermalZoneTemperature()
                if tz:
                    return (tz[0].CurrentTemperature / 10.0) - 273.15
            except Exception:
                pass

        return -1.0   # N/A — zero subprocess on all platforms

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "cpu": self.cpu,
                "mem": self.mem,
                "net": self.net,
                "gpu": self.gpu,
                "tmp": self.tmp,
            }


_metrics = _SysMetrics()


class HandGestureTracker:
    """Dependency-free hand position tracker for Python 3.14.

    It intentionally returns normalized, smoothed interaction values so a
    future landmark model can replace the detector without changing the UI.
    """

    def __init__(self):
        self._pan_x = 0.0
        self._pan_y = 0.0
        self._last_center: tuple[float, float] | None = None
        self._face_detector = None
        self._face_detector_loaded = False

    def _ensure_face_detector(self) -> None:
        """Load OpenCV only when hand mode processes its first camera frame."""
        if self._face_detector_loaded:
            return
        self._face_detector_loaded = True
        try:
            import cv2
            cascade = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            detector = cv2.CascadeClassifier(cascade)
            if not detector.empty():
                self._face_detector = detector
        except Exception:
            self._face_detector = None

    @staticmethod
    def _smooth(current: float, target: float, amount: float = 0.18) -> float:
        return current + (target - current) * amount

    def process(self, frame) -> dict:
        import cv2
        import numpy as np

        self._ensure_face_detector()

        small = cv2.resize(frame, (320, 180), interpolation=cv2.INTER_AREA)
        blurred = cv2.GaussianBlur(small, (7, 7), 0)
        ycrcb = cv2.cvtColor(blurred, cv2.COLOR_BGR2YCrCb)
        # Broad skin range; morphology and contour constraints reject most
        # background regions. Lighting calibration can be added in V2.1.
        mask = cv2.inRange(
            ycrcb,
            np.array([0, 130, 70], dtype=np.uint8),
            np.array([255, 180, 135], dtype=np.uint8),
        )
        kernel = np.ones((5, 5), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

        # A face occupies a large skin-coloured region and used to be selected
        # as the hand. Remove padded face rectangles before contour analysis.
        if self._face_detector is not None:
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            faces = self._face_detector.detectMultiScale(
                gray, scaleFactor=1.15, minNeighbors=5, minSize=(34, 34)
            )
            for fx, fy, fw_face, fh_face in faces:
                pad_x, pad_y = int(fw_face * 0.28), int(fh_face * 0.22)
                x1, y1 = max(0, fx - pad_x), max(0, fy - pad_y)
                x2 = min(mask.shape[1], fx + fw_face + pad_x)
                y2 = min(mask.shape[0], fy + fh_face + pad_y)
                mask[y1:y2, x1:x2] = 0
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            self._last_center = None
            return {"detected": False, "gesture": "SEARCHING FOR HAND"}

        contour = max(contours, key=cv2.contourArea)
        area = float(cv2.contourArea(contour))
        if area < 1500:
            self._last_center = None
            return {"detected": False, "gesture": "SEARCHING FOR HAND"}

        moments = cv2.moments(contour)
        if not moments["m00"]:
            return {"detected": False, "gesture": "SEARCHING FOR HAND"}
        cx = float(moments["m10"] / moments["m00"])
        cy = float(moments["m01"] / moments["m00"])
        nx = (cx / 320.0 - 0.5) * 2.0
        ny = (cy / 180.0 - 0.5) * 2.0
        self._pan_x = self._smooth(self._pan_x, nx, 0.14)
        self._pan_y = self._smooth(self._pan_y, ny, 0.14)

        self._last_center = (cx, cy)
        return {
            "detected": True,
            "gesture": "MOVE",
            "pan_x": round(self._pan_x, 3),
            "pan_y": round(self._pan_y, 3),
            "rotation": 0.0,
            "center_x": round(cx / 320.0, 3),
            "center_y": round(cy / 180.0, 3),
        }

class HolographicSurface(QWidget):
    """Animated glass surface shared by every Mk II workspace."""

    def __init__(self, edge: str = "full", parent=None):
        super().__init__(parent)
        self._edge = edge
        self._phase = 0.0
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self._surface_timer = QTimer(self)
        self._surface_timer.timeout.connect(self._advance_surface)
        self._surface_timer.start(66)

    def _advance_surface(self) -> None:
        if self.isVisible():
            self._phase = (self._phase + 1.0) % 240.0
            self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())

        glass = QLinearGradient(rect.topLeft(), rect.bottomRight())
        glass.setColorAt(0.0, qcol(C.PANEL2, 242))
        glass.setColorAt(0.46, qcol(C.PANEL, 235))
        glass.setColorAt(1.0, qcol(C.DARK, 248))
        p.fillRect(rect, glass)

        p.setPen(QPen(qcol(C.PRI, 12), 1))
        for y in range(8, self.height(), 18):
            p.drawLine(0, y, self.width(), y)
        for x in range(10, self.width(), 32):
            p.drawLine(x, 0, x, self.height())

        sweep_y = self._phase / 240.0 * max(1, self.height())
        sweep = QLinearGradient(0, sweep_y, self.width(), sweep_y)
        sweep.setColorAt(0.0, qcol(C.PRI, 0))
        sweep.setColorAt(0.5, qcol(C.PRI, 52))
        sweep.setColorAt(1.0, qcol(C.PRI, 0))
        p.fillRect(QRectF(0, sweep_y, self.width(), 1), sweep)

        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(qcol(C.BORDER_B, 210), 1))
        p.drawRect(rect.adjusted(0.5, 0.5, -0.5, -0.5))
        accent_x = 0.5 if self._edge != "right" else rect.right() - 1.5
        p.setPen(QPen(qcol(C.PRI, 210), 2))
        p.drawLine(QPointF(accent_x, 18), QPointF(accent_x, min(rect.bottom() - 18, 104)))

        arm = 16.0
        p.setPen(QPen(qcol(C.PRI, 110), 1))
        for x, y, dx, dy in (
            (4.0, 4.0, 1.0, 1.0), (rect.right() - 4.0, 4.0, -1.0, 1.0),
            (4.0, rect.bottom() - 4.0, 1.0, -1.0),
            (rect.right() - 4.0, rect.bottom() - 4.0, -1.0, -1.0),
        ):
            p.drawLine(QPointF(x, y), QPointF(x + dx * arm, y))
            p.drawLine(QPointF(x, y), QPointF(x, y + dy * arm))
        p.end()


class FutureModuleButton(QPushButton):
    """Visible roadmap control with intentionally no runtime action yet."""

    def __init__(self, title: str, code: str, parent=None):
        super().__init__(f"{title}\n{code}", parent)
        self.setObjectName("FutureModuleButton")
        self.setEnabled(False)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFont(mono_font(7, QFont.Weight.DemiBold))
        self.setToolTip(f"{title.title()} is planned for a later phase")
        self.setStyleSheet(f"""
            QPushButton#FutureModuleButton {{
                color: {C.TEXT_DIM};
                background: rgba(6, 20, 27, 218);
                border: 1px solid {C.BORDER};
                border-left: 2px solid {C.PRI_DIM};
                border-radius: 9px;
                padding: 8px 12px;
                text-align: left;
            }}
            QPushButton#FutureModuleButton:disabled {{
                color: {C.TEXT_DIM};
                background: rgba(6, 20, 27, 218);
                border-color: {C.BORDER};
                border-left-color: {C.PRI_DIM};
            }}
        """)


class HudCanvas(QWidget):
    def __init__(self, face_path: str, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setMinimumSize(300, 300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.muted    = False
        self.speaking = False
        self.state    = "INITIALISING"
        self.camera_active = False
        self._camera_px: QPixmap | None = None
        self._camera_mix = 0.0
        self._camera_mode = "normal"
        self._camera_zoom = 1.0
        self._camera_pan_x = 0.0
        self._camera_pan_y = 0.0
        self._gesture = {"detected": False, "gesture": "NORMAL MODE"}
        self.context_active = False
        self._context_title = ""
        self._context_text = ""
        self._context_px: QPixmap | None = None
        self._context_scale = 1.0
        self._context_pan_x = 0.0
        self._context_pan_y = 0.0
        self._context_card_rect = QRectF()
        self._contexts: list[dict] = []
        self._context_index = -1
        self._context_tab_rects: list[QRectF] = []
        self._dragging_context = False
        self._drag_last = QPointF()

        self._tick       = 0
        self._scale      = 1.0
        self._tgt_scale  = 1.0
        self._halo       = 55.0
        self._tgt_halo   = 55.0
        self._last_t     = time.time()
        self._scan       = 0.0
        self._scan2      = 180.0
        self._rings      = [0.0, 120.0, 240.0]
        self._pulses: list[float] = [0.0, 50.0, 100.0]
        self._blink      = True
        self._blink_tick = 0
        self._particles: list[list[float]] = []
        self._face_px: QPixmap | None = None
        self._load_face(face_path)
        self._core = CoreRenderer(self.state)
        self._frame_t = time.time()

        self._future_buttons = [
            FutureModuleButton("AUTOMATIONS", "MODULE 01 / PLANNED", self),
            FutureModuleButton("COMMS HUB", "MODULE 02 / PLANNED", self),
            FutureModuleButton("ROBOTICS", "MODULE 03 / PLANNED", self),
            FutureModuleButton("SMART HOME", "MODULE 04 / PLANNED", self),
        ]
        self._layout_future_modules()

        self._tmr = QTimer(self)
        self._tmr.timeout.connect(self._step)
        self._tmr.start(16)

    def resizeEvent(self, event) -> None:
        self._layout_future_modules()
        super().resizeEvent(event)

    def _layout_future_modules(self) -> None:
        """Anchor the non-functional roadmap dock without covering the core."""
        visible = self.width() >= 1040 and not self.camera_active and not self.context_active
        button_w = min(220, max(176, int(self.width() * 0.155)))
        button_h = 54
        gap = 9
        x = self.width() - button_w - 28
        y = max(86, int((self.height() - (button_h * 4 + gap * 3)) / 2))
        for index, button in enumerate(self._future_buttons):
            button.setGeometry(x, y + index * (button_h + gap), button_w, button_h)
            button.setVisible(visible)
            button.raise_()

    def _draw_operational_field(self, p: QPainter, width: int, height: int) -> None:
        """Paint the ambient telemetry and data routes around the Mk II core."""
        if self.camera_active or self.context_active:
            return

        compact = width < 1040
        margin = 28.0
        rail_w = min(220.0, max(176.0, width * 0.155))
        rail_x = margin
        top = max(84.0, height * 0.20)

        p.setPen(QPen(qcol(C.PRI, 118), 1))
        p.setFont(mono_font(7, QFont.Weight.DemiBold))
        p.drawText(
            QRectF(margin, 24, width - margin * 2, 18),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            "MARK LI  //  NEURAL OPERATING FIELD",
        )
        p.setPen(QPen(qcol(C.TEXT_DIM, 180), 1))
        p.setFont(mono_font(6))
        p.drawText(
            QRectF(margin, 44, width - margin * 2, 16),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            "REALTIME CORE  /  LOCAL CONTROL  /  SECURE CONTEXT",
        )

        if compact:
            return

        telemetry = [
            ("VOICE CHANNEL", "READY" if not self.muted else "MUTED", 0.86),
            ("MEMORY MATRIX", "SYNCHRONIZED", 0.72),
            ("VISION ARRAY", "STANDBY", 0.34),
            ("SECURITY LAYER", "LOCAL / CLEAR", 0.94),
        ]
        card_h = 54.0
        gap = 9.0
        for index, (label, value, level) in enumerate(telemetry):
            card = QRectF(rail_x, top + index * (card_h + gap), rail_w, card_h)
            p.setPen(QPen(qcol(C.BORDER_B, 175), 1))
            p.setBrush(QBrush(qcol(C.PANEL, 215)))
            p.drawRoundedRect(card, 9, 9)
            p.fillRect(QRectF(card.x(), card.y() + 11, 2, card.height() - 22), qcol(C.PRI, 190))
            p.setPen(QPen(qcol(C.TEXT_DIM), 1))
            p.setFont(mono_font(6, QFont.Weight.DemiBold))
            p.drawText(card.adjusted(13, 7, -10, -28), Qt.AlignmentFlag.AlignLeft, label)
            value_color = C.GREEN if value not in {"MUTED", "STANDBY"} else C.PRI_DIM
            p.setPen(QPen(qcol(value_color), 1))
            p.setFont(mono_font(7, QFont.Weight.DemiBold))
            p.drawText(card.adjusted(13, 24, -10, -9), Qt.AlignmentFlag.AlignLeft, value)
            graph_left = card.right() - 72
            graph_mid = card.center().y() + 4
            graph = QPainterPath()
            for sample in range(15):
                sample_x = graph_left + sample * 4.0
                phase = self._tick * 0.055 + sample * 0.82 + index * 1.4
                amplitude = 4.0 + level * 6.0
                sample_y = graph_mid + math.sin(phase) * amplitude * (0.35 + 0.65 * abs(math.sin(phase * 0.37)))
                if sample == 0:
                    graph.moveTo(sample_x, sample_y)
                else:
                    graph.lineTo(sample_x, sample_y)
            p.setPen(QPen(qcol(value_color, 145), 1))
            p.drawPath(graph)
            track = QRectF(card.x() + 13, card.bottom() - 8, card.width() - 26, 2)
            p.fillRect(track, qcol(C.BORDER, 220))
            p.fillRect(QRectF(track.x(), track.y(), track.width() * level, 2), qcol(C.PRI, 190))

            # Each subsystem has a faint physical route toward the reactor.
            route = QPainterPath()
            route.moveTo(card.right() + 7, card.center().y())
            elbow_x = card.right() + 28 + index * 8
            route.lineTo(elbow_x, card.center().y())
            route.lineTo(width * 0.31, height * (0.39 + index * 0.075))
            p.setPen(QPen(qcol(C.PRI, 30 + index * 5), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(route)
            p.setBrush(QBrush(qcol(C.PRI, 92)))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(elbow_x, card.center().y()), 2.1, 2.1)

        connector_y = top + (card_h * 4 + gap * 3) / 2
        left_end = rail_x + rail_w
        center_gap = width * 0.30
        p.setPen(QPen(qcol(C.PRI, 42), 1))
        p.drawLine(QPointF(left_end + 12, connector_y), QPointF(width / 2 - center_gap, connector_y))
        p.drawEllipse(QPointF(left_end + 7, connector_y), 2.2, 2.2)

        right_x = width - rail_w - margin
        p.setPen(QPen(qcol(C.TEXT_DIM, 170), 1))
        p.setFont(mono_font(6, QFont.Weight.DemiBold))
        p.drawText(
            QRectF(right_x, top - 26, rail_w, 18),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            "EXPANSION MODULES  /  ROADMAP",
        )

        # Low-opacity routes continue behind the disabled roadmap controls.
        p.setPen(QPen(qcol(C.PRI, 28), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        for index in range(4):
            module_y = top + index * (card_h + gap) + card_h / 2
            route = QPainterPath()
            route.moveTo(width * 0.69, height * (0.39 + index * 0.075))
            route.lineTo(right_x - 28 - index * 8, module_y)
            route.lineTo(right_x - 7, module_y)
            p.drawPath(route)

        sweep = (self._tick * 2.2) % max(1.0, height - 150.0)
        sweep_y = 76.0 + sweep
        gradient = QLinearGradient(0, sweep_y, width, sweep_y)
        gradient.setColorAt(0.0, qcol(C.PRI, 0))
        gradient.setColorAt(0.50, qcol(C.PRI, 34))
        gradient.setColorAt(1.0, qcol(C.PRI, 0))
        p.fillRect(QRectF(rail_w + 70, sweep_y, width - (rail_w + 70) * 2, 1), gradient)

    def _draw_core_stage(self, p: QPainter, bounds: QRectF) -> None:
        """Give the reactor a luminous physical stage before drawing its rings."""
        center = bounds.center()
        radius = bounds.width() * 0.62
        glow = QRadialGradient(center, radius)
        glow.setColorAt(0.0, qcol(C.PRI, 42 if self._core.state.value != "DORMANT" else 24))
        glow.setColorAt(0.42, qcol(C.PRI_DIM, 14))
        glow.setColorAt(1.0, qcol(C.BG, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(glow))
        p.drawEllipse(center, radius, radius)

        p.setBrush(Qt.BrushStyle.NoBrush)
        for scale, alpha in ((1.04, 46), (1.16, 28), (1.30, 18)):
            orbit = QRectF(
                center.x() - bounds.width() * scale / 2,
                center.y() - bounds.height() * scale / 2,
                bounds.width() * scale,
                bounds.height() * scale,
            )
            p.setPen(QPen(qcol(C.PRI, alpha), 1))
            p.drawEllipse(orbit)
        sweep_angle = int((self._tick * 1.8) % 360)
        p.setPen(QPen(qcol(C.PRI, 126), 2))
        p.drawArc(bounds.adjusted(-12, -12, 12, 12), sweep_angle * 16, 42 * 16)

    def _load_face(self, path: str):
        try:
            from PIL import Image, ImageDraw
            import io
            img = Image.open(path).convert("RGBA")
            sz  = min(img.size)
            img = img.resize((sz, sz), Image.LANCZOS)
            mk  = Image.new("L", (sz, sz), 0)
            ImageDraw.Draw(mk).ellipse((2, 2, sz - 2, sz - 2), fill=255)
            img.putalpha(mk)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            px = QPixmap(); px.loadFromData(buf.getvalue())
            self._face_px = px
        except Exception:
            self._face_px = None

    def _step(self):
        self._tick += 1
        now = time.time()
        dt = min(0.05, max(0.0, now - self._frame_t))
        self._frame_t = now
        self._core.set_audio_energy(0.82 if self.speaking else 0.18)
        self._core.advance(dt or 0.016)
        target_interval = 33 if self._core.state.value == "DORMANT" and not self.camera_active else 16
        if self._tmr.interval() != target_interval:
            self._tmr.setInterval(target_interval)
        target_mix = 1.0 if self.camera_active and self._camera_px else 0.0
        self._camera_mix += (target_mix - self._camera_mix) * 0.11
        self.update()
        return
        if now - self._last_t > (0.12 if self.speaking else 0.5):
            if self.speaking:
                self._tgt_scale = random.uniform(1.06, 1.14)
                self._tgt_halo  = random.uniform(145, 190)
            elif self.muted:
                self._tgt_scale = random.uniform(0.998, 1.002)
                self._tgt_halo  = random.uniform(15, 28)
            else:
                self._tgt_scale = random.uniform(1.001, 1.008)
                self._tgt_halo  = random.uniform(48, 68)
            self._last_t = now

        sp = 0.38 if self.speaking else 0.15
        self._scale += (self._tgt_scale - self._scale) * sp
        self._halo  += (self._tgt_halo  - self._halo)  * sp

        speeds = [1.3, -0.9, 2.0] if self.speaking else [0.55, -0.35, 0.9]
        for i, spd in enumerate(speeds):
            self._rings[i] = (self._rings[i] + spd) % 360

        self._scan  = (self._scan  + (3.0 if self.speaking else 1.3)) % 360
        self._scan2 = (self._scan2 + (-2.0 if self.speaking else -0.75)) % 360

        fw  = min(self.width(), self.height())
        lim = fw * 0.74
        spd = 4.2 if self.speaking else 2.0
        self._pulses = [r + spd for r in self._pulses if r + spd < lim]
        if len(self._pulses) < 3 and random.random() < (0.07 if self.speaking else 0.025):
            self._pulses.append(0.0)

        if self.speaking and random.random() < 0.28:
            cx, cy = self.width() / 2, self.height() / 2
            ang = random.uniform(0, 2 * math.pi)
            r_s = fw * 0.28
            self._particles.append([
                cx + math.cos(ang) * r_s, cy + math.sin(ang) * r_s,
                math.cos(ang) * random.uniform(0.9, 2.4),
                math.sin(ang) * random.uniform(0.9, 2.4) - 0.4, 1.0,
            ])
        self._particles = [
            [p[0]+p[2], p[1]+p[3], p[2]*0.97, p[3]*0.97, p[4]-0.028]
            for p in self._particles if p[4] > 0
        ]

        self._blink_tick += 1
        if self._blink_tick >= 38:
            self._blink = not self._blink
            self._blink_tick = 0
        target_mix = 1.0 if self.camera_active and self._camera_px else 0.0
        self._camera_mix += (target_mix - self._camera_mix) * 0.11
        self.update()

    def set_camera_frame(self, pixmap: QPixmap) -> None:
        self._camera_px = pixmap
        self.update()

    def set_camera_active(self, active: bool) -> None:
        self.camera_active = active
        if not active:
            self._gesture = {"detected": False, "gesture": "NORMAL MODE"}
        self._layout_future_modules()
        self.update()

    def set_camera_mode(self, mode: str) -> None:
        self._camera_mode = "hand" if mode == "hand" else "normal"
        label = "SEARCHING FOR HAND" if self._camera_mode == "hand" else "NORMAL MODE"
        self._gesture = {"detected": False, "gesture": label}
        self.update()

    def set_camera_view(self, zoom: float, pan_x: float, pan_y: float) -> None:
        self._camera_zoom = max(1.0, min(4.0, float(zoom)))
        self._camera_pan_x = max(-1.0, min(1.0, float(pan_x)))
        self._camera_pan_y = max(-1.0, min(1.0, float(pan_y)))
        self.update()

    def set_gesture(self, data: dict) -> None:
        self._gesture = dict(data)
        if self._camera_mode == "hand" and self.context_active and data.get("detected"):
            if data.get("gesture") == "MOVE":
                self._context_pan_x = max(-1.0, min(1.0, float(data.get("pan_x", 0.0))))
                self._context_pan_y = max(-1.0, min(1.0, float(data.get("pan_y", 0.0))))
        self.update()

    def set_context(self, title: str, text: str, image_path: str | None = None) -> None:
        context_title = title.strip().upper()[:52] or "CONTENT"
        context_px = None
        if image_path:
            px = QPixmap(image_path)
            if not px.isNull():
                context_px = px
        self._contexts.append({
            "title": context_title,
            "text": text.strip(),
            "pixmap": context_px,
        })
        self._contexts = self._contexts[-5:]
        self._load_context(len(self._contexts) - 1)

    def _load_context(self, index: int) -> None:
        if not self._contexts:
            self.context_active = False
            self._context_index = -1
            self.update()
            return
        self._context_index = max(0, min(index, len(self._contexts) - 1))
        context = self._contexts[self._context_index]
        self._context_title = str(context["title"])
        self._context_text = str(context["text"])
        self._context_px = context.get("pixmap")
        self._context_scale = 1.0
        self._context_pan_x = 0.0
        self._context_pan_y = 0.0
        self.context_active = True
        self._layout_future_modules()
        self.update()

    def clear_context(self) -> None:
        if 0 <= self._context_index < len(self._contexts):
            self._contexts.pop(self._context_index)
        if self._contexts:
            self._load_context(min(self._context_index, len(self._contexts) - 1))
        else:
            self._context_title = ""
            self._context_text = ""
            self._context_px = None
            self._load_context(-1)

    def show_core(self) -> None:
        """Show the clean core without deleting the user's context history."""
        self.context_active = False
        self._layout_future_modules()
        self.update()

    def show_context_workspace(self) -> bool:
        """Restore the last context card, returning whether one exists."""
        if not self._contexts:
            return False
        index = self._context_index if self._context_index >= 0 else len(self._contexts) - 1
        self._load_context(index)
        return True

    def mousePressEvent(self, event) -> None:
        if self.context_active and event.button() == Qt.MouseButton.LeftButton:
            pos = event.position()
            for index, tab_rect in enumerate(self._context_tab_rects):
                if tab_rect.contains(pos):
                    self._load_context(index)
                    return
            close_rect = QRectF(
                self._context_card_rect.right() - 48,
                self._context_card_rect.top() + 8,
                38, 34,
            )
            if close_rect.contains(pos):
                self.clear_context()
                return
            if self._context_card_rect.contains(pos):
                self._dragging_context = True
                self._drag_last = pos
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._dragging_context:
            delta = event.position() - self._drag_last
            self._drag_last = event.position()
            self._context_pan_x = max(-1.0, min(1.0,
                self._context_pan_x + delta.x() / max(80.0, self.width() * 0.12)))
            self._context_pan_y = max(-1.0, min(1.0,
                self._context_pan_y + delta.y() / max(60.0, self.height() * 0.10)))
            self.update()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._dragging_context:
            self._dragging_context = False
            self.unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:
        if self.context_active and self._context_card_rect.contains(event.position()):
            step = 0.08 if event.angleDelta().y() > 0 else -0.08
            self._context_scale = max(0.72, min(1.35, self._context_scale + step))
            self.update(); event.accept(); return
        super().wheelEvent(event)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), qcol(C.BG))

        W, H = self.width(), self.height()
        cx, cy = W / 2, H / 2
        fw = min(W, H)

        # Camera is a true dynamic background. The core and controls are
        # painted afterwards, so they remain continuously visible.
        if self._camera_px and self._camera_mix > 0.01:
            zoom = self._camera_zoom
            pan_x = self._camera_pan_x
            pan_y = self._camera_pan_y
            source_w = self._camera_px.width() / max(1.0, zoom)
            source_h = self._camera_px.height() / max(1.0, zoom)
            target_aspect = W / max(1.0, H)
            if source_w / max(1.0, source_h) > target_aspect:
                source_w = source_h * target_aspect
            else:
                source_h = source_w / target_aspect
            center_x = self._camera_px.width() * (0.5 + pan_x * 0.32)
            center_y = self._camera_px.height() * (0.5 + pan_y * 0.32)
            sx = center_x - source_w / 2
            sy = center_y - source_h / 2
            source = QRectF(
                max(0.0, min(sx, self._camera_px.width() - source_w)),
                max(0.0, min(sy, self._camera_px.height() - source_h)),
                source_w, source_h,
            )
            p.save()
            p.setOpacity(min(1.0, self._camera_mix))
            p.drawPixmap(QRectF(0, 0, W, H), self._camera_px, source)
            p.restore()
            p.fillRect(self.rect(), qcol(C.BG, int(105 + 35 * (1.0 - self._camera_mix))))

        # Deep-black technical grid.  It remains intentionally subtle so the
        # core stays dominant while the background still has depth.
        grid_step = max(58, int(min(W, H) * 0.095))
        p.setPen(QPen(qcol(C.PRI, 13), 1))
        for x in range(0, W + grid_step, grid_step):
            p.drawLine(x, 0, x, H)
        for y in range(0, H + grid_step, grid_step):
            p.drawLine(0, y, W, y)
        p.setPen(QPen(qcol(C.PRI, 18), 1))
        p.drawLine(int(cx), 0, int(cx), H)
        p.drawLine(0, int(cy), W, int(cy))
        self._draw_operational_field(p, W, H)

        if self.camera_active:
            hand_mode = self._camera_mode == "hand"
            detected = hand_mode and bool(self._gesture.get("detected"))
            p.setPen(QPen(qcol(C.GREEN if detected else C.ACC2), 1.2))
            p.setBrush(QBrush(qcol(C.PANEL, 215)))
            p.drawRoundedRect(QRectF(18, 18, 210, 64), 12, 12)
            p.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            p.drawText(QRectF(34, 29, 180, 18), Qt.AlignmentFlag.AlignLeft,
                       "LIVE CAMERA")
            p.setPen(QPen(qcol(C.GREEN if detected else C.TEXT_MED), 1))
            p.setFont(QFont("Segoe UI", 8))
            p.drawText(QRectF(34, 52, 180, 18), Qt.AlignmentFlag.AlignLeft,
                       str(self._gesture.get("gesture", "NORMAL MODE")))
            if detected:
                hx = float(self._gesture.get("center_x", 0.5)) * W
                hy = float(self._gesture.get("center_y", 0.5)) * H
                p.setPen(QPen(qcol(C.PRI, 210), 2))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(QPointF(hx, hy), 24, 24)
                p.drawLine(QPointF(hx - 34, hy), QPointF(hx - 12, hy))
                p.drawLine(QPointF(hx + 12, hy), QPointF(hx + 34, hy))

            # Full-frame optical reticle: visual only, camera processing remains
            # unchanged and continues to run through the guarded capture thread.
            frame = QRectF(18, 18, W - 36, H - 36)
            arm = min(72.0, min(W, H) * 0.10)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(qcol(C.PRI, 125), 1.2))
            for px, py, dx, dy in (
                (frame.left(), frame.top(), 1, 1),
                (frame.right(), frame.top(), -1, 1),
                (frame.left(), frame.bottom(), 1, -1),
                (frame.right(), frame.bottom(), -1, -1),
            ):
                p.drawLine(QPointF(px, py), QPointF(px + dx * arm, py))
                p.drawLine(QPointF(px, py), QPointF(px, py + dy * arm))

            scan_y = frame.top() + ((self._tick * 2.0) % max(1.0, frame.height()))
            optical_scan = QLinearGradient(frame.left(), scan_y, frame.right(), scan_y)
            optical_scan.setColorAt(0.0, qcol(C.PRI, 0))
            optical_scan.setColorAt(0.5, qcol(C.PRI, 92))
            optical_scan.setColorAt(1.0, qcol(C.PRI, 0))
            p.fillRect(QRectF(frame.left(), scan_y, frame.width(), 1), optical_scan)

            p.setFont(mono_font(6, QFont.Weight.DemiBold))
            p.setPen(QPen(qcol(C.TEXT_MED, 210), 1))
            p.drawText(
                QRectF(28, H - 48, 260, 18),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                f"OPTICAL FEED / ZOOM {self._camera_zoom:.1f}X / 30 FPS TARGET",
            )

        if self.context_active:
            base_w = min(W * 0.70, 980.0) * self._context_scale
            base_h = min(H * 0.72, 640.0) * self._context_scale
            card_x = 54.0 + self._context_pan_x * max(45.0, W * 0.10)
            card_y = 58.0 + self._context_pan_y * max(32.0, H * 0.08)
            card_x = max(18.0, min(card_x, W - base_w - 18.0))
            card_y = max(90.0, min(card_y, H - base_h - 18.0))
            card = QRectF(card_x, card_y, base_w, base_h)
            self._context_card_rect = QRectF(card)
            p.setPen(QPen(qcol(C.PRI, 205), 1.3))
            context_glass = QLinearGradient(card.topLeft(), card.bottomRight())
            context_glass.setColorAt(0.0, qcol(C.PANEL2, 238))
            context_glass.setColorAt(0.55, qcol(C.PANEL, 232))
            context_glass.setColorAt(1.0, qcol(C.DARK, 246))
            p.setBrush(QBrush(context_glass))
            p.drawRoundedRect(card, 18, 18)

            p.setPen(QPen(qcol(C.PRI, 22), 1))
            for scan_y in range(int(card.top()) + 62, int(card.bottom()) - 20, 18):
                p.drawLine(QPointF(card.left() + 12, scan_y), QPointF(card.right() - 12, scan_y))
            live_scan_y = card.top() + 58 + ((self._tick * 1.7) % max(1.0, card.height() - 84))
            scan_gradient = QLinearGradient(card.left(), live_scan_y, card.right(), live_scan_y)
            scan_gradient.setColorAt(0.0, qcol(C.PRI, 0))
            scan_gradient.setColorAt(0.5, qcol(C.PRI, 76))
            scan_gradient.setColorAt(1.0, qcol(C.PRI, 0))
            p.fillRect(QRectF(card.left() + 14, live_scan_y, card.width() - 28, 1), scan_gradient)

            p.setPen(QPen(qcol(C.PRI, 150), 1.2))
            arm = 20.0
            for px, py, dx, dy in (
                (card.left() + 5, card.top() + 5, 1, 1),
                (card.right() - 5, card.top() + 5, -1, 1),
                (card.left() + 5, card.bottom() - 5, 1, -1),
                (card.right() - 5, card.bottom() - 5, -1, -1),
            ):
                p.drawLine(QPointF(px, py), QPointF(px + dx * arm, py))
                p.drawLine(QPointF(px, py), QPointF(px, py + dy * arm))
            self._context_tab_rects = []
            tab_count = max(1, len(self._contexts))
            tab_width = min(142.0, (card.width() - 82.0) / tab_count)
            for index, context in enumerate(self._contexts):
                tab = QRectF(
                    card.x() + 14.0 + index * tab_width,
                    card.y() + 10.0,
                    tab_width - 4.0,
                    34.0,
                )
                self._context_tab_rects.append(tab)
                active = index == self._context_index
                p.setPen(QPen(qcol(C.PRI if active else C.BORDER_B), 1.0))
                p.setBrush(QBrush(qcol(C.PRI_GHO if active else C.DARK, 235)))
                p.drawRoundedRect(tab, 8, 8)
                p.setPen(QPen(qcol(C.WHITE if active else C.TEXT_MED), 1))
                p.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
                p.drawText(
                    tab.adjusted(9, 0, -7, 0),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    str(context["title"])[:18],
                )
            p.setPen(QPen(qcol(C.TEXT_MED), 1.5))
            p.drawLine(QPointF(card.right() - 34, card.y() + 18),
                       QPointF(card.right() - 22, card.y() + 30))
            p.drawLine(QPointF(card.right() - 22, card.y() + 18),
                       QPointF(card.right() - 34, card.y() + 30))
            p.setPen(QPen(qcol(C.TEXT_DIM), 1))
            p.drawLine(
                QPointF(card.x() + 20, card.y() + 50),
                QPointF(card.right() - 20, card.y() + 50),
            )

            content = QRectF(card.x() + 22, card.y() + 66,
                             card.width() - 44, card.height() - 88)
            p.save(); p.setClipRect(content)
            title_upper = self._context_title.upper()
            if self._context_px:
                target_h = content.height() * 0.62
                target = QRectF(content.x(), content.y(), content.width(), target_h)
                src = QRectF(0, 0, self._context_px.width(), self._context_px.height())
                p.drawPixmap(target, self._context_px, src)
                content.setTop(target.bottom() + 14)
            elif "MAP" in title_upper or "RUTA" in title_upper:
                p.setPen(QPen(qcol(C.PRI, 75), 1))
                for i in range(1, 7):
                    xx = content.x() + content.width() * i / 7
                    p.drawLine(QPointF(xx, content.y()), QPointF(xx - 45, content.bottom() - 70))
                for i in range(1, 6):
                    yy = content.y() + content.height() * i / 6
                    p.drawLine(QPointF(content.x(), yy), QPointF(content.right(), yy - 24))
                p.setPen(QPen(qcol(C.GREEN), 2)); p.setBrush(QBrush(qcol(C.GREEN, 90)))
                p.drawEllipse(QPointF(content.center().x(), content.center().y()), 10, 10)
                content.setTop(content.bottom() - 76)
            elif any(word in title_upper for word in ("MAT", "FUNCI", "GRÁF", "GRAF", "EJERCICIO")):
                axis_y = content.center().y()
                p.setPen(QPen(qcol(C.TEXT_DIM, 150), 1))
                p.drawLine(QPointF(content.x(), axis_y), QPointF(content.right(), axis_y))
                p.drawLine(QPointF(content.center().x(), content.y()),
                           QPointF(content.center().x(), content.bottom()))
                p.setPen(QPen(qcol(C.PRI), 2))
                last = None
                for i in range(80):
                    xx = content.x() + content.width() * i / 79
                    yy = axis_y - math.sin(i / 8.0) * content.height() * 0.22
                    if last: p.drawLine(last, QPointF(xx, yy))
                    last = QPointF(xx, yy)
                content.setTop(content.bottom() - 88)

            p.setPen(QPen(qcol(C.WHITE, 230), 1))
            p.setFont(QFont("Segoe UI", 9))
            display_text = self._context_text[:1800]
            p.drawText(content, Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignTop, display_text)
            p.restore()

            p.setPen(QPen(qcol(C.TEXT_MED), 1))
            p.setFont(QFont("Segoe UI", 7))
            p.drawText(
                QRectF(card.x() + 22, card.bottom() - 26, card.width() - 44, 18),
                Qt.AlignmentFlag.AlignRight,
                "VOICE: ZOOM  ·  HAND MODE: MOVE",
            )

        # Context mode: reduce and move the core out of the working area.
        # The same positioning rule will be reused by maps/images/math in V3.
        if self.camera_active or self.context_active:
            cx, cy = W * 0.86, H * 0.73
            fw = min(W, H) * 0.38

        core_size = min(fw * 0.72, 520.0)
        core_bounds = QRectF(
            cx - core_size / 2,
            cy - core_size / 2,
            core_size,
            core_size,
        )
        self._draw_core_stage(p, core_bounds)
        self._core.draw(p, core_bounds)
        status = "MUTED" if self.muted else self._core.state.value
        status_color = C.MUTED_C if self.muted else (C.RED if status == "ERROR" else C.PRI)
        p.setPen(QPen(qcol(status_color, 225), 1))
        p.setFont(mono_font(8, QFont.Weight.DemiBold))
        p.drawText(
            QRectF(core_bounds.left(), core_bounds.bottom() + 8, core_bounds.width(), 20),
            Qt.AlignmentFlag.AlignCenter,
            f"CORE / {status}",
        )
        p.end()
        return

        r_face = fw * 0.31

        # halo glow
        for i in range(10):
            r   = r_face * (1.8 - i * 0.08)
            frc = 1.0 - i / 10
            a   = max(0, min(255, int(self._halo * 0.085 * frc)))
            col = qcol(C.MUTED_C if self.muted else C.PRI, a)
            p.setPen(QPen(col, 1.5)); p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))

        # pulse rings
        for pr in self._pulses:
            a   = max(0, int(230 * (1.0 - pr / (fw * 0.74))))
            col = qcol(C.MUTED_C if self.muted else C.PRI, a)
            p.setPen(QPen(col, 1.5)); p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QRectF(cx - pr, cy - pr, pr * 2, pr * 2))

        # spinning arc rings
        for idx, (r_frac, w_r, arc_l, gap) in enumerate(
            [(0.48, 3, 115, 78), (0.40, 2, 78, 55), (0.32, 1, 56, 40)]
        ):
            ring_r = fw * r_frac
            base   = self._rings[idx]
            a_val  = max(0, min(255, int(self._halo * (1.0 - idx * 0.18))))
            col    = qcol(C.MUTED_C if self.muted else C.PRI, a_val)
            p.setPen(QPen(col, w_r)); p.setBrush(Qt.BrushStyle.NoBrush)
            angle = base
            rect  = QRectF(cx - ring_r, cy - ring_r, ring_r * 2, ring_r * 2)
            while angle < base + 360:
                p.drawArc(rect, int(angle * 16), int(arc_l * 16))
                angle += arc_l + gap

        # scanners
        sr = fw * 0.50
        sa = min(255, int(self._halo * 1.5))
        ex = 75 if self.speaking else 44
        p.setPen(QPen(qcol(C.MUTED_C if self.muted else C.PRI, sa), 2.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        srect = QRectF(cx - sr, cy - sr, sr * 2, sr * 2)
        p.drawArc(srect, int(self._scan * 16), int(ex * 16))
        p.setPen(QPen(qcol(C.ACC, sa // 2), 1.5))
        p.drawArc(srect, int(self._scan2 * 16), int(ex * 16))

        # tick marks
        t_out, t_in = fw * 0.497, fw * 0.474
        p.setPen(QPen(qcol(C.PRI, 140), 1))
        for deg in range(0, 360, 10):
            rad = math.radians(deg)
            inn = t_in if deg % 30 == 0 else t_in + 6
            p.drawLine(
                QPointF(cx + t_out * math.cos(rad), cy - t_out * math.sin(rad)),
                QPointF(cx + inn  * math.cos(rad), cy - inn  * math.sin(rad)),
            )

        # crosshair
        ch_r, gap_h = fw * 0.51, fw * 0.16
        p.setPen(QPen(qcol(C.PRI, int(self._halo * 0.5)), 1))
        p.drawLine(QPointF(cx - ch_r, cy), QPointF(cx - gap_h, cy))
        p.drawLine(QPointF(cx + gap_h, cy), QPointF(cx + ch_r, cy))
        p.drawLine(QPointF(cx, cy - ch_r), QPointF(cx, cy - gap_h))
        p.drawLine(QPointF(cx, cy + gap_h), QPointF(cx, cy + ch_r))

        # corner brackets
        bl = 24
        bc = qcol(C.PRI, 210)
        hl, hr = cx - fw // 2, cx + fw // 2
        ht, hb = cy - fw // 2, cy + fw // 2
        p.setPen(QPen(bc, 2))
        for bx, by, dx, dy in [(hl,ht,1,1),(hr,ht,-1,1),(hl,hb,1,-1),(hr,hb,-1,-1)]:
            p.drawLine(QPointF(bx, by), QPointF(bx + dx * bl, by))
            p.drawLine(QPointF(bx, by), QPointF(bx, by + dy * bl))

        # face
        if self._face_px:
            fsz    = int(fw * 0.62 * self._scale)
            scaled = self._face_px.scaled(
                fsz, fsz,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            p.drawPixmap(int(cx - fsz / 2), int(cy - fsz / 2), scaled)
        else:
            orb_r = int(fw * 0.27 * self._scale)
            oc    = (200, 0, 50) if self.muted else (0, 60, 110)
            for i in range(8, 0, -1):
                r2  = int(orb_r * i / 8)
                frc = i / 8
                a   = max(0, min(255, int(self._halo * 1.1 * frc)))
                p.setBrush(QBrush(QColor(int(oc[0]*frc), int(oc[1]*frc), int(oc[2]*frc), a)))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(QRectF(cx - r2, cy - r2, r2 * 2, r2 * 2))
            p.setPen(QPen(qcol(C.PRI, min(255, int(self._halo * 2))), 1))
            p.setFont(QFont("Courier New", 13, QFont.Weight.Bold))
            p.drawText(QRectF(cx - 80, cy - 14, 160, 28),
                       Qt.AlignmentFlag.AlignCenter, "J.A.R.V.I.S")

        # particles
        for pt in self._particles:
            a = max(0, min(255, int(pt[4] * 255)))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(qcol(C.PRI, a)))
            p.drawEllipse(QPointF(pt[0], pt[1]), 2.5, 2.5)

        # status text
        sy = cy + fw * 0.40
        if self.muted:
            txt, col = "⊘  MUTED",     qcol(C.MUTED_C)
        elif self.speaking:
            txt, col = "●  SPEAKING",  qcol(C.ACC)
        elif self.state == "THINKING":
            sym = "◈" if self._blink else "◇"
            txt, col = f"{sym}  THINKING",   qcol(C.ACC2)
        elif self.state == "PROCESSING":
            sym = "▷" if self._blink else "▶"
            txt, col = f"{sym}  PROCESSING", qcol(C.ACC2)
        elif self.state == "LISTENING":
            sym = "●" if self._blink else "○"
            txt, col = f"{sym}  LISTENING",  qcol(C.GREEN)
        else:
            sym = "●" if self._blink else "○"
            txt, col = f"{sym}  {self.state}", qcol(C.PRI)

        p.setPen(QPen(col, 1))
        p.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        p.drawText(
            QRectF(cx - fw * 0.55, sy, fw * 1.10, 26),
            Qt.AlignmentFlag.AlignCenter,
            txt,
        )

        # waveform
        wy = sy + 30
        N, bw = 36, 8
        wx0 = cx - (N * bw) / 2
        for i in range(N):
            if self.muted:
                hgt, cl = 2, qcol(C.MUTED_C)
            elif self.speaking:
                hgt = random.randint(3, 20)
                cl  = qcol(C.PRI) if hgt > 12 else qcol(C.PRI_DIM)
            else:
                hgt = int(3 + 2 * math.sin(self._tick * 0.09 + i * 0.6))
                cl  = qcol(C.BORDER_B)
            p.fillRect(QRectF(wx0 + i * bw, wy + 20 - hgt, bw - 1, hgt), cl)

class MetricBar(QWidget):

    def __init__(self, label: str, color: str = C.PRI, parent=None):
        super().__init__(parent)
        self._label = label
        self._color = color
        self._value = 0.0       # 0–100
        self._text  = "--"
        self._history: list[float] = [0.0] * 24
        self.setFixedHeight(54)
        self.setMinimumWidth(80)

    def set_value(self, pct: float, text: str):
        self._value = max(0.0, min(100.0, pct))
        self._text  = text
        self._history = [*self._history[-23:], self._value]
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()

        panel_gradient = QLinearGradient(0, 0, W, H)
        panel_gradient.setColorAt(0.0, qcol(C.PANEL2, 235))
        panel_gradient.setColorAt(1.0, qcol(C.DARK, 245))
        p.setBrush(QBrush(panel_gradient))
        p.setPen(QPen(qcol(C.BORDER_A), 1))
        p.drawRoundedRect(QRectF(1, 1, W - 2, H - 2), 7, 7)

        bar_h   = 3
        bar_y   = H - bar_h - 5
        bar_w   = W - 12
        bar_x   = 6
        fill_w  = int(bar_w * self._value / 100)

        p.setBrush(QBrush(qcol(C.BAR_BG)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(bar_x, bar_y, bar_w, bar_h), 2, 2)

        if self._value > 85:
            bar_col = qcol(C.RED)
        elif self._value > 65:
            bar_col = qcol(C.ACC)
        else:
            bar_col = qcol(self._color)

        if fill_w > 0:
            p.setBrush(QBrush(bar_col))
            p.drawRoundedRect(QRectF(bar_x, bar_y, fill_w, bar_h), 2, 2)

        p.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.TEXT_DIM), 1))
        p.drawText(QRectF(8, 5, 50, 14), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._label)

        p.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        p.setPen(QPen(bar_col if self._text != "--" else qcol(C.TEXT_DIM), 1))
        p.drawText(QRectF(0, 4, W - 6, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, self._text)

        graph = QPainterPath()
        graph_left = 8.0
        graph_top = 22.0
        graph_width = max(10.0, W - 16.0)
        graph_height = max(8.0, H - 34.0)
        for index, value in enumerate(self._history):
            x = graph_left + graph_width * index / max(1, len(self._history) - 1)
            y = graph_top + graph_height * (1.0 - value / 100.0)
            if index == 0:
                graph.moveTo(x, y)
            else:
                graph.lineTo(x, y)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(qcol(bar_col.name(), 145), 1))
        p.drawPath(graph)

        p.setPen(QPen(qcol(C.PRI, 22), 1))
        for division in range(1, 4):
            x = graph_left + graph_width * division / 4
            p.drawLine(QPointF(x, graph_top), QPointF(x, graph_top + graph_height))

class LogWidget(QTextEdit):
    _sig = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFont(QFont("Courier New", 9))
        self.setStyleSheet(f"""
            QTextEdit {{
                background: rgba(1, 10, 15, 225);
                color: {C.TEXT};
                border: 1px solid {C.BORDER_B};
                border-left: 2px solid {C.PRI_DIM};
                border-radius: 10px;
                padding: 12px;
                selection-background-color: {C.PRI_GHO};
            }}
            QTextEdit:focus {{ border-color: {C.PRI}; }}
            QScrollBar:vertical {{
                background: {C.BG};
                width: 8px;
                border: none;
            }}
            QScrollBar::handle:vertical {{
                background: {C.BORDER_B};
                border-radius: 4px;
                min-height: 20px;
            }}
        """)
        self._queue: list[str] = []
        self._typing  = False
        self._text    = ""
        self._pos     = 0
        self._tag     = "sys"
        self._tmr = QTimer(self)
        self._tmr.timeout.connect(self._step)
        self._sig.connect(self._enqueue)

    def append_log(self, text: str):
        self._sig.emit(text)

    def _enqueue(self, text: str):
        self._queue.append(text)
        if not self._typing:
            self._next()

    def _next(self):
        if not self._queue:
            self._typing = False
            return
        self._typing = True
        self._text   = self._queue.pop(0)
        self._pos    = 0
        tl = self._text.lower()
        if   tl.startswith("you:"):    self._tag = "you"
        elif tl.startswith("jarvis:"): self._tag = "ai"
        elif tl.startswith("file:"):   self._tag = "file"
        elif "err" in tl:              self._tag = "err"
        else:                          self._tag = "sys"
        self._tmr.start(6)

    def _step(self):
        if self._pos < len(self._text):
            ch  = self._text[self._pos]
            cur = self.textCursor()
            fmt = cur.charFormat()
            col = {
                "you":  qcol(C.WHITE),
                "ai":   qcol(C.PRI),
                "err":  qcol(C.RED),
                "file": qcol(C.GREEN),
                "sys":  qcol(C.ACC2),
            }.get(self._tag, qcol(C.TEXT))
            fmt.setForeground(QBrush(col))
            cur.movePosition(cur.MoveOperation.End)
            cur.insertText(ch, fmt)
            self.setTextCursor(cur)
            self.ensureCursorVisible()
            self._pos += 1
        else:
            self._tmr.stop()
            cur = self.textCursor()
            cur.movePosition(cur.MoveOperation.End)
            cur.insertText("\n")
            self.setTextCursor(cur)
            self.ensureCursorVisible()
            QTimer.singleShot(20, self._next)

_FILE_ICONS = {
    "image":   ("🖼", "#00d4ff"), "video":   ("🎬", "#ff6b00"),
    "audio":   ("🎵", "#cc44ff"), "pdf":     ("📄", "#ff4444"),
    "word":    ("📝", "#4488ff"), "excel":   ("📊", "#44bb44"),
    "code":    ("💻", "#ffcc00"), "archive": ("📦", "#ff8844"),
    "pptx":    ("📊", "#ff6622"), "text":    ("📃", "#aaaaaa"),
    "data":    ("🔧", "#88ddff"), "unknown": ("📎", "#888888"),
}
_EXT_TO_CAT = {
    **dict.fromkeys(["jpg","jpeg","png","gif","webp","bmp","tiff","svg","ico"], "image"),
    **dict.fromkeys(["mp4","avi","mov","mkv","wmv","flv","webm","m4v"],         "video"),
    **dict.fromkeys(["mp3","wav","ogg","m4a","aac","flac","wma","opus"],        "audio"),
    **dict.fromkeys(["pdf"],                                                     "pdf"),
    **dict.fromkeys(["doc","docx"],                                              "word"),
    **dict.fromkeys(["xls","xlsx","ods"],                                        "excel"),
    **dict.fromkeys(["ppt","pptx"],                                              "pptx"),
    **dict.fromkeys(["py","js","ts","jsx","tsx","html","css","java","c","cpp",
                     "cs","go","rs","rb","php","swift","kt","sh","sql","lua"],   "code"),
    **dict.fromkeys(["zip","rar","tar","gz","7z","bz2","xz"],                   "archive"),
    **dict.fromkeys(["txt","md","rst","log"],                                    "text"),
    **dict.fromkeys(["csv","tsv","json","xml"],                                  "data"),
}

def _file_category(path: Path) -> str:
    return _EXT_TO_CAT.get(path.suffix.lower().lstrip("."), "unknown")

def _fmt_size(size: int) -> str:
    if   size < 1024:    return f"{size} B"
    elif size < 1024**2: return f"{size/1024:.1f} KB"
    elif size < 1024**3: return f"{size/1024**2:.1f} MB"
    else:                return f"{size/1024**3:.1f} GB"


class FileDropZone(QWidget):
    file_selected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(150)
        self._current_file: str | None = None
        self._hovering  = False
        self._drag_over = False
        self._dash_offset = 0.0
        self._anim_tmr = QTimer(self)
        self._anim_tmr.timeout.connect(self._animate)
        self._anim_tmr.start(40)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._canvas = _DropCanvas(self)
        layout.addWidget(self._canvas)

    def _animate(self):
        self._dash_offset = (self._dash_offset + 0.8) % 20
        self._canvas.update()

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self._drag_over = True; self._canvas.update()

    def dragLeaveEvent(self, e):
        self._drag_over = False; self._canvas.update()

    def dropEvent(self, e: QDropEvent):
        self._drag_over = False
        urls = e.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if Path(path).is_file():
                self._set_file(path)
        self._canvas.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._browse()

    def enterEvent(self, e):
        self._hovering = True; self._canvas.update()

    def leaveEvent(self, e):
        self._hovering = False; self._canvas.update()

    def current_file(self) -> str | None:
        return self._current_file

    def clear_file(self):
        self._current_file = None; self._canvas.update()

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select a file for JARVIS", str(Path.home()),
            "All Files (*.*);;"
            "Images (*.jpg *.jpeg *.png *.gif *.webp *.bmp *.svg);;"
            "Documents (*.pdf *.docx *.txt *.md *.pptx);;"
            "Data (*.csv *.xlsx *.json *.xml);;"
            "Code (*.py *.js *.ts *.html *.css *.java *.cpp *.go);;"
            "Audio (*.mp3 *.wav *.ogg *.m4a *.aac *.flac);;"
            "Video (*.mp4 *.avi *.mov *.mkv *.wmv *.webm);;"
            "Archives (*.zip *.rar *.tar *.gz *.7z)",
        )
        if path:
            self._set_file(path)

    def _set_file(self, path: str):
        self._current_file = path
        self._canvas.update()
        self.file_selected.emit(path)


class _DropCanvas(QWidget):
    def __init__(self, zone: FileDropZone):
        super().__init__(zone)
        self._z = zone

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        z    = self._z
        W, H = self.width(), self.height()
        pad  = 6
        rect = QRectF(pad, pad, W - pad * 2, H - pad * 2)

        bg = QLinearGradient(rect.topLeft(), rect.bottomRight())
        bg.setColorAt(0.0, qcol("#002536" if z._drag_over else "#071b24", 238))
        bg.setColorAt(1.0, qcol(C.DARK, 248))
        p.setBrush(QBrush(bg)); p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(rect, 6, 6)

        p.setPen(QPen(qcol(C.PRI, 18), 1))
        for x in range(pad + 12, W - pad, 22):
            p.drawLine(x, pad + 1, x, H - pad - 1)
        for y in range(pad + 12, H - pad, 18):
            p.drawLine(pad + 1, y, W - pad - 1, y)
        scan_y = pad + 8 + (z._dash_offset / 20.0) * max(1, H - pad * 2 - 16)
        p.setPen(QPen(qcol(C.PRI, 78 if z._drag_over else 34), 1))
        p.drawLine(pad + 8, int(scan_y), W - pad - 8, int(scan_y))

        if z._current_file:   border_col = qcol(C.GREEN, 200)
        elif z._drag_over:    border_col = qcol(C.PRI, 230)
        elif z._hovering:     border_col = qcol(C.BORDER_B, 200)
        else:                 border_col = qcol(C.BORDER, 160)

        pen = QPen(border_col, 1.5, Qt.PenStyle.DashLine)
        pen.setDashOffset(z._dash_offset)
        p.setPen(pen); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect, 6, 6)

        if z._current_file:   self._paint_file(p, W, H)
        elif z._drag_over:    self._paint_drag_over(p, W, H)
        else:                 self._paint_idle(p, W, H, z._hovering)

    def _paint_idle(self, p, W, H, hover):
        cx, cy = W / 2, H / 2
        col = qcol(C.PRI_DIM if not hover else C.PRI)
        p.setPen(QPen(col, 2)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(QPointF(cx, cy - 14), QPointF(cx, cy + 4))
        p.drawLine(QPointF(cx - 8, cy - 6), QPointF(cx, cy - 14))
        p.drawLine(QPointF(cx + 8, cy - 6), QPointF(cx, cy - 14))
        p.drawLine(QPointF(cx - 14, cy + 4), QPointF(cx + 14, cy + 4))
        p.setFont(QFont("Courier New", 8))
        p.setPen(QPen(qcol(C.PRI_DIM if not hover else C.TEXT), 1))
        p.drawText(QRectF(0, cy + 8, W, 16), Qt.AlignmentFlag.AlignCenter,
                   "Drop file here  or  Click to Browse")
        p.setFont(QFont("Courier New", 7))
        p.setPen(QPen(qcol("#1a4a5a"), 1))
        p.drawText(QRectF(0, cy + 24, W, 14), Qt.AlignmentFlag.AlignCenter,
                   "Images · Video · Audio · PDF · Docs · Code · Data")

    def _paint_drag_over(self, p, W, H):
        cx, cy = W / 2, H / 2
        p.setFont(QFont("Courier New", 20))
        p.setPen(QPen(qcol(C.PRI), 1))
        p.drawText(QRectF(0, cy - 24, W, 32), Qt.AlignmentFlag.AlignCenter, "⬇")
        p.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.PRI), 1))
        p.drawText(QRectF(0, cy + 12, W, 16), Qt.AlignmentFlag.AlignCenter, "Release to load")

    def _paint_file(self, p, W, H):
        path = Path(self._z._current_file)
        cat  = _file_category(path)
        icon, icon_col = _FILE_ICONS.get(cat, _FILE_ICONS["unknown"])
        size_str = _fmt_size(path.stat().st_size)
        ext_str  = path.suffix.upper().lstrip(".") or "FILE"

        block_x, block_w = 10, 60
        p.setFont(QFont("Segoe UI Emoji", 22) if _OS == "Windows" else QFont("Arial", 22))
        p.setPen(QPen(qcol(icon_col), 1))
        p.drawText(QRectF(block_x, 0, block_w, H), Qt.AlignmentFlag.AlignCenter, icon)

        tx = block_x + block_w + 6
        tw = W - tx - 38

        p.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.WHITE), 1))
        name = path.name if len(path.name) <= 34 else path.name[:31] + "..."
        p.drawText(QRectF(tx, H * 0.18, tw, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, name)

        p.setFont(QFont("Courier New", 7))
        p.setPen(QPen(qcol(C.TEXT_DIM), 1))
        p.drawText(QRectF(tx, H * 0.18 + 18, tw, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   f"{ext_str}  ·  {size_str}")

        p.setFont(QFont("Courier New", 6))
        p.setPen(QPen(qcol("#1e5c6a"), 1))
        par = str(path.parent)
        if len(par) > 42: par = "…" + par[-41:]
        p.drawText(QRectF(tx, H * 0.18 + 34, tw, 12),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, par)

        p.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.RED, 180), 1))
        p.drawText(QRectF(W - 34, 0, 28, H), Qt.AlignmentFlag.AlignCenter, "✕")

    def mousePressEvent(self, e):
        z = self._z
        if z._current_file and e.pos().x() > self.width() - 34:
            z.clear_file()
        else:
            z.mousePressEvent(e)


class _CameraPreview(QWidget):
    """Floating overlay that briefly shows what the camera captured."""

    _W, _H = 244, 188

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            _CameraPreview {{
                background: rgba(0, 6, 10, 242);
                border: 1px solid {C.PRI};
                border-radius: 6px;
            }}
        """)
        self.setFixedWidth(self._W)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 5, 6, 6)
        lay.setSpacing(4)

        hdr = QHBoxLayout()
        title = QLabel("◈  VISUAL INPUT")
        title.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        hdr.addWidget(title)
        hdr.addStretch()
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(16, 16)
        close_btn.setFont(QFont("Courier New", 8))
        close_btn.setStyleSheet(
            f"color: {C.TEXT_DIM}; background: transparent; border: none;"
        )
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.hide)
        hdr.addWidget(close_btn)
        lay.addLayout(hdr)

        self._img_lbl = QLabel()
        self._img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img_lbl.setStyleSheet("background: transparent;")
        lay.addWidget(self._img_lbl)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

        self.hide()

    def show_frame(self, img_bytes: bytes) -> None:
        px = QPixmap()
        px.loadFromData(img_bytes)
        if not px.isNull():
            max_w = self._W - 12
            scaled = px.scaled(
                max_w, 160,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._img_lbl.setPixmap(scaled)
            self._img_lbl.setFixedSize(scaled.width(), scaled.height())
            self.adjustSize()
        self.show()
        self.raise_()
        self._timer.start(6_000)   # auto-dismiss after 6 s


class SetupOverlay(QWidget):
    done = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            SetupOverlay {{
                background: rgba(0, 6, 10, 245);
                border: 1px solid {C.BORDER_B};
                border-radius: 6px;
            }}
        """)

        detected = {"darwin": "mac", "windows": "windows"}.get(
            _OS.lower(), "linux"
        )
        self._sel_os = detected

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 22, 30, 22)
        layout.setSpacing(8)

        def _lbl(txt, font_size=9, bold=False, color=C.PRI,
                 align=Qt.AlignmentFlag.AlignCenter):
            w = QLabel(txt)
            w.setAlignment(align)
            w.setFont(QFont("Courier New", font_size,
                            QFont.Weight.Bold if bold else QFont.Weight.Normal))
            w.setStyleSheet(f"color: {color}; background: transparent;")
            return w

        layout.addWidget(_lbl("◈  INITIALISATION REQUIRED", 13, True))
        layout.addWidget(_lbl("Configure J.A.R.V.I.S. before first boot.", 9, color=C.PRI_DIM))
        layout.addSpacing(6)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER};"); layout.addWidget(sep)
        layout.addSpacing(4)

        layout.addWidget(_lbl("GEMINI API KEY", 8, color=C.TEXT_DIM,
                               align=Qt.AlignmentFlag.AlignLeft))
        self._key_input = QLineEdit()
        self._key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._key_input.setPlaceholderText("AIza…")
        self._key_input.setFont(QFont("Courier New", 10))
        self._key_input.setFixedHeight(32)
        self._key_input.setStyleSheet(f"""
            QLineEdit {{
                background: #000d12; color: {C.TEXT};
                border: 1px solid {C.BORDER}; border-radius: 3px; padding: 4px 8px;
            }}
            QLineEdit:focus {{ border: 1px solid {C.PRI}; }}
        """)
        layout.addWidget(self._key_input)
        layout.addSpacing(12)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"color: {C.BORDER};"); layout.addWidget(sep2)
        layout.addSpacing(4)

        layout.addWidget(_lbl("OPERATING SYSTEM", 8, color=C.TEXT_DIM,
                               align=Qt.AlignmentFlag.AlignLeft))
        det_name = {"windows": "Windows", "mac": "macOS", "linux": "Linux"}[detected]
        layout.addWidget(_lbl(f"Auto-detected: {det_name}", 8, color=C.ACC2,
                               align=Qt.AlignmentFlag.AlignLeft))

        os_row = QHBoxLayout(); os_row.setSpacing(6)
        self._os_btns: dict[str, QPushButton] = {}
        for key, label in [("windows","⊞  Windows"),("mac","  macOS"),("linux","🐧  Linux")]:
            btn = QPushButton(label)
            btn.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
            btn.setFixedHeight(32)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, k=key: self._sel(k))
            os_row.addWidget(btn)
            self._os_btns[key] = btn
        layout.addLayout(os_row)
        self._sel(detected)
        layout.addSpacing(12)

        init_btn = QPushButton("▸  INITIALISE SYSTEMS")
        init_btn.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        init_btn.setFixedHeight(36)
        init_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        init_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.PRI};
                border: 1px solid {C.PRI_DIM}; border-radius: 3px;
            }}
            QPushButton:hover {{
                background: {C.PRI_GHO}; border: 1px solid {C.PRI};
            }}
        """)
        init_btn.clicked.connect(self._submit)
        layout.addWidget(init_btn)

    def _sel(self, key: str):
        self._sel_os = key
        pal = {"windows":(C.PRI,"#001a22"),"mac":(C.ACC2,"#1a1400"),"linux":(C.GREEN,"#001a0d")}
        for k, btn in self._os_btns.items():
            if k == key:
                fg, bg = pal[k]
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {fg}; color: {bg};
                        border: none; border-radius: 3px; font-weight: bold;
                    }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: #000d12; color: {C.TEXT_DIM};
                        border: 1px solid {C.BORDER}; border-radius: 3px;
                    }}
                    QPushButton:hover {{ color: {C.TEXT}; border: 1px solid {C.BORDER_B}; }}
                """)

    def _submit(self):
        key = self._key_input.text().strip()
        if not key:
            self._key_input.setStyleSheet(
                self._key_input.styleSheet() +
                f" QLineEdit {{ border: 1px solid {C.RED}; }}"
            )
            return
        self.done.emit(key, self._sel_os)


class RemoteKeyOverlay(QWidget):
    """Floating overlay — QR code for instant phone pairing + manual key fallback."""

    closed = pyqtSignal()

    _OW, _OH = 400, 465

    def __init__(self, url: str, key: str, auto_login_url: str = "",
                 manual_url: str = "", expiry_secs: int = 600, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            RemoteKeyOverlay {{
                background: rgba(0, 4, 12, 0.95);
                border: 1px solid {C.BORDER_B};
                border-radius: 14px;
            }}
        """)
        self._expiry          = time.time() + expiry_secs
        self._on_new_key      = None
        self._auto_login_url  = auto_login_url
        self._manual_url      = manual_url or url

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 16, 24, 16)
        lay.setSpacing(5)

        def _lbl(txt, fs=9, bold=False, color=C.PRI,
                 align=Qt.AlignmentFlag.AlignCenter):
            w = QLabel(txt)
            w.setAlignment(align)
            w.setFont(QFont("Courier New", fs,
                            QFont.Weight.Bold if bold else QFont.Weight.Normal))
            w.setStyleSheet(f"color: {color}; background: transparent;")
            w.setWordWrap(True)
            return w

        lay.addWidget(_lbl("◈  REMOTE ACCESS", 12, True))
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER}; margin: 1px 0;")
        lay.addWidget(sep)

        # ── QR code ───────────────────────────────────────────────────────────
        self._qr_label = QLabel()
        self._qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._qr_label.setFixedSize(176, 176)
        self._qr_label.setStyleSheet(
            "background: white; border-radius: 10px; padding: 4px;"
        )
        qr_row = QHBoxLayout()
        qr_row.addStretch()
        qr_row.addWidget(self._qr_label)
        qr_row.addStretch()
        lay.addLayout(qr_row)

        self._update_qr(auto_login_url)

        lay.addWidget(_lbl("Scan with phone camera to connect instantly", 8, color=C.TEXT_DIM))

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"color: {C.BORDER}; margin: 1px 0;")
        lay.addWidget(sep2)

        lay.addWidget(_lbl("Or enter manually:", 7, color=C.TEXT_DIM,
                           align=Qt.AlignmentFlag.AlignLeft))

        self._url_lbl = QLabel(self._manual_url)
        self._url_lbl.setFont(QFont("Courier New", 8))
        self._url_lbl.setStyleSheet(f"color: {C.PRI_DIM}; background: transparent;")
        self._url_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._url_lbl.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self._url_lbl)

        self._key_lbl = QLabel(key)
        self._key_lbl.setFont(QFont("Courier New", 20, QFont.Weight.Bold))
        self._key_lbl.setStyleSheet(f"""
            color: {C.ACC};
            background: {C.PANEL2};
            border: 1px solid {C.BORDER_B};
            border-radius: 8px;
            padding: 6px 4px;
            letter-spacing: 5px;
        """)
        self._key_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._key_lbl)

        self._timer_lbl = QLabel()
        self._timer_lbl.setFont(QFont("Courier New", 8))
        self._timer_lbl.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
        self._timer_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._timer_lbl)

        btn_row = QHBoxLayout(); btn_row.setSpacing(8)
        new_btn = QPushButton("NEW KEY")
        new_btn.setFixedHeight(32)
        new_btn.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        new_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        new_btn.setStyleSheet(f"""
            QPushButton {{
                background: {C.PANEL}; color: {C.PRI};
                border: 1px solid {C.PRI_DIM}; border-radius: 5px;
            }}
            QPushButton:hover {{ background: {C.PRI_GHO}; border: 1px solid {C.PRI}; }}
        """)
        new_btn.clicked.connect(self._refresh_key)
        btn_row.addWidget(new_btn)

        close_btn = QPushButton("DISMISS")
        close_btn.setFixedHeight(32)
        close_btn.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 5px;
            }}
            QPushButton:hover {{ color: {C.TEXT}; border: 1px solid {C.BORDER_B}; }}
        """)
        close_btn.clicked.connect(self._do_close)
        btn_row.addWidget(close_btn)
        lay.addLayout(btn_row)

        self._ctimer = QTimer(self)
        self._ctimer.timeout.connect(self._tick)
        self._ctimer.start(1000)
        self._tick()

    def set_new_key_callback(self, fn) -> None:
        self._on_new_key = fn

    def _update_qr(self, url: str) -> None:
        if not url:
            self._qr_label.setText("—")
            return
        try:
            import qrcode as _qrmod
            from io import BytesIO
            qr = _qrmod.QRCode(
                box_size=5, border=2,
                error_correction=_qrmod.constants.ERROR_CORRECT_M,
            )
            qr.add_data(url)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            buf = BytesIO()
            img.save(buf, format="PNG")
            px = QPixmap()
            px.loadFromData(buf.getvalue())
            self._qr_label.setPixmap(
                px.scaled(170, 170,
                          Qt.AspectRatioMode.KeepAspectRatio,
                          Qt.TransformationMode.SmoothTransformation)
            )
        except ImportError:
            self._qr_label.setText("pip install\nqrcode[pil]")
            self._qr_label.setFont(QFont("Courier New", 8))
            self._qr_label.setStyleSheet(
                "color: #888; background: white; border-radius: 10px; padding: 4px;"
            )
        except Exception:
            self._qr_label.setText(url[:28])
            self._qr_label.setFont(QFont("Courier New", 7))
            self._qr_label.setStyleSheet(
                f"color: {C.PRI}; background: white; border-radius: 10px; padding: 4px;"
            )

    def _tick(self):
        remaining = max(0, int(self._expiry - time.time()))
        m, s = divmod(remaining, 60)
        self._timer_lbl.setText(f"Key expires in  {m:02d}:{s:02d}")
        if remaining == 0:
            self._do_close()

    def mark_connected(self) -> None:
        """Call from any thread when a phone successfully connects."""
        self._ctimer.stop()
        self._key_lbl.setText("CONNECTED")
        self._key_lbl.setStyleSheet(f"""
            color: {C.GREEN};
            background: rgba(34,197,94,0.08);
            border: 2px solid rgba(34,197,94,0.4);
            border-radius: 8px;
            padding: 6px 4px;
            letter-spacing: 4px;
        """)
        self._qr_label.setText("✓")
        self._qr_label.setFont(QFont("Courier New", 54, QFont.Weight.Bold))
        self._qr_label.setStyleSheet(
            "color: #00ff88; background: #001a0d; border-radius: 10px;"
        )
        self._timer_lbl.setText("Phone connected — JARVIS ready")
        self._timer_lbl.setStyleSheet(f"color: {C.GREEN}; background: transparent;")

    def _refresh_key(self):
        if self._on_new_key:
            result = self._on_new_key()
            if result:
                url    = result[0]
                key    = result[1]
                auto   = result[2] if len(result) >= 3 else ""
                manual = result[3] if len(result) >= 4 else url
                self._manual_url     = manual or url
                self._url_lbl.setText(self._manual_url)
                self._key_lbl.setText(key)
                self._auto_login_url = auto
                self._update_qr(auto or url)
                self._expiry = time.time() + 600
                self._key_lbl.setStyleSheet(f"""
                    color: {C.ACC};
                    background: {C.PANEL2};
                    border: 1px solid {C.BORDER_B};
                    border-radius: 8px;
                    padding: 6px 4px;
                    letter-spacing: 5px;
                """)
                self._timer_lbl.setStyleSheet(
                    f"color: {C.TEXT_MED}; background: transparent;"
                )
                self._ctimer.start(1000)
                self._tick()

    def _do_close(self):
        self._ctimer.stop()
        self.hide()
        self.closed.emit()


class SymbolButton(QPushButton):
    """Small vector-only control used by the minimal bottom navigation."""

    def __init__(self, symbol: str, tooltip: str, parent=None):
        super().__init__(parent)
        self.symbol = symbol
        self.setToolTip(tooltip)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(46, 46)
        self.setStyleSheet("background: transparent; border: none;")

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        active = self.isChecked()
        hover = self.underMouse()
        border = qcol(C.PRI if active or hover else C.BORDER_B, 245)
        fill = qcol(C.PRI_GHO if active or hover else C.PANEL, 245)
        p.setPen(QPen(border, 1.4))
        p.setBrush(QBrush(fill))
        p.drawRoundedRect(QRectF(1.5, 1.5, 43, 43), 11, 11)

        col = qcol(C.WHITE if active else C.PRI, 245)
        p.setPen(QPen(col, 2.0, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.setBrush(Qt.BrushStyle.NoBrush)

        if self.symbol == "chat":
            path = QPainterPath()
            path.addRoundedRect(QRectF(12, 12, 22, 17), 4, 4)
            path.moveTo(17, 29); path.lineTo(14, 35); path.lineTo(22, 29)
            p.drawPath(path)
            p.drawLine(17, 18, 29, 18); p.drawLine(17, 23, 26, 23)
        elif self.symbol == "file":
            path = QPainterPath()
            path.moveTo(15, 10); path.lineTo(27, 10); path.lineTo(34, 17)
            path.lineTo(34, 36); path.lineTo(15, 36); path.closeSubpath()
            p.drawPath(path)
            p.drawLine(27, 10, 27, 18); p.drawLine(27, 18, 34, 18)
            p.drawLine(20, 25, 29, 25); p.drawLine(20, 30, 29, 30)
        elif self.symbol == "camera":
            p.drawRoundedRect(QRectF(10, 15, 27, 20), 4, 4)
            p.drawEllipse(QRectF(19, 20, 9, 9))
            p.drawLine(16, 15, 19, 11); p.drawLine(19, 11, 27, 11)
            p.drawLine(27, 11, 30, 15)
        elif self.symbol == "brain":
            p.drawArc(QRectF(12, 11, 14, 25), 80 * 16, 205 * 16)
            p.drawArc(QRectF(21, 11, 14, 25), -105 * 16, 205 * 16)
            p.drawLine(23, 14, 23, 34)
            p.drawArc(QRectF(15, 16, 9, 8), 40 * 16, 185 * 16)
            p.drawArc(QRectF(23, 23, 9, 8), 210 * 16, 190 * 16)
        elif self.symbol == "globe":
            p.drawEllipse(QRectF(11, 11, 24, 24))
            p.drawArc(QRectF(17, 11, 12, 24), 90 * 16, 180 * 16)
            p.drawArc(QRectF(17, 11, 12, 24), -90 * 16, 180 * 16)
            p.drawLine(12, 23, 34, 23)
        elif self.symbol == "study":
            p.drawLine(14, 11, 32, 11); p.drawLine(17, 11, 17, 34)
            p.drawLine(29, 11, 29, 34); p.drawLine(17, 34, 29, 34)
            p.drawLine(20, 18, 26, 18); p.drawLine(20, 23, 26, 23)
            p.drawEllipse(QRectF(21, 27, 4, 4))
        elif self.symbol == "pet":
            p.drawRoundedRect(QRectF(12, 16, 22, 18), 7, 7)
            p.drawLine(17, 34, 17, 38); p.drawLine(29, 34, 29, 38)
            p.drawLine(23, 16, 23, 11); p.drawEllipse(QRectF(21, 8, 4, 4))
            p.drawEllipse(QRectF(17, 22, 2.5, 2.5))
            p.drawEllipse(QRectF(26.5, 22, 2.5, 2.5))
            p.drawArc(QRectF(19, 23, 8, 7), 205 * 16, 130 * 16)


class MainWindow(QMainWindow):
    _log_sig     = pyqtSignal(str)
    _state_sig   = pyqtSignal(str)
    _content_sig = pyqtSignal(str, str)   # (title, text) — thread-safe content display
    _reconfig_sig = pyqtSignal()          # trigger setup overlay from any thread
    _camera_sig     = pyqtSignal(bytes)   # show camera frame preview (small overlay)
    _cam_stream_sig = pyqtSignal(bool)   # True=start live stream, False=stop
    _cam_frame_sig  = pyqtSignal(object)  # copied QImage → HUD without JPEG round-trip
    _gesture_sig    = pyqtSignal(dict)
    _camera_mode_sig = pyqtSignal(str)
    _camera_view_sig = pyqtSignal(float, float, float)
    _camera_request_sig = pyqtSignal(bool)
    _pet_mode_sig = pyqtSignal(str, str)
    _geo_focus_sig = pyqtSignal(float, float, str)
    _workspace_sig = pyqtSignal(str, object)
    _interface_sig = pyqtSignal(object)
    _study_sig = pyqtSignal(object)
    _main_mode_sig = pyqtSignal()
    _phone_connected_sig = pyqtSignal()

    def __init__(self, face_path: str):
        super().__init__()
        self._face_path = face_path
        icon_path = CONFIG_DIR / "jarvis.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        self.setWindowTitle("J.A.R.V.I.S — MARK LI")
        self.setMinimumSize(_MIN_W, _MIN_H)
        self.resize(_DEFAULT_W, _DEFAULT_H)

        screen = QApplication.primaryScreen().availableGeometry()
        self.move(
            (screen.width()  - _DEFAULT_W) // 2,
            (screen.height() - _DEFAULT_H) // 2,
        )

        self.on_text_command   = None
        self.on_remote_clicked = None   # callable: () -> (url, key) | None
        self.on_interrupt      = None   # callable: () -> None — stop JARVIS mid-speech
        self._tool_state_lock  = threading.RLock()
        self._muted            = False
        self._listen_mode       = "always"   # toggle | always
        self._talk_enabled      = True
        self._current_file: str | None = None
        self._remote_overlay: RemoteKeyOverlay | None = None
        self._active_v1_panel: str | None = None
        self._panel_animation: QPropertyAnimation | None = None
        self._panel_motion: QParallelAnimationGroup | None = None
        self._memory_animation: QPropertyAnimation | None = None
        self._system_animation: QPropertyAnimation | None = None
        self._system_open = False

        central = QWidget()
        central.setStyleSheet(f"background: {C.BG};")
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self._left_panel = self._build_left_panel()
        self._left_panel.hide()
        self._left_panel.setMaximumWidth(0)
        body.addWidget(self._left_panel, stretch=0)

        # Center column: HUD + resizable content panel via QSplitter
        self.hud = HudCanvas(face_path)
        self.hud.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._content_panel = self._build_content_panel()

        # Live camera container — replaces HUD when camera stream is active
        _cam_cont = QWidget()
        _cam_cont.setStyleSheet("background: #000308;")
        _cam_v = QVBoxLayout(_cam_cont)
        _cam_v.setContentsMargins(0, 0, 0, 0)
        _cam_v.setSpacing(0)
        _cam_hdr = QHBoxLayout()
        _cam_hdr.setContentsMargins(8, 5, 8, 5)
        _cam_title = QLabel("◈  CAMERA FEED")
        _cam_title.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        _cam_title.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        _cam_hdr.addWidget(_cam_title)
        _cam_hdr.addStretch()
        _cam_x = QPushButton("✕  CLOSE")
        _cam_x.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        _cam_x.setCursor(Qt.CursorShape.PointingHandCursor)
        _cam_x.setStyleSheet(f"""
            QPushButton {{
                color: {C.TEXT_DIM}; background: transparent;
                border: none; padding: 2px 6px;
            }}
            QPushButton:hover {{ color: {C.PRI}; }}
        """)
        _cam_x.clicked.connect(self.stop_camera_stream)
        _cam_hdr.addWidget(_cam_x)
        _cam_v.addLayout(_cam_hdr)
        self._cam_live_lbl = QLabel()
        self._cam_live_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cam_live_lbl.setStyleSheet("background: transparent;")
        self._cam_live_lbl.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        _cam_v.addWidget(self._cam_live_lbl, stretch=1)

        # Stack: 0 = animated HUD, 1 = live camera, 2 = memory, 3 = geo, 4 = study
        self._hud_cam_stack = QStackedWidget()
        self._hud_cam_stack.addWidget(self.hud)
        self._hud_cam_stack.addWidget(_cam_cont)
        self._memory_workspace = MemoryGraphWorkspace(self)
        self._geo_workspace = GeoWorkspace(self)
        self._study_workspace = StudyWorkspace(self)
        self._hud_cam_stack.addWidget(self._memory_workspace)
        self._hud_cam_stack.addWidget(self._geo_workspace)
        self._hud_cam_stack.addWidget(self._study_workspace)
        self._geo_workspace.locationRequested.connect(self._locate_geo_query)
        self._geo_focus_sig.connect(self._apply_geo_focus)

        self._center_split = QSplitter(Qt.Orientation.Vertical)
        self._center_split.setStyleSheet(f"""
            QSplitter::handle {{
                background: {C.BORDER};
                height: 4px;
            }}
            QSplitter::handle:hover {{
                background: {C.PRI_DIM};
            }}
        """)
        self._center_split.addWidget(self._hud_cam_stack)
        self._center_split.addWidget(self._content_panel)
        self._center_split.setStretchFactor(0, 3)
        self._center_split.setStretchFactor(1, 1)
        self._center_split.setCollapsible(0, False)
        body.addWidget(self._center_split, stretch=5)

        self._right_panel = self._build_right_panel()
        self._right_panel.hide()
        self._right_panel.setMaximumWidth(0)
        body.addWidget(self._right_panel, stretch=0)

        root.addLayout(body, stretch=1)
        root.addWidget(self._build_control_bar())
        root.addWidget(self._build_footer())

        self._clock_tmr = QTimer(self)
        self._clock_tmr.timeout.connect(self._tick_clock)
        self._clock_tmr.start(1000)
        self._tick_clock()

        # Metrik güncelleme timer'ı
        self._metric_tmr = QTimer(self)
        self._metric_tmr.timeout.connect(self._update_metrics)
        self._metric_tmr.start(2000)
        self._update_metrics()

        self._log_sig.connect(self._log.append_log)
        self._state_sig.connect(self._apply_state)
        self._content_sig.connect(self._show_content)
        self._reconfig_sig.connect(self._show_setup)
        self._camera_sig.connect(self._show_camera_frame)
        self._cam_stream_sig.connect(self._on_cam_stream)
        self._cam_frame_sig.connect(self._on_cam_frame)
        self._gesture_sig.connect(self._on_gesture)
        self._camera_mode_sig.connect(self._set_camera_mode)
        self._camera_view_sig.connect(self.hud.set_camera_view)
        self._camera_request_sig.connect(self._set_camera_stream_running)
        self._workspace_sig.connect(self._show_workspace_request)
        self._interface_sig.connect(self._execute_interface_request)
        self._study_sig.connect(self._show_study_request)
        self._phone_connected_sig.connect(self.notify_phone_connected)
        self._cam_stop = threading.Event()
        self._cam_lock = threading.Lock()
        self._cam_generation = 0
        self._cam_thread = None
        self._camera_mode = "normal"
        self._gesture_tracker = HandGestureTracker()
        self._gesture_frame_count = 0
        self._last_gesture_action = 0.0
        self._last_camera_ui_frame = 0.0
        self._camera_frame_callback = None
        self._last_camera_ai_frame = 0.0

        # Camera preview overlay (child of central widget, positioned in resizeEvent)
        self._cam_preview = _CameraPreview(self.centralWidget())

        self._overlay: SetupOverlay | None = None
        self._ready = self._check_config()
        if not self._ready:
            self._show_setup()

        self._sc_full = QShortcut(QKeySequence("F11"), self)
        self._sc_full.activated.connect(self._toggle_fullscreen)
        self._sc_intr = QShortcut(QKeySequence("Escape"), self)
        self._sc_intr.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self._sc_intr.activated.connect(self._do_interrupt)

        # QShortcut cannot see ESC while another application has focus. On
        # Windows, poll the key state without registering/consuming a global
        # hotkey, and only act while JARVIS is actually speaking.
        self._global_esc_timer = None
        self._esc_was_down = False
        if platform.system() == "Windows":
            self._global_esc_timer = QTimer(self)
            self._global_esc_timer.timeout.connect(self._poll_global_escape)
            self._global_esc_timer.start(30)

        # Local backslash only works while the JARVIS window has focus.
        self._sc_talk = QShortcut(QKeySequence("\\"), self)
        self._sc_talk.activated.connect(self._toggle_talk)

    def closeEvent(self, event) -> None:
        """Closing the main window must release the process and wake-word mic."""
        if hasattr(self, "_cam_stop"):
            self._cam_stop.set()
        update_runtime_state("jarvis", "off", reason="window_closed")
        event.accept()
        QApplication.quit()

        # Some audio/network libraries retain non-daemon native threads after
        # Qt exits. Guarantee that the wake detector can observe a real close.
        exit_timer = threading.Timer(0.35, lambda: os._exit(0))
        exit_timer.daemon = True
        exit_timer.start()

    def _show_camera_frame(self, img_bytes: bytes):
        """Slot — display camera preview overlay (main thread)."""
        self._cam_preview.show_frame(img_bytes)
        cw = self.centralWidget()
        pw = _CameraPreview._W
        ph = self._cam_preview.height()
        self._cam_preview.setGeometry(
            cw.width() - _RIGHT_W - pw - 12,
            cw.height() - ph - 28,
            pw, ph,
        )

    # --- Live camera stream in HUD area ------------------------------------
    def _on_cam_stream(self, start: bool) -> None:
        self._hud_cam_stack.setCurrentIndex(0)
        self.hud.set_camera_active(start)
        if hasattr(self, "_v1_camera_btn"):
            self._v1_camera_btn.setChecked(start)
        if not start:
            self._cam_live_lbl.clear()

    def _on_cam_frame(self, image: QImage) -> None:
        px = QPixmap.fromImage(image)
        if not px.isNull():
            self.hud.set_camera_frame(px)
            w, h = self._cam_live_lbl.width(), self._cam_live_lbl.height()
            if w > 1 and h > 1:
                self._cam_live_lbl.setPixmap(
                    px.scaled(w, h,
                              Qt.AspectRatioMode.KeepAspectRatio,
                              Qt.TransformationMode.SmoothTransformation)
                )

    def _on_gesture(self, data: dict) -> None:
        self.hud.set_gesture(data)

    def _set_camera_mode(self, mode: str) -> None:
        self._camera_mode = "hand" if mode == "hand" else "normal"
        self.hud.set_camera_mode(self._camera_mode)

    def start_camera_stream(self) -> None:
        with self._cam_lock:
            if self._cam_thread is not None and self._cam_thread.is_alive():
                return
            self._cam_generation += 1
            generation = self._cam_generation
            self._cam_stop.clear()
            t = threading.Thread(
                target=self._cam_loop,
                args=(generation,),
                daemon=True,
                name=f"cam-stream-{generation}",
            )
            self._cam_thread = t
        self._cam_stream_sig.emit(True)
        t.start()

    def _set_camera_stream_running(self, running: bool) -> None:
        """Run camera lifecycle changes only on Qt's owning thread."""
        if running:
            self.start_camera_stream()
        else:
            self.stop_camera_stream()

    def _cam_loop(self, generation: int) -> None:
        cap = None
        try:
            import cv2
            # Reuse the camera index owned by the process settings service.
            cam_idx = 0
            try:
                cam_idx = int(get_settings().extras.get("camera_index", 0))
            except (TypeError, ValueError):
                pass
            try:
                backend = cv2.CAP_DSHOW if _OS == "Windows" else cv2.CAP_ANY
            except AttributeError:
                backend = 0
            cap = cv2.VideoCapture(cam_idx, backend)
            if not cap.isOpened():
                cap = cv2.VideoCapture(0)
            if not cap.isOpened():
                return
            if self._cam_stop.is_set():
                return
            cfg = get_settings().as_legacy_dict()
            profile = profile_from_config(cfg)
            actual = configure_capture(cap, cv2, profile)
            if self._cam_stop.is_set():
                return
            print(
                "[Camera] Capture "
                f"{actual['width']:.0f}x{actual['height']:.0f} @ {actual['fps']:.0f} FPS"
            )
            # warm-up frames
            for _ in range(5):
                if self._cam_stop.is_set():
                    return
                cap.read()
            while not self._cam_stop.wait(0.033) and cap.isOpened():
                ret, frame = cap.read()
                if ret and frame is not None:
                    now = time.monotonic()
                    if (
                        self._camera_mode == "hand"
                        and now - self._last_gesture_action >= 0.10
                    ):
                        self._last_gesture_action = now
                        try:
                            self._gesture_sig.emit(self._gesture_tracker.process(frame))
                        except Exception as exc:
                            self._gesture_sig.emit({
                                "detected": False,
                                "gesture": f"TRACKER: {type(exc).__name__}",
                            })
                    if now - self._last_camera_ui_frame >= (1.0 / 30.0):
                        self._last_camera_ui_frame = now
                        height, width, channels = frame.shape
                        image = QImage(
                            frame.data,
                            width,
                            height,
                            channels * width,
                            QImage.Format.Format_BGR888,
                        ).copy()
                        self._cam_frame_sig.emit(image)
                    with self._cam_lock:
                        callback = self._camera_frame_callback
                    if callback and now - self._last_camera_ai_frame >= 1.0:
                        self._last_camera_ai_frame = now
                        try:
                            ok, buf = cv2.imencode(
                                ".jpg",
                                frame,
                                [cv2.IMWRITE_JPEG_QUALITY, profile.jpeg_quality],
                            )
                            if ok:
                                callback(buf.tobytes())
                        except Exception as exc:
                            print(f"[Camera] AI frame callback failed: {exc}")
        except Exception as e:
            print(f"[Camera] Stream error: {e}")
        finally:
            if cap is not None:
                try:
                    cap.release()
                except Exception:
                    pass
            with self._cam_lock:
                owns_session = (
                    self._cam_generation == generation
                    and self._cam_thread is threading.current_thread()
                )
                if owns_session:
                    self._cam_thread = None
            if owns_session:
                self._cam_stream_sig.emit(False)

    def stop_camera_stream(self) -> None:
        self._cam_stop.set()
        with self._cam_lock:
            self._camera_frame_callback = None
        self._cam_stream_sig.emit(False)

    def set_camera_frame_callback(self, callback) -> None:
        with self._cam_lock:
            self._camera_frame_callback = callback

    def set_camera_mode(self, mode: str) -> None:
        self._camera_mode_sig.emit(mode)

    def set_camera_view(self, zoom: float, pan_x: float, pan_y: float) -> None:
        self._camera_view_sig.emit(zoom, pan_x, pan_y)

    # ------------------------------------------------------------------
    # Icon generation — arc-reactor style, rendered with Pillow
    # ------------------------------------------------------------------
    @staticmethod
    def _build_jarvis_icon(out_path: Path) -> bool:
        """
        Render a JARVIS arc-reactor icon at 4× resolution and downsample
        for crisp results at all sizes. Saves a multi-res .ico to out_path.
        Returns True on success.
        """
        try:
            import math
            import PIL.Image
            import PIL.ImageDraw
            import PIL.ImageFilter
        except ImportError:
            return False

        CYAN   = (0, 212, 255)
        DIM    = (0, 100, 140)
        DARK   = (0, 6, 10)
        GLOW   = (0, 160, 200)
        WHITE  = (220, 240, 255)

        def _render(sz: int) -> PIL.Image.Image:
            S  = sz * 4                     # draw at 4× then downscale
            img = PIL.Image.new("RGBA", (S, S), (0, 0, 0, 0))
            d   = PIL.ImageDraw.Draw(img)
            cx = cy = S // 2

            # ── filled background circle ──────────────────────────────────
            R = S // 2 - 2
            d.ellipse([cx-R, cy-R, cx+R, cy+R], fill=(*DARK, 255))

            # ── outer border ring ─────────────────────────────────────────
            lw = max(2, S // 40)
            d.ellipse([cx-R, cy-R, cx+R, cy+R],
                      outline=(*CYAN, 220), width=lw)

            # ── mid decorative ring ───────────────────────────────────────
            R2 = int(R * 0.72)
            d.ellipse([cx-R2, cy-R2, cx+R2, cy+R2],
                      outline=(*DIM, 180), width=max(1, lw // 2))

            # ── 6 radial spokes (hex bolt) ────────────────────────────────
            R_inner = int(R * 0.30)
            R_outer = int(R * 0.62)
            spoke_w = max(1, S // 80)
            for i in range(6):
                angle = math.radians(i * 60 - 30)
                x1 = cx + int(R_inner * math.cos(angle))
                y1 = cy + int(R_inner * math.sin(angle))
                x2 = cx + int(R_outer * math.cos(angle))
                y2 = cy + int(R_outer * math.sin(angle))
                d.line([x1, y1, x2, y2], fill=(*GLOW, 200), width=spoke_w)

            # ── 6 tick marks on outer ring ────────────────────────────────
            for i in range(6):
                angle = math.radians(i * 60)
                for dr in range(lw * 2):
                    rx = (R - lw - dr)
                    d.point(
                        [cx + int(rx * math.cos(angle)),
                         cy + int(rx * math.sin(angle))],
                        fill=(*WHITE, 220),
                    )

            # ── inner glowing ring ────────────────────────────────────────
            Ri = int(R * 0.26)
            d.ellipse([cx-Ri, cy-Ri, cx+Ri, cy+Ri],
                      outline=(*CYAN, 255), width=max(2, lw))

            # ── bright glow soft blur applied before core ─────────────────
            # (draw a slightly larger cyan circle on a separate layer)
            glow_layer = PIL.Image.new("RGBA", (S, S), (0, 0, 0, 0))
            gd = PIL.ImageDraw.Draw(glow_layer)
            Rc = int(R * 0.13)
            gd.ellipse([cx-Rc*2, cy-Rc*2, cx+Rc*2, cy+Rc*2],
                       fill=(*CYAN, 110))
            glow_layer = glow_layer.filter(PIL.ImageFilter.GaussianBlur(S // 14))
            img = PIL.Image.alpha_composite(img, glow_layer)
            d   = PIL.ImageDraw.Draw(img)

            # ── core dot ──────────────────────────────────────────────────
            d.ellipse([cx-Rc, cy-Rc, cx+Rc, cy+Rc], fill=(*WHITE, 255))

            # ── downscale to target size ──────────────────────────────────
            return img.resize((sz, sz), PIL.Image.LANCZOS)

        try:
            sizes  = [256, 128, 64, 48, 32, 16]
            frames = [_render(s) for s in sizes]
            frames[0].save(
                out_path,
                format="ICO",
                append_images=frames[1:],
                sizes=[(s, s) for s in sizes],
            )
            return True
        except Exception as e:
            print(f"[Shortcut] ⚠️  Icon generation failed: {e}")
            return False

    @staticmethod
    def _create_lnk_windows(lnk: str, target: str, args: str,
                             work_dir: str, icon_loc: str) -> None:
        """
        Create a Windows .lnk shortcut WITHOUT launching PowerShell or cmd.
        Tries win32com (pywin32) first; falls back to wscript.exe + VBScript.
        wscript.exe is a GUI-mode host — it never opens a console window.
        """
        # ── Option 1: pywin32 (pure Python COM, zero subprocess) ──────────
        try:
            from win32com.client import Dispatch   # type: ignore
            sh = Dispatch("WScript.Shell")
            sc = sh.CreateShortCut(lnk)
            sc.TargetPath       = target
            sc.Arguments        = args
            sc.WorkingDirectory = work_dir
            sc.Description      = "J.A.R.V.I.S AI Assistant"
            sc.IconLocation     = icon_loc
            sc.save()
            return
        except ImportError:
            pass

        # ── Option 2: wscript.exe + VBScript (always available on Windows,
        #    GUI-mode executable — never opens a console window) ────────────
        vbs = "\n".join([
            'Set ws = CreateObject("WScript.Shell")',
            f'Set sc = ws.CreateShortcut("{lnk}")',
            f'sc.TargetPath = "{target}"',
            f'sc.Arguments = "{args.replace(chr(34), chr(34) + chr(34))}"',
            f'sc.WorkingDirectory = "{work_dir}"',
            'sc.Description = "J.A.R.V.I.S AI Assistant"',
            f'sc.IconLocation = "{icon_loc}"',
            'sc.Save',
        ])
        import tempfile
        fd, tmp = tempfile.mkstemp(suffix=".vbs")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(vbs)
            proc = subprocess.Popen(
                ["wscript.exe", "/nologo", tmp],
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW,
            )
            proc.wait(timeout=10)
        finally:
            try:
                os.unlink(tmp)
            except Exception:
                pass

    def _create_desktop_shortcut(self):
        """
        Create a desktop shortcut on Windows / macOS / Linux.
        Never opens a terminal, console, or PowerShell window on any platform.
        """
        import stat as _stat
        script  = Path(__file__).resolve().parent / "jarvis_launcher.py"
        python  = Path(sys.executable)
        from utils.paths import get_desktop
        desktop = get_desktop()

        # Arc-reactor icon (.ico — also exported as .png for Linux/macOS)
        ico_path = Path(__file__).resolve().parent / "config" / "jarvis.ico"
        if not ico_path.exists():
            self._build_jarvis_icon(ico_path)

        try:
            _os = platform.system()

            # ── Windows ───────────────────────────────────────────────────────
            if _os == "Windows":
                pythonw  = python.parent / "pythonw.exe"
                target   = str(pythonw if pythonw.exists() else python)
                icon_loc = str(ico_path) if ico_path.exists() else f"{target},0"
                wake_bootstrap = script.parent / "launch_jarvis_wake.vbs"
                wscript = Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "wscript.exe"
                wake_target = str(wscript) if wake_bootstrap.exists() and wscript.exists() else target
                wake_args = (
                    f'"{wake_bootstrap}"'
                    if wake_target == str(wscript)
                    else f'"{script}" --mode wake'
                )
                self._create_lnk_windows(
                    str(desktop / "J.A.R.V.I.S Direct.lnk"), target,
                    f'"{script}" --mode direct', str(script.parent), icon_loc,
                )
                self._create_lnk_windows(
                    str(desktop / "J.A.R.V.I.S Voice Activation.lnk"), wake_target,
                    wake_args, str(script.parent), icon_loc,
                )
                # The primary shortcut is the normal/manual launch. Direct mode
                # also closes this project's wake detector so it releases the
                # microphone and does not remain as a stray pythonw process.
                self._create_lnk_windows(
                    str(desktop / "J.A.R.V.I.S.lnk"), target,
                    f'"{script}" --mode direct', str(script.parent), icon_loc,
                )

            # ── macOS — proper .app bundle (no Terminal window) ───────────────
            elif _os == "Darwin":
                app     = desktop / "J.A.R.V.I.S.app"
                mac_dir = app / "Contents" / "MacOS"
                res_dir = app / "Contents" / "Resources"
                mac_dir.mkdir(parents=True, exist_ok=True)
                res_dir.mkdir(exist_ok=True)

                # Launcher executable (bash — runs as background process,
                # macOS does NOT open Terminal for executables inside .app bundles)
                launcher = mac_dir / "JARVIS"
                launcher.write_text(
                    "#!/usr/bin/env bash\n"
                    f'cd "{script.parent}"\n'
                    f'exec "{python}" "{script}"\n'
                )
                launcher.chmod(launcher.stat().st_mode
                               | _stat.S_IEXEC | _stat.S_IXGRP | _stat.S_IXOTH)

                # Minimal Info.plist (required for .app recognition)
                (app / "Contents" / "Info.plist").write_text(
                    '<?xml version="1.0" encoding="UTF-8"?>\n'
                    '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
                    '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
                    '<plist version="1.0"><dict>\n'
                    '  <key>CFBundleExecutable</key><string>JARVIS</string>\n'
                    '  <key>CFBundleIdentifier</key>'
                    '<string>com.jarvis.assistant</string>\n'
                    '  <key>CFBundleName</key><string>J.A.R.V.I.S</string>\n'
                    '  <key>CFBundlePackageType</key><string>APPL</string>\n'
                    '  <key>CFBundleVersion</key><string>1.0</string>\n'
                    '</dict></plist>\n'
                )

                # Optional: copy icon as .icns (skip silently if Pillow is missing)
                try:
                    import PIL.Image
                    icns = res_dir / "AppIcon.icns"
                    PIL.Image.open(ico_path).save(icns, format="ICNS")
                    # Inject icon reference into plist
                    plist = app / "Contents" / "Info.plist"
                    txt = plist.read_text()
                    plist.write_text(
                        txt.replace(
                            '</dict></plist>',
                            '  <key>CFBundleIconFile</key>'
                            '<string>AppIcon</string>\n</dict></plist>\n',
                        )
                    )
                except Exception:
                    pass  # icon is optional

            # ── Linux — .desktop file (Terminal=false, no console) ────────────
            else:
                # Export .ico → .png for better desktop integration
                png_path = ico_path.with_suffix(".png")
                if not png_path.exists() and ico_path.exists():
                    try:
                        import PIL.Image
                        PIL.Image.open(ico_path).resize(
                            (256, 256), PIL.Image.LANCZOS
                        ).save(png_path, format="PNG")
                    except Exception:
                        png_path = ico_path  # fallback to .ico

                icon_line = f"Icon={png_path}\n" if png_path.exists() else ""
                desk = desktop / "J.A.R.V.I.S.desktop"
                desk.write_text(
                    "[Desktop Entry]\n"
                    "Name=J.A.R.V.I.S\n"
                    f"Exec={python} {script}\n"
                    f"Path={script.parent}\n"
                    "Type=Application\n"
                    "Terminal=false\n"
                    "Categories=Utility;\n"
                    + icon_line
                )
                desk.chmod(desk.stat().st_mode | 0o755)

            self._log.append_log("SYS: Desktop shortcut created.")
        except Exception as e:
            self._log.append_log(f"ERR: Shortcut failed — {e}")

    def _toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cw = self.centralWidget()
        if self._overlay and self._overlay.isVisible():
            ow, oh = 460, 390
            self._overlay.setGeometry(
                (cw.width()  - ow) // 2,
                (cw.height() - oh) // 2,
                ow, oh,
            )
        if self._remote_overlay and self._remote_overlay.isVisible():
            ow, oh = RemoteKeyOverlay._OW, RemoteKeyOverlay._OH
            self._remote_overlay.setGeometry(
                (cw.width()  - ow) // 2,
                (cw.height() - oh) // 2,
                ow, oh,
            )
        # Camera preview — bottom-right corner of the center/HUD area
        pw = _CameraPreview._W
        ph = self._cam_preview.height() or _CameraPreview._H
        self._cam_preview.setGeometry(
            cw.width() - _RIGHT_W - pw - 12,
            cw.height() - ph - 28,
            pw, ph,
        )

    def _update_metrics(self):
        snap = _metrics.snapshot()

        # CPU
        cpu = snap["cpu"]
        self._bar_cpu.set_value(cpu, f"{cpu:.0f}%")

        # MEM
        mem = snap["mem"]
        self._bar_mem.set_value(mem, f"{mem:.0f}%")

        # NET
        net = snap["net"]
        if net < 1.0:
            net_str = f"{net*1024:.0f}KB/s"
        else:
            net_str = f"{net:.1f}MB/s"
        net_pct = min(100, net * 10)  # 10 MB/s = %100
        self._bar_net.set_value(net_pct, net_str)

        # GPU
        gpu = snap["gpu"]
        if gpu >= 0:
            self._bar_gpu.set_value(gpu, f"{gpu:.0f}%")
        else:
            self._bar_gpu.set_value(0, "N/A")

        # TMP
        tmp = snap["tmp"]
        if tmp >= 0:
            tmp_pct = min(100, (tmp / 100) * 100)
            self._bar_tmp.set_value(tmp_pct, f"{tmp:.0f}°C")
        else:
            self._bar_tmp.set_value(0, "N/A")

        try:
            boot_t  = psutil.boot_time()
            elapsed = time.time() - boot_t
            h = int(elapsed // 3600)
            m = int((elapsed % 3600) // 60)
            self._uptime_lbl.setText(f"UP  {h:02d}:{m:02d}")
        except Exception:
            self._uptime_lbl.setText("UP  --:--")

        try:
            proc_count = len(psutil.pids())
            self._proc_lbl.setText(f"PROC  {proc_count}")
        except Exception:
            self._proc_lbl.setText("PROC  --")


    def _build_header(self) -> QWidget:
        w = QWidget()
        w.setObjectName("Mk2Header")
        w.setFixedHeight(78)
        w.setStyleSheet(f"""
            QWidget#Mk2Header {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {C.DARK}, stop:0.5 {C.PANEL}, stop:1 {C.DARK});
                border-bottom: 1px solid {C.BORDER_B};
            }}
        """)
        lay = QHBoxLayout(w)
        lay.setContentsMargins(28, 0, 28, 0)
        lay.setSpacing(12)

        brand = QVBoxLayout(); brand.setSpacing(1)
        title = QLabel("JARVIS / MARK LI")
        title.setFont(display_font(13, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {C.WHITE}; background: transparent;")
        brand.addWidget(title)
        descriptor = QLabel("COMPOSITION SYSTEM  ·  MK II")
        descriptor.setFont(mono_font(6, QFont.Weight.DemiBold))
        descriptor.setStyleSheet(f"color: {C.PRI}; background: transparent; letter-spacing: 1px;")
        brand.addWidget(descriptor)
        lay.addLayout(brand)

        lay.addStretch()
        self._header_tabs: dict[str, QPushButton] = {}
        for label in ("CORE", "STUDY", "MEMORY", "GEO", "CONTEXT", "SYSTEM"):
            key = label.lower()
            tab = QPushButton(label)
            tab.setFont(mono_font(7, QFont.Weight.DemiBold))
            tab.setFixedSize(68, 30)
            tab.setCheckable(True)
            tab.setCursor(Qt.CursorShape.PointingHandCursor)
            tab.setToolTip({
                "core": "Return to the animated core",
                "study": "Open the scientific Study workspace",
                "memory": "Explore the local Obsidian and JARVIS memory graph",
                "geo": "Open the holographic geographic workspace",
                "context": "Open the current context workspace",
                "system": "Toggle live system telemetry",
            }[key])
            tab.setStyleSheet(f"""
                QPushButton {{
                    color: {C.TEXT_DIM}; background: transparent; border: none;
                    border-bottom: 1px solid {C.BORDER}; padding-top: 2px;
                }}
                QPushButton:hover {{ color: {C.TEXT}; border-bottom-color: {C.PRI_DIM}; }}
                QPushButton:checked {{ color: {C.PRI}; border-bottom: 2px solid {C.PRI}; }}
                QPushButton:pressed {{ color: {C.WHITE}; background: {C.PRI_GHO}; }}
            """)
            tab.clicked.connect(lambda _checked=False, view=key: self._select_header_view(view))
            self._header_tabs[key] = tab
            lay.addWidget(tab)
        self._set_header_tab("core")
        lay.addStretch()

        self._state_chip_lbl = QLabel("CORE / DORMANT")
        self._state_chip_lbl.setFont(mono_font(7, QFont.Weight.DemiBold))
        self._state_chip_lbl.setStyleSheet(
            f"color: {C.PRI}; background: {C.PANEL}; border: 1px solid {C.BORDER}; "
            "border-radius: 10px; padding: 4px 10px;"
        )
        lay.addWidget(self._state_chip_lbl)

        clock = QVBoxLayout(); clock.setSpacing(0)
        self._clock_lbl = QLabel("00:00:00")
        self._clock_lbl.setFont(mono_font(12, QFont.Weight.DemiBold))
        self._clock_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._clock_lbl.setStyleSheet(f"color: {C.WHITE}; background: transparent;")
        clock.addWidget(self._clock_lbl)
        self._date_lbl = QLabel("")
        self._date_lbl.setFont(mono_font(6))
        self._date_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._date_lbl.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        clock.addWidget(self._date_lbl)
        lay.addLayout(clock)
        return w

    def _set_header_tab(self, active: str) -> None:
        """Keep the top navigation visually aligned with the visible workspace."""
        for name, button in self._header_tabs.items():
            button.setChecked(name == active)

    def _select_header_view(self, view: str) -> None:
        """Navigate between the real Core, Context and System workspaces."""
        if view == "system":
            self._animate_system_panel(not self._system_open)
            self._set_header_tab(
                "system" if self._system_open else ("context" if self.hud.context_active else "core")
            )
            return

        if self._system_open:
            self._animate_system_panel(False)

        if view == "memory":
            self.show_memory_graph()
            return

        if view == "study":
            self.show_study_workspace()
            return

        if view == "geo":
            self.show_geo_workspace()
            return

        if view == "context":
            if self.hud.camera_active:
                self.stop_camera_stream()
            self._hud_cam_stack.setCurrentIndex(0)
            if self.hud.show_context_workspace():
                if self._right_panel.isVisible():
                    self._animate_side_panel(False)
                self._active_v1_panel = None
                self._set_v1_button_state(None)
            else:
                self._toggle_v1_panel("files")
            self._set_header_tab("context")
            return

        if self.hud.camera_active:
            self.stop_camera_stream()
        self._hud_cam_stack.setCurrentIndex(0)
        self.hud.show_core()
        if self._right_panel.isVisible():
            self._animate_side_panel(False)
        if self._content_panel.isVisible():
            self._content_panel.hide()
        self._active_v1_panel = None
        self._set_v1_button_state(None)
        self._set_header_tab("core")

    def _show_central_workspace(self, index: int, header: str) -> None:
        if self.hud.camera_active:
            self.stop_camera_stream()
        if self._content_panel.isVisible():
            self._content_panel.hide()
        if self._right_panel.isVisible():
            self._animate_side_panel(False)
        self._active_v1_panel = header
        self._hud_cam_stack.setCurrentIndex(index)
        self._set_v1_button_state(header)
        self._set_header_tab(header)

    def show_memory_graph(self) -> None:
        self._show_central_workspace(2, "memory")
        self._memory_workspace.refresh()

    def show_geo_workspace(self) -> None:
        self._show_central_workspace(3, "geo")

    def show_study_workspace(self) -> None:
        self._show_central_workspace(4, "study")
        self._study_workspace.restore_latest()

    def _locate_geo_query(self, query: str) -> None:
        def resolve() -> None:
            try:
                from actions.open_geo import OpenGeoClient

                place = OpenGeoClient().resolve_place(query)
                self._geo_focus_sig.emit(
                    float(place["latitude"]), float(place["longitude"]),
                    str(place.get("name") or query),
                )
            except Exception as exc:
                self._log_sig.emit(f"GEO: {exc}")

        threading.Thread(target=resolve, daemon=True, name="jarvis-geo-lookup").start()

    def _apply_geo_focus(self, latitude: float, longitude: float, label: str) -> None:
        self._geo_workspace.focus_location(latitude, longitude, label)
        self._log_sig.emit(f"GEO: Focused {label} ({latitude:.4f}, {longitude:.4f}).")

    def _show_workspace_request(self, name: str, payload: object) -> None:
        data = payload if isinstance(payload, dict) else {}
        if name == "memory":
            self.show_memory_graph()
        elif name == "memory_refresh":
            self._memory_workspace.refresh()
        elif name == "geo":
            self.show_geo_workspace()
            if data.get("latitude") is not None and data.get("longitude") is not None:
                self._apply_geo_focus(
                    float(data["latitude"]), float(data["longitude"]),
                    str(data.get("label", "Location")),
                )
            if data.get("path"):
                self._geo_workspace.show_route(data["path"])
        elif name == "study":
            self.show_study_workspace()

    def _show_study_request(self, request: object) -> None:
        """Store a Study artifact and reveal it only when the caller requests it."""
        if not isinstance(request, dict):
            return
        event = request.get("event")
        try:
            artifact = request.get("artifact")
            automatic = bool(request.get("automatic", True))
            opening = not automatic or (
                request.get("surface_mode") == "main"
                and self.isVisible()
                and not self.isMinimized()
            )
            if isinstance(artifact, dict):
                self._study_workspace.set_artifact(artifact, pending=not opening)
            if opening:
                self.show_study_workspace()
                result = "Study workspace opened with the latest result."
            else:
                result = "Study result stored without opening the application."
            request["result"] = result
        except Exception as exc:
            request["error"] = f"Study display failed: {exc}"
        finally:
            if event is not None:
                event.set()

    def _set_side_workspace(self, panel: str, opening: bool) -> str:
        if panel not in {"chat", "files"}:
            raise ValueError(f"Unknown side workspace: {panel}")
        already_open = self._right_panel.isVisible() and self._active_v1_panel == panel
        if opening and not already_open:
            self._active_v1_panel = panel
            self._show_panel_view(panel)
            self._set_v1_button_state(panel)
            self._animate_side_panel(True)
            if panel == "chat":
                self._input.setFocus(Qt.FocusReason.ShortcutFocusReason)
            else:
                self._drop_zone.setFocus(Qt.FocusReason.ShortcutFocusReason)
        elif not opening and already_open:
            self._active_v1_panel = None
            self._set_v1_button_state(None)
            self._animate_side_panel(False)
        state = "open" if opening else "closed"
        return f"{panel.title()} workspace {state}."

    def _interface_status(self, surface_mode: str = "main") -> dict:
        index = self._hud_cam_stack.currentIndex()
        workspace = {0: "core", 1: "camera", 2: "memory", 3: "geo", 4: "study"}.get(index, "core")
        if self.hud.camera_active:
            workspace = "camera"
        elif self.hud.context_active and index == 0:
            workspace = "context"
        return {
            "surface": surface_mode,
            "workspace": workspace,
            "side_panel": self._active_v1_panel if self._right_panel.isVisible() else None,
            "system_panel": self._system_open,
            "camera_active": self.hud.camera_active,
            "camera_mode": self._camera_mode,
            "fullscreen": self.isFullScreen(),
            "listening_mode": self._listen_mode,
            "microphone_enabled": self._listen_mode == "always" or self._talk_enabled,
        }

    def _execute_interface_request(self, request: object) -> None:
        """Execute one verified voice/UI command on Qt's owning thread."""
        if not isinstance(request, dict):
            return
        event = request.get("event")
        try:
            action = str(request.get("action", "open")).lower().strip()
            target = str(request.get("target", "status")).lower().strip()
            mode = str(request.get("mode", "")).lower().strip()
            aliases = {
                "map": "geo", "maps": "geo", "globe": "geo",
                "conversation": "chat", "conversation_panel": "chat",
                "file": "files", "documents": "files",
                "memories": "memory", "knowledge": "memory",
                "science": "study", "school": "study", "estudio": "study",
                "telemetry": "system", "metrics": "system",
                "main": "app", "application": "app", "jarvis": "app",
                "results": "content", "result": "content",
                "mic": "listening", "microphone": "listening",
            }
            target = aliases.get(target, target)

            # Any concrete workspace request made while the desktop pet is
            # active first restores the main surface, just as clicking the pet
            # does. The same voice session and MainWindow instance are kept.
            surface_mode = str(request.get("surface_mode", "main"))
            if surface_mode == "pet" and target not in {"pet", "status"}:
                self._main_mode_sig.emit()

            if action == "status" or target == "status":
                result = self._interface_status(surface_mode)
            elif target == "pet":
                closing = action == "close" or (action == "toggle" and surface_mode == "pet")
                if closing:
                    self._main_mode_sig.emit()
                    result = "Main JARVIS application restored from Pet Mode."
                else:
                    self._pet_mode_sig.emit(self.hud.state, "Pet Mode active.")
                    result = "Pet Mode activated; the current voice session remains active."
            elif target == "app":
                self._main_mode_sig.emit()
                result = "Main JARVIS application opened."
            elif target in {"chat", "files"}:
                opening = action != "close"
                if action == "toggle":
                    opening = not (
                        self._right_panel.isVisible() and self._active_v1_panel == target
                    )
                result = self._set_side_workspace(target, opening)
            elif target == "core":
                self._select_header_view("core")
                result = "Core workspace opened."
            elif target == "context":
                if action == "close":
                    self._select_header_view("core")
                    result = "Context workspace closed; Core workspace opened."
                else:
                    self._select_header_view("context")
                    result = (
                        "Context workspace opened." if self.hud.context_active
                        else "No visual context is attached; Files workspace opened instead."
                    )
            elif target == "system":
                opening = action != "close"
                if action == "toggle":
                    opening = not self._system_open
                if self._system_open != opening:
                    self._animate_system_panel(opening)
                self._set_header_tab("system" if opening else "core")
                result = f"System telemetry panel {'opened' if opening else 'closed'}."
            elif target == "memory":
                if action == "close":
                    self._select_header_view("core")
                    result = "Memory graph closed; Core workspace opened."
                else:
                    self.show_memory_graph()
                    result = "Interactive memory graph opened and reindexed."
            elif target == "study":
                if action == "close":
                    self._select_header_view("core")
                    result = "Study workspace closed; Core workspace opened."
                else:
                    self.show_study_workspace()
                    result = "Study workspace opened with the latest result."
            elif target == "geo":
                if action == "close":
                    self._select_header_view("core")
                    result = "Geographic workspace closed; Core workspace opened."
                else:
                    self.show_geo_workspace()
                    result = "Geographic workspace opened."
            elif target in {"live_map", "map_mode"}:
                if action == "close":
                    self._select_header_view("core")
                    result = "Map workspace closed; Core workspace opened."
                elif mode in {"holo", "holographic", "offline"}:
                    self.show_geo_workspace()
                    self._geo_workspace.show_offline()
                    result = "Holographic globe mode opened."
                else:
                    self.show_geo_workspace()
                    self._geo_workspace.show_open_map()
                    result = "Live open-data map mode opened."
            elif target == "camera":
                closing = action == "close" or (action == "toggle" and self.hud.camera_active)
                if closing:
                    self.stop_camera_stream()
                    result = "Camera stream closed."
                else:
                    self.start_camera_stream()
                    result = "Camera stream started without AI analysis."
            elif target == "content":
                opening = action != "close"
                if action == "toggle":
                    opening = not self._content_panel.isVisible()
                self._content_panel.setVisible(opening)
                result = f"Result panel {'opened' if opening else 'closed'}."
            elif target == "fullscreen":
                desired = action != "close"
                if action == "toggle":
                    desired = not self.isFullScreen()
                if desired and not self.isFullScreen():
                    self.showFullScreen()
                elif not desired and self.isFullScreen():
                    self.showNormal()
                result = f"Fullscreen mode {'enabled' if desired else 'disabled'}."
            elif target == "listening":
                desired = "toggle" if mode in {"toggle", "push_to_talk", "standby"} else "always"
                if self._listen_mode != desired:
                    self._toggle_listen_mode()
                result = (
                    "Always Listening mode enabled." if desired == "always"
                    else "Toggle to Speak enabled; microphone is now in standby until backslash is pressed."
                )
            elif target == "interrupt":
                self._do_interrupt()
                result = "Current speech or operation interrupted."
            else:
                raise ValueError(f"Unsupported interface target: {target}")
            request["result"] = result
        except Exception as exc:
            request["error"] = f"Interface command failed: {exc}"
        finally:
            if event is not None:
                event.set()

    def _discard_animation(self, attribute: str) -> None:
        """Stop and release an in-flight UI transition.

        Qt animations parented to the main window otherwise survive after they
        finish.  Repeated fast navigation then accumulates animation objects and
        lets stale ``finished`` callbacks hide a panel that has since reopened.
        """
        animation = getattr(self, attribute, None)
        if animation is None:
            return
        setattr(self, attribute, None)
        try:
            animation.stop()
            animation.finished.disconnect()
            animation.deleteLater()
        except RuntimeError:
            # The underlying Qt object may already be queued for deletion.
            pass

    def _animate_system_panel(self, opening: bool) -> None:
        """Reveal the telemetry rail without replacing or resizing the core abruptly."""
        self._system_open = opening
        self._discard_animation("_system_animation")
        if self.hud.speaking:
            self._left_panel.setMaximumWidth(_LEFT_W if opening else 0)
            self._left_panel.setVisible(opening)
            return
        if opening:
            self._left_panel.show()
        animation = QPropertyAnimation(self._left_panel, b"maximumWidth", self)
        animation.setDuration(Motion.PANEL)
        animation.setStartValue(self._left_panel.maximumWidth())
        animation.setEndValue(_LEFT_W if opening else 0)
        animation.setEasingCurve(
            QEasingCurve.Type.OutCubic if opening else QEasingCurve.Type.InCubic
        )
        self._system_animation = animation
        animation.finished.connect(
            lambda: self._finish_system_animation(animation, opening)
        )
        animation.start()

    def _finish_system_animation(
        self, animation: QPropertyAnimation, opening: bool
    ) -> None:
        if self._system_animation is not animation:
            return
        if not opening:
            self._left_panel.hide()
        self._system_animation = None
        animation.deleteLater()

    def _build_control_bar(self) -> QWidget:
        """Minimal V1 navigation that keeps the animated core central."""
        bar = QWidget()
        bar.setObjectName("Mk2ControlBar")
        bar.setFixedHeight(92)
        bar.setStyleSheet(f"""
            QWidget#Mk2ControlBar {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {C.DARK}, stop:0.5 {C.PANEL}, stop:1 {C.DARK});
                border-top: 1px solid {C.BORDER_B};
            }}
        """)
        row = QHBoxLayout(bar)
        row.setContentsMargins(28, 10, 28, 10)
        row.setSpacing(12)

        left_status = QLabel("LOCAL CORE\nSECURE SESSION")
        left_status.setFont(mono_font(6, QFont.Weight.DemiBold))
        left_status.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent; line-height: 1.3;")
        row.addWidget(left_status)
        row.addStretch()

        def _button(symbol: str, label: str, callback) -> SymbolButton:
            group = QWidget()
            group.setStyleSheet("background: transparent;")
            column = QVBoxLayout(group)
            column.setContentsMargins(0, 0, 0, 0)
            column.setSpacing(3)
            button = SymbolButton(symbol, label)
            button.clicked.connect(callback)
            column.addWidget(button, 0, Qt.AlignmentFlag.AlignHCenter)
            caption = QLabel(label.upper())
            caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
            caption.setFont(mono_font(6, QFont.Weight.DemiBold))
            caption.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
            column.addWidget(caption)
            row.addWidget(group)
            return button

        self._v1_chat_btn = _button("chat", "Chat", lambda: self._toggle_v1_panel("chat"))
        self._v1_files_btn = _button("file", "Files", lambda: self._toggle_v1_panel("files"))
        self._v1_camera_btn = _button("camera", "Camera", self._toggle_v1_camera)
        self._v1_memory_btn = _button("brain", "Memory", self.show_memory_graph)
        self._v1_geo_btn = _button("globe", "Geo", self.show_geo_workspace)
        self._v1_study_btn = _button("study", "Study", self.show_study_workspace)
        self._v1_pet_btn = _button("pet", "Pet Mode", self._request_pet_mode)
        # Pet is a surface transition, not a persistent workspace selection.
        self._v1_pet_btn.setCheckable(False)

        row.addStretch()
        right_status = QLabel("VOICE READY\nDOUBLE-ESC TO INTERRUPT")
        right_status.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        right_status.setFont(mono_font(6, QFont.Weight.DemiBold))
        right_status.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        row.addWidget(right_status)
        return bar

    def _request_pet_mode(self) -> None:
        """Request the App → Pet handoff from the visible navigation."""
        self._pet_mode_sig.emit(self.hud.state, "Pet Mode active.")

    def _toggle_v1_panel(self, panel: str) -> None:
        """Open lightweight V1 overlays without replacing the central core."""
        if panel == "memory":
            self.show_memory_graph()
            return

        if panel in {"chat", "files"}:
            opening = not self._right_panel.isVisible() or self._active_v1_panel != panel
            self._active_v1_panel = panel if opening else None
            self._set_v1_button_state(panel if opening else None)
            if opening:
                self._show_panel_view(panel)
            self._animate_side_panel(opening)
            if opening:
                if panel == "chat":
                    self._input.setFocus(Qt.FocusReason.ShortcutFocusReason)
                else:
                    self._drop_zone.setFocus(Qt.FocusReason.ShortcutFocusReason)
            return

    def _show_panel_view(self, panel: str) -> None:
        index = 0 if panel == "chat" else 1
        self._panel_stack.setCurrentIndex(index)
        self._panel_title_lbl.setText("CONVERSATION" if panel == "chat" else "FILES")
        self._panel_subtitle_lbl.setText(
            "HISTORY AND TEXT INPUT" if panel == "chat"
            else "ATTACH CONTEXT FOR JARVIS"
        )

    def _set_v1_button_state(self, active: str | None) -> None:
        mapping = {
            "chat": self._v1_chat_btn,
            "files": self._v1_files_btn,
            "camera": self._v1_camera_btn,
            "memory": self._v1_memory_btn,
            "geo": self._v1_geo_btn,
            "study": self._v1_study_btn,
        }
        for name, button in mapping.items():
            button.setChecked(self.hud.camera_active if name == "camera" else name == active)

    def _animate_side_panel(self, opening: bool) -> None:
        self._discard_animation("_panel_motion")
        self._panel_animation = None
        if self.hud.speaking:
            self._right_panel.setMaximumWidth(_RIGHT_W if opening else 0)
            self._panel_opacity.setOpacity(1.0 if opening else 0.0)
            self._right_panel.setVisible(opening)
            return
        if opening:
            self._right_panel.show()
        start = self._right_panel.maximumWidth()
        end = _RIGHT_W if opening else 0
        animation = QPropertyAnimation(self._right_panel, b"maximumWidth", self)
        animation.setDuration(Motion.PANEL + 40)
        animation.setStartValue(start)
        animation.setEndValue(end)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic if opening else QEasingCurve.Type.InCubic)
        fade = QPropertyAnimation(self._panel_opacity, b"opacity", self)
        fade.setDuration(Motion.PANEL - 60)
        fade.setStartValue(self._panel_opacity.opacity())
        fade.setEndValue(1.0 if opening else 0.0)
        fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        motion = QParallelAnimationGroup(self)
        motion.addAnimation(animation)
        motion.addAnimation(fade)
        self._panel_animation = animation
        self._panel_motion = motion
        motion.finished.connect(lambda: self._finish_side_animation(motion, opening))
        motion.start()

    def _finish_side_animation(
        self, motion: QParallelAnimationGroup, opening: bool
    ) -> None:
        if self._panel_motion is not motion:
            return
        if not opening:
            self._right_panel.hide()
        self._panel_motion = None
        self._panel_animation = None
        motion.deleteLater()

    def _animate_memory_panel(self, opening: bool) -> None:
        self._discard_animation("_memory_animation")
        if self.hud.speaking:
            self._content_panel.setMaximumHeight(230 if opening else 0)
            self._content_panel.setVisible(opening)
            return
        if opening:
            self._content_panel.show()
        animation = QPropertyAnimation(self._content_panel, b"maximumHeight", self)
        animation.setDuration(Motion.PANEL)
        animation.setStartValue(0 if opening else self._content_panel.height())
        animation.setEndValue(230 if opening else 0)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic if opening else QEasingCurve.Type.InCubic)
        self._memory_animation = animation
        animation.finished.connect(
            lambda: self._finish_memory_animation(animation, opening)
        )
        animation.start()

    def _finish_memory_animation(
        self, animation: QPropertyAnimation, opening: bool
    ) -> None:
        if self._memory_animation is not animation:
            return
        if not opening:
            self._content_panel.hide()
        self._memory_animation = None
        animation.deleteLater()

    def _toggle_v1_camera(self) -> None:
        if self.hud.camera_active:
            self.stop_camera_stream()
            self._v1_camera_btn.setChecked(False)
        else:
            self._show_camera_selector()

    def _detect_camera_indices(self) -> list[int]:
        """Return camera indices that OpenCV can actually open."""
        try:
            import cv2
        except Exception:
            return []
        found = []
        backend = cv2.CAP_DSHOW if _OS == "Windows" else cv2.CAP_ANY
        for index in range(6):
            cap = cv2.VideoCapture(index, backend)
            try:
                if cap.isOpened():
                    ok, _ = cap.read()
                    if ok:
                        found.append(index)
            finally:
                cap.release()
        return found

    def _show_camera_selector(self) -> None:
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background: {C.PANEL}; color: {C.WHITE};
                border: 1px solid {C.BORDER_B}; padding: 6px;
            }}
            QMenu::item {{ padding: 8px 24px 8px 12px; border-radius: 6px; }}
            QMenu::item:selected {{ background: {C.PRI_GHO}; color: {C.PRI}; }}
        """)
        indices = self._detect_camera_indices()
        current = 0
        try:
            current = int(get_settings().extras.get("camera_index", 0))
        except (TypeError, ValueError):
            pass
        if not indices:
            action = menu.addAction("No available cameras detected")
            action.setEnabled(False)
        for index in indices:
            suffix = "  ·  CURRENT" if index == current else ""
            action = menu.addAction(f"Camera {index}{suffix}")
            action.triggered.connect(
                lambda _checked=False, selected=index: self._select_camera(selected)
            )
        menu.exec(self._v1_camera_btn.mapToGlobal(self._v1_camera_btn.rect().topLeft()))

    def _select_camera(self, index: int) -> None:
        try:
            update_settings({"camera_index": int(index)})
        except Exception as exc:
            self._log.append_log(f"CAMERA: could not save the device ({exc})")
        self._set_v1_button_state("camera")
        self.start_camera_stream()

    def _tick_clock(self):
        self._clock_lbl.setText(time.strftime("%H:%M:%S"))
        self._date_lbl.setText(time.strftime("%a %d %b %Y"))

    def _build_left_panel(self) -> QWidget:
        w = HolographicSurface("left")
        w.setMinimumWidth(0)
        w.setMaximumWidth(_LEFT_W)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(14, 16, 14, 14)
        lay.setSpacing(8)

        hdr = QLabel("SYS MONITOR  /  LIVE")
        hdr.setFont(mono_font(8, QFont.Weight.Bold))
        hdr.setStyleSheet(f"color: {C.PRI}; background: transparent; "
                          f"border-bottom: 1px solid {C.BORDER_B}; padding: 0 0 8px 5px;")
        lay.addWidget(hdr)
        lay.addSpacing(2)

        self._bar_cpu = MetricBar("CPU", C.PRI)
        self._bar_mem = MetricBar("MEM", C.ACC2)
        self._bar_net = MetricBar("NET", C.GREEN)
        self._bar_gpu = MetricBar("GPU", C.ACC)
        self._bar_tmp = MetricBar("TMP", "#ff6688")

        for bar in [self._bar_cpu, self._bar_mem, self._bar_net,
                    self._bar_gpu, self._bar_tmp]:
            lay.addWidget(bar)

        lay.addSpacing(4)

        info_panel = QWidget()
        info_panel.setStyleSheet(
            f"background: rgba(4, 23, 31, 225); border: 1px solid {C.BORDER_B}; "
            f"border-left: 2px solid {C.PRI_DIM}; border-radius: 8px;"
        )
        ip_lay = QVBoxLayout(info_panel)
        ip_lay.setContentsMargins(6, 5, 6, 5)
        ip_lay.setSpacing(3)

        self._uptime_lbl = QLabel("UP  --:--")
        self._uptime_lbl.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self._uptime_lbl.setStyleSheet(f"color: {C.GREEN}; background: transparent; border: none;")
        ip_lay.addWidget(self._uptime_lbl)

        self._proc_lbl = QLabel("PROC  --")
        self._proc_lbl.setFont(QFont("Courier New", 8))
        self._proc_lbl.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent; border: none;")
        ip_lay.addWidget(self._proc_lbl)

        os_name = {"Windows": "WIN", "Darwin": "macOS", "Linux": "LINUX"}.get(_OS, _OS.upper())
        os_lbl = QLabel(f"OS  {os_name}")
        os_lbl.setFont(QFont("Courier New", 8))
        os_lbl.setStyleSheet(f"color: {C.ACC2}; background: transparent; border: none;")
        ip_lay.addWidget(os_lbl)

        lay.addWidget(info_panel)
        lay.addSpacing(4)

        lay.addStretch()

        for txt, col in [
            ("AI CORE\nACTIVE",     C.GREEN),
            ("SEC\nCLEARED",        C.PRI),
            ("PROTOCOL\nMARK LI",   C.TEXT_DIM),
        ]:
            lbl = QLabel(txt)
            lbl.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet(
                f"color: {col}; background: rgba(4, 23, 31, 225);"
                f"border: 1px solid {C.BORDER_A}; border-radius: 7px; padding: 7px;"
            )
            lay.addWidget(lbl)

        return w
    def _build_right_panel(self) -> QWidget:
        w = HolographicSurface("right")
        w.setMinimumWidth(0)
        w.setMaximumWidth(_RIGHT_W)
        self._panel_opacity = QGraphicsOpacityEffect(w)
        self._panel_opacity.setOpacity(0.0)
        w.setGraphicsEffect(self._panel_opacity)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(10)

        self._panel_title_lbl = QLabel("CONVERSATION")
        self._panel_title_lbl.setFont(display_font(14, QFont.Weight.Bold))
        self._panel_title_lbl.setStyleSheet(f"color: {C.WHITE}; background: transparent;")
        lay.addWidget(self._panel_title_lbl)
        self._panel_subtitle_lbl = QLabel("HISTORY AND TEXT INPUT")
        self._panel_subtitle_lbl.setFont(mono_font(7, QFont.Weight.DemiBold))
        self._panel_subtitle_lbl.setStyleSheet(f"color: {C.PRI_DIM}; letter-spacing: 1px;")
        lay.addWidget(self._panel_subtitle_lbl)

        session_rail = QHBoxLayout()
        session_rail.setSpacing(6)
        for text, tone in (("CHANNEL 01", C.PRI), ("ENCRYPTED", C.GREEN), ("LIVE", C.ACC)):
            chip = QLabel(text)
            chip.setFont(mono_font(6, QFont.Weight.DemiBold))
            chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
            chip.setStyleSheet(
                f"color: {tone}; background: {C.PRI_GHO}; border: 1px solid {C.BORDER}; "
                "border-radius: 7px; padding: 4px 7px;"
            )
            session_rail.addWidget(chip)
        session_rail.addStretch()
        lay.addLayout(session_rail)

        self._panel_stack = QStackedWidget()
        self._panel_stack.setStyleSheet("background: transparent; border: none;")

        chat = QWidget()
        chat.setStyleSheet("background: transparent;")
        chat_lay = QVBoxLayout(chat)
        chat_lay.setContentsMargins(0, 4, 0, 0)
        chat_lay.setSpacing(9)
        self._log = LogWidget()
        chat_lay.addWidget(self._log, stretch=1)
        chat_lay.addLayout(self._build_input_row())

        self._interrupt_btn = QPushButton("INTERRUPT  ·  ESC")
        self._interrupt_btn.setFixedHeight(38)
        self._interrupt_btn.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        self._interrupt_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._interrupt_btn.setStyleSheet(f"""
            QPushButton {{ background: #140008; color: {C.MUTED_C};
                border: 1px solid {C.MUTED_C}; border-radius: 9px; }}
            QPushButton:hover {{ background: #200010; color: #ff6688; }}
        """)
        self._interrupt_btn.clicked.connect(self._do_interrupt)
        chat_lay.addWidget(self._interrupt_btn)
        self._panel_stack.addWidget(chat)

        files = QWidget()
        files.setStyleSheet("background: transparent;")
        files_lay = QVBoxLayout(files)
        files_lay.setContentsMargins(0, 12, 0, 0)
        files_lay.setSpacing(12)
        files_intro = QLabel(
            "Images, documents, audio, and code appear as visual context "
            "without replacing the Jarvis core."
        )
        files_intro.setWordWrap(True)
        files_intro.setFont(QFont("Segoe UI", 9))
        files_intro.setStyleSheet(f"color: {C.TEXT_MED}; line-height: 1.4;")
        files_lay.addWidget(files_intro)
        file_types = QHBoxLayout()
        file_types.setSpacing(5)
        for label in ("IMAGE", "DOC", "AUDIO", "CODE"):
            badge = QLabel(label)
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setFont(mono_font(6, QFont.Weight.DemiBold))
            badge.setStyleSheet(
                f"color: {C.PRI_DIM}; background: {C.PRI_GHO}; border: 1px solid {C.BORDER}; "
                "border-radius: 6px; padding: 3px 5px;"
            )
            file_types.addWidget(badge)
        files_lay.addLayout(file_types)
        self._drop_zone = FileDropZone()
        self._drop_zone.file_selected.connect(self._on_file_selected)
        files_lay.addWidget(self._drop_zone)

        self._file_hint = QLabel("No files attached yet")
        self._file_hint.setFont(QFont("Segoe UI", 8))
        self._file_hint.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
        self._file_hint.setWordWrap(True)
        files_lay.addWidget(self._file_hint)
        files_lay.addStretch()
        self._panel_stack.addWidget(files)
        lay.addWidget(self._panel_stack, stretch=1)

        self._mute_btn = QPushButton("LISTENING MODE")
        self._mute_btn.setFixedHeight(34)
        self._mute_btn.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        self._mute_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mute_btn.clicked.connect(self._toggle_listen_mode)
        self._style_mute_btn()
        lay.addWidget(self._mute_btn)

        return w

    def _build_input_row(self) -> QHBoxLayout:
        row = QHBoxLayout(); row.setSpacing(5)
        self._input = QLineEdit()
        self._input.setPlaceholderText("Message Jarvis…")
        self._input.setFont(QFont("Segoe UI", 9))
        self._input.setFixedHeight(38)
        self._input.setStyleSheet(f"""
            QLineEdit {{
                background: rgba(1, 13, 20, 232); color: {C.WHITE};
                border: 1px solid {C.BORDER_B}; border-left: 2px solid {C.PRI_DIM};
                border-radius: 10px; padding: 5px 12px;
            }}
            QLineEdit:focus {{ border: 1px solid {C.PRI}; border-left: 2px solid {C.PRI}; }}
        """)
        self._input.returnPressed.connect(self._send)
        row.addWidget(self._input)

        send = QPushButton("▸")
        send.setFixedSize(38, 38)
        send.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        send.setCursor(Qt.CursorShape.PointingHandCursor)
        send.setStyleSheet(f"""
            QPushButton {{
                background: {C.PRI_GHO}; color: {C.PRI};
                border: 1px solid {C.PRI}; border-radius: 10px;
            }}
            QPushButton:hover {{ background: {C.PANEL2}; color: {C.WHITE}; }}
        """)
        send.clicked.connect(self._send)
        row.addWidget(send)
        return row

    def _build_content_panel(self) -> QWidget:
        """
        Collapsible panel below the HUD — shows search results, news, briefings.
        Hidden by default; appears when show_content() is called.
        """
        w = HolographicSurface("full")
        w.setObjectName("ContentPanel")
        w.hide()

        lay = QVBoxLayout(w)
        lay.setContentsMargins(20, 12, 20, 14)
        lay.setSpacing(8)

        # ── header row ───────────────────────────────────────────────────────
        hdr = QHBoxLayout(); hdr.setSpacing(6)

        dot = QLabel("◈")
        dot.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        dot.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        hdr.addWidget(dot)

        self._content_title_lbl = QLabel("BRIEFING")
        self._content_title_lbl.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self._content_title_lbl.setStyleSheet(
            f"color: {C.PRI}; background: transparent; letter-spacing: 1px;"
        )
        hdr.addWidget(self._content_title_lbl)
        hdr.addStretch()

        self._content_ts_lbl = QLabel("")
        self._content_ts_lbl.setFont(QFont("Courier New", 7))
        self._content_ts_lbl.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        hdr.addWidget(self._content_ts_lbl)

        dismiss = QPushButton("DISMISS  ✕")
        dismiss.setFont(QFont("Courier New", 7))
        dismiss.setFixedHeight(18)
        dismiss.setCursor(Qt.CursorShape.PointingHandCursor)
        dismiss.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_DIM};
                border: 1px solid {C.BORDER}; border-radius: 2px; padding: 0 5px;
            }}
            QPushButton:hover {{ color: {C.TEXT}; border-color: {C.BORDER_B}; }}
        """)
        dismiss.clicked.connect(w.hide)
        hdr.addWidget(dismiss)
        lay.addLayout(hdr)

        # ── separator ─────────────────────────────────────────────────────────
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER};"); lay.addWidget(sep)

        memory_rail = QHBoxLayout()
        memory_rail.setSpacing(7)
        self._memory_chips: list[QPushButton] = []
        for label in ("IDENTITY", "PREFERENCES", "PROJECT", "LONG-TERM"):
            chip = QPushButton(label)
            chip.setEnabled(False)
            chip.setFont(mono_font(6, QFont.Weight.DemiBold))
            chip.setFixedHeight(24)
            chip.setStyleSheet(f"""
                QPushButton {{
                    color: {C.TEXT_MED}; background: {C.PRI_GHO};
                    border: 1px solid {C.BORDER}; border-radius: 7px; padding: 2px 9px;
                }}
                QPushButton:disabled {{ color: {C.TEXT_MED}; background: {C.PRI_GHO}; }}
            """)
            self._memory_chips.append(chip)
            memory_rail.addWidget(chip)
        memory_rail.addStretch()
        lay.addLayout(memory_rail)

        # ── text display ──────────────────────────────────────────────────────
        self._content_display = QTextEdit()
        self._content_display.setReadOnly(True)
        self._content_display.setFont(QFont("Courier New", 8))
        self._content_display.setMinimumHeight(60)
        self._content_display.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._content_display.setStyleSheet(f"""
            QTextEdit {{
                background: rgba(1, 9, 14, 228);
                color: {C.TEXT};
                border: 1px solid {C.BORDER_B};
                border-left: 2px solid {C.PRI_DIM};
                border-radius: 9px;
                padding: 10px 12px;
                selection-background-color: {C.PRI_GHO};
            }}
            QScrollBar:vertical {{
                background: {C.BG}; width: 6px; border: none;
            }}
            QScrollBar::handle:vertical {{
                background: {C.BORDER_B}; border-radius: 3px; min-height: 16px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0; border: none;
            }}
        """)
        lay.addWidget(self._content_display)

        return w

    def _show_content(self, title: str, text: str):
        """Route tool output to the V3 workspace; keep Memory in its panel."""
        import time as _time
        if title.strip().upper() not in {"MEMORY", "MEMORIA"}:
            image_path = None
            candidates = re.findall(
                r"([A-Za-z]:[\\/][^\n\r\"'|<>]+?\.(?:png|jpg|jpeg|webp))",
                text,
                flags=re.IGNORECASE,
            )
            for candidate in candidates:
                cleaned = candidate.strip().rstrip(".,;)")
                if Path(cleaned).is_file():
                    image_path = cleaned
                    break
            self.hud.set_context(title, text, image_path)
            self._set_header_tab("context")
            self._content_panel.hide()
            return

        self._content_title_lbl.setText(title.upper()[:48])
        self._content_ts_lbl.setText(_time.strftime("%H:%M:%S"))
        self._content_display.setPlainText(text)
        self._content_display.moveCursor(
            self._content_display.textCursor().MoveOperation.Start
        )
        first_show = not self._content_panel.isVisible()
        self._content_panel.show()
        if first_show:
            total = self._center_split.height()
            self._center_split.setSizes([max(total - 220, 120), 220])

    def _build_footer(self) -> QWidget:
        w = QWidget()
        w.setFixedHeight(30)
        w.setStyleSheet(
            f"background: {C.DARK}; border-top: 1px solid {C.BORDER_B}; "
            f"border-bottom: 1px solid {C.PRI_DIM};"
        )
        lay = QHBoxLayout(w); lay.setContentsMargins(28, 0, 28, 0)
        left = QLabel("VOICE  ·  VISION  ·  MEMORY")
        center = QLabel("MARK LI  /  LOCAL COMPOSITION")
        right = QLabel("SYSTEM ACTIVE")
        for label in (left, center, right):
            label.setFont(mono_font(6, QFont.Weight.DemiBold))
            label.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        left.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        center.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        right.setStyleSheet(f"color: {C.PRI_DIM}; background: transparent;")
        lay.addWidget(left, 1); lay.addWidget(center, 1); lay.addWidget(right, 1)
        return w

        w = QWidget()
        w.setFixedHeight(22)
        w.setStyleSheet(f"background: {C.DARK}; border-top: 1px solid {C.BORDER};")
        lay = QHBoxLayout(w); lay.setContentsMargins(14, 0, 14, 0)

        def _fl(txt, color=C.TEXT_MED):
            l = QLabel(txt); l.setFont(QFont("Segoe UI", 7))
            l.setStyleSheet(f"color: {color}; background: transparent;")
            return l

        left = _fl("[\\] Voice  ·  [F9] Mute  ·  [F11] Full screen")
        center = _fl("MARK LI  ·  LOCAL CORE  ·  SECURE")
        right = _fl("SYSTEM ACTIVE", C.PRI_DIM)
        left.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        center.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(left, stretch=1)
        lay.addWidget(center, stretch=1)
        lay.addWidget(right, stretch=1)
        return w

    def _on_file_selected(self, path: str):
        with self._tool_state_lock:
            self._current_file = path
        p    = Path(path)
        cat  = _file_category(p)
        icon, _ = _FILE_ICONS.get(cat, _FILE_ICONS["unknown"])
        size = _fmt_size(p.stat().st_size)
        self._file_hint.setText(f"{icon}  {p.name}  ·  {size}  ·  Tell JARVIS what to do with it")
        self._log.append_log(f"FILE: {p.name} ({size}) loaded")
        if self.on_text_command:
            msg = (
                f"[FILE_UPLOADED] path={path} | name={p.name} | "
                f"type={p.suffix.lstrip('.')} | size={size} | "
                "The file path is now available, but you have NOT read its contents yet. "
                "Briefly confirm that the file was attached. For every question or command "
                "about this file, call file_processor and leave file_path empty or use the exact path above. "
                "Never claim to know the file contents before calling file_processor."
            )
            threading.Thread(target=self.on_text_command, args=(msg,), daemon=True).start()

    def notify_phone_connected(self) -> None:
        if self._remote_overlay and self._remote_overlay.isVisible():
            self._remote_overlay.mark_connected()

    def tool_snapshot(self) -> dict:
        """Return worker-readable state without touching any QWidget."""
        with self._tool_state_lock:
            return {
                "current_file": self._current_file,
                "listen_mode": self._listen_mode,
                "microphone_enabled": (
                    self._listen_mode == "always" or self._talk_enabled
                ),
                "muted": self._muted,
            }

    def _open_remote(self):
        if not self.on_remote_clicked:
            self._log.append_log("SYS: Dashboard not running — remote unavailable.")
            return
        result = self.on_remote_clicked()
        if not result:
            self._log.append_log("SYS: Could not generate remote key.")
            return
        url    = result[0]
        key    = result[1]
        auto   = result[2] if len(result) >= 3 else ""
        manual = result[3] if len(result) >= 4 else url
        if self._remote_overlay:
            self._remote_overlay._do_close()
        cw  = self.centralWidget()
        ow, oh = RemoteKeyOverlay._OW, RemoteKeyOverlay._OH
        ov  = RemoteKeyOverlay(url, key, auto_login_url=auto, manual_url=manual,
                               expiry_secs=600, parent=cw)
        ov.set_new_key_callback(self.on_remote_clicked)
        ov.setGeometry(
            (cw.width()  - ow) // 2,
            (cw.height() - oh) // 2,
            ow, oh,
        )
        ov.closed.connect(lambda: setattr(self, '_remote_overlay', None))
        ov.show()
        self._remote_overlay = ov
        self._log.append_log(f"SYS: Remote key generated — manual: {manual or url}")

    def _do_interrupt(self):
        if self.on_interrupt:
            self.on_interrupt()

    def _poll_global_escape(self) -> None:
        """Observe global ESC without preventing the active app from receiving it."""
        try:
            import ctypes
            down = bool(ctypes.windll.user32.GetAsyncKeyState(0x1B) & 0x8000)
        except Exception:
            return
        if (
            down
            and not self._esc_was_down
            and self.hud.speaking
            and not self.isActiveWindow()
        ):
            self._do_interrupt()
        self._esc_was_down = down

    def _toggle_talk(self):
        """\\ toggles the microphone only while using Toggle to Speak."""
        if self._listen_mode != "toggle":
            self._log.append_log("SYS: \\ ignored — Always Listening is active.")
            return

        with self._tool_state_lock:
            self._talk_enabled = not self._talk_enabled
        self.hud.muted = not self._talk_enabled
        self._style_mute_btn()

        if self._talk_enabled:
            self._apply_state("LISTENING")
            self._log.append_log("SYS: Toggle to Speak ON — microphone listening.")
        else:
            self._apply_state("STANDBY")
            self._log.append_log("SYS: Toggle to Speak OFF — press \\ to talk.")

    def _toggle_listen_mode(self):
        """Switch between Toggle to Speak and Always Listening."""
        if self._listen_mode == "toggle":
            with self._tool_state_lock:
                self._listen_mode = "always"
                self._talk_enabled = True
            self.hud.muted = False
            self._apply_state("LISTENING")
            self._log.append_log("SYS: Listening mode changed to Always Listening.")
        else:
            with self._tool_state_lock:
                self._listen_mode = "toggle"
                self._talk_enabled = False
            self.hud.muted = True
            self._apply_state("STANDBY")
            self._log.append_log("SYS: Listening mode changed to Toggle to Speak. Press \\ to talk.")

        self._style_mute_btn()

    def _toggle_mute(self):
        """Compatibility path; the physical mute hotkey is F9 on Windows."""
        with self._tool_state_lock:
            self._talk_enabled = not self._talk_enabled
        self.hud.muted = not self.microphone_enabled
        self._style_mute_btn()

    def _style_mute_btn(self):
        if self._listen_mode == "always":
            self._mute_btn.setText("ALWAYS LISTENING  ·  ACTIVE")
            self._mute_btn.setStyleSheet(f"""
                QPushButton {{
                    background: #00140a; color: {C.GREEN};
                    border: 1px solid {C.GREEN}; border-radius: 9px;
                }}
                QPushButton:hover {{ background: #001f10; }}
            """)
        elif self._talk_enabled:
            self._mute_btn.setText("TOGGLE TO SPEAK  ·  ACTIVE")
            self._mute_btn.setStyleSheet(f"""
                QPushButton {{
                    background: #00140a; color: {C.GREEN};
                    border: 1px solid {C.GREEN}; border-radius: 9px;
                }}
                QPushButton:hover {{ background: #001f10; }}
            """)
        else:
            self._mute_btn.setText("TOGGLE TO SPEAK  ·  STANDBY")
            self._mute_btn.setStyleSheet(f"""
                QPushButton {{
                    background: #140b00; color: {C.ACC2};
                    border: 1px solid {C.ACC2}; border-radius: 9px;
                }}
                QPushButton:hover {{ background: #1f1200; }}
            """)

    def _send(self):
        txt = self._input.text().strip()
        if not txt: return
        self._input.clear()
        # Enter submits the command and returns keyboard control to the window.
        # Do not change Toggle-to-Speak: typing and microphone state are separate.
        self._input.clearFocus()
        self.setFocus(Qt.FocusReason.OtherFocusReason)
        self._log.append_log(f"You: {txt}")
        if self.on_text_command:
            threading.Thread(target=self.on_text_command, args=(txt,), daemon=True).start()

    def _apply_state(self, state: str):
        self.hud.state    = state
        self.hud.speaking = (state == "SPEAKING")
        self.hud._core.set_state(state)
        if hasattr(self, "_state_chip_lbl"):
            visual = self.hud._core.state.value
            self._state_chip_lbl.setText(f"CORE / {visual}")
            tone = C.RED if visual == "ERROR" else C.PRI
            self._state_chip_lbl.setStyleSheet(
                f"color: {tone}; background: {C.PANEL}; border: 1px solid {C.BORDER}; "
                "border-radius: 10px; padding: 4px 10px;"
            )

    def _check_config(self) -> bool:
        try:
            settings = get_settings()
            return bool(settings.gemini_api_key) and bool(settings.os_system)
        except Exception:
            return False

    def _show_setup(self):
        ov = SetupOverlay(self.centralWidget())
        cw = self.centralWidget()
        ow, oh = 460, 390
        ov.setGeometry(
            (cw.width()  - ow) // 2,
            (cw.height() - oh) // 2,
            ow, oh,
        )
        ov.done.connect(self._on_setup_done)
        ov.show()
        self._overlay = ov

    def _on_setup_done(self, key: str, os_name: str):
        update_settings({"gemini_api_key": key, "os_system": os_name})
        self._ready = True
        if self._overlay:
            self._overlay.hide()
            self._overlay = None
        self._apply_state("LISTENING")
        self._log.append_log(f"SYS: Initialised. OS={os_name.upper()}. JARVIS online.")

class _RootShim:
    def __init__(self, app: QApplication):
        self._app = app
    def mainloop(self):
        self._app.exec()
    def protocol(self, *_):
        pass


class JarvisUI:
    def __init__(self, face_path: str, size=None, start_in_pet_mode: bool = False):
        if platform.system() == "Windows":
            try:
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                    "AlejoGaisser.JARVIS.MarkXLVIII"
                )
            except (AttributeError, OSError):
                pass
        self._app = QApplication.instance() or QApplication(sys.argv)
        icon_path = CONFIG_DIR / "jarvis.ico"
        if icon_path.exists():
            self._app.setWindowIcon(QIcon(str(icon_path)))
        self._app.setStyle("Fusion")
        self._app.setStyleSheet(app_stylesheet())

        self._win = MainWindow(face_path)
        self._pet = PetOverlayWindow()
        self._pet.open_requested.connect(self._open_from_pet)
        self._pet.dismissed.connect(self._open_from_pet)
        self._win._state_sig.connect(self._pet.set_state)
        self._win._content_sig.connect(self._pet.show_result)
        self._win._pet_mode_sig.connect(self._apply_pet_mode)
        self._win._main_mode_sig.connect(self._open_from_pet)
        self._start_in_pet_mode = bool(start_in_pet_mode and self._win._ready)
        self._surface_lock = threading.RLock()
        self._surface_mode = "pet" if self._start_in_pet_mode else "main"

        if self._start_in_pet_mode:
            self._win.hide()
            self._pet.show_pet("LISTENING", "I'm here.")
        else:
            self._win.showFullScreen()
            self._win.raise_()
            self._win.activateWindow()

        # WMI/GPU polling can contend with Qt construction for hundreds of
        # milliseconds. Start the existing metrics owner only after paint.
        QTimer.singleShot(250, _metrics.start)

        # Windows often rejects activateWindow() when Python was started by the
        # background wake-word process. Retry after Qt has created a real HWND.
        if not self._start_in_pet_mode:
            QTimer.singleShot(0, self._bring_main_window_to_front)
            QTimer.singleShot(250, self._bring_main_window_to_front)
            QTimer.singleShot(750, self._bring_main_window_to_front)
            QTimer.singleShot(1500, self._bring_main_window_to_front)
            QTimer.singleShot(3000, self._bring_main_window_to_front)

        # Remove any ghost Qt window created during startup.
        QTimer.singleShot(500, self._close_ghost_windows)

        self.root = _RootShim(self._app)

    def _bring_main_window_to_front(self):
        # Delayed startup focus retries must not undo a newer App -> Pet
        # transition.  This is especially easy to trigger during the first
        # 1.2 seconds after launch.
        if self._surface_mode != "main":
            return
        self._pet.hide_pet()

        if platform.system() == "Windows":
            try:
                hwnd = int(self._win.winId())
                user32 = ctypes.windll.user32
                SW_RESTORE = 9
                SWP_NOMOVE = 0x0002
                SWP_NOSIZE = 0x0001
                SWP_SHOWWINDOW = 0x0040

                # SW_SHOW leaves an iconic/minimized HWND in the taskbar.
                # Restore it first; Qt then owns the final fullscreen state.
                user32.AllowSetForegroundWindow(-1)
                user32.ShowWindowAsync(hwnd, SW_RESTORE)
                user32.SetWindowPos(
                    hwnd, -1, 0, 0, 0, 0,
                    SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW,
                )
                user32.SetWindowPos(
                    hwnd, -2, 0, 0, 0, 0,
                    SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW,
                )
            except (AttributeError, OSError, TypeError, ValueError) as exc:
                print(f"[UI] Could not restore JARVIS window: {exc}")

        state = self._win.windowState()
        state &= ~Qt.WindowState.WindowMinimized
        state |= Qt.WindowState.WindowFullScreen | Qt.WindowState.WindowActive
        self._win.setWindowState(state)
        self._win.showFullScreen()
        self._win.raise_()
        self._win.activateWindow()

        if platform.system() != "Windows":
            return

        try:
            hwnd = int(self._win.winId())
            user32 = ctypes.windll.user32
            user32.SetForegroundWindow(hwnd)
            user32.BringWindowToTop(hwnd)
        except (AttributeError, OSError, TypeError, ValueError) as exc:
            print(f"[UI] Could not bring JARVIS to the foreground: {exc}")

    def start_after_visible(self, callback, delay_ms: int = 50) -> None:
        """Start backend work only after Qt has had time to paint the first frame."""
        QTimer.singleShot(max(0, int(delay_ms)), callback)

    def _open_from_pet(self) -> None:
        """Complete the desktop-pet to application handoff on the Qt thread."""
        if self._surface_mode == "main" and self._win.isVisible():
            return
        with self._surface_lock:
            self._surface_mode = "main"
        self._pet.hide_pet()
        self._bring_main_window_to_front()

    def enter_pet_mode(self, state: str = "LISTENING", message: str = "I'm here.") -> None:
        """Thread-safe App → Pet request used by voice tools and other workers."""
        self._win._pet_mode_sig.emit(state, message)

    def _surface_mode_snapshot(self) -> str:
        """Copy coordinator state; tolerate minimal test adapters without a lock."""
        lock = getattr(self, "_surface_lock", None)
        if lock is None:
            return self._surface_mode
        with lock:
            return self._surface_mode

    def control_interface(self, action: str, target: str, mode: str = ""):
        """Run a JARVIS UI command on Qt's thread and return its confirmed result."""
        completed = threading.Event()
        surface_mode = self._surface_mode_snapshot()
        request = {
            "action": action,
            "target": target,
            "mode": mode,
            "surface_mode": surface_mode,
            "event": completed,
        }
        self._win._interface_sig.emit(request)
        if not completed.wait(timeout=3.0):
            raise RuntimeError(
                "Interface command timed out; no UI change was confirmed."
            )
        if request.get("error"):
            raise RuntimeError(str(request["error"]))
        if "result" not in request:
            raise RuntimeError("Interface command completed without a verified result.")
        return request["result"]

    def _apply_pet_mode(self, state: str, message: str) -> None:
        """Hide the application surface and keep the same assistant session alive."""
        if self._surface_mode == "pet" and self._pet.isVisible():
            self._pet.set_state(state)
            return
        with self._surface_lock:
            self._surface_mode = "pet"
        # A hidden UI must not keep decoding, scaling and uploading webcam
        # frames. Stop the capture before the App -> Pet handoff.
        self._win.stop_camera_stream()
        self._win.hide()
        self._pet.show_pet(state, message)

    def exit_pet_mode(self) -> None:
        self._open_from_pet()

    def _close_ghost_windows(self):
        for widget in QApplication.topLevelWidgets():
            if widget in {self._win, self._pet}:
                continue

            if widget.isVisible():
                print(
                    f"[UI] Closing extra window: "
                    f"{type(widget).__name__} | "
                    f"title={widget.windowTitle()!r}"
                )
                widget.close()
                widget.deleteLater()

        if self._surface_mode == "pet":
            if not self._pet.isVisible():
                self._pet.show_pet("LISTENING", "I'm here.")
            self._pet.raise_()
        else:
            self._win.showFullScreen()
            self._win.raise_()
            self._win.activateWindow()
    @property
    def muted(self) -> bool:
        return bool(self._win.tool_snapshot()["muted"])

    @muted.setter
    def muted(self, v: bool):
        if v != self._win._muted:
            self._win._toggle_mute()

    @property
    def microphone_enabled(self) -> bool:
        return bool(self._win.tool_snapshot()["microphone_enabled"])

    @property
    def listen_mode(self) -> str:
        return str(self._win.tool_snapshot()["listen_mode"])

    @property
    def current_file(self) -> str | None:
        value = self._win.tool_snapshot()["current_file"]
        return str(value) if value is not None else None

    @property
    def on_text_command(self):
        return self._win.on_text_command

    @on_text_command.setter
    def on_text_command(self, cb):
        self._win.on_text_command = cb

    @property
    def on_remote_clicked(self):
        return self._win.on_remote_clicked

    @on_remote_clicked.setter
    def on_remote_clicked(self, cb):
        self._win.on_remote_clicked = cb

    @property
    def on_interrupt(self):
        return self._win.on_interrupt

    @on_interrupt.setter
    def on_interrupt(self, cb):
        self._win.on_interrupt = cb

    def notify_phone_connected(self) -> None:
        self._win._phone_connected_sig.emit()

    def set_state(self, state: str):
        self._win._state_sig.emit(state)

    def write_log(self, text: str):
        self._win._log_sig.emit(text)

    def wait_for_api_key(self):
        while not self._win._ready:
            time.sleep(0.1)

    def show_content(self, title: str, text: str):
        """Thread-safe: display content in the panel below the HUD."""
        self._win._content_sig.emit(title[:48], text[:4000])

    def show_memory_graph(self) -> None:
        """Thread-safe: open and refresh the local knowledge graph."""
        self._win._workspace_sig.emit("memory", {})

    def refresh_memory_graph(self) -> None:
        """Refresh real memory nodes without forcing the workspace to open."""
        self._win._workspace_sig.emit("memory_refresh", {})

    def show_geo(self, place: dict | None = None) -> None:
        """Thread-safe: open Geo and optionally fly to a resolved place."""
        payload = {}
        if place:
            payload = {
                "latitude": place.get("latitude"),
                "longitude": place.get("longitude"),
                "label": place.get("name") or place.get("label") or "Location",
            }
            if place.get("path"):
                payload["path"] = place["path"]
        self._win._workspace_sig.emit("geo", payload)

    def show_study_result(self, artifact: dict | None, automatic: bool = True) -> str:
        """Store a Study result; auto-open only while the main app is already visible."""
        surface_mode = self._surface_mode_snapshot()
        completed = threading.Event()
        request = {
            "artifact": artifact,
            "automatic": automatic,
            "surface_mode": surface_mode,
            "event": completed,
        }
        self._win._study_sig.emit(request)
        if not completed.wait(timeout=3.0):
            raise RuntimeError("Study display timed out; the result was not confirmed.")
        if request.get("error"):
            raise RuntimeError(str(request["error"]))
        return str(request.get("result") or "Study result stored.")

    def prompt_reconfig(self):
        """Thread-safe: show the API key setup overlay (e.g. after an auth error)."""
        self._win._ready = False
        self._win._reconfig_sig.emit()

    def show_camera_frame(self, img_bytes: bytes):
        """Thread-safe: show a webcam frame in the small overlay (screen captures)."""
        self._win._camera_sig.emit(img_bytes)

    def start_camera_stream(self) -> None:
        """Thread-safe: start live camera feed in the full HUD area."""
        self._win._camera_request_sig.emit(True)

    def stop_camera_stream(self) -> None:
        """Thread-safe: stop the live camera feed."""
        self._win._camera_request_sig.emit(False)

    def set_camera_frame_callback(self, callback) -> None:
        self._win.set_camera_frame_callback(callback)

    def set_camera_mode(self, mode: str) -> None:
        """Switch between stable voice control and explicit hand movement."""
        self._win.set_camera_mode(mode)

    def set_camera_view(self, zoom: float, pan_x: float, pan_y: float) -> None:
        """Set the voice-controlled camera crop."""
        self._win.set_camera_view(zoom, pan_x, pan_y)

    def start_speaking(self):
        self.set_state("SPEAKING")

    def stop_speaking(self):
        if not self.muted:
            self.set_state("LISTENING")
