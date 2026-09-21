from types import SimpleNamespace
from threading import Event
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QTest

from salem_tv_box_emulator.config import SettingsStore
from salem_tv_box_emulator.services.tasks import TaskRunner
from salem_tv_box_emulator.services.session import SessionState
from salem_tv_box_emulator.ui.window import MAX_PENDING_REMOTE_COMMANDS, SalemMainWindow


@pytest.fixture
def window(qapp, tmp_path):
    view = SalemMainWindow(auto_discover=False, settings_store=SettingsStore(tmp_path / "settings.json"))
    view.poll.stop()
    view.controller.session.state = SessionState.READY
    view.controller.session.adb_state = "device"
    view.controller.session.boot_completed = True
    view.show()
    qapp.processEvents()
    yield view
    view.busy = False
    view.mode.state = None
    view.close()
    qapp.processEvents()


def test_ordered_tasks_and_errors(qapp, pump):
    runner = TaskRunner(qapp)
    results, errors = [], []
    for number in range(10):
        assert runner.submit(str(number), lambda n=number: n, results.append, errors.append)
    def fail():
        raise ValueError("expected")
    runner.submit("failure", fail, results.append, errors.append)
    pump(lambda: len(results) == 10 and len(errors) == 1)
    assert results == list(range(10))
    assert isinstance(errors[0], ValueError)
    runner.close()


def test_popout_shared_backend_and_close(window, qapp, pump):
    window.running = True
    window.controller.session.serial = "emulator-5580"
    window.controller.send_remote_key = Mock(return_value="sent")
    window.controller.stop = Mock()
    window.open_remote()
    window.remote_window.top.setChecked(True)
    assert window.remote_window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    window.controls.pad.key.emit("up")
    window.remote_window.pad.key.emit("down")
    pump(lambda: window.controller.send_remote_key.call_count == 2)
    assert [call.args[0] for call in window.controller.send_remote_key.call_args_list] == ["up", "down"]
    window.remote_window.close()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()
    assert window.remote_window is None
    window.controller.stop.assert_not_called()


def test_text_field_does_not_send_remote(window, qapp, pump):
    window.running = True
    window.controller.session.serial = "emulator-5580"
    window.controller.send_text = Mock(return_value="Text sent")
    window.controller.send_remote_key = Mock()
    window.refresh()
    window.navigate("controls")
    window.controls.text.setFocus()
    QTest.keyClicks(window.controls.text, "Salem 123")
    QTest.keyClick(window.controls.text, Qt.Key.Key_Return)
    pump(lambda: not window.busy)
    window.controller.send_text.assert_called_once_with("Salem 123")
    window.controller.send_remote_key.assert_not_called()


def test_text_failure_visible(window, pump):
    window.running = True
    window.controller.session.serial = "emulator-5580"
    window.controller.send_text = Mock(side_effect=RuntimeError("clipboard unavailable"))
    window.controls.text.setText("مرحبا")
    window.send_text()
    pump(lambda: not window.busy)
    assert "failed" in window.controls.text_status.text()
    assert "clipboard" in window.controls.text_status.text()


def test_diagnostics_copy_and_activity_preserved(window, qapp):
    window.notify("test message")
    window.refresh()
    assert "test message" in window.diagnostics.activity.toPlainText()
    window.diagnostics.runtime.setPlainText("PID: 123\nDevice: emulator-5580")
    window.copy_diagnostics()
    assert qapp.clipboard().text().startswith("PID: 123")


def test_f11_toggles(window, qapp, monkeypatch):
    actions = []
    monkeypatch.setattr(window, "enter_tv", lambda: actions.append("enter"))
    monkeypatch.setattr(window, "exit_tv", lambda: actions.append("exit"))
    window.f11.activated.emit()
    window.mode.state = SimpleNamespace()
    window.f11.activated.emit()
    assert actions == ["enter", "exit"]


def test_close_does_not_stop_engine(window):
    window.controller.stop = Mock()
    window.running = True
    window.close()
    window.controller.stop.assert_not_called()


def test_stop_restores_before_engine(window, monkeypatch, pump):
    sequence = []
    window.running = True
    monkeypatch.setattr(window, "exit_tv", lambda: sequence.append("restore") or True)
    monkeypatch.setattr(window.controller, "stop", lambda: sequence.append("stop"))
    window.stop()
    pump(lambda: not window.busy)
    assert sequence == ["restore", "stop"]


def test_small_screen_popout_scrolls_without_hiding_controls(window, qapp):
    window.open_remote()
    remote = window.remote_window
    remote.resize(344, 390)
    qapp.processEvents()
    assert remote.height() == 390
    assert remote.scroll.verticalScrollBar().maximum() > 0
    remote.scroll.verticalScrollBar().setValue(remote.scroll.verticalScrollBar().maximum())
    assert remote.pad.controls[-1].isVisible()


def test_remote_backpressure_preserves_order_and_recovers(window, pump):
    gate = Event()
    window.running = True
    window.controller.session.serial = "emulator-5580"
    window.controller.send_remote_key = Mock(return_value="sent")
    window.tasks.submit("test-blocker", lambda: gate.wait(5), lambda _: None, lambda _: None)
    keys = ["up", "down", "left", "right"] * (MAX_PENDING_REMOTE_COMMANDS // 4)
    try:
        for key in keys:
            window.remote_key(key)
        window.remote_key("ok")
        assert window.tasks.pending_count("remote-") == MAX_PENDING_REMOTE_COMMANDS
        assert "not queued" in window.home.activity.text()
        window.controller.send_remote_key.assert_not_called()
    finally:
        gate.set()
    pump(lambda: window.tasks.pending_count("remote-") == 0)
    assert [call.args[0] for call in window.controller.send_remote_key.call_args_list] == keys
    window.remote_key("home")
    pump(lambda: window.tasks.pending_count("remote-") == 0)
    window.controller.send_remote_key.assert_called_with("home")


def test_stop_is_accepted_with_full_remote_queue(window, pump):
    gate = Event()
    window.running = True
    window.controller.session.serial = "emulator-5580"
    window.controller.send_remote_key = Mock(return_value="sent")
    window.controller.stop = Mock()
    window.tasks.submit("test-blocker", lambda: gate.wait(5), lambda _: None, lambda _: None)
    try:
        for _ in range(MAX_PENDING_REMOTE_COMMANDS):
            window.remote_key("up")
        window.stop()
        assert "stop" in window.tasks.callbacks
        assert window.busy
    finally:
        gate.set()
    pump(lambda: not window.busy)
    window.controller.stop.assert_called_once()
    window.controller.send_remote_key.assert_not_called()
