"""Engine, diagnostics, preferences and support views."""
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QLineEdit, QPlainTextEdit,
    QProgressBar, QSpinBox, QStyle, QTabWidget, QVBoxLayout, QWidget,
)

from .. import __app_name__, __version__
from ..config import SUPPORT_EMAIL, Settings
from ..setup_wizard import SETUP_STAGES
from .components import Page, app_logo, button, label, row


class SetupPage(Page):
    def __init__(self) -> None:
        super().__init__("Setup & repair")
        self.status = label("Check or repair your Google TV engine.", "muted")
        self.body.addWidget(self.status)
        self.install = button("Install Google TV Engine", "primary", QStyle.StandardPixmap.SP_DialogApplyButton)
        self.retry = button("Retry", icon=QStyle.StandardPixmap.SP_BrowserReload)
        self.refresh = button("Refresh", icon=QStyle.StandardPixmap.SP_BrowserReload)
        self.body.addLayout(row(self.install, self.retry, self.refresh))
        self.progress = QProgressBar()
        self.progress.setRange(0, len(SETUP_STAGES))
        self.progress.setValue(0)
        self.body.addWidget(self.progress)
        self.stages = {}
        for stage in SETUP_STAGES:
            self.stages[stage] = label(stage, "muted")
            self.body.addWidget(self.stages[stage])
        self.details = QCheckBox("Advanced toolchain details")
        self.body.addWidget(self.details)
        self.package = QLineEdit()
        self.package.setPlaceholderText("Reviewed image from toolchain manifest")
        self.package.setReadOnly(True)
        self.package.setVisible(False)
        self.details.toggled.connect(self.package.setVisible)
        self.body.addWidget(self.package)
        self.repair = button("Fix Everything & Launch", icon=QStyle.StandardPixmap.SP_BrowserReload)
        self.body.addWidget(self.repair)
        self.setup_log = button("Open Setup Log", icon=QStyle.StandardPixmap.SP_FileIcon)
        self.body.addWidget(self.setup_log)
        self.body.addStretch()


class DiagnosticsPage(Page):
    def __init__(self) -> None:
        super().__init__("Diagnostics")
        self.refresh = button("Refresh", icon=QStyle.StandardPixmap.SP_BrowserReload)
        self.copy = button("Copy Diagnostics", icon=QStyle.StandardPixmap.SP_FileDialogDetailedView)
        self.logs = button("Open Logs Folder", icon=QStyle.StandardPixmap.SP_DirOpenIcon)
        self.body.addLayout(row(self.refresh, self.copy, self.logs))
        self.tabs = QTabWidget()
        self.runtime = QPlainTextEdit()
        self.activity = QPlainTextEdit()
        self.setup = QPlainTextEdit()
        for title, editor in [("Runtime", self.runtime), ("Activity", self.activity), ("Engine setup", self.setup)]:
            editor.setReadOnly(True)
            editor.setMaximumBlockCount(3000)
            editor.setMinimumHeight(260)
            self.tabs.addTab(editor, title)
        self.body.addWidget(self.tabs, 1)


class PreferencesPage(Page):
    def __init__(self, settings: Settings) -> None:
        super().__init__("Preferences")
        form = QFormLayout()
        form.setSpacing(16)
        self.theme = QComboBox()
        self.theme.addItems(["Dark", "Light", "System"])
        self.retention = QSpinBox()
        self.retention.setRange(1, 365)
        self.retention.setSuffix(" days")
        self.auto_update = QCheckBox("Check for updates at startup")
        self.top = QCheckBox("Remote always on top")
        form.addRow("Appearance", self.theme)
        form.addRow("Log retention", self.retention)
        form.addRow("Updates", self.auto_update)
        form.addRow("Remote", self.top)
        self.body.addLayout(form)
        self.body.addWidget(label("Interface language: English. Arabic and English text input are supported.", "muted"))
        self.save = button("Save Preferences", "primary", QStyle.StandardPixmap.SP_DialogSaveButton)
        self.reset = button("Reset", icon=QStyle.StandardPixmap.SP_BrowserReload)
        self.cleanup = button("Clear Old Logs", icon=QStyle.StandardPixmap.SP_TrashIcon)
        self.body.addLayout(row(self.save, self.reset))
        self.body.addWidget(self.cleanup)
        self.status = label("Preferences are stored for this Windows user.", "muted")
        self.body.addWidget(self.status)
        self.body.addStretch()
        self.load(settings)

    def load(self, settings: Settings) -> None:
        self.theme.setCurrentText(settings.theme)
        self.retention.setValue(settings.log_retention_days)
        self.auto_update.setChecked(settings.auto_update)
        self.top.setChecked(settings.remote_always_on_top)


class HelpPage(Page):
    def __init__(self, settings: Settings) -> None:
        super().__init__("Help & updates")
        self.body.addLayout(row(app_logo(52), label(f"{__app_name__}\nv{__version__}", "section")))
        tabs = QTabWidget()
        self.body.addWidget(tabs)
        update = QWidget()
        layout = QVBoxLayout(update)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)
        self.check = button("Check for Updates", "primary", QStyle.StandardPixmap.SP_BrowserReload)
        self.release = button("Open Release Page", icon=QStyle.StandardPixmap.SP_ArrowForward)
        self.update_status = label("No update check yet.", "muted")
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.check)
        layout.addWidget(self.progress)
        layout.addWidget(self.update_status)
        layout.addWidget(self.release)
        tabs.addTab(update, "Updates")
        support = QWidget()
        layout = QVBoxLayout(support)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)
        layout.addWidget(label("Support email", "section"))
        self.email = QLineEdit(settings.support_email or SUPPORT_EMAIL)
        self.mail = button("Open Support Draft", "primary", QStyle.StandardPixmap.SP_MessageBoxInformation)
        self.copy = button("Copy Diagnostic Info", icon=QStyle.StandardPixmap.SP_FileDialogDetailedView)
        self.logs = button("Open Logs Folder", icon=QStyle.StandardPixmap.SP_DirOpenIcon)
        self.support_status = label("Review the draft before sending. Diagnostics stay on this PC unless you share them.", "muted")
        self.setup_log = button("Open Setup Log", icon=QStyle.StandardPixmap.SP_FileIcon)
        for widget in [self.email, self.mail, self.copy, self.logs, self.setup_log, self.support_status]:
            layout.addWidget(widget)
        tabs.addTab(support, "Support")
        about = QWidget()
        layout = QVBoxLayout(about)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.addWidget(label(f"Version {__version__}", "section"))
        layout.addWidget(label("Google TV launcher for Windows 10/11 x64. Powered by the official Android Emulator. Engine downloads are managed separately."))
        layout.addWidget(label("Independent Salem project. Custom TV/remote icon; no official Google logo. Google TV is a trademark of Google LLC.", "muted"))
        layout.addWidget(label("Open-source notices are included in the application folder.", "muted"))
        tabs.addTab(about, "About")
        self.tabs = tabs
        self.body.addStretch()
