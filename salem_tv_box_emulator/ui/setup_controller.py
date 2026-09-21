"""Setup presentation and explicit license/feature confirmation."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QMessageBox

from ..android_backend import apply_salem_sdk_environment
from ..services.engine_setup import RepairResult, repair_engine
from ..setup_wizard import SETUP_STAGES, SetupProgress, SetupResult
from ..windows_features import load_pending_fix_launch

if TYPE_CHECKING:
    from .window import SalemMainWindow


class SetupController(QObject):
    progress = Signal(object)

    def __init__(self, window: SalemMainWindow) -> None:
        super().__init__(window)
        self.window = window
        self.running = False
        self.stage = ""
        self.completed: set[str] = set()
        self.launch_after = False
        self.progress.connect(self.on_progress)

    def start(self, repair: bool = False, resume: bool = False) -> None:
        w = self.window
        if self.running or w.busy or w.running:
            w.notify("Stop Google TV before running engine setup.")
            return
        if not resume:
            text = ("Download and install the official Google TV engine and portable JDK 21? "
                    "Continuing authorizes Salem to accept the Android SDK licenses.")
            text += "\n\nWindows virtualization features will also be checked. Changes require administrator approval and may require a restart."
            if QMessageBox.question(w, "Google TV engine", text,
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                    QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                return
        self.running = True
        self.launch_after = repair
        self.completed.clear()
        w.navigate("setup")
        w.set_busy(True, "Preparing engine...")
        package = w.setup_page.package.text().strip()
        callback = self.progress.emit
        def operation():
            return repair_engine(package, callback)
        w.tasks.submit("setup", operation, self.success, self.failure, engine=False)

    def on_progress(self, progress: SetupProgress) -> None:
        w = self.window
        self.stage = progress.stage
        if progress.status == "complete":
            self.completed.add(progress.stage)
        prefix = {"active": "In progress", "complete": "Complete", "error": "Failed"}.get(progress.status, "Pending")
        if progress.stage in w.setup_page.stages:
            w.setup_page.stages[progress.stage].setText(f"{prefix}  |  {progress.stage}")
        w.setup_page.progress.setRange(0, 0 if progress.status == "active" else len(SETUP_STAGES))
        if progress.status != "active":
            w.setup_page.progress.setValue(len(self.completed))
        w.setup_page.status.setText(progress.message)
        w.diagnostics.setup.appendPlainText(f"{progress.stage}: {progress.status}\n{progress.message}")
        if progress.diagnostics:
            w.diagnostics.setup.setPlainText(progress.diagnostics.to_text())
        elif progress.diagnostic_text:
            w.diagnostics.setup.setPlainText(progress.diagnostic_text)

    def success(self, result: SetupResult | RepairResult) -> None:
        w = self.window
        self.running = False
        setup = result.setup if isinstance(result, RepairResult) else result
        if isinstance(result, RepairResult) and result.restart_required:
            w.hypervisor = result.hypervisor
            w.set_busy(False, "Restart Windows, then reopen Salem to continue engine setup.")
            w.setup_page.status.setText("Restart required. Engine setup will continue after Windows restarts.")
            QMessageBox.information(w, "Restart required", "Restart Windows, then reopen Salem to continue.")
            return
        if setup is None:
            self.failure(RuntimeError("Setup did not return a verified engine."))
            return
        apply_salem_sdk_environment(force=True)
        w.set_busy(False, setup.summary())
        if setup.diagnostics:
            w.diagnostics.setup.setPlainText(setup.diagnostics.to_text())
        if isinstance(result, RepairResult):
            w.hypervisor = result.hypervisor
            w.discover(launch_after=self.launch_after)
        else:
            w.discover()

    def failure(self, error: Exception) -> None:
        self.running = False
        if self.stage in SETUP_STAGES:
            self.window.setup_page.stages[self.stage].setText(f"Failed  |  {self.stage}")
        self.window.setup_page.status.setText(str(error))
        self.window.fail(error)

    def resume(self) -> None:
        if load_pending_fix_launch():
            self.start(repair=True, resume=True)
