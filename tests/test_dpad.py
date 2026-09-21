from math import ceil, hypot, sqrt
from pathlib import Path
import subprocess
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest

from salem_tv_box_emulator.android_backend import ToolPaths
from salem_tv_box_emulator.config import SettingsStore
from salem_tv_box_emulator.services.session import SessionState
from salem_tv_box_emulator.styles import stylesheet
from salem_tv_box_emulator.ui.dpad import DPadWidget
from salem_tv_box_emulator.ui.window import SalemMainWindow


@pytest.fixture(params=[252, 378, 504], ids=["100pct", "150pct", "200pct"])
def pad(request, qapp):
    widget = DPadWidget()
    widget.resize(request.param, request.param)
    widget.show()
    qapp.processEvents()
    yield widget
    widget.close()


def point(pad, dx, dy):
    center, outer, _ = pad.geometry_values()
    # Round offsets symmetrically so a diagonal remains a diagonal at 150%.
    return (center + QPointF(round(dx * outer), round(dy * outer))).toPoint()


@pytest.mark.parametrize("dx,dy,expected", [
    (0, 0, "ok"), (0, -.65, "up"), (0, -.97, "up"),
    (0, .7, "down"), (-.7, 0, "left"), (.7, 0, "right"),
    (-.5, -.5, "up"), (.5, -.5, "up"), (-.5, .5, "down"), (.5, .5, "down"),
    (.25, .25, "down"),  # Inside the old center rectangle, outside its circle.
])
def test_click_regions_emit_once(pad, dx, dy, expected):
    received = []
    pad.key.connect(received.append)
    QTest.mouseClick(pad, Qt.MouseButton.LeftButton, pos=point(pad, dx, dy))
    assert received == [expected]
    assert pad.pressed_region is None


def test_center_and_outer_boundaries(pad):
    received = []
    pad.key.connect(received.append)
    center, outer, inner = pad.geometry_values()
    edge = center + QPointF(inner, 0)
    QTest.mouseClick(pad, Qt.MouseButton.LeftButton, pos=edge.toPoint())
    assert received == ["ok"]
    QTest.mouseClick(pad, Qt.MouseButton.LeftButton, pos=(edge + QPointF(1, 0)).toPoint())
    assert received == ["ok", "right"]
    assert pad.hit_test(center + QPointF(0, -outer)) == "up"
    assert pad.hit_test(center + QPointF(0, -outer - .01)) is None
    diagonal = ceil(outer / sqrt(2)) + 1
    outside = center + QPointF(diagonal, diagonal)
    QTest.mouseClick(pad, Qt.MouseButton.LeftButton, pos=outside.toPoint())
    assert received == ["ok", "right"]


def test_complete_partition_no_gaps_or_overlaps(pad):
    center, outer, inner = pad.geometry_values()
    for x in range(0, pad.width(), 3):
        for y in range(0, pad.height(), 3):
            dx, dy = x - center.x(), y - center.y()
            radius = hypot(dx, dy)
            expected = None if radius > outer else (
                "ok" if radius <= inner else
                ("right" if dx > 0 else "left") if abs(dx) > abs(dy) else
                ("down" if dy > 0 else "up")
            )
            assert pad.hit_test(QPointF(x, y)) == expected


def test_exact_diagonals_and_both_sides(pad):
    center, outer, _ = pad.geometry_values()
    for xsign in (-1, 1):
        for ysign in (-1, 1):
            offset = QPointF(xsign * outer / 2, ysign * outer / 2)
            vertical = "up" if ysign < 0 else "down"
            horizontal = "left" if xsign < 0 else "right"
            assert pad.hit_test(center + offset) == vertical
            assert pad.hit_test(center + offset + QPointF(xsign * .1, 0)) == horizontal
            assert pad.hit_test(center + offset + QPointF(0, ysign * .1)) == vertical


def move(pad, position, buttons=Qt.MouseButton.NoButton):
    event = QMouseEvent(QEvent.Type.MouseMove, QPointF(position), QPointF(position),
                        Qt.MouseButton.NoButton, buttons, Qt.KeyboardModifier.NoModifier)
    QCoreApplication.sendEvent(pad, event)


