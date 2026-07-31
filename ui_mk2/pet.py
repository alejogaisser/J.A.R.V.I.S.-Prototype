"""Small, movable JARVIS orb used while the main workspace is hidden."""

from __future__ import annotations

import math

from PyQt6.QtCore import QPoint, QPointF, QRectF, QSettings, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QBrush,
    QCloseEvent,
    QColor,
    QConicalGradient,
    QMouseEvent,
    QPainter,
    QPen,
    QRadialGradient,
)
from PyQt6.QtWidgets import QApplication, QWidget

from .state import VisualState, normalize_state
from .tokens import Palette, color


class PetOverlayWindow(QWidget):
    """A focus-free Siri-like orb that communicates state through motion."""

    open_requested = pyqtSignal()
    dismissed = pyqtSignal()

    SIZE = 136

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("JarvisPetOrb")
        self.setWindowTitle("J.A.R.V.I.S · Pet")
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setCursor(Qt.CursorShape.OpenHandCursor)

        self._state = VisualState.DORMANT
        self._phase = 0.0
        self._drag_origin: QPointF | None = None
        self._window_origin = QPoint()
        self._has_saved_position = False
        self._settings = QSettings("AlejoGaisser", "JARVIS-Mark-L")

        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._advance)

    def show_pet(self, state: str = "LISTENING", message: str | None = None) -> None:
        del message  # Pet state is intentionally visual-only.
        self.set_state(state)
        self._restore_or_position()
        self.show()
        self.raise_()
        self._timer.start()

    def hide_pet(self) -> None:
        self._timer.stop()
        self._reset_pointer_interaction()
        self.hide()

    def _reset_pointer_interaction(self) -> None:
        """Release any drag/grab before handing input back to the main window."""
        self._drag_origin = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        if QWidget.mouseGrabber() is self:
            self.releaseMouse()

    def set_state(
        self,
        state: str,
        message: str | None = None,
        detail: str | None = None,
    ) -> None:
        del message, detail
        self._state = normalize_state(state)
        self._timer.setInterval(33 if self._state == VisualState.DORMANT else 16)
        self.update()

    def show_result(self, title: str, text: str) -> None:
        del title, text
        self.set_state("LISTENING")

    def _screen_area(self):
        center = self.frameGeometry().center()
        screen = QApplication.screenAt(center) or QApplication.primaryScreen()
        return screen.availableGeometry() if screen else None

    def _restore_or_position(self) -> None:
        saved = self._settings.value("pet/position")
        if isinstance(saved, QPoint):
            self.move(saved)
            self._has_saved_position = True
        elif not self._has_saved_position:
            screen = QApplication.screenAt(self.cursor().pos()) or QApplication.primaryScreen()
            if screen:
                area = screen.availableGeometry()
                self.move(area.right() - self.width() - 24, area.bottom() - self.height() - 24)
        self._clamp_to_screen()

    def _clamp_to_screen(self) -> None:
        area = self._screen_area()
        if not area:
            return
        x = max(area.left(), min(self.x(), area.right() - self.width() + 1))
        y = max(area.top(), min(self.y(), area.bottom() - self.height() + 1))
        self.move(x, y)

    def _advance(self) -> None:
        speed = {
            VisualState.DORMANT: 0.018,
            VisualState.LISTENING: 0.040,
            VisualState.THINKING: 0.095,
            VisualState.SPEAKING: 0.070,
            VisualState.EXECUTING: 0.115,
            VisualState.ERROR: 0.035,
        }.get(self._state, 0.045)
        self._phase = (self._phase + speed) % (math.tau * 100)
        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = event.globalPosition()
            self._window_origin = self.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_origin is not None and event.buttons() & Qt.MouseButton.LeftButton:
            delta = event.globalPosition() - self._drag_origin
            self.move(self._window_origin + QPoint(round(delta.x()), round(delta.y())))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._drag_origin is not None:
            self._drag_origin = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            self._clamp_to_screen()
            self._settings.setValue("pet/position", self.pos())
            self._has_saved_position = True
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            # The coordinator hides this window synchronously from the signal.
            # Release the implicit grab first so the restored app receives the
            # next mouse event instead of leaving the hidden pet as grabber.
            self._reset_pointer_interaction()
            self.open_requested.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def closeEvent(self, event: QCloseEvent) -> None:
        self._timer.stop()
        self.dismissed.emit()
        event.accept()

    def _state_scale(self) -> float:
        wave = (math.sin(self._phase) + 1.0) * 0.5
        if self._state == VisualState.LISTENING:
            return 1.04 + wave * 0.08
        if self._state == VisualState.SPEAKING:
            return 0.98 + wave * 0.10
        if self._state == VisualState.THINKING:
            return 0.98 + wave * 0.025
        if self._state == VisualState.EXECUTING:
            return 1.0 + wave * 0.035
        if self._state == VisualState.ERROR:
            return 0.98 + wave * 0.06
        return 0.98 + wave * 0.018

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        center = QPointF(self.width() / 2, self.height() / 2)
        radius = 48.0 * self._state_scale()
        if self._state == VisualState.ERROR:
            primary = color(Palette.ERROR)
            bright = color(Palette.ERROR_SOFT)
            deep = QColor(92, 8, 28)
        else:
            primary = color(Palette.CYAN)
            bright = color(Palette.CYAN_BRIGHT)
            deep = color(Palette.CYAN_MUTED)

        # Segmented reactor halos reuse the Mk II palette. They follow the
        # existing phase only; state timing and animation behaviour stay intact.
        painter.setBrush(Qt.BrushStyle.NoBrush)
        halo_rotation = int(math.degrees(self._phase) * 16)
        outer_halo = QRectF(
            center.x() - radius - 8,
            center.y() - radius - 8,
            (radius + 8) * 2,
            (radius + 8) * 2,
        )
        middle_halo = outer_halo.adjusted(3.5, 3.5, -3.5, -3.5)
        painter.setPen(QPen(QColor(primary.red(), primary.green(), primary.blue(), 72), 1.0))
        painter.drawEllipse(outer_halo)
        painter.setPen(QPen(QColor(bright.red(), bright.green(), bright.blue(), 185), 1.7))
        for start, span in ((8, 38), (72, 18), (111, 52), (198, 24), (248, 62), (334, 14)):
            painter.drawArc(outer_halo, halo_rotation + start * 16, span * 16)
        painter.setPen(QPen(QColor(primary.red(), primary.green(), primary.blue(), 122), 1.1))
        for start, span in ((28, 24), (96, 44), (181, 31), (267, 38)):
            painter.drawArc(middle_halo, -halo_rotation // 2 + start * 16, span * 16)

        # Small circuit ticks make the halo read as JARVIS tech rather than a
        # generic decorative ring.
        painter.setPen(QPen(QColor(bright.red(), bright.green(), bright.blue(), 155), 1.0))
        for angle_deg in range(0, 360, 30):
            angle = math.radians(angle_deg)
            inner = radius + 4.5
            outer = radius + (8.0 if angle_deg % 60 == 0 else 6.5)
            painter.drawLine(
                QPointF(center.x() + math.cos(angle) * inner, center.y() + math.sin(angle) * inner),
                QPointF(center.x() + math.cos(angle) * outer, center.y() + math.sin(angle) * outer),
            )

        glow = QRadialGradient(center, radius * 1.36)
        glow.setColorAt(0.0, QColor(bright.red(), bright.green(), bright.blue(), 92))
        glow.setColorAt(0.55, QColor(primary.red(), primary.green(), primary.blue(), 34))
        glow.setColorAt(1.0, QColor(deep.red(), deep.green(), deep.blue(), 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(glow))
        painter.drawEllipse(center, radius * 1.36, radius * 1.36)

        orb = QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2)
        shell = QRadialGradient(
            QPointF(center.x() - radius * 0.28, center.y() - radius * 0.34),
            radius * 1.34,
        )
        shell.setColorAt(0.0, color(Palette.TEXT, 246))
        shell.setColorAt(0.16, QColor(bright.red(), bright.green(), bright.blue(), 232))
        shell.setColorAt(0.48, QColor(primary.red(), primary.green(), primary.blue(), 238))
        shell.setColorAt(0.78, QColor(deep.red(), deep.green(), deep.blue(), 235))
        shell.setColorAt(1.0, color(Palette.VOID_DEEP, 248))
        painter.setBrush(QBrush(shell))
        painter.setPen(QPen(QColor(bright.red(), bright.green(), bright.blue(), 190), 1.4))
        painter.drawEllipse(orb)

        # Thinking/executing is rotation; listening is expansion; speaking is
        # a soft rhythmic wave. No labels are needed to explain the state.
        rotation = math.degrees(self._phase)
        ring = QConicalGradient(center, -rotation)
        ring.setColorAt(0.0, QColor(primary.red(), primary.green(), primary.blue(), 25))
        ring.setColorAt(0.24, QColor(bright.red(), bright.green(), bright.blue(), 245))
        ring.setColorAt(0.50, QColor(deep.red(), deep.green(), deep.blue(), 40))
        ring.setColorAt(0.76, QColor(primary.red(), primary.green(), primary.blue(), 235))
        ring.setColorAt(1.0, QColor(primary.red(), primary.green(), primary.blue(), 25))
        ring_width = 3.2 if self._state in {VisualState.THINKING, VisualState.EXECUTING} else 2.0
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QBrush(ring), ring_width))
        inset = 7.0
        painter.drawEllipse(orb.adjusted(inset, inset, -inset, -inset))

        for offset, alpha in ((0.0, 150), (math.pi * 0.66, 105), (math.pi * 1.33, 75)):
            angle = self._phase * (1.8 if self._state == VisualState.THINKING else 0.8) + offset
            orbit = radius * 0.56
            dot = QPointF(center.x() + math.cos(angle) * orbit, center.y() + math.sin(angle) * orbit)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(225, 255, 255, alpha))
            painter.drawEllipse(dot, 3.2, 3.2)

        highlight = QRadialGradient(
            QPointF(center.x() - radius * 0.31, center.y() - radius * 0.38),
            radius * 0.48,
        )
        highlight.setColorAt(0.0, QColor(255, 255, 255, 205))
        highlight.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.setBrush(QBrush(highlight))
        painter.drawEllipse(orb)
