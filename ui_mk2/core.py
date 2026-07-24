"""High-fidelity, state-driven JARVIS Mk II core renderer."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QConicalGradient,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
    QPicture,
    QPolygonF,
    QRadialGradient,
)

from .state import VisualState, VisualStateController
from .tokens import Palette, color


@dataclass(frozen=True)
class CoreGeometry:
    center: QPointF
    size: float


def _mix_color(a: QColor, b: QColor, amount: float) -> QColor:
    amount = max(0.0, min(1.0, amount))
    return QColor(
        round(a.red() + (b.red() - a.red()) * amount),
        round(a.green() + (b.green() - a.green()) * amount),
        round(a.blue() + (b.blue() - a.blue()) * amount),
        round(a.alpha() + (b.alpha() - a.alpha()) * amount),
    )


class CoreRenderer:
    """Paints the Figma Mk II core without raster assets or random movement."""

    # The central lens is intentionally frozen to lower its per-frame workload.
    # Outer rings, arcs, nodes and state signatures keep using the live clock.
    STATIC_NUCLEUS_TIME = 0.0

    ARC_LAYOUT = (
        (0.458, 342.0, 48.0, 2.4),
        (0.458, 218.0, 39.0, 1.25),
        (0.458, 147.0, 34.0, 1.15),
        (0.458, 84.0, 31.0, 1.1),
        (0.458, 24.0, 25.0, 1.05),
        (0.458, 291.0, 24.0, 1.05),
        (0.365, 302.0, 51.0, 1.45),
        (0.365, 190.0, 45.0, 1.25),
        (0.365, 111.0, 39.0, 1.2),
        (0.365, 38.0, 34.0, 1.15),
    )

    def __init__(self, state: str | VisualState = VisualState.DORMANT):
        self.controller = VisualStateController(state)
        self.phase = 0.0
        self.time_seconds = 0.0
        self.audio_energy = 0.18
        self.target_audio_energy = 0.18
        self.reduced_motion = os.getenv("JARVIS_REDUCED_MOTION", "0") == "1"
        self.controller.reduced_motion = self.reduced_motion
        self._iris_cache_key: tuple[object, ...] | None = None
        self._iris_cache: QPicture | None = None

    @property
    def state(self) -> VisualState:
        return self.controller.state

    def set_state(self, state: str | VisualState) -> bool:
        return self.controller.set_state(state)

    def set_audio_energy(self, value: float) -> None:
        self.target_audio_energy = max(0.0, min(1.0, float(value)))

    def set_reduced_motion(self, enabled: bool) -> None:
        self.reduced_motion = bool(enabled)
        self.controller.reduced_motion = self.reduced_motion
        if enabled:
            self.controller.progress = 1.0

    def advance(self, dt: float) -> None:
        self.controller.advance(dt)
        self.audio_energy += (self.target_audio_energy - self.audio_energy) * min(1.0, dt * 11.0)
        if self.reduced_motion:
            return
        self.time_seconds += max(0.0, dt)
        speed = self.controller.value("ring_speed")
        self.phase = (self.phase + max(0.0, dt) * speed * 360.0) % 360.0

    @staticmethod
    def geometry(bounds: QRectF) -> CoreGeometry:
        size = max(80.0, min(bounds.width(), bounds.height()))
        # The lens sits optically below the mathematical centre in the Figma master.
        center = QPointF(bounds.center().x(), bounds.center().y() + size * 0.018)
        return CoreGeometry(center=center, size=size)

    def draw(self, painter: QPainter, bounds: QRectF, *, compact: bool = False) -> None:
        geo = self.geometry(bounds)
        center, size = geo.center, geo.size
        transition = self.controller.progress
        primary = _mix_color(
            QColor(self.controller.previous_spec.primary),
            QColor(self.controller.spec.primary),
            transition * transition * (3.0 - 2.0 * transition),
        )
        secondary = _mix_color(
            QColor(self.controller.previous_spec.secondary),
            QColor(self.controller.spec.secondary),
            transition * transition * (3.0 - 2.0 * transition),
        )
        intensity = self.controller.value("intensity")

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self._draw_atmosphere(painter, center, size, primary, intensity)
        self._draw_data_orbits(painter, center, size, primary, secondary, intensity)
        self._draw_precision_arcs(painter, center, size, primary, secondary, intensity)
        self._draw_segmented_housing(painter, center, size, primary, secondary, intensity)
        self._draw_micro_ticks(painter, center, size, primary, secondary, intensity)
        self._draw_ticks(painter, center, size, primary, secondary, intensity)
        self._draw_iris(painter, center, size, primary, secondary, intensity)
        if not compact:
            self._draw_state_signature(painter, center, size, primary, secondary, intensity)
        painter.restore()

    def _draw_atmosphere(
        self, painter: QPainter, center: QPointF, size: float,
        primary: QColor, intensity: float,
    ) -> None:
        radius = size * 0.46
        gradient = QRadialGradient(center, radius)
        gradient.setColorAt(0.0, color(Palette.VOID, 0))
        halo = QColor(primary)
        halo.setAlpha(round(32 * intensity))
        gradient.setColorAt(0.48, halo)
        gradient.setColorAt(0.76, color(Palette.VOID, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(gradient))
        painter.drawEllipse(center, radius, radius)

    @staticmethod
    def _point(center: QPointF, radius: float, angle_degrees: float) -> QPointF:
        angle = math.radians(angle_degrees)
        return QPointF(
            center.x() + math.cos(angle) * radius,
            center.y() + math.sin(angle) * radius,
        )

    def _draw_data_orbits(
        self, painter: QPainter, center: QPointF, size: float,
        primary: QColor, secondary: QColor, intensity: float,
    ) -> None:
        """Sparse orbital telemetry gives the core the scale of a real system."""
        for index, (radius_factor, alpha) in enumerate(((0.488, 54), (0.445, 38))):
            radius = size * radius_factor
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(color(secondary.name(), round(alpha * intensity)),
                                max(0.6, size / 520.0)))
            painter.drawEllipse(center, radius, radius)

            direction = 1.0 if index == 0 else -0.72
            offset = self.phase * direction + index * 37.0
            for node in range(8 if index == 0 else 6):
                angle = offset + node * (360.0 / (8 if index == 0 else 6))
                point = self._point(center, radius, angle)
                active = (node + int(self.time_seconds * 2.0)) % 5 == 0
                node_color = primary if active else secondary
                painter.setPen(QPen(color(node_color.name(), round((210 if active else 90) * intensity)),
                                    max(0.8, size / 360.0)))
                painter.setBrush(QBrush(color(node_color.name(), round((95 if active else 18) * intensity))))
                node_r = size * (0.010 if active else 0.006)
                painter.drawEllipse(point, node_r, node_r)

    def _draw_segmented_housing(
        self, painter: QPainter, center: QPointF, size: float,
        primary: QColor, secondary: QColor, intensity: float,
    ) -> None:
        """Mechanical sector crown inspired by dense cinematic HUD reactors."""
        outer = size * 0.405
        inner = size * 0.322
        count = 28
        step = 360.0 / count
        offset = -90.0 + self.phase * 0.065
        highlighted = int((self.time_seconds * 4.0) % count)

        for index in range(count):
            start = offset + index * step + 1.15
            end = offset + (index + 1) * step - 1.15
            polygon = QPolygonF([
                self._point(center, inner, start),
                self._point(center, outer, start),
                self._point(center, outer, end),
                self._point(center, inner, end),
            ])
            active = index == highlighted or index == (highlighted + 1) % count
            line = primary if active or index % 7 == 0 else secondary
            painter.setPen(QPen(color(line.name(), round((230 if active else 112) * intensity)),
                                max(0.65, size / 650.0)))
            painter.setBrush(QBrush(color(line.name(), round((68 if active else 13) * intensity))))
            painter.drawPolygon(polygon)

        # Cardinal hardpoints make the ring feel assembled rather than decorative.
        for angle in (0.0, 90.0, 180.0, 270.0):
            anchor = self._point(center, size * 0.447, angle)
            hardpoint_r = size * 0.020
            painter.setPen(QPen(color(primary.name(), round(190 * intensity)),
                                max(0.8, size / 420.0)))
            painter.setBrush(QBrush(color(Palette.SURFACE_RAISED, 235)))
            painter.drawEllipse(anchor, hardpoint_r, hardpoint_r)
            painter.setPen(QPen(color(primary.name(), round(95 * intensity)),
                                max(0.6, size / 650.0)))
            painter.drawEllipse(anchor, hardpoint_r * 0.48, hardpoint_r * 0.48)

    def _draw_micro_ticks(
        self, painter: QPainter, center: QPointF, size: float,
        primary: QColor, secondary: QColor, intensity: float,
    ) -> None:
        """High-density calibration crown surrounding the energy chamber."""
        outer = size * 0.309
        for index in range(96):
            angle = index * 3.75 - 90.0 - self.phase * 0.12
            major = index % 8 == 0
            medium = index % 4 == 0
            length = size * (0.036 if major else 0.025 if medium else 0.015)
            inner = outer - length
            tick = primary if major or index % 3 == 0 else secondary
            painter.setPen(QPen(
                color(tick.name(), round((245 if major else 172) * intensity)),
                max(0.75, size / 520.0 * (1.65 if major else 1.0)),
            ))
            painter.drawLine(
                self._point(center, inner, angle),
                self._point(center, outer, angle),
            )

        # Compact identifiers are intentionally sparse; they imply scale without noise.
        painter.setFont(QFont("Cascadia Mono", max(5, round(size * 0.015)), QFont.Weight.DemiBold))
        painter.setPen(QPen(color(Palette.CYAN_SOFT, round(180 * intensity)), 1))
        for label_index, angle in enumerate((-74.0, -18.0, 42.0, 108.0, 166.0, 226.0)):
            point = self._point(center, size * 0.353, angle)
            rect = QRectF(point.x() - size * 0.03, point.y() - size * 0.014,
                          size * 0.06, size * 0.028)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, f"{label_index + 1:02d}")

    def _draw_precision_arcs(
        self, painter: QPainter, center: QPointF, size: float,
        primary: QColor, secondary: QColor, intensity: float,
    ) -> None:
        motion = self.phase
        state = self.controller.state
        if state == VisualState.EXECUTING:
            motion *= 1.08
        for index, (radius_factor, start, span, width) in enumerate(self.ARC_LAYOUT):
            radius = size * radius_factor
            rect = QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2)
            arc_color = primary if index in {0, 4, 6, 9} else secondary
            alpha_scale = 0.90 if index < 6 else 0.68
            arc_color = QColor(arc_color)
            arc_color.setAlpha(round(255 * intensity * alpha_scale))
            painter.setPen(QPen(arc_color, max(0.8, size / 280.0 * width), Qt.PenStyle.SolidLine,
                                Qt.PenCapStyle.RoundCap))
            direction = 1 if index % 2 == 0 else -0.64
            painter.drawArc(rect, round((start + motion * direction) * 16), round(span * 16))

        # Fine housing circles add the 2.5D precision visible in the master.
        for radius_factor, alpha, width in ((0.432, 34, 0.7), (0.306, 70, 0.8), (0.212, 115, 0.85)):
            radius = size * radius_factor
            line = QColor(secondary)
            line.setAlpha(round(alpha * intensity))
            painter.setPen(QPen(line, max(0.65, width * size / 280.0)))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(center, radius, radius)

    def _draw_ticks(
        self, painter: QPainter, center: QPointF, size: float,
        primary: QColor, secondary: QColor, intensity: float,
    ) -> None:
        outer = size * 0.475
        for index in range(24):
            angle = math.radians(index * 15.0 - 90.0)
            major = index % 3 == 0
            length = size * (0.043 if major else 0.017)
            inner = outer - length
            tick_color = QColor(primary if major else secondary)
            tick_color.setAlpha(round(255 * intensity * (0.96 if major else 0.72)))
            painter.setPen(QPen(tick_color, max(1.0, size / 280.0 * (2.0 if major else 1.35)),
                                Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(
                QPointF(center.x() + math.cos(angle) * inner, center.y() + math.sin(angle) * inner),
                QPointF(center.x() + math.cos(angle) * outer, center.y() + math.sin(angle) * outer),
            )

        # Four floating registration brackets.
        bracket_radius = size * 0.515
        arm = size * 0.041
        gap = size * 0.018
        bracket = QColor(primary)
        bracket.setAlpha(round(230 * intensity))
        painter.setPen(QPen(bracket, max(1.0, size / 280.0 * 1.8), cap=Qt.PenCapStyle.RoundCap))
        for angle_deg in (0, 90, 180, 270):
            angle = math.radians(angle_deg)
            radial = QPointF(math.cos(angle), math.sin(angle))
            tangent = QPointF(-math.sin(angle), math.cos(angle))
            anchor = QPointF(center.x() + radial.x() * bracket_radius,
                             center.y() + radial.y() * bracket_radius)
            painter.drawLine(
                QPointF(anchor.x() - tangent.x() * arm, anchor.y() - tangent.y() * arm),
                QPointF(anchor.x() - tangent.x() * gap, anchor.y() - tangent.y() * gap),
            )
            painter.drawLine(
                QPointF(anchor.x() + tangent.x() * gap, anchor.y() + tangent.y() * gap),
                QPointF(anchor.x() + tangent.x() * arm, anchor.y() + tangent.y() * arm),
            )

    def _draw_iris(
        self, painter: QPainter, center: QPointF, size: float,
        primary: QColor, secondary: QColor, intensity: float,
    ) -> None:
        cache_key = (
            center.x(), center.y(), size, primary.rgba(), secondary.rgba(),
            intensity, self.controller.state,
        )
        if cache_key != self._iris_cache_key or self._iris_cache is None:
            picture = QPicture()
            cache_painter = QPainter(picture)
            cache_painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            self._paint_static_iris(
                cache_painter, center, size, primary, secondary, intensity,
            )
            cache_painter.end()
            self._iris_cache_key = cache_key
            self._iris_cache = picture
        self._iris_cache.play(painter)

    def _paint_static_iris(
        self, painter: QPainter, center: QPointF, size: float,
        primary: QColor, secondary: QColor, intensity: float,
    ) -> None:
        """Paint the nucleus once per visual configuration, never per animation frame."""
        state = self.controller.state
        nucleus_time = self.STATIC_NUCLEUS_TIME
        lens_radius = size * 0.258
        focus = center

        # Deep holographic energy sphere. The larger chamber and hard cyan rim
        # are the visual anchor of the entire interface.
        outer_glow = QRadialGradient(center, lens_radius * 1.42, focus)
        outer_glow.setColorAt(0.0, color(primary.name(), round(48 * intensity)))
        outer_glow.setColorAt(0.62, color(primary.name(), round(72 * intensity)))
        outer_glow.setColorAt(0.82, color(primary.name(), round(20 * intensity)))
        outer_glow.setColorAt(1.0, color(primary.name(), 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(outer_glow))
        painter.drawEllipse(center, lens_radius * 1.42, lens_radius * 1.42)

        housing = QRadialGradient(center, lens_radius * 1.15, focus)
        luminous = QColor(primary)
        luminous.setAlpha(round(210 * intensity))
        housing.setColorAt(0.0, color(Palette.CYAN_SOFT if state != VisualState.ERROR else Palette.ERROR_SOFT,
                                      round(245 * intensity)))
        housing.setColorAt(0.10, luminous)
        housing.setColorAt(0.30, color(primary.name(), round(152 * intensity)))
        housing.setColorAt(0.56, color(Palette.SURFACE_RAISED, round(245 * intensity)))
        housing.setColorAt(0.82, color(Palette.VOID_DEEP, 248))
        housing.setColorAt(1.0, color(Palette.VOID, 255))
        painter.setPen(QPen(color(primary.name(), round(245 * intensity)),
                            max(1.5, size / 280.0 * 2.4)))
        painter.setBrush(QBrush(housing))
        painter.drawEllipse(center, lens_radius, lens_radius)

        # Multi-pass energy torus gives the chamber the electric rim visible in
        # the references while remaining fully state-driven.
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for radius_scale, width_scale, alpha in (
            (0.96, 8.0, 34), (0.91, 4.2, 205), (0.86, 1.3, 245), (0.72, 1.0, 86)
        ):
            painter.setPen(QPen(
                color(primary.name(), round(alpha * intensity)),
                max(0.8, size / 520.0 * width_scale),
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
            ))
            painter.drawEllipse(center, lens_radius * radius_scale, lens_radius * radius_scale)

        # Latitude/longitude traces turn the lens into a holographic intelligence
        # sphere instead of a flat camera aperture.
        painter.save()
        sphere_clip = QPainterPath()
        sphere_clip.addEllipse(center, lens_radius * 0.70, lens_radius * 0.70)
        painter.setClipPath(sphere_clip)
        trace = color(Palette.CYAN_SOFT if state != VisualState.ERROR else Palette.ERROR_SOFT,
                      round(86 * intensity))
        painter.setPen(QPen(trace, max(0.55, size / 700.0)))
        for height_scale in (0.22, 0.48, 0.78):
            rect = QRectF(
                center.x() - lens_radius * 0.68,
                center.y() - lens_radius * 0.68 * height_scale,
                lens_radius * 1.36,
                lens_radius * 1.36 * height_scale,
            )
            painter.drawEllipse(rect)
        longitude_shift = math.sin(nucleus_time * 0.65) * lens_radius * 0.08
        for width_scale in (0.30, 0.62):
            rect = QRectF(
                center.x() - lens_radius * 0.68 * width_scale + longitude_shift,
                center.y() - lens_radius * 0.68,
                lens_radius * 1.36 * width_scale,
                lens_radius * 1.36,
            )
            painter.drawEllipse(rect)

        # Deterministic plasma filaments remain visible at a fixed phase.
        for filament in range(4):
            path = QPainterPath()
            angle = nucleus_time * (0.42 + filament * 0.05) + filament * 1.57
            start = QPointF(
                center.x() + math.cos(angle) * lens_radius * 0.08,
                center.y() + math.sin(angle) * lens_radius * 0.08,
            )
            path.moveTo(start)
            for point_index in range(1, 9):
                progress = point_index / 8.0
                radial = lens_radius * (0.08 + progress * 0.56)
                bend = math.sin(point_index * 1.7 + nucleus_time * 2.0 + filament) * lens_radius * 0.05
                point_angle = angle + progress * (0.82 if filament % 2 == 0 else -0.76)
                point = QPointF(
                    center.x() + math.cos(point_angle) * radial - math.sin(point_angle) * bend,
                    center.y() + math.sin(point_angle) * radial + math.cos(point_angle) * bend,
                )
                path.lineTo(point)
            painter.setPen(QPen(
                color(Palette.CYAN_SOFT if state != VisualState.ERROR else Palette.ERROR_SOFT,
                      round((138 - filament * 15) * intensity)),
                max(0.7, size / 560.0 * (1.7 if filament == 0 else 1.1)),
            ))
            painter.drawPath(path)
        painter.restore()

        # Aperture ring and compact intelligence seed.
        aperture_r = lens_radius * 0.43
        dash_pen = QPen(color(secondary.name(), round(235 * intensity)), max(1.0, size / 280.0 * 1.5))
        dash_pen.setStyle(Qt.PenStyle.DashLine)
        dash_pen.setDashPattern([5.0, 4.0])
        painter.setPen(dash_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(center, aperture_r, aperture_r)

        pupil_r = lens_radius * 0.14
        pupil = QRadialGradient(center, pupil_r)
        pupil.setColorAt(0.0, color(Palette.TEXT, round(255 * intensity)))
        pupil.setColorAt(0.34, color(primary.name(), round(235 * intensity)))
        pupil.setColorAt(1.0, color(Palette.VOID_DEEP, 255))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(pupil))
        painter.drawEllipse(center, pupil_r, pupil_r)

        # Specular crescent keeps the holographic chamber from looking flat.
        specular = QRadialGradient(
            QPointF(center.x() - lens_radius * 0.26, center.y() - lens_radius * 0.28),
            lens_radius * 0.48,
        )
        specular.setColorAt(0.0, color(Palette.TEXT, round(150 * intensity)))
        specular.setColorAt(1.0, color(Palette.TEXT, 0))
        painter.setBrush(QBrush(specular))
        painter.drawEllipse(center, lens_radius * 0.78, lens_radius * 0.78)

    def _draw_state_signature(
        self, painter: QPainter, center: QPointF, size: float,
        primary: QColor, secondary: QColor, intensity: float,
    ) -> None:
        state = self.controller.state
        if state in {VisualState.THINKING, VisualState.EXECUTING}:
            radius = size * 0.285
            rect = QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2)
            scan = QPen(color(primary.name(), round(185 * intensity)), max(1.0, size / 280.0 * 2.1))
            scan.setStyle(Qt.PenStyle.DashLine)
            scan.setDashPattern([6.0, 3.0])
            painter.setPen(scan)
            start = 30.0 + self.phase * (1 if state == VisualState.THINKING else -1)
            painter.drawArc(rect, round(start * 16), round(112 * 16))
        elif state == VisualState.SPEAKING:
            baseline = center.y() + size * 0.445
            count = 9
            width = size * 0.013
            gap = size * 0.011
            total = count * width + (count - 1) * gap
            for index in range(count):
                wave = 0.32 + 0.68 * abs(math.sin(self.time_seconds * 8.0 + index * 0.72))
                height = size * 0.08 * wave * max(0.25, self.audio_energy)
                alpha = round(255 * intensity * (0.72 + 0.28 * wave))
                painter.fillRect(
                    QRectF(center.x() - total / 2 + index * (width + gap), baseline - height / 2,
                           width, height),
                    color((primary if index % 2 == 0 else secondary).name(), alpha),
                )
        elif state == VisualState.ERROR:
            radius = size * 0.265
            warning = QConicalGradient(center, 90.0 + self.time_seconds * 72.0)
            warning.setColorAt(0.0, color(primary.name(), 20))
            warning.setColorAt(0.24, color(primary.name(), round(225 * intensity)))
            warning.setColorAt(0.36, color(primary.name(), 20))
            warning.setColorAt(1.0, color(primary.name(), 20))
            painter.setPen(QPen(QBrush(warning), max(1.0, size / 280.0 * 1.7)))
            painter.drawEllipse(center, radius, radius)
