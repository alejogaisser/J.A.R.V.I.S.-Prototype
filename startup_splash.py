"""Immediate lightweight feedback while the full JARVIS process imports."""
from __future__ import annotations

import ctypes
import sys
import time

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget


class ActivationSplash(QWidget):
    def __init__(self, target_pid: int) -> None:
        super().__init__()
        self.target_pid = target_pid
        self.started = time.monotonic()
        self.phase = 0
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(560, 210)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(42, 44, 42, 38)
        layout.setSpacing(12)
        title = QLabel("J.A.R.V.I.S")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setFont(QFont("Segoe UI", 25, QFont.Weight.Light))
        title.setStyleSheet("color: #d8f8ff; letter-spacing: 8px;")
        layout.addWidget(title)

        self.status = QLabel("NEURAL SYSTEM ACTIVATING")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        self.status.setStyleSheet("color: #00d4ff; letter-spacing: 2px;")
        layout.addWidget(self.status)

        screen = QApplication.primaryScreen().availableGeometry()
        self.move(
            screen.x() + (screen.width() - self.width()) // 2,
            screen.y() + (screen.height() - self.height()) // 2,
        )
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(140)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(0, 8, 14, 246))
        painter.setPen(QPen(QColor(0, 212, 255, 210), 1.5))
        painter.drawRoundedRect(self.rect().adjusted(2, 2, -2, -2), 22, 22)
        width = int((self.width() - 84) * ((self.phase % 28) / 27))
        painter.setPen(QPen(QColor(0, 212, 255, 230), 3))
        painter.drawLine(42, self.height() - 28, 42 + width, self.height() - 28)

    def _main_window_visible(self) -> bool:
        if sys.platform != "win32":
            return False
        found = False
        user32 = ctypes.windll.user32
        callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        def inspect(hwnd, _lparam):
            nonlocal found
            process_id = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
            if process_id.value != self.target_pid or not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            if "J.A.R.V.I.S" in buffer.value:
                found = True
                return False
            return True

        callback = callback_type(inspect)
        user32.EnumWindows(callback, 0)
        return found

    def _process_alive(self) -> bool:
        if sys.platform == "win32":
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x1000, False, self.target_pid)
            if not handle:
                return False
            try:
                exit_code = ctypes.c_ulong()
                return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))) and exit_code.value == 259
            finally:
                kernel32.CloseHandle(handle)
        try:
            import psutil
            return psutil.pid_exists(self.target_pid)
        except ImportError:
            return True

    def _tick(self) -> None:
        self.phase += 1
        self.status.setText("NEURAL SYSTEM ACTIVATING" + "." * (self.phase % 4))
        self.update()
        elapsed = time.monotonic() - self.started
        process_alive = self._process_alive()
        if elapsed >= 0.9 and self._main_window_visible():
            self.close()
        elif not process_alive or elapsed >= 45:
            self.close()


def main() -> int:
    if len(sys.argv) != 2:
        return 2
    app = QApplication(sys.argv)
    splash = ActivationSplash(int(sys.argv[1]))
    splash.show()
    splash.raise_()
    splash.activateWindow()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