def test_hover_pressed_cursor_and_release(pad):
    received = []
    pad.key.connect(received.append)
    upper, lower = point(pad, 0, -.9), point(pad, 0, .9)
    move(pad, upper)
    assert pad.hover_region == "up"
    assert pad.cursor().shape() == Qt.CursorShape.PointingHandCursor
    QTest.mousePress(pad, Qt.MouseButton.LeftButton, pos=upper)
    assert received == ["up"] and pad.pressed_region == "up"
    move(pad, lower, Qt.MouseButton.LeftButton)
    assert pad.hover_region == "down"
    QTest.mouseRelease(pad, Qt.MouseButton.LeftButton, pos=lower)
    assert received == ["up"] and pad.pressed_region is None
    move(pad, point(pad, .9, .9))
    assert pad.hover_region is None
    assert pad.cursor().shape() == Qt.CursorShape.ArrowCursor
    QTest.mouseClick(pad, Qt.MouseButton.RightButton, pos=upper)
    assert received == ["up"]
    pad.setEnabled(False)
    QTest.mouseClick(pad, Qt.MouseButton.LeftButton, pos=upper)
    assert received == ["up"] and pad.hover_region is None


def test_double_click_is_two_physical_presses_not_three(pad):
    received = []
    pad.key.connect(received.append)
    pos = point(pad, 0, 0)
    QTest.mouseClick(pad, Qt.MouseButton.LeftButton, pos=pos)
    QTest.mouseDClick(pad, Qt.MouseButton.LeftButton, pos=pos)
    QTest.mouseRelease(pad, Qt.MouseButton.LeftButton, pos=pos)
    assert received == ["ok", "ok"]


def test_geometry_recomputed_on_resize(pad):
    pad.resize(pad.width() + 100, pad.height())
    center, outer, inner = pad.geometry_values()
    assert center == QPointF(pad.width() / 2, pad.height() / 2)
    assert outer == pad.height() / 2
    assert pad.hit_test(center) == "ok"
    assert pad.hit_test(center + QPointF(inner + 1, 0)) == "right"
    assert pad.hit_test(QPointF(1, center.y())) is None


@pytest.mark.parametrize("theme", ["Dark", "Light"])
def test_paint_uses_same_center_and_hover_sector(pad, qapp, theme):
    pad.setStyleSheet(stylesheet(theme))
    qapp.processEvents()
    base = pad.grab().toImage()
    center = point(pad, 0, 0)
    upper = point(pad, .2, -.75)
    lower = point(pad, .2, .75)
    move(pad, upper)
    hover = pad.grab().toImage()
    # QImage pixels are physical; convert the logical test points at real DPI too.
    def color(image, pos):
        scale = image.devicePixelRatio()
        return image.pixelColor(round(pos.x() * scale), round(pos.y() * scale))
    assert color(base, upper) != color(hover, upper)
    assert color(base, lower) == color(hover, lower)
    assert color(base, center) == color(hover, center)
    assert pad.get_theme() == theme


@pytest.mark.parametrize("popout", [False, True], ids=["main", "popout"])
@pytest.mark.parametrize("size", [252, 378, 504], ids=["100pct", "150pct", "200pct"])
@pytest.mark.parametrize("dx,dy,code", [(0, -.95, "19"), (0, .8, "20"), (-.8, 0, "21"), (.8, 0, "22"), (0, 0, "23")])
def test_shared_service_maps_one_click_to_one_adb_command(qapp, pump, tmp_path, monkeypatch, popout, size, dx, dy, code):
    view = SalemMainWindow(auto_discover=False, settings_store=SettingsStore(tmp_path / "settings.json"))
    view.poll.stop()
    view.controller.tools = ToolPaths(None, None, Path("adb.exe"), None, None)
    session = view.controller.session
    session.serial, session.adb_state, session.boot_completed = "emulator-5554", "device", True
    session.state = SessionState.READY
    view.running = True
    run = Mock(side_effect=lambda command, **_: subprocess.CompletedProcess(command, 0, "", ""))
    monkeypatch.setattr(subprocess, "run", run)
    try:
        if popout:
            view.open_remote()
        view.refresh()
        widget = view.remote_window.pad.dpad if popout else view.controls.pad.dpad
        widget.setFixedSize(size, size)
        QTest.mouseClick(widget, Qt.MouseButton.LeftButton, pos=point(widget, dx, dy))
        pump(lambda: not view.tasks.callbacks)
        assert run.call_count == 1
        assert run.call_args.args[0] == ["adb.exe", "-s", "emulator-5554", "shell", "input", "keyevent", code]
        assert view.sequence == 1
        assert view.tasks.pending_count("remote-") == 0
    finally:
        view.close()
        qapp.processEvents()
