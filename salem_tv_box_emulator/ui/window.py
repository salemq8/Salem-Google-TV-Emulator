"""Coordinate views and services. Slow engine operations never execute in Qt callbacks."""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import QEvent, Qt, QTimer, QUrl
from PySide6.QtGui import QCloseEvent, QDesktopServices, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLineEdit, QMainWindow, QMessageBox,
    QPlainTextEdit, QStackedWidget, QStatusBar, QStyle, QVBoxLayout, QWidget, QFileDialog, QAbstractSpinBox, QComboBox,
)

from .. import __app_name__, __version__
from ..android_backend import (
    EmulatorController, PerformanceSettings, ToolPaths,
    apply_google_tv_performance_settings, apply_salem_sdk_environment,
    detect_android_tools, find_google_tv_avd, list_avds,
)
from ..config import APP_LOGS, SettingsStore, resource_path
from ..services.support import sanitize
from ..services.diagnostics import collect_diagnostics
from ..services.tasks import TaskRunner
from ..services.tv_mode import TVMode
from ..services.session import RemoteService
from ..styles import stylesheet
from ..windows_features import check_hypervisor_features
from .components import RemoteWindow, app_logo, button, label, row
from .management import DiagnosticsPage, HelpPage, PreferencesPage, SetupPage
from .pages import ControlsPage, HomePage, PerformancePage, TVPage
from .preferences_controller import PreferencesController
from .setup_controller import SetupController


MAX_PENDING_REMOTE_COMMANDS = 16


