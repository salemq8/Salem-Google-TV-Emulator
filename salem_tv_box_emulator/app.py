from __future__ import annotations

import ctypes
import json
import os
import sys
import time
import traceback
from urllib.parse import quote
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QCloseEvent, QDesktopServices, QIcon, QKeyEvent, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QStatusBar,
    QStyle,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from . import __app_name__, __version__
from .android_backend import (
    AvdInfo,
    EmulatorController,
    LaunchInfo,
    PerformanceSettings,
    SALEM_LOG_DIR,
    apply_google_tv_performance_settings,
    apply_salem_sdk_environment,
    build_setup_instructions,
    choose_avd,
    detect_android_tools,
    find_google_tv_avd,
    list_avds,
)
from .setup_wizard import SETUP_STAGES, ImageDetectionDiagnostics, SetupProgress, SetupResult, install_tv_emulator_engine
from .styles import APP_STYLE
from .windows_embed import (
    ChildWindowInfo,
    EmbeddedWindow,
    TVModeState,
    WindowRect,
    WindowCandidate,
    bring_to_front,
    embed,
    enter_tv_mode,
    exit_tv_mode,
    find_emulator_window,
    get_window_title,
    list_child_windows,
    list_emulator_windows,
    place_next_to,
)
from .windows_features import (
    check_and_enable_hypervisor_features_elevated,
    check_hypervisor_features,
    clear_pending_fix_launch,
    load_pending_fix_launch,
    save_pending_fix_launch,
)


APP_USER_MODEL_ID = "Salem.GoogleTVEmulator.1.0"
SUPPORT_EMAIL = "support@salemgtv.com"
UPDATE_FEED_URL = ""
SETTINGS_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "Salem Google TV Emulator"
SETTINGS_PATH = SETTINGS_DIR / "settings.json"


@dataclass(frozen=True)
class TaskFailure:
    exception: Exception
    details: str


@dataclass(frozen=True)
class FixEverythingResult:
    setup_result: SetupResult
    selected_type: str
    restart_required: bool
    hypervisor_status: str
    feature_enable_output: str = ""


class SignalBridge(QObject):
    task_done = Signal(object, object, object)
    setup_progress = Signal(object)


