from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QSizePolicy, QStyle, QVBoxLayout, QWidget,
)

from ..config import resource_path
from .dpad import DPadWidget


def label(text: str, role: str = "body") -> QLabel:
    widget = QLabel(text)
    widget.setProperty("role", role)
    widget.setWordWrap(True)
    widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return widget


def button(text: str, role: str = "secondary", icon: QStyle.StandardPixmap | None = None) -> QPushButton:
    widget = QPushButton(text.replace("&", "&&"))
    widget.setProperty("role", role)
    widget.setMinimumHeight(40)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    if icon is not None:
        widget.setIcon(widget.style().standardIcon(icon))
        widget.setIconSize(QSize(18, 18))
    return widget


def row(*widgets: QWidget) -> QHBoxLayout:
    layout = QHBoxLayout()
    layout.setSpacing(10)
    for widget in widgets:
        layout.addWidget(widget)
    return layout


class Page(QScrollArea):
    def __init__(self, title: str, subtitle: str = "") -> None:
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName("page")
        self.body = QVBoxLayout(content)
        self.body.setContentsMargins(30, 24, 30, 24)
        self.body.setSpacing(18)
        self.body.addWidget(label(title, "title"))
        if subtitle:
            self.body.addWidget(label(subtitle, "muted"))
        self.setWidget(content)

    def section(self, title: str) -> QVBoxLayout:
        divider = QFrame()
        divider.setObjectName("section")
        layout = QVBoxLayout(divider)
        layout.setContentsMargins(0, 16, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(label(title, "section"))
        self.body.addWidget(divider)
        return layout


class RemotePad(QWidget):
    key = Signal(str)
    stop = Signal()
    sound = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("remotePad")
        self.setFixedWidth(292)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Maximum)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)
        self.controls: list[QWidget] = []
        layout.addLayout(row(self.command("Back", "back", QStyle.StandardPixmap.SP_ArrowBack),
                             self.command("Home", "home", QStyle.StandardPixmap.SP_DirHomeIcon),
                             self.command("Menu", "menu", QStyle.StandardPixmap.SP_FileDialogListView)))
        self.dpad = DPadWidget()
        self.dpad.key.connect(self.key)
        self.controls.append(self.dpad)
        layout.addWidget(self.dpad, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addLayout(row(self.command("Volume down", "volume_down", QStyle.StandardPixmap.SP_ArrowDown),
                             self.command("Mute", "mute", QStyle.StandardPixmap.SP_MediaVolumeMuted),
                             self.command("Volume up", "volume_up", QStyle.StandardPixmap.SP_MediaVolume)))
        sound = button("Test Sound", icon=QStyle.StandardPixmap.SP_MediaVolume)
        sound.clicked.connect(self.sound)
        stop = button("Stop Google TV", "danger", QStyle.StandardPixmap.SP_MediaStop)
        stop.clicked.connect(self.stop)
        self.controls.extend([sound, stop])
        layout.addWidget(sound)
        layout.addWidget(stop)

    def command(self, title: str, key: str, icon: QStyle.StandardPixmap | None = None) -> QPushButton:
        control = button("" if icon is not None else title, icon=icon)
        control.setToolTip(title)
        control.setAccessibleName(title)
        control.setObjectName(f"remote_{key}")
        control.clicked.connect(lambda _checked=False: self.key.emit(key))
        self.controls.append(control)
        return control

    def set_available(self, available: bool) -> None:
        for control in self.controls:
            control.setEnabled(available)


class RemoteWindow(QWidget):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle("Salem Remote")
        self.setWindowIcon(QIcon(str(resource_path("assets/salem_google_tv_emulator.ico"))))
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addWidget(label("Salem Remote", "section"))
        self.status = label("Remote unavailable", "muted")
        self.status.setMaximumWidth(292)
        layout.addWidget(self.status)
        self.top = QCheckBox("Always on top")
        self.top.toggled.connect(self.set_top)
        layout.addWidget(self.top)
        self.pad = RemotePad()
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.scroll.setWidget(self.pad)
        self.scroll.setMinimumHeight(160)
        layout.addWidget(self.scroll)
        self.setMinimumWidth(344)
        available = self.screen().availableGeometry()
        self.resize(344, min(660, max(320, available.height() - 80)))

    def set_top(self, enabled: bool) -> None:
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, enabled)
        self.show()


def app_logo(size: int) -> QLabel:
    widget = QLabel()
    widget.setFixedSize(size, size)
    pixmap = QPixmap(str(resource_path("assets/salem_google_tv_emulator.png")))
    widget.setPixmap(pixmap.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
    return widget