class SalemMainWindow(QMainWindow):
    def __init__(self, *, auto_discover: bool = True, settings_store: SettingsStore | None = None) -> None:
        super().__init__()
        self.setWindowTitle(f"{__app_name__} v{__version__}")
        self.setWindowIcon(QIcon(str(resource_path("assets/salem_google_tv_emulator.ico"))))
        self.resize(1060, 800)
        self.setMinimumSize(780, 520)
        self.settings_store = settings_store or SettingsStore()
        self.settings = self.settings_store.load()
        self.tasks = TaskRunner(self)
        self.controller = EmulatorController(ToolPaths(None, None, None, None, None))
        self.remote_service = RemoteService(self.controller)
        self.avds = []
        self.mode = TVMode()
        self.busy = False
        self.running = False
        self.launching = False
        self.deadline = 0.0
        self.sequence = 0
        self.hypervisor = "Not checked"
        self.remote_window: RemoteWindow | None = None
        self._build_ui()
        self.setup_actions = SetupController(self)
        self.preferences_actions = PreferencesController(self)
        self._connect_actions()
        self.poll = QTimer(self)
        self.poll.setInterval(1500)
        self.poll.timeout.connect(self.poll_device)
        self.poll.start()
        self.f11 = QShortcut(QKeySequence("F11"), self)
        self.f11.activated.connect(self.toggle_tv)
        QApplication.instance().installEventFilter(self)
        QApplication.instance().setStyleSheet(stylesheet(self.settings.theme))
        self.refresh()
        if self.settings_store.warning:
            self.notify(self.settings_store.warning)
        if auto_discover:
            QTimer.singleShot(0, self.discover)
            QTimer.singleShot(500, self.check_hypervisor)
            QTimer.singleShot(1500, self.setup_actions.resume)
            if self.settings.auto_update:
                QTimer.singleShot(2500, self.preferences_actions.check)

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(208)
        nav = QVBoxLayout(sidebar)
        nav.setContentsMargins(14, 22, 14, 16)
        nav.setSpacing(6)
        nav.addLayout(row(app_logo(38), label("SALEM", "section")))
        nav.addSpacing(20)
        self.home = HomePage()
        self.controls = ControlsPage()
        self.tv = TVPage()
        self.performance = PerformancePage()
        self.setup_page = SetupPage()
        self.diagnostics = DiagnosticsPage()
        self.preferences = PreferencesPage(self.settings)
        self.help = HelpPage(self.settings)
        self.pages = {"home": self.home, "controls": self.controls, "tv": self.tv, "performance": self.performance,
                      "setup": self.setup_page, "diagnostics": self.diagnostics, "preferences": self.preferences, "help": self.help}
        names = ["Overview", "Remote & input", "TV Mode", "Performance", "Setup & repair", "Diagnostics", "Preferences", "Help & updates"]
        icons = [QStyle.StandardPixmap.SP_ComputerIcon, QStyle.StandardPixmap.SP_ArrowRight,
                 QStyle.StandardPixmap.SP_TitleBarMaxButton, QStyle.StandardPixmap.SP_DriveHDIcon,
                 QStyle.StandardPixmap.SP_BrowserReload, QStyle.StandardPixmap.SP_FileDialogDetailedView,
                 QStyle.StandardPixmap.SP_FileDialogContentsView, QStyle.StandardPixmap.SP_DialogHelpButton]
        self.stack = QStackedWidget()
        self.navigation = {}
        for (key, page), name, icon in zip(self.pages.items(), names, icons):
            control = button(name, icon=icon)
            control.setObjectName("nav")
            control.setCheckable(True)
            control.clicked.connect(lambda _checked=False, name=key: self.navigate(name))
            nav.addWidget(control)
            self.stack.addWidget(page)
            self.navigation[key] = control
        nav.addStretch()
        self.sidebar_status = label("Checking engine", "muted")
        nav.addWidget(self.sidebar_status)
        nav.addWidget(label(f"Version {__version__}", "muted"))
        layout.addWidget(sidebar)
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(root)
        self.setStatusBar(QStatusBar())
        self.navigate("home")

    def _connect_actions(self) -> None:
        bindings = [
            (self.home.launch, self.launch), (self.home.stop, self.stop), (self.home.restart, self.restart),
            (self.home.enter_tv, self.enter_tv), (self.tv.enter, self.enter_tv),
            (self.home.exit_tv, self.exit_tv), (self.tv.exit, self.exit_tv),
            (self.home.popout, self.open_remote), (self.controls.popout, self.open_remote),
            (self.home.remote, lambda: self.navigate("controls")),
            (self.controls.send, self.send_text), (self.home.install, self.install_apk),
            (self.performance.apply, self.optimize), (self.performance.network, self.network),
            (self.setup_page.refresh, self.discover),
            (self.setup_page.install, self.setup_actions.start), (self.setup_page.retry, self.setup_actions.start),
            (self.setup_page.repair, lambda: self.setup_actions.start(repair=True)),
            (self.home.repair, lambda: self.setup_actions.start(repair=True)),
            (self.diagnostics.refresh, self.refresh_diagnostics), (self.diagnostics.copy, self.copy_diagnostics),
            (self.help.copy, self.copy_diagnostics), (self.diagnostics.logs, self.open_logs), (self.help.logs, self.open_logs),
            (self.help.setup_log, self.open_setup_log), (self.setup_page.setup_log, self.open_setup_log),
            (self.preferences.save, self.preferences_actions.save), (self.preferences.reset, self.preferences_actions.reset),
            (self.preferences.cleanup, self.preferences_actions.cleanup), (self.help.check, self.preferences_actions.check),
            (self.help.release, self.preferences_actions.open_release), (self.help.mail, self.preferences_actions.support),
        ]
        for control, callback in bindings:
            control.clicked.connect(lambda _checked=False, action=callback: action())
        self.controls.text.returnPressed.connect(self.send_text)
        self.connect_pad(self.controls.pad)

    def connect_pad(self, pad) -> None:
        pad.key.connect(self.remote_key)
        pad.stop.connect(self.stop)
        pad.sound.connect(self.test_sound)

    def navigate(self, key: str) -> None:
        self.stack.setCurrentWidget(self.pages[key])
        for name, control in self.navigation.items():
            control.setChecked(name == key)

    def discover(self, launch_after: bool = False) -> None:
        if self.busy:
            return
        def find():
            apply_salem_sdk_environment()
            tools = detect_android_tools()
            return tools, list_avds(tools)
        def found(result):
            self.controller.tools, self.avds = result
            avd = find_google_tv_avd(self.avds)
            if avd:
                self.performance.summary.setText(f"{avd.name} | RAM {avd.config.get('hw.ramSize', '?')} MB | CPU {avd.config.get('hw.cpu.ncore', '?')} | GPU {avd.config.get('hw.gpu.mode', 'default')}")
            self.refresh()
            self.notify("Engine check complete.")
            if launch_after:
                self.launch()
        self.tasks.submit("discover", find, found, self.fail)

    def refresh(self) -> None:
        ready = bool(self.controller.tools.ready and find_google_tv_avd(self.avds))
        online = self.running and self.controller.session.ready
        enabled = not self.busy
        state = "Starting Google TV..." if self.launching else ("Google TV running" if self.running else ("Ready to launch" if ready else "Engine setup required"))
        self.home.state.setText(state)
        self.sidebar_status.setText(state)
        serial = f"{self.controller.session.state.value} | {self.controller.device_serial or 'No active device'}"
        self.home.serial.setText(serial)
        self.controls.serial.setText(serial)
        self.home.engine_status.setText("Google TV engine installed" if ready else "Set up the engine to get started.")
        self.home.launch.setEnabled(ready and enabled and not self.running)
        self.home.restart.setEnabled(ready and enabled)
        self.home.stop.setEnabled(self.running and enabled)
        self.home.install.setEnabled(online and enabled)
        self.performance.apply.setEnabled(ready and enabled and not self.running)
        self.performance.network.setEnabled(online and enabled)
        for control in [self.setup_page.install, self.setup_page.retry, self.setup_page.repair, self.home.repair, self.setup_page.refresh]:
            control.setEnabled(enabled and not self.running)
        for control in [self.home.enter_tv, self.tv.enter]:
            control.setEnabled(self.running and enabled and not self.mode.active)
        for control in [self.home.exit_tv, self.tv.exit]:
            control.setEnabled(self.mode.active and enabled)
        self.controls.pad.set_available(online and enabled)
        self.controls.send.setEnabled(online and enabled)
        self.controls.text.setEnabled(online and enabled)
        if self.remote_window:
            self.remote_window.pad.set_available(online and enabled)
            self.remote_window.status.setText(serial)
        self.tv.status.setText(self.mode.message)
        self.home.tv_status.setText(self.mode.message)
        self.tv.details.setPlainText(json.dumps(asdict(self.mode), default=str, indent=2))

    def set_busy(self, busy: bool, message: str) -> None:
        self.busy = busy
        self.refresh()
        self.notify(message)

    def notify(self, message: str) -> None:
        logging.getLogger(__name__).info(message)
        self.statusBar().showMessage(message.splitlines()[0], 12000)
        self.home.activity.setText(message.splitlines()[0][:240])
        self.diagnostics.activity.appendPlainText(f"{time.strftime('%H:%M:%S')}  {message}")

    def fail(self, error: Exception) -> None:
        self.set_busy(False, f"Action failed: {error}")

    def launch(self, restart: bool = False) -> None:
        if self.busy or (self.running and not restart):
            return
        avd = find_google_tv_avd(self.avds)
        if not avd:
            self.navigate("setup")
            self.notify("Google TV profile is missing. Set up the engine first.")
            return
        if restart and not self.exit_tv():
            return
        if restart:
            self.controller.session.stopping()
        self.set_busy(True, "Restarting Google TV..." if restart else "Launching Google TV...")
        work = (lambda: self.controller.restart_with_info(avd, wait_for_serial=False)) if restart else (
            lambda: self.controller.start_with_info(avd, wait_for_serial=False))
        self.tasks.submit("launch", work, self.launched, self.fail)

    def launched(self, result) -> None:
        self.running = True
        self.launching = True
        self.deadline = time.monotonic() + 90
        self.set_busy(False, f"Google TV process {result.pid} started. Waiting for device...")
        self.refresh_diagnostics()

    def restart(self) -> None:
        self.launch(restart=True)

    def stop(self) -> None:
        if self.busy or not self.running or not self.exit_tv():
            return
        self.set_busy(True, "Stopping Google TV...")
        self.controller.session.stopping()
        self.tasks.submit("stop", self.controller.stop, self.stopped, self.fail)

    def stopped(self, _result) -> None:
        self.running = False
        self.launching = False
        self.set_busy(False, "Google TV stopped.")
        self.refresh_diagnostics()

    def poll_device(self) -> None:
        if self.busy or not self.running:
            return
        process = self.controller.process
        if process and process.poll() is not None:
            self.controller.session.invalidate()
            self.running = self.launching = False
            self.notify("Google TV process exited. See emulator log in Diagnostics.")
            self.refresh()
            return
        if self.launching and time.monotonic() >= self.deadline:
            self.launching = False
            self.notify("No device detected within 90 seconds. Open Diagnostics for the emulator log.")
            self.refresh_diagnostics()
        self.poll.setInterval(1500 if self.launching else 5000)
        self.tasks.submit("serial", self.controller.refresh_device_serial, self.serial_found, self.poll_failed)

    def serial_found(self, serial: str | None) -> None:
        if serial and self.running and self.launching:
            self.launching = False
            self.notify(f"Google TV connected: {serial}")
        self.refresh()

    def poll_failed(self, error: Exception) -> None:
        self.notify(f"Device discovery: {error}")

    def remote_key(self, key: str) -> None:
        if not self.running or not self.controller.session.ready or self.busy:
            return
        if self.tasks.pending_count("remote-") >= MAX_PENDING_REMOTE_COMMANDS:
            self.notify("Remote busy. This key was not queued; wait for pending commands to finish.")
            return
        self.sequence += 1
        generation = self.controller.session.generation
        self.tasks.submit(f"remote-{self.sequence}", lambda: self.remote_service.key(key, generation),
                          lambda output: self.notify(str(output)), lambda error: self.notify(f"Remote failed: {error}"))

    def send_text(self) -> None:
        text = self.controls.text.text()
        if not text or self.busy or not self.controller.session.ready:
            return
        self.set_busy(True, "Sending text...")
        self.controls.text_status.setText("Sending...")
        def sent(output):
            self.controls.text_status.setText(str(output))
            self.set_busy(False, "Text command completed.")
        def failed(error):
            self.controls.text_status.setText(f"Text input failed: {error}")
            self.fail(error)
        generation = self.controller.session.generation
        self.tasks.submit("text", lambda: self.remote_service.text(text, generation), sent, failed)

    def test_sound(self) -> None:
        generation = self.controller.session.generation
        self.tasks.submit("sound", lambda: self.remote_service.sound(generation), lambda output: self.notify(str(output)), self.fail)

    def open_remote(self) -> None:
        if self.remote_window is None:
            self.remote_window = RemoteWindow(self)
            self.connect_pad(self.remote_window.pad)
            self.remote_window.destroyed.connect(self.remote_closed)
            self.remote_window.top.setChecked(self.settings.remote_always_on_top)
        self.remote_window.show()
        self.remote_window.raise_()
        self.refresh()

    def remote_closed(self) -> None:
        self.remote_window = None

    def enter_tv(self) -> None:
        if not self.running or self.busy:
            return
        launch = self.controller.launch_info
        try:
            self.mode.enter(launch.pid if launch else None, launch.avd_name if launch else None)
        except Exception as exc:
            self.mode.message = f"TV Mode failed: {exc}"
        self.notify(self.mode.message)
        self.refresh()
        self.refresh_diagnostics()

    def exit_tv(self) -> bool:
        try:
            self.mode.restore()
        except Exception as exc:
            self.notify(f"Window restore failed: {exc}")
            return False
        self.refresh()
        return True

    def toggle_tv(self) -> None:
        self.exit_tv() if self.mode.active else self.enter_tv()

    def install_apk(self) -> None:
        name, _ = QFileDialog.getOpenFileName(self, "Install APK", str(Path.home()), "APK files (*.apk)")
        if name:
            self.set_busy(True, "Installing APK...")
            self.tasks.submit("apk", lambda: self.controller.install_apk(Path(name)),
                              lambda output: self.set_busy(False, str(output)), self.fail)

    def optimize(self) -> None:
        avd = find_google_tv_avd(self.avds)
        if not avd or self.running or self.busy:
            return
        settings = PerformanceSettings(self.performance.ram.value(), self.performance.cpus.value(), self.performance.gpu.isChecked())
        self.set_busy(True, "Applying performance settings...")
        def done(output):
            self.performance.status.setText(str(output))
            self.set_busy(False, "Performance settings saved.")
            self.discover()
        self.tasks.submit("performance", lambda: apply_google_tv_performance_settings(avd, settings), done, self.fail)

    def network(self) -> None:
        self.tasks.submit("network", self.controller.network_status,
                          lambda output: self.performance.output.setPlainText(str(output)),
                          lambda error: self.performance.output.setPlainText(str(error)))

    def refresh_diagnostics(self) -> None:
        self.tasks.submit("diagnostics", lambda: collect_diagnostics(self.controller, self.mode, self.hypervisor),
                          lambda output: self.diagnostics.runtime.setPlainText(str(output)),
                          lambda error: self.diagnostics.runtime.setPlainText(f"Diagnostics failed: {error}"))

    def copy_diagnostics(self) -> None:
        text = "\n\n".join(editor.toPlainText() for editor in (self.diagnostics.runtime, self.diagnostics.setup, self.diagnostics.activity))
        QApplication.clipboard().setText(sanitize(text or f"{__app_name__} v{__version__}\nDevice: {self.controller.device_serial or 'none'}"))
        self.notify("Support diagnostics copied. Review before sharing.")

    def open_logs(self) -> None:
        try:
            APP_LOGS.mkdir(parents=True, exist_ok=True)
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(APP_LOGS))):
                raise RuntimeError(f"Windows could not open {APP_LOGS}")
        except (OSError, RuntimeError) as exc:
            self.fail(exc)

    def open_setup_log(self) -> None:
        path = APP_LOGS / "setup.log"
        if not path.exists():
            self.notify("Setup has not written a log yet.")
        elif not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            self.notify(f"Windows could not open {path}")

    def check_hypervisor(self) -> None:
        def done(status):
            self.hypervisor = status.to_text()
        self.tasks.submit("hypervisor", check_hypervisor_features, done,
                          lambda error: self.notify(f"Virtualization check unavailable: {error}"), engine=False)

    def eventFilter(self, watched, event) -> bool:
        if event.type() != QEvent.Type.KeyPress or not isinstance(watched, QWidget):
            return False
        if watched.window() not in (self, self.remote_window):
            return False
        if watched is self.controls.text and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.send_text()
            return True
        if isinstance(watched, (QLineEdit, QPlainTextEdit, QAbstractSpinBox, QComboBox)):
            return False
        if event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.MetaModifier):
            return False
        keys = {Qt.Key.Key_Up: "up", Qt.Key.Key_Down: "down", Qt.Key.Key_Left: "left", Qt.Key.Key_Right: "right",
                Qt.Key.Key_Return: "ok", Qt.Key.Key_Enter: "ok", Qt.Key.Key_Escape: "back", Qt.Key.Key_Backspace: "back", Qt.Key.Key_Home: "home"}
        if event.key() in keys and self.controller.device_serial:
            self.remote_key(keys[event.key()])
            return True
        return False

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.setup_actions.running or self.busy:
            QMessageBox.information(self, "Operation in progress", "Wait for the current operation to finish before closing Salem.")
            event.ignore()
            return
        if not self.exit_tv():
            event.ignore()
            return
        self.poll.stop()
        QApplication.instance().removeEventFilter(self)
        if self.remote_window:
            self.remote_window.close()
        self.tasks.close()
        event.accept()