def _resource_path(relative_path: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    return base / relative_path


def _set_windows_app_user_model_id() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:
        return


def _default_settings() -> dict[str, object]:
    return {
        "theme": "Dark",
        "language": "System default",
        "auto_update": False,
        "log_retention_days": 14,
        "support_email": SUPPORT_EMAIL,
    }


class RemoteWindow(QWidget):
    def __init__(
        self,
        send_key: Callable[[str], None],
        test_sound: Callable[[], None],
        stop_emulator: Callable[[], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Salem Remote")
        self.setMinimumSize(QSize(300, 520))
        self.setObjectName("remoteWindow")
        self._send_key = send_key
        self._test_sound = test_sound
        self._stop_emulator = stop_emulator
        self.remote_buttons: list[QPushButton] = []
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        header = QHBoxLayout()
        title = QLabel("Salem Remote")
        title.setObjectName("pageTitle")
        header.addWidget(title, 1)
        self.always_on_top = QCheckBox("Always on top")
        self.always_on_top.toggled.connect(self._set_always_on_top)
        header.addWidget(self.always_on_top)
        layout.addLayout(header)

        layout.addWidget(self._remote_body(), 1)

    def _remote_body(self) -> QWidget:
        body = QFrame()
        body.setObjectName("remoteBody")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(18, 18, 18, 18)
        body_layout.setSpacing(16)

        top_row = QHBoxLayout()
        top_row.addWidget(self._remote_button("Back", "back", "remoteAuxButton"))
        top_row.addWidget(self._remote_button("Home", "home", "remoteAuxButton"))
        top_row.addWidget(self._remote_button("Menu", "menu", "remoteAuxButton"))
        body_layout.addLayout(top_row)

        dpad = QGridLayout()
        dpad.setHorizontalSpacing(10)
        dpad.setVerticalSpacing(10)
        dpad.addWidget(self._remote_button("Up", "up", "remoteDpadButton"), 0, 1)
        dpad.addWidget(self._remote_button("Left", "left", "remoteDpadButton"), 1, 0)
        dpad.addWidget(self._remote_button("OK", "ok", "remoteOkButton"), 1, 1)
        dpad.addWidget(self._remote_button("Right", "right", "remoteDpadButton"), 1, 2)
        dpad.addWidget(self._remote_button("Down", "down", "remoteDpadButton"), 2, 1)
        body_layout.addLayout(dpad)

        audio = QGridLayout()
        audio.setHorizontalSpacing(8)
        audio.setVerticalSpacing(8)
        audio.addWidget(self._remote_button("Vol +", "volume_up", "remoteAuxButton"), 0, 0)
        audio.addWidget(self._remote_button("Vol -", "volume_down", "remoteAuxButton"), 0, 1)
        audio.addWidget(self._remote_button("Mute", "mute", "remoteAuxButton"), 0, 2)
        test_sound = QPushButton("Test Sound")
        test_sound.setObjectName("secondaryButton")
        test_sound.setMinimumHeight(38)
        test_sound.clicked.connect(self._test_sound)
        self.remote_buttons.append(test_sound)
        audio.addWidget(test_sound, 1, 0, 1, 3)
        power = QPushButton("Power / Stop")
        power.setObjectName("dangerButton")
        power.setMinimumHeight(38)
        power.clicked.connect(self._stop_emulator)
        self.remote_buttons.append(power)
        audio.addWidget(power, 2, 0, 1, 3)
        body_layout.addLayout(audio)
        body_layout.addStretch(1)
        return body

    def _remote_button(self, label: str, key_name: str, object_name: str) -> QPushButton:
        button = QPushButton(label)
        button.setObjectName(object_name)
        button.clicked.connect(lambda _checked=False, name=key_name: self._send_key(name))
        self.remote_buttons.append(button)
        return button

    def set_remote_enabled(self, enabled: bool) -> None:
        for button in self.remote_buttons:
            button.setEnabled(enabled)

    def _set_always_on_top(self, enabled: bool) -> None:
        flags = self.windowFlags()
        if enabled:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.show()


class SalemMainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{__app_name__} v{__version__}")
        self.logo_path = _resource_path("assets/salem_google_tv_emulator.png")
        if self.logo_path.exists():
            self.setWindowIcon(QIcon(str(self.logo_path)))
        self.resize(1220, 760)
        self.setMinimumSize(QSize(960, 620))

        self.executor = ThreadPoolExecutor(max_workers=3)
        self.signals = SignalBridge()
        self.signals.task_done.connect(self._on_task_done)
        self.signals.setup_progress.connect(self._on_setup_progress)
        self.shortcuts: list[QShortcut] = []
        self.pending_tasks: list[tuple[Future[object], Callable[[object], None], bool]] = []
        self.task_poll_timer = QTimer(self)
        self.task_poll_timer.setInterval(100)
        self.task_poll_timer.timeout.connect(self._poll_tasks)

        apply_salem_sdk_environment()
        self.tools = detect_android_tools()
        self.avds: list[AvdInfo] = list_avds(self.tools)
        self.controller = EmulatorController(self.tools)
        self.selected_type = "google_tv"
        self.embedded_window: EmbeddedWindow | None = None
        self.embed_attempts = 0
        self.setup_running = False
        self.current_setup_stage: str | None = None
        self.setup_stage_status: dict[str, str] = {stage: "pending" for stage in SETUP_STAGES}
        self.latest_diagnostics: ImageDetectionDiagnostics | None = None
        self.emulator_process = None
        self.tv_mode_active = False
        self.tv_mode_state: TVModeState | None = None
        self.last_tv_mode_hwnd: int | None = None
        self.last_tv_mode_title = "Not matched yet."
        self.last_tv_mode_class_name = "Not matched yet."
        self.last_tv_mode_pid: int | None = None
        self.last_tv_mode_message = "TV Mode has not been used yet."
        self.last_tv_mode_restored_rect: WindowRect | None = None
        self.hypervisor_status_text = "Hypervisor status: Not checked yet."
        self.nav_buttons: list[QPushButton] = []
        self.remote_buttons: list[QPushButton] = []
        self.busy_sensitive_buttons: list[QPushButton] = []
        self.remote_window: RemoteWindow | None = None
        self.text_send_pending = False
        self.launch_serial_deadline = 0.0
        self.launch_serial_poll_in_flight = False
        self.local_settings = self._load_local_settings()
        self.update_check_in_progress = False

        self._build_ui()
        self._wire_actions()
        self._refresh_state()

        self.embed_timer = QTimer(self)
        self.embed_timer.setInterval(1500)
        self.embed_timer.timeout.connect(self._try_embed_running_emulator)
        self.launch_poll_timer = QTimer(self)
        self.launch_poll_timer.setInterval(1500)
        self.launch_poll_timer.timeout.connect(self._poll_launch_serial)
        QTimer.singleShot(500, self._refresh_hypervisor_status_async)
        QTimer.singleShot(1000, self._maybe_resume_pending_fix_launch)

    def _build_ui(self) -> None:
        self.resize(1320, 820)
        self.setMinimumSize(QSize(1120, 720))

        root = QWidget()
        root.setObjectName("appRoot")
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        self.setCentralWidget(root)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_group.idClicked.connect(self._switch_page)
        root_layout.addWidget(self._build_sidebar())

        self.pages = QStackedWidget()
        self.pages.setObjectName("contentStack")
        self.home_page = self._build_home_page()
        self.remote_page = self._build_remote_page()
        self.text_input_page = self._build_text_input_page()
        self.audio_page = self._build_audio_page()
        self.tv_mode_page = self._build_tv_mode_page()
        self.performance_page = self._build_performance_page()
        self.diagnostics_page = self._build_diagnostics_page()
        self.settings_page = self._build_settings_page()
        self.updates_page = self._build_updates_page()
        self.setup_page = self._build_setup_page()
        self.support_page = self._build_support_page()
        self.about_page = self._build_about_page()
        self.page_lookup = {
            "home": self.home_page,
            "remote": self.remote_page,
            "text": self.text_input_page,
            "audio": self.audio_page,
            "tv_mode": self.tv_mode_page,
            "performance": self.performance_page,
            "diagnostics": self.diagnostics_page,
            "settings": self.settings_page,
            "updates": self.updates_page,
            "setup": self.setup_page,
            "support": self.support_page,
            "about": self.about_page,
        }
        for page in self.page_lookup.values():
            self.pages.addWidget(page)
        root_layout.addWidget(self.pages, 1)

        self.status = QStatusBar()
        self.setStatusBar(self.status)

        tv_mode_action = QAction("Toggle TV Mode", self)
        tv_mode_action.setShortcut("F11")
        tv_mode_action.triggered.connect(lambda _checked=False: self._toggle_tv_mode())
        self.addAction(tv_mode_action)

        self.nav_buttons[0].setChecked(True)
        self._reset_setup_progress()

    def _build_sidebar(self) -> QWidget:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(282)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(18, 18, 18, 14)
        layout.setSpacing(10)

        brand_row = QHBoxLayout()
        logo = QLabel()
        logo.setObjectName("brandLogo")
        logo.setFixedSize(QSize(44, 44))
        if self.logo_path.exists():
            logo.setPixmap(QPixmap(str(self.logo_path)).scaled(44, 44, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        brand_text = QVBoxLayout()
        brand_text.setSpacing(0)
        brand = QLabel("Salem Google TV")
        brand.setObjectName("brandTitle")
        subtitle = QLabel("Emulator v1.0")
        subtitle.setObjectName("brandSubtitle")
        brand_text.addWidget(brand)
        brand_text.addWidget(subtitle)
        brand_row.addWidget(logo)
        brand_row.addLayout(brand_text, 1)
        layout.addLayout(brand_row)

        status_card = QFrame()
        status_card.setObjectName("sidebarStatus")
        status_layout = QVBoxLayout(status_card)
        status_layout.setContentsMargins(12, 12, 12, 12)
        status_layout.setSpacing(4)
        self.sidebar_state_label = QLabel("Idle")
        self.sidebar_state_label.setObjectName("statusStrong")
        self.sidebar_serial_label = QLabel("Serial: not detected")
        self.sidebar_serial_label.setObjectName("mutedText")
        status_layout.addWidget(self.sidebar_state_label)
        status_layout.addWidget(self.sidebar_serial_label)
        layout.addWidget(status_card)

        nav_items = [
            ("Home", 0),
            ("Remote", 1),
            ("Text Input", 2),
            ("Audio", 3),
            ("TV Mode", 4),
            ("Network && Performance", 5),
            ("Diagnostics", 6),
            ("Settings", 7),
            ("Updates", 8),
            ("Setup / Repair", 9),
            ("Support", 10),
            ("About", 11),
        ]
        for label, index in nav_items:
            button = QPushButton(label)
            button.setObjectName("navButton")
            button.setCheckable(True)
            button.setMinimumHeight(36)
            self.nav_group.addButton(button, index)
            self.nav_buttons.append(button)
            layout.addWidget(button)

        layout.addStretch(1)
        footer = QLabel("Official Android Emulator backend\nCustom Salem icon, not Google branding")
        footer.setObjectName("sidebarFooter")
        footer.setWordWrap(True)
        layout.addWidget(footer)
        hint = QLabel("F11 toggles TV Mode")
        hint.setObjectName("mutedText")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        return sidebar

    def _build_home_page(self) -> QWidget:
        page, layout = self._scroll_page()
        layout.addWidget(self._page_header("Home", "Google TV emulator launcher for Windows."))

        hero = QFrame()
        hero.setObjectName("heroCard")
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(20, 18, 20, 18)
        hero_layout.setSpacing(12)
        hero.setObjectName("heroCard")
        hero_top = QHBoxLayout()
        logo = QLabel()
        logo.setObjectName("heroLogo")
        logo.setFixedSize(QSize(76, 76))
        if self.logo_path.exists():
            logo.setPixmap(QPixmap(str(self.logo_path)).scaled(76, 76, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        title_stack = QVBoxLayout()
        title_stack.setSpacing(4)
        title = QLabel("Salem Google TV Emulator")
        title.setObjectName("heroTitle")
        subtitle = QLabel("Google TV emulator launcher for Windows")
        subtitle.setObjectName("pageSubtitle")
        subtitle.setWordWrap(True)
        title_stack.addWidget(title)
        title_stack.addWidget(subtitle)
        hero_top.addWidget(logo)
        hero_top.addLayout(title_stack, 1)
        self.home_status_label = QLabel("Ready status will appear here.")
        self.home_status_label.setObjectName("statusPill")
        hero_top.addWidget(self.home_status_label)
        hero_layout.addLayout(hero_top)
        layout.addWidget(hero)

        top_grid = QGridLayout()
        top_grid.setSpacing(16)

        system_card, system_layout = self._card("Google TV Status", "Single supported TV profile for Salem v1.0.")
        self.choice_group = QButtonGroup(self)
        self.choice_group.setExclusive(True)
        self.google_tv_button = self._choice_button("Google TV", "Google TV profile")
        self.google_tv_button.setChecked(True)
        self.choice_group.addButton(self.google_tv_button, 0)
        system_layout.addWidget(self.google_tv_button)
        top_grid.addWidget(system_card, 0, 0)

        quick_card, quick_layout = self._card("Quick Status", "Live launch, ADB, audio, network, and TV Mode state.")
        quick_grid = QGridLayout()
        quick_grid.setSpacing(10)
        self.active_serial_label = QLabel("Active serial: not detected")
        self.active_serial_label.setObjectName("statusPillAlt")
        self.home_adb_status_label = QLabel("ADB: checking")
        self.home_adb_status_label.setObjectName("statusPillAlt")
        self.home_window_status_label = QLabel("Emulator window: not detected")
        self.home_window_status_label.setObjectName("statusPillAlt")
        self.home_tv_mode_quick_label = QLabel("TV Mode: inactive")
        self.home_tv_mode_quick_label.setObjectName("statusPillAlt")
        self.home_audio_status_label = QLabel("Audio: enabled")
        self.home_audio_status_label.setObjectName("statusPillAlt")
        self.home_network_status_label = QLabel("Network: run diagnostics")
        self.home_network_status_label.setObjectName("statusPillAlt")
        quick_labels = [
            self.active_serial_label,
            self.home_adb_status_label,
            self.home_window_status_label,
            self.home_tv_mode_quick_label,
            self.home_audio_status_label,
            self.home_network_status_label,
        ]
        for index, label in enumerate(quick_labels):
            label.setWordWrap(True)
            quick_grid.addWidget(label, index // 2, index % 2)
        quick_layout.addLayout(quick_grid)
        top_grid.addWidget(quick_card, 0, 1)
        layout.addLayout(top_grid)

        launch_card, launch_layout = self._card("Launch Controls", "Open the official Android Emulator window and manage the current TV session.")
        self.fix_launch_button = self._action_button("Fix Everything && Launch", "accentButton", QStyle.StandardPixmap.SP_MediaPlay)
        self.launch_google_button = self._action_button("Launch Google TV", "primaryButton", QStyle.StandardPixmap.SP_MediaPlay)
        self.start_button = QPushButton("Launch Selected")
        self.start_button.hide()
        self.restart_button = self._action_button("Restart Google TV", "secondaryButton", QStyle.StandardPixmap.SP_BrowserReload)
        self.stop_button = self._action_button("Stop Google TV", "dangerButton", QStyle.StandardPixmap.SP_MediaStop)
        launch_grid = QGridLayout()
        launch_grid.setSpacing(10)
        launch_grid.addWidget(self.launch_google_button, 0, 0, 1, 2)
        launch_grid.addWidget(self.restart_button, 1, 0)
        launch_grid.addWidget(self.stop_button, 1, 1)
        launch_grid.addWidget(self.fix_launch_button, 2, 0, 1, 2)
        launch_layout.addLayout(launch_grid)
        layout.addWidget(launch_card)

        home_tools_grid = QGridLayout()
        home_tools_grid.setSpacing(16)
        tv_mode_card, tv_mode_layout = self._card("TV Mode", "Borderless fullscreen controls for the official emulator window.")
        self.home_enter_tv_mode_button = self._action_button("Enter TV Mode", "primaryButton", QStyle.StandardPixmap.SP_TitleBarMaxButton)
        self.home_exit_tv_mode_button = self._action_button("Exit TV Mode", "secondaryButton", QStyle.StandardPixmap.SP_TitleBarNormalButton)
        home_tv_grid = QGridLayout()
        home_tv_grid.setSpacing(10)
        home_tv_grid.addWidget(self.home_enter_tv_mode_button, 0, 0)
        home_tv_grid.addWidget(self.home_exit_tv_mode_button, 0, 1)
        f11_hint = QLabel("Shortcut: F11")
        f11_hint.setObjectName("mutedText")
        home_tv_grid.addWidget(f11_hint, 1, 0, 1, 2)
        tv_mode_layout.addLayout(home_tv_grid)
        home_tools_grid.addWidget(tv_mode_card, 0, 0)

        diagnostics_card, diagnostics_layout = self._card("Logs & Diagnostics", "Privacy-safe diagnostics stay local until you copy them.")
        self.home_open_logs_button = self._action_button("Open Logs Folder", "secondaryButton", QStyle.StandardPixmap.SP_DirOpenIcon)
        self.home_copy_diagnostics_button = self._action_button("Copy Diagnostics", "secondaryButton", QStyle.StandardPixmap.SP_FileDialogDetailedView)
        diagnostics_grid = QGridLayout()
        diagnostics_grid.setSpacing(10)
        diagnostics_grid.addWidget(self.home_open_logs_button, 0, 0)
        diagnostics_grid.addWidget(self.home_copy_diagnostics_button, 0, 1)
        diagnostics_layout.addLayout(diagnostics_grid)
        home_tools_grid.addWidget(diagnostics_card, 0, 1)
        layout.addLayout(home_tools_grid)

        preview_card, preview_layout = self._card("TV Window", "The official emulator opens normally; TV Mode makes it feel like a full-screen TV.")
        self.emulator_host = QFrame()
        self.emulator_host.setObjectName("emulatorHost")
        self.emulator_host.setMinimumHeight(180)
        self.emulator_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        emulator_layout = QVBoxLayout(self.emulator_host)
        emulator_layout.setContentsMargins(18, 18, 18, 18)
        self.placeholder = QLabel("Launch Google TV, then use TV Mode for the fullscreen screen.")
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder.setObjectName("mutedText")
        emulator_layout.addStretch(1)
        emulator_layout.addWidget(self.placeholder)
        emulator_layout.addStretch(1)
        preview_layout.addWidget(self.emulator_host)
        layout.addWidget(preview_card)
        layout.addStretch(1)
        return page

    def _build_remote_page(self) -> QWidget:
        page, layout = self._scroll_page()
        layout.addWidget(self._page_header("Remote", "Control the running TV system with a physical-feeling remote."))

        remote_card, remote_layout = self._card("Remote Control", "D-pad, navigation, and TV actions use the existing ADB backend.")
        remote_header = QHBoxLayout()
        self.popout_remote_button = self._action_button("Pop-out Remote", "secondaryButton", QStyle.StandardPixmap.SP_TitleBarNormalButton)
        self.popout_always_on_top_check = QCheckBox("Open pop-out always on top")
        self.popout_always_on_top_check.setChecked(bool(self.local_settings.get("remote_always_on_top", False)))
        remote_header.addStretch(1)
        remote_header.addWidget(self.popout_always_on_top_check)
        remote_header.addWidget(self.popout_remote_button)
        remote_layout.addLayout(remote_header)
        remote_layout.addWidget(self._remote_body())
        self.remote_stop_button = self._action_button("Power / Stop Google TV", "dangerButton", QStyle.StandardPixmap.SP_MediaStop)
        remote_layout.addWidget(self.remote_stop_button)
        layout.addWidget(remote_card)
        layout.addStretch(1)
        return page

    def _build_text_input_page(self) -> QWidget:
        page, layout = self._scroll_page()
        layout.addWidget(self._page_header("Text Input", "Send Arabic, English, numbers, and symbols into the active Google TV emulator."))

        text_card, text_layout = self._card("Send Text to TV", "Arabic and English text use the existing input/clipboard fallback logic.")
        text_row = QHBoxLayout()
        self.tv_text_input = QLineEdit()
        self.tv_text_input.setPlaceholderText("Type text for the TV")
        self.tv_text_input.setMinimumHeight(42)
        self.send_text_button = self._action_button("Send Text", "primaryButton", QStyle.StandardPixmap.SP_ArrowRight)
        text_row.addWidget(self.tv_text_input, 1)
        text_row.addWidget(self.send_text_button)
        self.text_status_label = QLabel("Last send: none")
        self.text_status_label.setObjectName("mutedText")
        text_layout.addLayout(text_row)
        text_layout.addWidget(self.text_status_label)
        note = QLabel("Supports English, Arabic, numbers, and symbols. Unicode text uses the existing clipboard paste fallback when ADB input text cannot handle it.")
        note.setObjectName("mutedText")
        note.setWordWrap(True)
        text_layout.addWidget(note)
        self.text_active_serial_label = QLabel("Active emulator serial: not detected")
        self.text_active_serial_label.setObjectName("statusPillAlt")
        text_layout.addWidget(self.text_active_serial_label)
        layout.addWidget(text_card)
        layout.addStretch(1)
        return page

    def _build_audio_page(self) -> QWidget:
        page, layout = self._scroll_page()
        layout.addWidget(self._page_header("Audio", "Verify and control Google TV audio through ADB media commands."))

        audio_card, audio_layout = self._card("Audio", "Quick volume commands for the active emulator serial.")
        audio_grid = QGridLayout()
        audio_grid.setSpacing(10)
        self._add_remote_button(audio_grid, "Volume Up", "volume_up", 0, 0, "secondaryButton")
        self._add_remote_button(audio_grid, "Volume Down", "volume_down", 0, 1, "secondaryButton")
        self._add_remote_button(audio_grid, "Mute", "mute", 0, 2, "secondaryButton")
        self.test_sound_button = self._action_button("Test Sound", "primaryButton", QStyle.StandardPixmap.SP_MediaVolume)
        self.remote_buttons.append(self.test_sound_button)
        audio_grid.addWidget(self.test_sound_button, 1, 0, 1, 3)
        audio_layout.addLayout(audio_grid)
        self.audio_status_label = QLabel("Audio: enabled; Salem never passes -no-audio.")
        self.audio_status_label.setObjectName("statusPillAlt")
        self.audio_backend_label = QLabel("Audio backend: default")
        self.audio_backend_label.setObjectName("mutedText")
        self.audio_diagnostics_label = QLabel("Run Test Sound or open Diagnostics to inspect audio log messages.")
        self.audio_diagnostics_label.setObjectName("mutedText")
        self.audio_diagnostics_label.setWordWrap(True)
        audio_layout.addWidget(self.audio_status_label)
        audio_layout.addWidget(self.audio_backend_label)
        audio_layout.addWidget(self.audio_diagnostics_label)
        layout.addWidget(audio_card)
        layout.addStretch(1)
        return page

    def _build_tv_mode_page(self) -> QWidget:
        page, layout = self._scroll_page()
        layout.addWidget(self._page_header("TV Mode", "Borderless fullscreen mode for the official emulator window."))

        controls_card, controls_layout = self._card("TV Mode Controls", "F11 toggles this mode from anywhere in Salem.")
        self.tv_mode_status_label = QLabel("TV Mode: inactive")
        self.tv_mode_status_label.setObjectName("statusLine")
        self.tv_mode_button = self._action_button("Enter TV Mode", "primaryButton", QStyle.StandardPixmap.SP_TitleBarMaxButton)
        self.exit_tv_mode_button = self._action_button("Exit TV Mode", "secondaryButton", QStyle.StandardPixmap.SP_TitleBarNormalButton)
        tv_mode_grid = QGridLayout()
        tv_mode_grid.setSpacing(10)
        tv_mode_grid.addWidget(self.tv_mode_status_label, 0, 0, 1, 2)
        tv_mode_grid.addWidget(self.tv_mode_button, 1, 0)
        tv_mode_grid.addWidget(self.exit_tv_mode_button, 1, 1)
        f11_hint = QLabel("Shortcut: F11")
        f11_hint.setObjectName("mutedText")
        tv_mode_grid.addWidget(f11_hint, 2, 0, 1, 2)
        controls_layout.addLayout(tv_mode_grid)
        layout.addWidget(controls_card)

        status_card, status_layout = self._card("Window & Viewport Diagnostics", "TV Mode diagnostics identify the selected emulator window and viewport fill.")
        self.tv_mode_selected_window_label = QLabel("Selected emulator window: not detected")
        self.tv_mode_selected_window_label.setObjectName("statusPillAlt")
        self.tv_mode_viewport_label = QLabel("Viewport fill percentage: unknown")
        self.tv_mode_viewport_label.setObjectName("statusPillAlt")
        self.tv_mode_message_label = QLabel("TV Mode has not been used yet.")
        self.tv_mode_message_label.setObjectName("mutedText")
        self.tv_mode_message_label.setWordWrap(True)
        status_layout.addWidget(self.tv_mode_selected_window_label)
        status_layout.addWidget(self.tv_mode_viewport_label)
        status_layout.addWidget(self.tv_mode_message_label)
        layout.addWidget(status_card)
        layout.addStretch(1)
        return page

    def _build_performance_page(self) -> QWidget:
        page, layout = self._scroll_page()
        layout.addWidget(self._page_header("Network & Performance", "Safe Google TV AVD settings and network diagnostics only."))

        performance_card, performance_layout = self._card(
            "Performance Settings",
            "Stop Google TV before applying changes. Salem updates only valid Salem_Google_TV AVD settings.",
        )
        perf_grid = QGridLayout()
        perf_grid.setSpacing(10)
        ram_label = QLabel("RAM (MB)")
        ram_label.setObjectName("mutedText")
        self.performance_ram_spin = QSpinBox()
        self.performance_ram_spin.setRange(1024, 8192)
        self.performance_ram_spin.setSingleStep(512)
        self.performance_ram_spin.setValue(2048)
        cpu_label = QLabel("CPU cores")
        cpu_label.setObjectName("mutedText")
        self.performance_cpu_spin = QSpinBox()
        self.performance_cpu_spin.setRange(1, 8)
        self.performance_cpu_spin.setValue(4)
        self.performance_gpu_host_check = QCheckBox("GPU host mode")
        self.performance_gpu_host_check.setChecked(True)
        self.performance_summary_label = QLabel("Current AVD settings will appear here after Refresh.")
        self.performance_summary_label.setObjectName("statusPillAlt")
        self.performance_summary_label.setWordWrap(True)
        self.optimize_performance_button = self._action_button("Optimize Emulator Performance", "primaryButton", QStyle.StandardPixmap.SP_ComputerIcon)
        perf_grid.addWidget(ram_label, 0, 0)
        perf_grid.addWidget(self.performance_ram_spin, 0, 1)
        perf_grid.addWidget(cpu_label, 0, 2)
        perf_grid.addWidget(self.performance_cpu_spin, 0, 3)
        perf_grid.addWidget(self.performance_gpu_host_check, 1, 0, 1, 2)
        perf_grid.addWidget(self.optimize_performance_button, 2, 0, 1, 4)
        performance_layout.addLayout(perf_grid)
        performance_layout.addWidget(self.performance_summary_label)
        layout.addWidget(performance_card)

        network_card, network_layout = self._card("Network Diagnostics", "Runs safe read-only emulator network diagnostics. Salem does not modify Windows network settings.")
        self.network_status_button = self._action_button("Network Status Diagnostics", "secondaryButton", QStyle.StandardPixmap.SP_DriveNetIcon)
        self.network_state_label = QLabel("Network state: not checked")
        self.network_state_label.setObjectName("statusPillAlt")
        self.performance_status_label = QLabel("No network or performance action has run yet.")
        self.performance_status_label.setObjectName("mutedText")
        self.performance_status_label.setWordWrap(True)
        network_layout.addWidget(self.network_status_button)
        network_layout.addWidget(self.network_state_label)
        network_layout.addWidget(self.performance_status_label)
        layout.addWidget(network_card)
        layout.addStretch(1)
        return page

    def _build_setup_page(self) -> QWidget:
        page, layout = self._scroll_page()
        layout.addWidget(self._page_header("Setup", "Install, repair, and inspect Salem's local Android engine."))

        repair_card, repair_layout = self._card("Setup / Repair", "Use these only when tools, images, or AVDs are missing.")
        self.setup_button = self._action_button("Install Google TV Engine", "primaryButton", QStyle.StandardPixmap.SP_DialogSaveButton)
        self.retry_setup_button = self._action_button("Retry Setup", "secondaryButton", QStyle.StandardPixmap.SP_BrowserReload)
        self.retry_setup_button.hide()
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setObjectName("secondaryButton")
        self.refresh_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload))
        self.refresh_button.setMinimumHeight(42)
        self.install_button = self._action_button("Install APK", "secondaryButton", QStyle.StandardPixmap.SP_DriveHDIcon)
        repair_grid = QGridLayout()
        repair_grid.setSpacing(10)
        repair_grid.addWidget(self.setup_button, 0, 0)
        repair_grid.addWidget(self.retry_setup_button, 0, 1)
        repair_grid.addWidget(self.refresh_button, 1, 0)
        repair_grid.addWidget(self.install_button, 1, 1)
        repair_layout.addLayout(repair_grid)
        layout.addWidget(repair_card)

        progress_card, progress_layout = self._card("Setup Progress", "Automatic engine installation stages.")
        self.setup_stage_labels: dict[str, QLabel] = {}
        for stage in SETUP_STAGES:
            label = QLabel()
            label.setObjectName("progressLabel")
            label.setWordWrap(True)
            self.setup_stage_labels[stage] = label
            progress_layout.addWidget(label)
        layout.addWidget(progress_card)

        manual_card, manual_layout = self._card("Manual Google TV Package", "Optional package override if automatic Google TV image detection fails.")
        self.manual_google_package = QLineEdit()
        self.manual_google_package.setPlaceholderText("Google TV system-image package (optional)")
        manual_layout.addWidget(self.manual_google_package)
        layout.addWidget(manual_card)

        layout.addStretch(1)
        return page

    def _build_diagnostics_page(self) -> QWidget:
        page, layout = self._scroll_page()
        layout.addWidget(self._page_header("Diagnostics", "Readable logs and runtime details without cluttering the launcher."))

        controls_card, controls_layout = self._card("Diagnostics Tools", "Copy reports or open Salem's local log folder.")
        self.copy_diagnostics_button = self._action_button("Copy Diagnostics", "secondaryButton", QStyle.StandardPixmap.SP_FileDialogDetailedView)
        self.open_logs_button = self._action_button("Open Logs Folder", "secondaryButton", QStyle.StandardPixmap.SP_DirOpenIcon)
        self.refresh_diagnostics_button = self._action_button("Refresh Diagnostics", "secondaryButton", QStyle.StandardPixmap.SP_BrowserReload)
        diagnostics_controls = QHBoxLayout()
        diagnostics_controls.addWidget(self.copy_diagnostics_button)
        diagnostics_controls.addWidget(self.open_logs_button)
        diagnostics_controls.addWidget(self.refresh_diagnostics_button)
        diagnostics_controls.addStretch(1)
        controls_layout.addLayout(diagnostics_controls)
        layout.addWidget(controls_card)

        self.output_tabs = QTabWidget()
        self.output_tabs.setObjectName("outputTabs")
        self.info_log = QPlainTextEdit()
        self.info_log.setReadOnly(True)
        self.info_log.setMinimumHeight(230)
        self.diagnostics_log = QPlainTextEdit()
        self.diagnostics_log.setReadOnly(True)
        self.diagnostics_log.setMinimumHeight(230)
        self.diagnostics_log.setPlainText("Diagnostics will appear after Salem runs sdkmanager --list during setup.")
        self.output_tabs.addTab(self.info_log, "Status")
        self.output_tabs.addTab(self.diagnostics_log, "Diagnostics")
        layout.addWidget(self.output_tabs, 1)
        return page

    def _build_settings_page(self) -> QWidget:
        page, layout = self._scroll_page()
        layout.addWidget(self._page_header("Settings", "Local app preferences stored outside release packages."))

        preferences_card, preferences_layout = self._card("Preferences", "These settings are saved locally for this Windows user.")
        form = QGridLayout()
        form.setSpacing(10)
        theme_label = QLabel("Theme")
        theme_label.setObjectName("mutedText")
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["Dark"])
        self.theme_combo.setCurrentText(str(self.local_settings.get("theme", "Dark")))
        language_label = QLabel("Language")
        language_label.setObjectName("mutedText")
        self.language_combo = QComboBox()
        self.language_combo.addItems(["System default", "English", "Arabic"])
        self.language_combo.setCurrentText(str(self.local_settings.get("language", "System default")))
        self.settings_auto_update_check = QCheckBox("Auto Update enabled")
        self.settings_auto_update_check.setChecked(bool(self.local_settings.get("auto_update", False)))
        retention_label = QLabel("Log retention days")
        retention_label.setObjectName("mutedText")
        self.log_retention_spin = QSpinBox()
        self.log_retention_spin.setRange(1, 365)
        self.log_retention_spin.setValue(int(self.local_settings.get("log_retention_days", 14)))
        form.addWidget(theme_label, 0, 0)
        form.addWidget(self.theme_combo, 0, 1)
        form.addWidget(language_label, 0, 2)
        form.addWidget(self.language_combo, 0, 3)
        form.addWidget(self.settings_auto_update_check, 1, 0, 1, 2)
        form.addWidget(retention_label, 2, 0)
        form.addWidget(self.log_retention_spin, 2, 1)
        preferences_layout.addLayout(form)
        self.settings_status_label = QLabel(f"Settings file: {SETTINGS_PATH}")
        self.settings_status_label.setObjectName("mutedText")
        self.settings_status_label.setWordWrap(True)
        preferences_layout.addWidget(self.settings_status_label)
        layout.addWidget(preferences_card)

        actions_card, actions_layout = self._card("Settings Actions", "Manage local logs and preferences.")
        action_grid = QGridLayout()
        action_grid.setSpacing(10)
        self.save_settings_button = self._action_button("Save Settings", "primaryButton", QStyle.StandardPixmap.SP_DialogSaveButton)
        self.clear_old_logs_button = self._action_button("Clear Old Logs", "secondaryButton", QStyle.StandardPixmap.SP_DialogDiscardButton)
        self.reset_settings_button = self._action_button("Reset App Settings", "dangerButton", QStyle.StandardPixmap.SP_BrowserStop)
        self.settings_open_logs_button = self._action_button("Open Logs Folder", "secondaryButton", QStyle.StandardPixmap.SP_DirOpenIcon)
        action_grid.addWidget(self.save_settings_button, 0, 0)
        action_grid.addWidget(self.clear_old_logs_button, 0, 1)
        action_grid.addWidget(self.settings_open_logs_button, 1, 0)
        action_grid.addWidget(self.reset_settings_button, 1, 1)
        actions_layout.addLayout(action_grid)
        layout.addWidget(actions_card)
        layout.addStretch(1)
        return page

    def _build_updates_page(self) -> QWidget:
        page, layout = self._scroll_page()
        layout.addWidget(self._page_header("Updates", "Manual and automatic update status for GitHub Releases."))

        update_card, update_layout = self._card("Update Status", "Manual checks work even when Auto Update is disabled.")
        self.current_version_label = QLabel(f"Current version: {__version__}")
        self.current_version_label.setObjectName("statusPillAlt")
        self.updates_auto_update_check = QCheckBox("Auto Update enabled")
        self.updates_auto_update_check.setChecked(bool(self.local_settings.get("auto_update", False)))
        self.check_updates_button = self._action_button("Check for Updates", "primaryButton", QStyle.StandardPixmap.SP_BrowserReload)
        self.update_progress = QProgressBar()
        self.update_progress.setRange(0, 100)
        self.update_progress.setValue(0)
        self.update_status_label = QLabel("Update status: not checked")
        self.update_status_label.setObjectName("mutedText")
        self.update_status_label.setWordWrap(True)
        update_layout.addWidget(self.current_version_label)
        update_layout.addWidget(self.updates_auto_update_check)
        update_layout.addWidget(self.check_updates_button)
        update_layout.addWidget(self.update_progress)
        update_layout.addWidget(self.update_status_label)
        layout.addWidget(update_card)

        phases_card, phases_layout = self._card("Update Pipeline", "These states are wired for a future GitHub Releases version.json feed.")
        phases = QLabel(
            "Checking for updates...\n"
            "Update found\n"
            "Downloading 0-100%\n"
            "Verifying download\n"
            "Preparing installer\n"
            "Installing update\n"
            "Closing app"
        )
        phases.setObjectName("bodyText")
        phases.setWordWrap(True)
        phases_layout.addWidget(phases)
        layout.addWidget(phases_card)
        layout.addStretch(1)
        return page

    def _build_support_page(self) -> QWidget:
        page, layout = self._scroll_page()
        layout.addWidget(self._page_header("Support", "Collect diagnostics locally and open a draft in your default mail app."))

        support_card, support_layout = self._card("Support Contact", "No SMTP, tokens, or passwords are stored by Salem.")
        self.support_email_input = QLineEdit(str(self.local_settings.get("support_email", SUPPORT_EMAIL)))
        self.support_email_input.setPlaceholderText("Support email")
        self.support_email_input.setMinimumHeight(42)
        self.discord_placeholder_label = QLabel("Discord: not configured yet")
        self.discord_placeholder_label.setObjectName("mutedText")
        self.discord_placeholder_label.setWordWrap(True)
        support_layout.addWidget(QLabel("Support Email"))
        support_layout.addWidget(self.support_email_input)
        support_layout.addWidget(self.discord_placeholder_label)
        layout.addWidget(support_card)

        support_actions_card, support_actions_layout = self._card("Support Actions", "You decide what to send. Salem only opens a draft.")
        support_grid = QGridLayout()
        support_grid.setSpacing(10)
        self.support_open_logs_button = self._action_button("Open Logs Folder", "secondaryButton", QStyle.StandardPixmap.SP_DirOpenIcon)
        self.support_copy_diagnostics_button = self._action_button("Copy Diagnostic Info", "secondaryButton", QStyle.StandardPixmap.SP_FileDialogDetailedView)
        self.support_send_email_button = self._action_button("Send Support Email", "primaryButton", QStyle.StandardPixmap.SP_MessageBoxInformation)
        support_grid.addWidget(self.support_open_logs_button, 0, 0)
        support_grid.addWidget(self.support_copy_diagnostics_button, 0, 1)
        support_grid.addWidget(self.support_send_email_button, 1, 0, 1, 2)
        support_actions_layout.addLayout(support_grid)
        self.support_status_label = QLabel("Email drafts open with your default mail app. Review before sending.")
        self.support_status_label.setObjectName("mutedText")
        self.support_status_label.setWordWrap(True)
        support_actions_layout.addWidget(self.support_status_label)
        layout.addWidget(support_actions_card)
        layout.addStretch(1)
        return page

    def _build_about_page(self) -> QWidget:
        page, layout = self._scroll_page()
        layout.addWidget(self._page_header("About", "What Salem controls, and what stays official."))
        about_card, about_layout = self._card("Salem Google TV Emulator", "Version 1.0")
        body = QLabel(
            "Salem Google TV Emulator is a Windows launcher and control surface for Google TV on Google's official Android Emulator. "
            "It manages the Salem_Google_TV AVD, ADB controls, audio commands, diagnostics, and a TV Mode window experience."
        )
        body.setObjectName("bodyText")
        body.setWordWrap(True)
        about_layout.addWidget(body)
        layout.addWidget(about_card)

        backend_card, backend_layout = self._card("License & Credits", "Backend and identity notes.")
        details = QLabel(
            "Portable JDK 21, Android command-line tools, Google TV image detection, AVD creation, Hypervisor checks, "
            "emulator launch, ADB serial detection, remote controls, text input, audio commands, and TV Mode logic "
            "use the existing Salem backend. Legal note: this app uses the official Android Emulator backend and does not build an emulator from scratch. "
            "The app icon is custom artwork inspired by TV and remote-control colors; it is not official Google branding."
        )
        details.setObjectName("bodyText")
        details.setWordWrap(True)
        backend_layout.addWidget(details)
        layout.addWidget(backend_card)
        layout.addStretch(1)
        return page

    def _scroll_page(self) -> tuple[QScrollArea, QVBoxLayout]:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        content.setObjectName("pageContent")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)
        scroll.setWidget(content)
        return scroll, layout

    def _page_header(self, title: str, subtitle: str) -> QWidget:
        header = QFrame()
        header.setObjectName("pageHeader")
        layout = QVBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        title_label = QLabel(title)
        title_label.setObjectName("pageTitle")
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("pageSubtitle")
        subtitle_label.setWordWrap(True)
        layout.addWidget(title_label)
        layout.addWidget(subtitle_label)
        return header

    def _card(self, title: str, subtitle: str = "") -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(12)
        title_label = QLabel(title)
        title_label.setObjectName("sectionTitle")
        layout.addWidget(title_label)
        if subtitle:
            subtitle_label = QLabel(subtitle)
            subtitle_label.setObjectName("sectionSubtitle")
            subtitle_label.setWordWrap(True)
            layout.addWidget(subtitle_label)
        return card, layout

    def _action_button(self, label: str, object_name: str, icon: QStyle.StandardPixmap | None = None) -> QPushButton:
        button = QPushButton(label)
        button.setObjectName(object_name)
        button.setMinimumHeight(42)
        if icon is not None:
            button.setIcon(self.style().standardIcon(icon))
        self.busy_sensitive_buttons.append(button)
        return button

    def _choice_button(self, title: str, body: str) -> QPushButton:
        button = QPushButton(f"{title}\n{body}\nStatus: Checking")
        button.setObjectName("tvCard")
        button.setCheckable(True)
        button.setMinimumHeight(126)
        return button

    def _remote_body(self) -> QWidget:
        body = QFrame()
        body.setObjectName("remoteBody")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(22, 22, 22, 22)
        body_layout.setSpacing(18)

        top_row = QHBoxLayout()
        self._add_remote_button(top_row, "Back", "back", 0, 0, "remoteAuxButton")
        self._add_remote_button(top_row, "Home", "home", 0, 0, "remoteAuxButton")
        self._add_remote_button(top_row, "Menu", "menu", 0, 0, "remoteAuxButton")
        body_layout.addLayout(top_row)

        dpad = QGridLayout()
        dpad.setHorizontalSpacing(10)
        dpad.setVerticalSpacing(10)
        self._add_remote_button(dpad, "Up", "up", 0, 1, "remoteDpadButton")
        self._add_remote_button(dpad, "Left", "left", 1, 0, "remoteDpadButton")
        self._add_remote_button(dpad, "OK", "ok", 1, 1, "remoteOkButton")
        self._add_remote_button(dpad, "Right", "right", 1, 2, "remoteDpadButton")
        self._add_remote_button(dpad, "Down", "down", 2, 1, "remoteDpadButton")
        body_layout.addLayout(dpad)

        volume_row = QHBoxLayout()
        self._add_remote_button(volume_row, "Volume Up", "volume_up", 0, 0, "remoteAuxButton")
        self._add_remote_button(volume_row, "Volume Down", "volume_down", 0, 0, "remoteAuxButton")
        self._add_remote_button(volume_row, "Mute", "mute", 0, 0, "remoteAuxButton")
        body_layout.addLayout(volume_row)

        hint = QLabel("Keyboard shortcuts: arrows, Enter, Esc/Backspace, Home")
        hint.setObjectName("mutedText")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body_layout.addWidget(hint)
        return body

    def _add_remote_button(
        self,
        layout: QGridLayout | QHBoxLayout,
        label: str,
        key_name: str,
        row: int,
        column: int,
        object_name: str = "secondaryButton",
    ) -> QPushButton:
        button = QPushButton(label)
        button.setObjectName(object_name)
        button.clicked.connect(lambda _checked=False, name=key_name: self._send_remote_key(name))
        self.remote_buttons.append(button)
        if isinstance(layout, QGridLayout):
            layout.addWidget(button, row, column)
        else:
            layout.addWidget(button)
        return button

    def _wire_actions(self) -> None:
        self.choice_group.idClicked.connect(self._select_system)
        self.refresh_button.clicked.connect(self._refresh_tools_and_avds)
        self.setup_button.clicked.connect(self._start_setup_wizard)
        self.fix_launch_button.clicked.connect(self._fix_everything_and_launch)
        self.retry_setup_button.clicked.connect(self._start_setup_wizard)
        self.launch_google_button.clicked.connect(lambda: self._launch_tv_window("google_tv", "Salem_Google_TV"))
        self.stop_button.clicked.connect(self._stop_emulator)
        self.restart_button.clicked.connect(self._restart_selected)
        self.tv_mode_button.clicked.connect(lambda _checked=False: self._enter_tv_mode())
        self.exit_tv_mode_button.clicked.connect(lambda _checked=False: self._exit_tv_mode())
        self.home_enter_tv_mode_button.clicked.connect(lambda _checked=False: self._enter_tv_mode())
        self.home_exit_tv_mode_button.clicked.connect(lambda _checked=False: self._exit_tv_mode())
        self.install_button.clicked.connect(self._install_apk)
        self.send_text_button.clicked.connect(self._send_text_to_tv)
        self.test_sound_button.clicked.connect(self._test_sound)
        self.tv_text_input.returnPressed.connect(self._send_text_to_tv)
        self.popout_remote_button.clicked.connect(self._open_remote_popout)
        self.popout_always_on_top_check.toggled.connect(self._store_remote_popout_preference)
        self.remote_stop_button.clicked.connect(self._stop_emulator)
        self.copy_diagnostics_button.clicked.connect(self._copy_diagnostics)
        self.open_logs_button.clicked.connect(self._open_logs_folder)
        self.home_copy_diagnostics_button.clicked.connect(self._copy_diagnostics)
        self.home_open_logs_button.clicked.connect(self._open_logs_folder)
        self.refresh_diagnostics_button.clicked.connect(self._refresh_runtime_diagnostics_async)
        self.optimize_performance_button.clicked.connect(self._optimize_performance)
        self.network_status_button.clicked.connect(self._check_network_status)
        self.save_settings_button.clicked.connect(self._save_settings_from_ui)
        self.clear_old_logs_button.clicked.connect(self._clear_old_logs)
        self.reset_settings_button.clicked.connect(self._reset_settings)
        self.settings_open_logs_button.clicked.connect(self._open_logs_folder)
        self.settings_auto_update_check.toggled.connect(self._sync_auto_update_from_settings)
        self.updates_auto_update_check.toggled.connect(self._sync_auto_update_from_updates)
        self.check_updates_button.clicked.connect(self._check_for_updates)
        self.support_open_logs_button.clicked.connect(self._open_logs_folder)
        self.support_copy_diagnostics_button.clicked.connect(self._copy_diagnostics)
        self.support_send_email_button.clicked.connect(self._send_support_email)
        self._wire_keyboard_shortcuts()

    def _wire_keyboard_shortcuts(self) -> None:
        shortcut_map = {
            Qt.Key.Key_Up: "up",
            Qt.Key.Key_Down: "down",
            Qt.Key.Key_Left: "left",
            Qt.Key.Key_Right: "right",
            Qt.Key.Key_Return: "ok",
            Qt.Key.Key_Enter: "ok",
            Qt.Key.Key_Escape: "back",
            Qt.Key.Key_Backspace: "back",
            Qt.Key.Key_Home: "home",
        }
        for key, remote_key in shortcut_map.items():
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
            shortcut.activated.connect(lambda name=remote_key: self._send_remote_key(name, quiet=True))
            self.shortcuts.append(shortcut)

    def _switch_page(self, index: int) -> None:
        if 0 <= index < self.pages.count():
            self.pages.setCurrentIndex(index)
            self._refresh_state()
            if self.pages.widget(index) == self.diagnostics_page:
                self._refresh_runtime_diagnostics_async()

    def _open_remote_popout(self) -> None:
        if self.remote_window:
            self.remote_window.show()
            self.remote_window.raise_()
            self.remote_window.activateWindow()
            return
        self.remote_window = RemoteWindow(
            send_key=lambda key_name: self._send_remote_key(key_name),
            test_sound=self._test_sound,
            stop_emulator=self._stop_emulator,
        )
        self.remote_window.destroyed.connect(lambda _obj=None: self._clear_remote_window())
        self.remote_window.set_remote_enabled(bool(self.tools.adb and self.controller.device_serial and not self.setup_running))
        if self.popout_always_on_top_check.isChecked():
            self.remote_window.always_on_top.setChecked(True)
        self.remote_window.show()

    def _clear_remote_window(self) -> None:
        self.remote_window = None

    def _copy_diagnostics(self) -> None:
        text = self.diagnostics_log.toPlainText()
        if not text.strip():
            text = self._build_runtime_diagnostics_safe()
        QApplication.clipboard().setText(text)
        self.status.showMessage("Diagnostics copied to clipboard")

    def _open_logs_folder(self) -> None:
        SALEM_LOG_DIR.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(SALEM_LOG_DIR)))
        self.status.showMessage(f"Opened logs folder: {SALEM_LOG_DIR}")

    def _load_local_settings(self) -> dict[str, object]:
        settings = _default_settings()
        if SETTINGS_PATH.exists():
            try:
                loaded = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    settings.update(loaded)
            except (OSError, json.JSONDecodeError):
                pass
        return settings

    def _save_local_settings(self) -> None:
        SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
        SETTINGS_PATH.write_text(json.dumps(self.local_settings, indent=2, sort_keys=True), encoding="utf-8")

    def _collect_settings_from_ui(self) -> dict[str, object]:
        settings = _default_settings()
        settings.update(
            {
                "theme": self.theme_combo.currentText(),
                "language": self.language_combo.currentText(),
                "auto_update": self.settings_auto_update_check.isChecked(),
                "log_retention_days": self.log_retention_spin.value(),
                "support_email": self.support_email_input.text().strip() or SUPPORT_EMAIL,
                "remote_always_on_top": self.popout_always_on_top_check.isChecked(),
            }
        )
        return settings

    def _save_settings_from_ui(self) -> None:
        self.local_settings = self._collect_settings_from_ui()
        try:
            self._save_local_settings()
        except OSError as exc:
            self.settings_status_label.setText(f"Settings save failed: {exc}")
            self.status.showMessage("Settings save failed")
            return
        self.settings_status_label.setText(f"Settings saved locally: {SETTINGS_PATH}")
        self.status.showMessage("Settings saved")

    def _reset_settings(self) -> None:
        self.local_settings = _default_settings()
        self.theme_combo.setCurrentText(str(self.local_settings["theme"]))
        self.language_combo.setCurrentText(str(self.local_settings["language"]))
        self.settings_auto_update_check.setChecked(bool(self.local_settings["auto_update"]))
        self.updates_auto_update_check.setChecked(bool(self.local_settings["auto_update"]))
        self.log_retention_spin.setValue(int(self.local_settings["log_retention_days"]))
        self.support_email_input.setText(str(self.local_settings["support_email"]))
        self.popout_always_on_top_check.setChecked(False)
        try:
            if SETTINGS_PATH.exists():
                SETTINGS_PATH.unlink()
        except OSError as exc:
            self.settings_status_label.setText(f"Settings reset failed: {exc}")
            return
        self.settings_status_label.setText("Settings reset to defaults.")
        self.status.showMessage("Settings reset")

    def _clear_old_logs(self) -> None:
        SALEM_LOG_DIR.mkdir(parents=True, exist_ok=True)
        retention_days = self.log_retention_spin.value()
        cutoff = time.time() - retention_days * 86400
        deleted = 0
        for log_file in SALEM_LOG_DIR.glob("*.log"):
            try:
                if log_file.stat().st_mtime < cutoff:
                    log_file.unlink()
                    deleted += 1
            except OSError:
                continue
        self.settings_status_label.setText(f"Cleared {deleted} log file(s) older than {retention_days} day(s).")
        self.status.showMessage("Old logs cleared")

    def _sync_auto_update_from_settings(self, enabled: bool) -> None:
        if hasattr(self, "updates_auto_update_check"):
            self.updates_auto_update_check.blockSignals(True)
            self.updates_auto_update_check.setChecked(enabled)
            self.updates_auto_update_check.blockSignals(False)
        self.local_settings["auto_update"] = enabled

    def _sync_auto_update_from_updates(self, enabled: bool) -> None:
        if hasattr(self, "settings_auto_update_check"):
            self.settings_auto_update_check.blockSignals(True)
            self.settings_auto_update_check.setChecked(enabled)
            self.settings_auto_update_check.blockSignals(False)
        self.local_settings["auto_update"] = enabled

    def _store_remote_popout_preference(self, enabled: bool) -> None:
        self.local_settings["remote_always_on_top"] = enabled

    def _check_for_updates(self) -> None:
        self.update_status_label.setText("Checking for updates...")
        self.update_progress.setValue(5)
        feed_url = os.environ.get("SALEM_UPDATE_VERSION_URL", UPDATE_FEED_URL).strip()
        if not feed_url:
            self.update_progress.setValue(0)
            self.update_status_label.setText(
                "Update status: not configured yet. Add a GitHub Releases version.json URL before enabling public update checks."
            )
            self.status.showMessage("Update check is not configured")
            return
        self._set_busy(True, "Checking for updates...")
        self._run_task(lambda: self._fetch_update_version(feed_url), self._after_update_check)

    def _fetch_update_version(self, feed_url: str) -> dict[str, object]:
        from urllib.request import urlopen

        with urlopen(feed_url, timeout=15) as response:  # noqa: S310 - feed URL is operator-configured.
            data = response.read(1024 * 1024).decode("utf-8", errors="replace")
        parsed = json.loads(data)
        if not isinstance(parsed, dict):
            raise RuntimeError("GitHub Releases version.json did not contain an object.")
        return parsed

    def _after_update_check(self, data: object) -> None:
        self._set_busy(False, "Update check complete")
        self.update_progress.setValue(100)
        info = data if isinstance(data, dict) else {}
        latest_version = str(info.get("version", "")).strip()
        if latest_version and latest_version != __version__:
            self.update_status_label.setText(f"Update found: {latest_version}. Download/install automation is not configured yet.")
        elif latest_version:
            self.update_status_label.setText(f"Salem Google TV Emulator is up to date at v{__version__}.")
        else:
            self.update_status_label.setText("Update check completed, but version.json did not include a version field.")

    def _send_support_email(self) -> None:
        email = self.support_email_input.text().strip() or SUPPORT_EMAIL
        subject = quote(f"{__app_name__} v{__version__} support")
        body = quote(
            "Describe the issue here.\n\n"
            f"App: {__app_name__} v{__version__}\n"
            f"Active serial: {self.controller.device_serial or 'not detected'}\n\n"
            "Use Copy Diagnostic Info in Salem if you want to include diagnostics after reviewing them."
        )
        QDesktopServices.openUrl(QUrl(f"mailto:{email}?subject={subject}&body={body}"))
        self.support_status_label.setText("Opened a support email draft in the default mail app. Review it before sending.")
        self.status.showMessage("Support email draft opened")

    def _optimize_performance(self) -> None:
        if self.controller.is_running:
            message = "Stop Google TV before applying AVD performance settings."
            self.performance_status_label.setText(message)
            self._log(message)
            return
        avd = find_google_tv_avd(self.avds)
        if not avd:
            message = "Salem_Google_TV was not found. Run Setup/Repair first."
            self.performance_status_label.setText(message)
            self._log(message)
            return
        settings = PerformanceSettings(
            ram_mb=self.performance_ram_spin.value(),
            cpu_cores=self.performance_cpu_spin.value(),
            gpu_host=self.performance_gpu_host_check.isChecked(),
        )
        self._set_busy(True, "Applying performance settings...")
        self._run_task(lambda: apply_google_tv_performance_settings(avd, settings), self._after_performance_optimized)

    def _after_performance_optimized(self, output: object) -> None:
        self._set_busy(False, "Performance settings applied")
        text = str(output)
        self.performance_status_label.setText(text.replace("\n", " | "))
        self._log(text)
        self._refresh_tools_and_avds()

    def _check_network_status(self) -> None:
        self._set_busy(True, "Checking network status...")
        self._run_task(self.controller.network_status, self._after_network_status)

    def _after_network_status(self, output: object) -> None:
        self._set_busy(False, "Network diagnostics complete")
        self.performance_status_label.setText("Network diagnostics copied into Diagnostics.")
        if hasattr(self, "network_state_label"):
            self.network_state_label.setText("Network state: diagnostics captured")
        if hasattr(self, "home_network_status_label"):
            self.home_network_status_label.setText("Network: diagnostics captured")
        text = f"Network Status Diagnostics\n==========================\n{output}"
        self.diagnostics_log.setPlainText(text)
        self.output_tabs.setCurrentWidget(self.diagnostics_log)
        self.pages.setCurrentWidget(self.diagnostics_page)

    def _select_system(self, button_id: int) -> None:
        self.selected_type = "google_tv"
        self._refresh_state()

    def _refresh_tools_and_avds(self) -> None:
        self._log("Refreshing Android SDK tools and AVDs...")
        self.tools = detect_android_tools()
        self.avds = list_avds(self.tools)
        self.controller.tools = self.tools
        self._refresh_hypervisor_status_async()
        self._refresh_state()

    def _refresh_state(self) -> None:
        selected_avd = self._active_avd()
        display_avd = selected_avd or self._display_avd_for_selected_type()
        ready = bool(self.tools.ready and selected_avd)
        running = self.controller.is_running
        self.start_button.setEnabled(ready)
        self.restart_button.setEnabled(ready)
        self.launch_google_button.setEnabled(bool(self.tools.ready and find_google_tv_avd(self.avds) and not running))
        self.stop_button.setEnabled(running)
        self.install_button.setEnabled(bool(self.tools.adb))
        self.setup_button.setEnabled(not self.setup_running)
        self.fix_launch_button.setEnabled(not self.setup_running)
        self.retry_setup_button.setEnabled(not self.setup_running)
        remote_ready = bool(self.tools.adb and (self.controller.device_serial or running))
        self._set_remote_controls_enabled(remote_ready and not self.setup_running)
        self.tv_text_input.setEnabled(remote_ready and not self.setup_running)
        self.send_text_button.setEnabled(remote_ready and not self.setup_running)
        self.popout_remote_button.setEnabled(bool(self.tools.adb))
        self.exit_tv_mode_button.setEnabled(self.tv_mode_active)
        self.tv_mode_button.setEnabled(bool(self.tools.ready and running))
        if hasattr(self, "home_enter_tv_mode_button"):
            self.home_enter_tv_mode_button.setEnabled(bool(self.tools.ready and running))
        if hasattr(self, "home_exit_tv_mode_button"):
            self.home_exit_tv_mode_button.setEnabled(self.tv_mode_active)
        if hasattr(self, "remote_stop_button"):
            self.remote_stop_button.setEnabled(running)

        if selected_avd:
            self.status.showMessage(f"Ready: Google TV -> {selected_avd.display_name}")
            self.info_log.setPlainText(self._environment_summary(selected_avd))
        else:
            if self.tools.ready and display_avd:
                self.status.showMessage(f"Ready: Google TV -> {display_avd.display_name}")
                self.info_log.setPlainText(self._environment_summary(display_avd))
            else:
                self.status.showMessage("Setup required")
                self.info_log.setPlainText(build_setup_instructions(self.selected_type, self.tools, self.avds))
        self._update_tv_cards()
        self._update_runtime_labels(display_avd)

    def _set_remote_controls_enabled(self, enabled: bool) -> None:
        for button in self.remote_buttons:
            button.setEnabled(enabled)
        if self.remote_window:
            self.remote_window.set_remote_enabled(enabled)

    def _display_avd_for_selected_type(self) -> AvdInfo | None:
        return find_google_tv_avd(self.avds)

    def _update_tv_cards(self) -> None:
        google_avd = find_google_tv_avd(self.avds)
        self.google_tv_button.setText(self._tv_card_text("Google TV", "Google TV profile", google_avd))
        self.google_tv_button.setChecked(True)

    def _tv_card_text(self, title: str, body: str, avd: AvdInfo | None) -> str:
        status = self._tv_status(avd)
        detail = avd.display_name if avd else "Install from Setup"
        return f"{title}\n{body}\nStatus: {status}\n{detail}"

    def _tv_status(self, avd: AvdInfo | None) -> str:
        if not avd:
            return "Missing"
        if self.controller.is_running and self.controller.current_avd and self.controller.current_avd.name == avd.name:
            return "Running"
        return "Ready"

    def _update_runtime_labels(self, selected_avd: AvdInfo | None) -> None:
        if self.controller.is_running and not self.controller.device_serial:
            try:
                self.controller.refresh_device_serial()
            except Exception:
                pass
        serial = self.controller.device_serial or "not detected"
        running = self.controller.is_running
        tv_mode = "active" if self.tv_mode_active else "inactive"
        selected = selected_avd.display_name if selected_avd else "none"
        state = "Running" if running else ("Ready" if selected_avd and self.tools.ready else "Setup required")
        launch = self.controller.launch_info
        adb_status = "ready" if self.tools.adb else "missing"
        window_status = "selected" if self.last_tv_mode_hwnd else ("running; use TV Mode to select" if running else "not detected")
        audio_backend = launch.audio_backend if launch else "default (enabled)"
        selected_window = (
            f"Selected emulator window: hwnd={self.last_tv_mode_hwnd} | {self.last_tv_mode_title}"
            if self.last_tv_mode_hwnd
            else "Selected emulator window: not detected"
        )
        viewport_fill = self._current_viewport_fill_text()
        if hasattr(self, "home_status_label"):
            self.home_status_label.setText(f"{state} | Selected: {selected}")
        if hasattr(self, "active_serial_label"):
            self.active_serial_label.setText(f"Active serial: {serial}")
        if hasattr(self, "home_adb_status_label"):
            self.home_adb_status_label.setText(f"ADB: {adb_status}")
        if hasattr(self, "home_window_status_label"):
            self.home_window_status_label.setText(f"Emulator window: {window_status}")
        if hasattr(self, "home_tv_mode_quick_label"):
            self.home_tv_mode_quick_label.setText(f"TV Mode: {tv_mode}")
        if hasattr(self, "home_audio_status_label"):
            self.home_audio_status_label.setText(f"Audio: {audio_backend}")
        if hasattr(self, "sidebar_state_label"):
            self.sidebar_state_label.setText(state)
        if hasattr(self, "sidebar_serial_label"):
            self.sidebar_serial_label.setText(f"Serial: {serial}")
        if hasattr(self, "tv_mode_status_label"):
            self.tv_mode_status_label.setText(f"TV Mode: {tv_mode} | F11 toggles")
        if hasattr(self, "text_active_serial_label"):
            self.text_active_serial_label.setText(f"Active emulator serial: {serial}")
        if hasattr(self, "audio_backend_label"):
            self.audio_backend_label.setText(f"Audio backend: {audio_backend}")
        if hasattr(self, "audio_status_label"):
            self.audio_status_label.setText("Audio: enabled; Salem never passes -no-audio.")
        if hasattr(self, "tv_mode_selected_window_label"):
            self.tv_mode_selected_window_label.setText(selected_window)
        if hasattr(self, "tv_mode_viewport_label"):
            self.tv_mode_viewport_label.setText(f"Viewport fill percentage: {viewport_fill}")
        if hasattr(self, "tv_mode_message_label"):
            self.tv_mode_message_label.setText(self.last_tv_mode_message)
        if hasattr(self, "performance_summary_label"):
            self.performance_summary_label.setText(self._performance_summary(selected_avd))

    def _active_avd(self) -> AvdInfo | None:
        return find_google_tv_avd(self.avds)

    def _performance_summary(self, avd: AvdInfo | None) -> str:
        if not avd:
            return "Performance settings: Salem_Google_TV is not created yet."
        ram = avd.config.get("hw.ramSize", "unknown")
        cpu = avd.config.get("hw.cpu.ncore", "unknown")
        gpu = avd.config.get("hw.gpu.mode") or avd.config.get("hw.gpu.enabled", "unknown")
        speed = avd.config.get("runtime.network.speed", "default")
        latency = avd.config.get("runtime.network.latency", "default")
        return f"Current AVD settings: RAM {ram} MB | CPU cores {cpu} | GPU {gpu} | Network {speed}/{latency}"

    def _current_viewport_fill_text(self) -> str:
        selected_rect = self.tv_mode_state.fullscreen_rect if self.tv_mode_state else None
        selected_hwnd = self.tv_mode_state.hwnd if self.tv_mode_state else self.last_tv_mode_hwnd
        if not selected_hwnd or not selected_rect:
            return "unknown"
        try:
            children = list_child_windows(selected_hwnd)
            render_child = self._find_render_surface_child(children, selected_rect)
        except Exception:
            return "unknown"
        if not render_child:
            return "unknown"
        fill_basis = self.tv_mode_state.monitor_rect if self.tv_mode_state else selected_rect
        return f"{self._viewport_fill_percentage(render_child.rect, fill_basis):.2f}%"

    def _find_avd(self, name: str) -> AvdInfo | None:
        for avd in self.avds:
            if avd.name == name:
                return avd
        return None

    def _environment_summary(self, selected_avd: AvdInfo) -> str:
        active_serial = self.controller.device_serial or "Not detected yet"
        lines = [
            "Environment:",
            *self.tools.status_lines(),
            f"Active emulator serial: {active_serial}",
            f"TV Mode active: {str(self.tv_mode_active).lower()}",
            "",
            "Selected AVD:",
            selected_avd.detail,
        ]
        unsupported_tv = [avd for avd in self.avds if avd.name != selected_avd.name and avd.tv_type]
        if unsupported_tv:
            lines.extend(["", "Other TV AVDs detected but not used by Salem v1.0:"])
            lines.extend(f"- {avd.detail}" for avd in unsupported_tv)
        lines.extend(
            [
                "",
                "Use the buttons on the left or the keyboard remote keys while this window is focused.",
            ]
        )
        return "\n".join(lines)

    def _fix_everything_and_launch(self, resume_after_reboot: bool = False) -> None:
        if not resume_after_reboot:
            reply = QMessageBox.question(
                self,
                "Fix Everything & Launch",
                (
                    "Salem will verify/install the portable JDK, Android SDK tools, TV system images, AVDs, "
                    "and Windows virtualization features. If HypervisorPlatform or VirtualMachinePlatform is disabled, "
                    "Windows will show an admin prompt and a restart will be required.\n\n"
                    "Do you confirm SDK license acceptance and Windows feature checks?"
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                self._log("Fix Everything & Launch cancelled.")
                return

        self.setup_running = True
        self.retry_setup_button.hide()
        self._reset_setup_progress()
        self.info_log.setPlainText("Fixing emulator engine and launch requirements...")
        self.diagnostics_log.setPlainText("Checking setup, Windows features, and launch diagnostics...")
        self.output_tabs.setCurrentWidget(self.info_log)
        self._set_busy(True, "Fixing setup and launch requirements...")
        selected_type = self.selected_type
        manual_google = self.manual_google_package.text()
        self._run_task(
            lambda: self._run_fix_everything_backend(selected_type, manual_google),
            self._after_fix_everything,
        )

    def _run_fix_everything_backend(
        self,
        selected_type: str,
        manual_google_package: str,
    ) -> FixEverythingResult:
        setup_result = install_tv_emulator_engine(
            accept_licenses=True,
            progress=lambda progress: self.signals.setup_progress.emit(progress),
            manual_google_tv_package=manual_google_package,
        )
        hypervisor = check_hypervisor_features()
        if not hypervisor.ready:
            enable_result = check_and_enable_hypervisor_features_elevated(hypervisor.missing)
            if enable_result.restart_required:
                save_pending_fix_launch(selected_type)
            else:
                clear_pending_fix_launch()
            return FixEverythingResult(
                setup_result=setup_result,
                selected_type=selected_type,
                restart_required=enable_result.restart_required,
                hypervisor_status=enable_result.status.to_text(),
                feature_enable_output=enable_result.output,
            )
        clear_pending_fix_launch()
        return FixEverythingResult(
            setup_result=setup_result,
            selected_type=selected_type,
            restart_required=False,
            hypervisor_status=hypervisor.to_text(),
        )

    def _after_fix_everything(self, result: FixEverythingResult) -> None:
        self.setup_running = False
        self.selected_type = result.selected_type
        self.google_tv_button.setChecked(True)
        apply_salem_sdk_environment(force=True)
        self.tools = detect_android_tools()
        self.avds = list_avds(self.tools)
        self.controller.tools = self.tools
        self.hypervisor_status_text = result.hypervisor_status
        if result.setup_result.diagnostics:
            self._set_diagnostics(result.setup_result.diagnostics)
        self._set_busy(False, "Setup checks complete")
        self._log(result.setup_result.summary())
        self._log(result.hypervisor_status)

        if result.restart_required:
            self._log("Restart required before Salem can launch the emulator. Reopen Salem after Windows restarts and it will continue.")
            if result.feature_enable_output:
                self._log(result.feature_enable_output)
            QMessageBox.information(
                self,
                "Restart Required",
                "Windows virtualization features were enabled. Restart Windows, then reopen Salem to continue setup and launch.",
            )
            return

        self._log("All launch requirements are ready. Starting selected TV system.")
        self._start_selected()

    def _maybe_resume_pending_fix_launch(self) -> None:
        pending_type = load_pending_fix_launch()
        if not pending_type:
            return
        self.selected_type = pending_type
        self.google_tv_button.setChecked(True)
        self._log("Continuing Fix Everything & Launch from the pending restart marker.")
        self._fix_everything_and_launch(resume_after_reboot=True)

    def _refresh_hypervisor_status_async(self) -> None:
        self._run_task(self._safe_hypervisor_status_text, self._after_hypervisor_status)

    def _safe_hypervisor_status_text(self) -> str:
        try:
            return check_hypervisor_features().to_text()
        except Exception as exc:  # noqa: BLE001 - diagnostics should stay non-fatal.
            return f"Hypervisor status: Could not check Windows features: {exc}"

    def _after_hypervisor_status(self, status_text: object) -> None:
        self.hypervisor_status_text = str(status_text)
        self._refresh_runtime_diagnostics_async()

    def _start_setup_wizard(self) -> None:
        reply = QMessageBox.question(
            self,
            "Install Google TV Engine",
            (
                "Salem will download Google's official Android Command Line Tools, install SDK packages, "
                "and run sdkmanager --licenses with yes answers for Android SDK license prompts.\n\n"
                "Do you confirm that Salem may accept the Android SDK licenses for this app setup?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            self._log("Setup cancelled before license acceptance.")
            return

        self.setup_running = True
        self.retry_setup_button.hide()
        self._reset_setup_progress()
        self.info_log.setPlainText("Starting automatic TV emulator engine setup...")
        self.diagnostics_log.setPlainText("Waiting for sdkmanager --list output...")
        self.output_tabs.setCurrentWidget(self.info_log)
        self._set_busy(True, "Installing TV emulator engine...")
        self._run_task(
            lambda: install_tv_emulator_engine(
                accept_licenses=True,
                progress=lambda progress: self.signals.setup_progress.emit(progress),
                manual_google_tv_package=self.manual_google_package.text(),
            ),
            self._after_setup_success,
        )

    def _after_setup_success(self, result: SetupResult) -> None:
        self.setup_running = False
        apply_salem_sdk_environment(force=True)
        self.tools = detect_android_tools()
        self.avds = list_avds(self.tools)
        self.controller.tools = self.tools
        if result.diagnostics:
            self._set_diagnostics(result.diagnostics)
        self._set_busy(False, "TV emulator engine installed")
        self._log(result.summary())

    def _after_setup_error(self, failure: TaskFailure) -> None:
        self.setup_running = False
        if self.current_setup_stage:
            self._set_setup_stage(self.current_setup_stage, "error")
        self.retry_setup_button.show()
        self._set_busy(False, "Setup failed")
        self._log(f"Setup failed:\n{failure.exception}\n\nRetry Setup can continue after the failing step is fixed.")
        self.output_tabs.setCurrentWidget(self.diagnostics_log)

    def _on_setup_progress(self, progress: SetupProgress) -> None:
        self.current_setup_stage = progress.stage
        self._set_setup_stage(progress.stage, progress.status)
        if progress.diagnostics:
            self._set_diagnostics(progress.diagnostics)
        elif progress.diagnostic_text:
            self.diagnostics_log.setPlainText(progress.diagnostic_text)
        if progress.message:
            self.status.showMessage(progress.message)
            if progress.status in {"complete", "error"} or "unavailable" in progress.message.lower():
                self._log(progress.message)

    def _set_diagnostics(self, diagnostics: ImageDetectionDiagnostics) -> None:
        self.latest_diagnostics = diagnostics
        self.diagnostics_log.setPlainText(diagnostics.to_text())

    def _reset_setup_progress(self) -> None:
        for stage in SETUP_STAGES:
            self._set_setup_stage(stage, "pending")

    def _set_setup_stage(self, stage: str, status: str) -> None:
        self.setup_stage_status[stage] = status
        label = self.setup_stage_labels[stage]
        prefix = {
            "pending": "[ ]",
            "active": "[>]",
            "complete": "[x]",
            "error": "[!]",
        }.get(status, "[ ]")
        color = {
            "pending": "#7d8a9b",
            "active": "#f5c84b",
            "complete": "#53d69f",
            "error": "#ff7b8a",
        }.get(status, "#7d8a9b")
        label.setText(f"{prefix} {stage}")
        label.setStyleSheet(f"color: {color};")

    def _start_selected(self) -> None:
        selected_avd = self._active_avd()
        if not selected_avd:
            self._refresh_state()
            return

        self._start_avd_window(selected_avd)

    def _launch_tv_window(self, tv_type: str, preferred_name: str) -> None:
        self.selected_type = "google_tv"
        self.google_tv_button.setChecked(True)
        selected_avd = self._find_avd(preferred_name) or find_google_tv_avd(self.avds)
        if not selected_avd:
            self._refresh_state()
            self._log(f"No AVD found for {preferred_name}.")
            return
        self._start_avd_window(selected_avd)

    def _start_avd_window(self, selected_avd: AvdInfo) -> None:
        self.launch_poll_timer.stop()
        self.launch_serial_poll_in_flight = False
        self._set_busy(True, "Starting emulator...")
        self._run_task(lambda: self.controller.start_with_info(selected_avd, wait_for_serial=False), self._after_start)

    def _after_start(self, result: LaunchInfo) -> None:
        self.emulator_process = self.controller.emulator_process
        self.tv_mode_active = False
        self.tv_mode_state = None
        self.last_tv_mode_hwnd = None
        self.last_tv_mode_title = "Not matched yet."
        self.last_tv_mode_class_name = "Not matched yet."
        self.last_tv_mode_pid = None
        self.last_tv_mode_message = "TV Mode has not been used for this launch yet."
        self.last_tv_mode_restored_rect = None
        self.launch_serial_deadline = time.monotonic() + 90
        self._set_busy(False, f"Started emulator process {result.pid}; waiting for ADB")
        self._log(
            "Emulator launch:\n"
            f"PID: {result.pid}\n"
            f"AVD: {result.avd_name}\n"
            f"Audio backend: {result.audio_backend}\n"
            f"CWD: {result.cwd}\n"
            f"Log: {result.log_path}\n"
            f"ADB serial: {result.serial or 'Not detected'}\n"
            f"Command: {result.command_line}"
        )
        self.placeholder.setVisible(True)
        self.embed_attempts = 0
        self.embed_timer.stop()
        self._log("Docking is disabled by default. The official emulator window is running normally.")
        self._refresh_runtime_diagnostics_async()
        self._refresh_state()
        self.status.showMessage("Emulator launched; waiting for active ADB serial...")
        self.launch_poll_timer.start()
        QTimer.singleShot(500, self._poll_launch_serial)

    def _poll_launch_serial(self) -> None:
        if self.launch_serial_poll_in_flight:
            return
        if not self.controller.is_running:
            self.launch_poll_timer.stop()
            self.status.showMessage("Emulator is not running")
            self._refresh_state()
            return
        if time.monotonic() >= self.launch_serial_deadline:
            self.launch_poll_timer.stop()
            self._log(
                "No active emulator serial was detected within 90 seconds.\n\n"
                f"Latest adb output:\n{self.controller.last_adb_output or 'No adb output yet.'}\n\n"
                f"Latest emulator log:\n{self.controller.emulator_log_tail(120)}"
            )
            self.status.showMessage("Emulator launched, but ADB serial was not detected")
            self._refresh_runtime_diagnostics_async()
            self._refresh_state()
            return

        self.launch_serial_poll_in_flight = True
        try:
            serial = self.controller.refresh_device_serial() or ""
        except Exception as exc:  # noqa: BLE001 - keep polling resilient while emulator boots.
            self._log(f"ADB serial poll failed: {exc}")
            serial = ""
        finally:
            self.launch_serial_poll_in_flight = False

        if not serial:
            self.status.showMessage("Emulator launched; waiting for active ADB serial...")
            QTimer.singleShot(1500, self._poll_launch_serial)
            return
        self.launch_poll_timer.stop()
        self._log(f"Active emulator serial detected: {serial}")
        self._refresh_runtime_diagnostics_async()
        self._refresh_state()
        self.status.showMessage(f"Running Google TV with active serial {serial}")

    def _restart_selected(self) -> None:
        selected_avd = self._active_avd()
        if not selected_avd:
            self._refresh_state()
            return

        self._set_busy(True, "Restarting emulator...")
        self.launch_poll_timer.stop()
        self.launch_serial_poll_in_flight = False
        if self.tv_mode_active and not self._exit_tv_mode():
            self._set_busy(False, "TV Mode restore failed")
            return
        self._run_task(lambda: self.controller.restart_with_info(selected_avd, wait_for_serial=False), self._after_start)

    def _stop_emulator(self) -> None:
        self._set_busy(True, "Stopping emulator...")
        self.embed_timer.stop()
        self.launch_poll_timer.stop()
        self.launch_serial_poll_in_flight = False
        if self.tv_mode_active and not self._exit_tv_mode():
            self._set_busy(False, "TV Mode restore failed")
            return
        self.embedded_window = None
        self._run_task(self.controller.stop, self._after_stop)

    def _after_stop(self, _result: object) -> None:
        self.emulator_process = None
        self.tv_mode_active = False
        self.tv_mode_state = None
        self.last_tv_mode_hwnd = None
        self.last_tv_mode_title = "Not matched yet."
        self.last_tv_mode_class_name = "Not matched yet."
        self.last_tv_mode_pid = None
        self.last_tv_mode_message = "TV Mode has not been used yet."
        self.last_tv_mode_restored_rect = None
        self.launch_poll_timer.stop()
        self.launch_serial_poll_in_flight = False
        self._set_busy(False, "Emulator stopped")
        self.placeholder.setVisible(True)
        self._refresh_runtime_diagnostics_async()
        self._refresh_state()

    def _send_remote_key(self, key_name: str, quiet: bool = False) -> None:
        self._run_task(
            lambda: self.controller.send_remote_key(key_name),
            lambda output: self._after_adb_command(output, quiet=quiet),
            quiet=quiet,
        )

    def _send_text_to_tv(self) -> None:
        text = self.tv_text_input.text()
        if not text:
            return
        self._set_busy(True, "Sending text to TV...")
        if hasattr(self, "text_status_label"):
            self.text_status_label.setText("Last send: sending...")
        self.text_send_pending = True
        self._run_task(lambda: self.controller.send_text(text), self._after_text_sent)

    def _after_text_sent(self, output: object) -> None:
        self.text_send_pending = False
        if hasattr(self, "text_status_label"):
            self.text_status_label.setText(f"Last send: {output or 'sent'}")
        self._after_adb_command(output)

    def _test_sound(self) -> None:
        self._set_busy(True, "Testing TV audio...")
        self._run_task(self.controller.test_sound, self._after_adb_command)

    def _after_adb_command(self, output: object, quiet: bool = False) -> None:
        if quiet:
            self._refresh_runtime_diagnostics_async()
            return
        self._set_busy(False, "ADB command finished")
        if not quiet and output:
            self._log(str(output))
        self._refresh_runtime_diagnostics_async()

    def _install_apk(self) -> None:
        apk_name, _ = QFileDialog.getOpenFileName(self, "Install APK", str(Path.home()), "Android APK (*.apk)")
        if not apk_name:
            return

        apk_path = Path(apk_name)
        self._set_busy(True, f"Installing {apk_path.name}...")
        self._run_task(lambda: self.controller.install_apk(apk_path), self._after_install)

    def _after_install(self, output: str) -> None:
        self._set_busy(False, "APK install finished")
        self._log(output)
        self._refresh_state()

    def _try_embed_running_emulator(self) -> None:
        if self.tv_mode_active:
            self.embed_timer.stop()
            return
        if not self.controller.process:
            self.embed_timer.stop()
            return

        self.embed_attempts += 1
        avd_name = self.controller.current_avd.name if self.controller.current_avd else None
        hwnd = find_emulator_window(self.controller.process.pid, avd_name)
        if not hwnd:
            if self.embed_attempts >= 20:
                self.embed_timer.stop()
                self._log("Emulator is running, but no dockable Windows window was found yet.")
            return

        host_hwnd = int(self.emulator_host.winId())
        embedded = embed(hwnd, host_hwnd, self.emulator_host.width(), self.emulator_host.height())
        if embedded:
            self.embedded_window = embedded
            self.placeholder.setVisible(False)
            self.embed_timer.stop()
            self._log("Emulator window docked inside Salem.")
            self._refresh_runtime_diagnostics_async()
        else:
            place_next_to(hwnd, int(self.winId()))
            self.embed_timer.stop()
            self._log("Emulator opened beside Salem.")
            self._refresh_runtime_diagnostics_async()

    def _enter_tv_mode(self) -> None:
        if self.tv_mode_active:
            self._log("TV Mode is already active.")
            self._refresh_runtime_diagnostics_async()
            return

        self.embed_timer.stop()
        self.embedded_window = None
        hwnd = self._current_emulator_hwnd()
        if not hwnd:
            self.last_tv_mode_hwnd = None
            self.last_tv_mode_title = "No matching emulator window found."
            self.last_tv_mode_class_name = "Not matched yet."
            self.last_tv_mode_pid = None
            self.last_tv_mode_message = "TV Mode failed: no main emulator window was found. Extended Controls windows are ignored."
            self._log(self.last_tv_mode_message)
            self._refresh_runtime_diagnostics_async()
            return

        try:
            state = enter_tv_mode(hwnd)
        except Exception as exc:  # noqa: BLE001 - diagnostics should capture exact failure.
            self.tv_mode_active = False
            self.tv_mode_state = None
            self.last_tv_mode_message = f"TV Mode failed: {exc}"
            self._log(self.last_tv_mode_message)
            self._refresh_runtime_diagnostics_async()
            return

        self.tv_mode_active = True
        self.tv_mode_state = state
        self.last_tv_mode_hwnd = state.hwnd
        self.last_tv_mode_title = state.title
        self.last_tv_mode_class_name = state.class_name
        self.last_tv_mode_pid = state.pid
        self.last_tv_mode_restored_rect = None
        if state.final_rect_matches_monitor:
            self.last_tv_mode_message = (
                "TV Mode active: outer emulator window matches monitor bounds. "
                "Viewport hierarchy diagnostics are available in Diagnostics."
            )
        else:
            self.last_tv_mode_message = "TV Mode active, but the outer emulator window does not match monitor bounds. See diagnostics."
        self._log(self.last_tv_mode_message)
        self._refresh_runtime_diagnostics_async()
        self._refresh_state()

    def _exit_tv_mode(self, log_result: bool = True) -> bool:
        if not self.tv_mode_state:
            self.tv_mode_active = False
            self.last_tv_mode_message = "Exit TV Mode skipped: no saved TV Mode window state exists."
            if log_result:
                self._log(self.last_tv_mode_message)
                self._refresh_runtime_diagnostics_async()
            return True

        state = self.tv_mode_state
        try:
            restored_rect = exit_tv_mode(state)
        except Exception as exc:  # noqa: BLE001 - diagnostics should capture exact failure.
            self.last_tv_mode_message = f"Exit TV Mode failed: {exc}"
            if log_result:
                self._log(self.last_tv_mode_message)
                self._refresh_runtime_diagnostics_async()
            return False

        self.tv_mode_active = False
        self.last_tv_mode_restored_rect = restored_rect
        self.last_tv_mode_message = "TV Mode exited: original emulator window style and rect were restored."
        self.tv_mode_state = None
        if log_result:
            self._log("TV Mode exited and the emulator window was restored.")
            self._refresh_runtime_diagnostics_async()
            self._refresh_state()
        return True

    def _toggle_tv_mode(self) -> None:
        if self.tv_mode_active:
            self._exit_tv_mode()
        else:
            self._enter_tv_mode()

    def _current_emulator_hwnd(self) -> int | None:
        if self.embedded_window:
            return self.embedded_window.hwnd
        candidate = self._selected_window_candidate()
        if candidate:
            self.last_tv_mode_hwnd = candidate.hwnd
            self.last_tv_mode_title = candidate.title or get_window_title(candidate.hwnd) or "Untitled emulator window"
            self.last_tv_mode_class_name = candidate.class_name
            self.last_tv_mode_pid = candidate.pid
            bring_to_front(candidate.hwnd)
            return candidate.hwnd
        else:
            self.last_tv_mode_hwnd = None
            self.last_tv_mode_title = "No matching emulator window found."
            self.last_tv_mode_class_name = "Not matched yet."
            self.last_tv_mode_pid = None
        return None

    def _selected_window_candidate(self) -> WindowCandidate | None:
        pid = self.controller.process.pid if self.controller.process else None
        candidates = list_emulator_windows(pid, self._current_avd_name())
        return self._select_candidate_from(candidates)

    def _current_avd_name(self) -> str | None:
        if self.controller.current_avd:
            return self.controller.current_avd.name
        launch = self.controller.launch_info
        return launch.avd_name if launch else None

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key_map = {
            Qt.Key.Key_Up: "up",
            Qt.Key.Key_Down: "down",
            Qt.Key.Key_Left: "left",
            Qt.Key.Key_Right: "right",
            Qt.Key.Key_Return: "ok",
            Qt.Key.Key_Enter: "ok",
            Qt.Key.Key_Escape: "back",
            Qt.Key.Key_Backspace: "back",
            Qt.Key.Key_Home: "home",
        }
        remote_key = key_map.get(event.key())
        if remote_key:
            self._send_remote_key(remote_key, quiet=True)
            event.accept()
            return
        super().keyPressEvent(event)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.embed_timer.stop()
        self.launch_poll_timer.stop()
        self.task_poll_timer.stop()
        if self.tv_mode_active and not self._exit_tv_mode():
            event.ignore()
            return
        self.executor.shutdown(wait=False, cancel_futures=True)
        event.accept()

    def _refresh_runtime_diagnostics_async(self) -> None:
        self._run_task(self._build_runtime_diagnostics_safe, self._set_runtime_diagnostics)

    def _build_runtime_diagnostics_safe(self) -> str:
        try:
            launch = self.controller.launch_info
            window_pid = self.controller.process.pid if self.controller.process else None
            candidates = list_emulator_windows(window_pid, self._current_avd_name())
            selected_candidate = self._select_candidate_from(candidates)
            selected_hwnd = self.tv_mode_state.hwnd if self.tv_mode_state else (selected_candidate.hwnd if selected_candidate else self.last_tv_mode_hwnd)
            child_windows = list_child_windows(selected_hwnd)
            selected_rect = self.tv_mode_state.fullscreen_rect if self.tv_mode_state else (selected_candidate.rect if selected_candidate else None)
            lines = [
                "Launch Diagnostics",
                "==================",
                f"Exact emulator command: {launch.command_line if launch else 'Not launched yet'}",
                f"PID: {launch.pid if launch else 'Not launched yet'}",
                f"Active emulator serial: {self.controller.device_serial or (launch.serial if launch else 'Not detected')}",
                f"Selected AVD: {launch.avd_name if launch else (self._active_avd().name if self._active_avd() else 'None')}",
                f"Audio backend: {launch.audio_backend if launch else 'default'}",
                "Audio enabled: Yes; Salem does not pass -no-audio",
                f"TV Mode active: {str(self.tv_mode_active).lower()}",
                f"Emulator hwnd: {self.last_tv_mode_hwnd or 'Not found'}",
                f"Matched window title: {self.last_tv_mode_title}",
                f"Matched class name: {self.last_tv_mode_class_name}",
                f"Matched window PID: {self.last_tv_mode_pid or 'Not matched'}",
                "",
                self.hypervisor_status_text,
                "",
                "adb devices",
                "===========",
                self.controller.adb_devices_output(),
                "",
                "Latest ADB command output",
                "=========================",
                self.controller.last_adb_output or "No ADB command output yet.",
                "",
                "Window Candidates",
                "=================",
                self._window_candidates_diagnostics(candidates, selected_hwnd),
                "",
                "TV Mode diagnostics",
                "===================",
                self._tv_mode_diagnostics(),
                "",
                "Viewport and Toolbar Analysis",
                "=============================",
                self._viewport_analysis_diagnostics(child_windows, selected_rect),
                "",
                "Window Hierarchy Tree",
                "=====================",
                self._window_hierarchy_diagnostics(selected_hwnd, child_windows, selected_rect),
                "",
                "Selected Window Child Diagnostics",
                "=================================",
                self._child_window_diagnostics(child_windows, selected_rect),
                "",
                "Audio log messages",
                "==================",
                self.controller.audio_log_tail(),
                "",
                "Latest emulator log",
                "===================",
                self.controller.emulator_log_tail(),
            ]
            return "\n".join(lines)
        except Exception as exc:  # noqa: BLE001 - diagnostics should not break the UI.
            return f"Diagnostics failed: {exc}"

    def _set_runtime_diagnostics(self, diagnostics: object) -> None:
        self.diagnostics_log.setPlainText(str(diagnostics))

    @staticmethod
    def _select_candidate_from(candidates: list[WindowCandidate]) -> WindowCandidate | None:
        selectable = [candidate for candidate in candidates if candidate.selectable]
        selectable.sort(key=lambda candidate: candidate.priority)
        return selectable[0] if selectable else None

    def _tv_mode_diagnostics(self) -> str:
        state = self.tv_mode_state
        lines = [
            f"TV Mode active: {str(self.tv_mode_active).lower()}",
            f"emulator hwnd: {self.last_tv_mode_hwnd or 'Not found'}",
            f"matched window title: {self.last_tv_mode_title}",
            f"matched class name: {self.last_tv_mode_class_name}",
            f"matched pid: {self.last_tv_mode_pid or 'Not matched'}",
            f"success/failure message: {self.last_tv_mode_message}",
        ]
        if not state:
            restored = self._format_rect(self.last_tv_mode_restored_rect) if self.last_tv_mode_restored_rect else "None"
            lines.append(f"last restored rect: {restored}")
            return "\n".join(lines)

        lines.extend(
            [
                f"monitor bounds: {self._format_rect(state.monitor_rect)}",
                f"original rect: {self._format_rect(state.original_rect)}",
                f"outer window rect after TV Mode: {self._format_rect(state.fullscreen_rect)}",
                f"outer window rect matches monitor bounds: {str(state.final_rect_matches_monitor).lower()}",
                f"style before: {self._format_style(state.style_before)}",
                f"style after: {self._format_style(state.style_after)}",
                f"ex style before: {self._format_style(state.ex_style_before)}",
                f"ex style after: {self._format_style(state.ex_style_after)}",
            ]
        )
        return "\n".join(lines)

    def _window_candidates_diagnostics(self, candidates: list[WindowCandidate], selected_hwnd: int | None) -> str:
        if not candidates:
            return "No emulator-related top-level windows detected."
        return "\n".join(self._format_candidate(candidate, selected_hwnd) for candidate in candidates)

    def _viewport_analysis_diagnostics(self, children: list[ChildWindowInfo], top_rect: WindowRect | None) -> str:
        if not top_rect:
            return "No selected emulator window is available for viewport analysis."

        render_child = self._find_render_surface_child(children, top_rect)
        toolbar_child = self._find_toolbar_child(children, top_rect)
        fill_basis = self.tv_mode_state.monitor_rect if self.tv_mode_state else top_rect
        lines = [
            f"top-level rect: {self._format_rect(top_rect)}",
            f"monitor/target rect: {self._format_rect(fill_basis)}",
        ]

        if render_child:
            fill = self._viewport_fill_percentage(render_child.rect, fill_basis)
            lines.extend(
                [
                    f"render surface candidate hwnd: {render_child.hwnd}",
                    f"render surface class: {render_child.class_name or 'Unknown'}",
                    f"render surface title: {render_child.title!r}",
                    f"render surface rect: {self._format_rect(render_child.rect)}",
                    f"child containing Google TV display: hwnd={render_child.hwnd} (largest visible non-toolbar child window)",
                    f"viewport fill percentage: {fill:.2f}%",
                ]
            )
        else:
            lines.extend(
                [
                    "render surface candidate hwnd: Not identified",
                    "render surface rect: Not identified from Win32 child windows",
                    "child containing Google TV display: Not identified",
                    "viewport fill percentage: Unknown",
                    (
                        "analysis note: no child HWND clearly exposes the TV render surface; "
                        "the Android Emulator may draw it inside the top-level Qt window or a non-HWND graphics surface."
                    ),
                ]
            )

        if toolbar_child:
            lines.extend(
                [
                    f"toolbar candidate hwnd: {toolbar_child.hwnd}",
                    f"toolbar class: {toolbar_child.class_name or 'Unknown'}",
                    f"toolbar title: {toolbar_child.title!r}",
                    f"toolbar rect: {self._format_rect(toolbar_child.rect)}",
                ]
            )
        else:
            lines.append("toolbar rect: Not identified as a child HWND.")

        qt_children = [child for child in children if self._is_qt_child(child)]
        lines.append(f"Qt child windows detected: {len(qt_children)}")
        lines.append(f"total child windows detected: {len(children)}")
        return "\n".join(lines)

    def _window_hierarchy_diagnostics(
        self,
        selected_hwnd: int | None,
        children: list[ChildWindowInfo],
        top_rect: WindowRect | None,
    ) -> str:
        if not selected_hwnd:
            return "No selected emulator hwnd."
        render_child = self._find_render_surface_child(children, top_rect)
        toolbar_child = self._find_toolbar_child(children, top_rect)
        render_hwnd = render_child.hwnd if render_child else None
        toolbar_hwnd = toolbar_child.hwnd if toolbar_child else None
        lines = [f"Main Emulator Window hwnd={selected_hwnd}"]
        if not children:
            lines.append("+- No child windows detected.")
            return "\n".join(lines)

        children_by_parent: dict[int, list[ChildWindowInfo]] = {}
        for child in children:
            children_by_parent.setdefault(child.parent_hwnd, []).append(child)
        for siblings in children_by_parent.values():
            siblings.sort(key=lambda item: (item.rect.top, item.rect.left, item.hwnd))

        shown_hwnds: set[int] = set()

        def add_nodes(parent_hwnd: int, prefix: str) -> None:
            siblings = children_by_parent.get(parent_hwnd, [])
            for index, child in enumerate(siblings):
                if child.hwnd in shown_hwnds:
                    continue
                shown_hwnds.add(child.hwnd)
                is_last = index == len(siblings) - 1
                branch = "`- " if is_last else "+- "
                role = self._child_role(child, top_rect, render_hwnd, toolbar_hwnd)
                lines.append(
                    f"{prefix}{branch}hwnd={child.hwnd} parent={child.parent_hwnd} "
                    f"depth={child.depth} class={child.class_name or 'Unknown'} role={role} "
                    f"visible={str(child.visible).lower()} rect=[{self._format_rect(child.rect)}] "
                    f"title={child.title!r}"
                )
                add_nodes(child.hwnd, prefix + ("   " if is_last else "|  "))

        add_nodes(selected_hwnd, "")
        orphan_children = [child for child in children if child.hwnd not in shown_hwnds]
        if orphan_children:
            lines.append("Detached descendants")
            for child in orphan_children:
                shown_hwnds.add(child.hwnd)
                role = self._child_role(child, top_rect, render_hwnd, toolbar_hwnd)
                lines.append(
                    f"+- hwnd={child.hwnd} parent={child.parent_hwnd} depth={child.depth} "
                    f"class={child.class_name or 'Unknown'} role={role} rect=[{self._format_rect(child.rect)}] title={child.title!r}"
                )
        return "\n".join(lines)

    def _child_window_diagnostics(self, children: list[ChildWindowInfo], top_rect: WindowRect | None) -> str:
        if not children:
            return "No child windows detected for the selected emulator hwnd."
        render_child = self._find_render_surface_child(children, top_rect)
        toolbar_child = self._find_toolbar_child(children, top_rect)
        render_hwnd = render_child.hwnd if render_child else None
        toolbar_hwnd = toolbar_child.hwnd if toolbar_child else None
        return "\n".join(self._format_child_window(child, top_rect, render_hwnd, toolbar_hwnd) for child in children)

    def _format_candidate(self, candidate: WindowCandidate, selected_hwnd: int | None) -> str:
        selected = "true" if selected_hwnd and candidate.hwnd == selected_hwnd else "false"
        excluded = candidate.excluded_reason or "no"
        return (
            f"selected={selected} hwnd={candidate.hwnd} pid={candidate.pid} "
            f"class={candidate.class_name or 'Unknown'} visible={str(candidate.visible).lower()} "
            f"priority={candidate.priority} excluded={excluded} "
            f"rect=[{self._format_rect(candidate.rect)}] "
            f"style={self._format_style(candidate.style)} ex_style={self._format_style(candidate.ex_style)} "
            f"title={candidate.title!r}"
        )

    def _format_child_window(
        self,
        child: ChildWindowInfo,
        top_rect: WindowRect | None,
        render_hwnd: int | None,
        toolbar_hwnd: int | None,
    ) -> str:
        role = self._child_role(child, top_rect, render_hwnd, toolbar_hwnd)
        return (
            f"hwnd={child.hwnd} parent={child.parent_hwnd} depth={child.depth} "
            f"class={child.class_name or 'Unknown'} role={role} visible={str(child.visible).lower()} "
            f"rect=[{self._format_rect(child.rect)}] "
            f"style={self._format_style(child.style)} ex_style={self._format_style(child.ex_style)} "
            f"title={child.title!r}"
        )

    def _child_role(
        self,
        child: ChildWindowInfo,
        top_rect: WindowRect | None,
        render_hwnd: int | None,
        toolbar_hwnd: int | None,
    ) -> str:
        if render_hwnd and child.hwnd == render_hwnd:
            return "render viewport candidate"
        if toolbar_hwnd and child.hwnd == toolbar_hwnd:
            return "toolbar candidate"
        if self._is_toolbar_candidate(child, top_rect):
            return "toolbar-like child"
        if self._is_qt_child(child):
            return "Qt child window"
        return "child window"

    def _find_render_surface_child(self, children: list[ChildWindowInfo], top_rect: WindowRect | None) -> ChildWindowInfo | None:
        if not top_rect:
            return None
        top_area = max(1, self._rect_area(top_rect))
        candidates = [
            child
            for child in children
            if child.visible
            and self._rect_area(child.rect) >= top_area * 0.05
            and not self._is_toolbar_candidate(child, top_rect)
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda child: self._rect_area(child.rect))

    def _find_toolbar_child(self, children: list[ChildWindowInfo], top_rect: WindowRect | None) -> ChildWindowInfo | None:
        candidates = [child for child in children if self._is_toolbar_candidate(child, top_rect)]
        if not candidates:
            return None
        return max(candidates, key=lambda child: self._rect_area(child.rect))

    def _is_toolbar_candidate(self, child: ChildWindowInfo, top_rect: WindowRect | None) -> bool:
        text = f"{child.class_name} {child.title}".lower()
        if "toolbar" in text or "tool bar" in text:
            return True
        if not top_rect or not child.visible:
            return False
        width = max(0, child.rect.width)
        height = max(0, child.rect.height)
        if not width or not height:
            return False
        right_edge_delta = abs(child.rect.right - top_rect.right)
        left_edge_delta = abs(child.rect.left - top_rect.left)
        top_edge_delta = abs(child.rect.top - top_rect.top)
        bottom_edge_delta = abs(child.rect.bottom - top_rect.bottom)
        vertical_strip = (
            width <= max(90, int(top_rect.width * 0.12))
            and height >= int(top_rect.height * 0.35)
            and right_edge_delta <= max(24, int(top_rect.width * 0.08))
        )
        horizontal_strip = (
            height <= max(90, int(top_rect.height * 0.16))
            and width >= int(top_rect.width * 0.35)
            and (top_edge_delta <= 24 or bottom_edge_delta <= 24 or left_edge_delta <= 24)
        )
        return vertical_strip or horizontal_strip

    @staticmethod
    def _is_qt_child(child: ChildWindowInfo) -> bool:
        text = f"{child.class_name} {child.title}".lower()
        return "qt" in text or "qwindow" in text

    @staticmethod
    def _rect_area(rect: WindowRect | None) -> int:
        if not rect:
            return 0
        return max(0, rect.width) * max(0, rect.height)

    def _viewport_fill_percentage(self, rect: WindowRect, target: WindowRect | None) -> float:
        target_area = self._rect_area(target)
        if not target_area:
            return 0.0
        return min(100.0, (self._rect_area(rect) / target_area) * 100)

    @staticmethod
    def _format_rect(rect: WindowRect | None) -> str:
        if not rect:
            return "None"
        return f"left={rect.left}, top={rect.top}, right={rect.right}, bottom={rect.bottom}, size={rect.width}x{rect.height}"

    @staticmethod
    def _format_style(value: int) -> str:
        return f"0x{value & 0xFFFFFFFF:08X}"

    def _set_busy(self, busy: bool, message: str) -> None:
        self.status.showMessage(message)
        buttons = (
            self.setup_button,
            self.fix_launch_button,
            self.retry_setup_button,
            self.start_button,
            self.launch_google_button,
            self.stop_button,
            self.restart_button,
            self.refresh_button,
            self.install_button,
            self.tv_mode_button,
            self.exit_tv_mode_button,
            self.test_sound_button,
            self.send_text_button,
            *self.remote_buttons,
            *self.busy_sensitive_buttons,
        )
        for button in dict.fromkeys(buttons):
            button.setEnabled(not busy)
        self.manual_google_package.setEnabled(not busy)
        self.tv_text_input.setEnabled(not busy)
        if hasattr(self, "performance_ram_spin"):
            self.performance_ram_spin.setEnabled(not busy)
            self.performance_cpu_spin.setEnabled(not busy)
            self.performance_gpu_host_check.setEnabled(not busy)
        if busy:
            self._set_remote_controls_enabled(False)
        if not busy:
            self._refresh_state()

    def _run_task(
        self,
        fn: Callable[[], object],
        on_success: Callable[[object], None],
        quiet: bool = False,
    ) -> None:
        future = self.executor.submit(fn)
        self.pending_tasks.append((future, on_success, quiet))
        if not self.task_poll_timer.isActive():
            self.task_poll_timer.start()

    def _poll_tasks(self) -> None:
        if not self.pending_tasks:
            self.task_poll_timer.stop()
            return

        still_pending: list[tuple[Future[object], Callable[[object], None], bool]] = []
        completed: list[tuple[Future[object], Callable[[object], None], bool]] = []
        for future, on_success, quiet in self.pending_tasks:
            if future.done():
                completed.append((future, on_success, quiet))
            else:
                still_pending.append((future, on_success, quiet))

        self.pending_tasks = still_pending
        for future, on_success, quiet in completed:
            try:
                result = future.result()
                error = None
            except Exception as exc:  # noqa: BLE001 - UI needs to show backend errors.
                result = None
                error = TaskFailure(exc, traceback.format_exc(limit=6))

            self._on_task_done(on_success, result, error if not quiet else None)

        if not self.pending_tasks:
            self.task_poll_timer.stop()

    def _on_task_done(self, on_success: Callable[[object], None], result: object, error: TaskFailure | None) -> None:
        if error:
            if self.text_send_pending and hasattr(self, "text_status_label"):
                self.text_send_pending = False
                self.text_status_label.setText(f"Last send: failed - {error.exception}")
            if self.setup_running:
                self._after_setup_error(error)
                return
            self._set_busy(False, "Action failed")
            self._log(f"Error: {error.exception}\n{error.details}")
            self._refresh_runtime_diagnostics_async()
            return
        on_success(result)

    def _log(self, message: str) -> None:
        current = self.info_log.toPlainText()
        text = f"{current.rstrip()}\n\n{message}" if current else message
        self.info_log.setPlainText(text)
        self.info_log.verticalScrollBar().setValue(self.info_log.verticalScrollBar().maximum())


def main() -> int:
    _set_windows_app_user_model_id()
    app = QApplication(sys.argv)
    app.setApplicationName(__app_name__)
    icon_path = _resource_path("assets/salem_google_tv_emulator.png")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    app.setStyleSheet(APP_STYLE)
    window = SalemMainWindow()
    window.show()
    return app.exec()
