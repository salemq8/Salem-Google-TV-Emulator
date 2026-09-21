"""Restrained native-widget theme; sizes are Qt logical pixels for DPI scaling."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication

DARK = dict(bg="#151618", side="#1b1d20", surface="#24272b", field="#1d1f22", border="#383c41",
            text="#f0f1f2", muted="#a6adb6", accent="#4ac7b4", ink="#102c28", hover="#30343a", danger="#e5a0a6")
LIGHT = dict(bg="#f5f6f8", side="#e9ecf0", surface="#ffffff", field="#ffffff", border="#c9cfd7",
             text="#20252c", muted="#556270", accent="#138676", ink="#ffffff", hover="#dfe7ec", danger="#a53243")


def stylesheet(theme: str = "Dark") -> str:
    light = theme == "Light" or (theme == "System" and QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Light)
    c = LIGHT if light else DARK
    return """
    QWidget {{ font-family: 'Segoe UI'; font-size: 13px; color: {text}; }}
    QMainWindow, QWidget#root, QWidget#page, QScrollArea {{ background: {bg}; }}
    QFrame#sidebar {{ background: {side}; border-right: 1px solid {border}; }}
    QFrame#section {{ border-top: 1px solid {border}; }}
    QLabel {{ background: transparent; }}
    QLabel[role='title'] {{ font-size: 27px; font-weight: 600; }}
    QLabel[role='section'] {{ font-size: 16px; font-weight: 600; }}
    QLabel[role='muted'] {{ color: {muted}; }}
    QLabel[role='status'] {{ font-size: 20px; font-weight: 600; color: {accent}; }}
    QPushButton {{ background: {surface}; border: 1px solid {border}; border-radius: 6px;
                   padding: 5px 12px; font-weight: 600; }}
    QPushButton:hover {{ background: {hover}; }}
    QPushButton:pressed {{ border-color: {accent}; }}
    QPushButton:focus {{ border: 1px solid {accent}; }}
    QPushButton:disabled {{ color: {muted}; background: {field}; border-color: {border}; }}
    QPushButton[role='primary'] {{ background: {accent}; color: {ink}; border-color: {accent}; }}
    QPushButton[role='primary']:disabled {{ background: {field}; color: {muted}; border-color: {border}; }}
    QPushButton[role='danger'] {{ color: {danger}; }}
    QPushButton#nav {{ background: transparent; border: 0; text-align: left; padding: 10px 12px; color: {muted}; }}
    QPushButton#nav:hover {{ background: {hover}; color: {text}; }}
    QPushButton#nav:checked {{ background: {surface}; color: {accent}; border-left: 3px solid {accent}; }}
    QLineEdit, QComboBox, QSpinBox {{ background: {field}; border: 1px solid {border}; border-radius: 5px;
                                   padding: 7px 10px; min-height: 26px; selection-background-color: {accent}; }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border-color: {accent}; }}
    QComboBox QAbstractItemView {{ background: {surface}; selection-background-color: {hover}; }}
    QPlainTextEdit {{ background: {field}; border: 1px solid {border}; border-radius: 5px; padding: 10px;
                     font-family: 'Cascadia Mono', Consolas, monospace; font-size: 12px; }}
    QTabWidget::pane {{ border: 1px solid {border}; background: {bg}; }}
    QTabBar::tab {{ background: {side}; padding: 11px 16px; border-bottom: 2px solid transparent; }}
    QTabBar::tab:selected {{ color: {accent}; border-bottom-color: {accent}; }}
    QProgressBar {{ background: {field}; border: 1px solid {border}; border-radius: 4px; min-height: 16px; text-align: center; }}
    QProgressBar::chunk {{ background: {accent}; }}
    QCheckBox {{ spacing: 9px; padding: 4px 0; }}
    QWidget#remotePad {{ background: {side}; border: 1px solid {border}; border-radius: 8px; }}
    DPadWidget {{ qproperty-theme: "{dpad_theme}"; }}
    QScrollBar:vertical {{ background: {bg}; width: 10px; }}
    QScrollBar::handle:vertical {{ background: {border}; border-radius: 4px; min-height: 30px; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QStatusBar {{ background: {side}; border-top: 1px solid {border}; color: {muted}; }}
    QToolTip {{ background: {surface}; color: {text}; border: 1px solid {border}; padding: 6px; }}
    """.format(**c, dpad_theme="Light" if light else "Dark")
