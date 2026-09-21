"""A single circular surface for D-pad rendering and pointer hit testing."""
from __future__ import annotations

from math import hypot

from PySide6.QtCore import QEvent, QPointF, Property, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QStyle, QWidget

from ..styles import DARK, LIGHT


class DPadWidget(QWidget):
    key = Signal(str)
    CENTER_RATIO = 76 / 252

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAccessibleName("D-pad")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        policy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self.hover_region: str | None = None
        self.pressed_region: str | None = None
        self._mouse_down = False
        self._pointer: QPointF | None = None
        self._theme = "Dark"
        self.resize(self.sizeHint())

    def sizeHint(self) -> QSize:
        return QSize(252, 252)

    def heightForWidth(self, width: int) -> int:
        return width

    def get_theme(self) -> str:
        return self._theme

    def set_theme(self, value: str) -> None:
        self._theme = value
        self.update()

    theme = Property(str, get_theme, set_theme)

    def geometry_values(self) -> tuple[QPointF, float, float]:
        outer = min(self.width(), self.height()) / 2
        return QPointF(self.width() / 2, self.height() / 2), outer, outer * self.CENTER_RATIO

    def hit_test(self, point: QPointF) -> str | None:
        center, outer, inner = self.geometry_values()
        if outer <= 0:
            return None
        dx, dy = point.x() - center.x(), point.y() - center.y()
        distance = hypot(dx, dy)
        if distance <= inner:
            return "ok"
        if distance > outer:
            return None
        if abs(dx) > abs(dy):
            return "right" if dx > 0 else "left"
        return "down" if dy > 0 else "up"

    def _hover(self, point: QPointF | None) -> None:
        self._pointer = point
        self.hover_region = self.hit_test(point) if point is not None and self.isEnabled() else None
        self.setCursor(Qt.CursorShape.PointingHandCursor if self.hover_region else Qt.CursorShape.ArrowCursor)
        self.setToolTip("OK" if self.hover_region == "ok" else (self.hover_region or "").title())
        self.update()

    def mouseMoveEvent(self, event) -> None:
        self._hover(event.position())
        event.accept()

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton or not self.isEnabled():
            event.ignore()
            return
        self._hover(event.position())
        if not self._mouse_down:
            self._mouse_down = True
            self.pressed_region = self.hover_region
            self.update()
            if self.pressed_region:
                self.setFocus(Qt.FocusReason.MouseFocusReason)
                # Dispatch only here; release/drag must never send another key.
                self.key.emit(self.pressed_region)
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:
        # Qt replaces the second press with a double-click event.
        self.mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._mouse_down = False
            self.pressed_region = None
            self._hover(event.position())
            event.accept()
        else:
            event.ignore()

    def leaveEvent(self, event) -> None:
        self._hover(None)
        super().leaveEvent(event)

    def changeEvent(self, event) -> None:
        if event.type() == QEvent.Type.EnabledChange:
            self._mouse_down = False
            self.pressed_region = None
            self._hover(None)
        super().changeEvent(event)

    def resizeEvent(self, event) -> None:
        self._hover(self._pointer)
        super().resizeEvent(event)

    def paintEvent(self, event) -> None:
        c = LIGHT if self._theme == "Light" else DARK
        center, outer, inner = self.geometry_values()
        circle = QRectF(center.x() - outer, center.y() - outer, 2 * outer, 2 * outer)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(c["surface"]))
        painter.drawEllipse(circle)
        active = self.hover_region if self.isEnabled() else None
        pressed = active is not None and active == self.pressed_region
        if active and active != "ok":
            sector = QPainterPath(center)
            sector.arcTo(circle, {"right": -45, "up": 45, "left": 135, "down": 225}[active], 90)
            sector.closeSubpath()
            painter.fillPath(sector, QColor(c["hover"]).lighter(115) if pressed else QColor(c["hover"]))
        painter.setPen(QPen(QColor(c["border"]), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(circle.adjusted(0.5, 0.5, -0.5, -0.5))
        painter.setPen(Qt.PenStyle.NoPen)
        center_color = QColor(c["accent"] if self.isEnabled() else c["field"])
        if active == "ok":
            center_color = center_color.darker(115) if pressed else center_color.lighter(110)
        painter.setBrush(center_color)
        painter.drawEllipse(center, inner, inner)
        painter.setPen(QColor(c["ink"] if self.isEnabled() else c["muted"]))
        painter.drawText(QRectF(center.x() - inner, center.y() - inner, 2 * inner, 2 * inner), Qt.AlignmentFlag.AlignCenter, "OK")
        for dx, dy, icon in ((0, -1, QStyle.StandardPixmap.SP_ArrowUp), (0, 1, QStyle.StandardPixmap.SP_ArrowDown),
                             (-1, 0, QStyle.StandardPixmap.SP_ArrowLeft), (1, 0, QStyle.StandardPixmap.SP_ArrowRight)):
            size = max(1, round(18 * outer / 126))
            position = center + QPointF(dx * outer * 82 / 126, dy * outer * 82 / 126)
            target = QRectF(position.x() - size / 2, position.y() - size / 2, size, size).toRect()
            mode = QIcon.Mode.Normal if self.isEnabled() else QIcon.Mode.Disabled
            self.style().standardIcon(icon).paint(painter, target, Qt.AlignmentFlag.AlignCenter, mode)
