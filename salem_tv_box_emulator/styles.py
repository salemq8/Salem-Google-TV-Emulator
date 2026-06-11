THEME = {
    "app_background": "#080d13",
    "sidebar_background": "#0d141d",
    "panel_background": "#0b121b",
    "card_background": "#101821",
    "input_background": "#071018",
    "border_color": "#233142",
    "border_strong": "#3a6ea8",
    "accent_color": "#13b886",
    "accent_hover": "#24c795",
    "accent_warm": "#f1c75b",
    "text_primary": "#eef4fb",
    "text_secondary": "#9aa9ba",
    "danger": "#8a3b50",
    "warning": "#f5c84b",
    "success": "#53d69f",
}


APP_STYLE = """
* {{
    font-family: "Segoe UI", "Tahoma", Arial, sans-serif;
    font-size: 13px;
    color: {text_primary};
}}

QMainWindow, QWidget#appRoot, QStackedWidget#contentStack {{
    background: {app_background};
}}

QFrame#sidebar {{
    background: {sidebar_background};
    border-right: 1px solid {border_color};
}}

QLabel#brandLogo, QLabel#heroLogo {{
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid {border_color};
    border-radius: 10px;
}}

QLabel#brandTitle {{
    font-size: 19px;
    font-weight: 800;
    color: #ffffff;
}}

QLabel#brandSubtitle, QLabel#mutedText, QLabel#pageSubtitle, QLabel#sectionSubtitle, QLabel#sidebarFooter {{
    color: {text_secondary};
}}

QLabel#sidebarFooter {{
    font-size: 11px;
    line-height: 1.35;
}}

QLabel#pageTitle {{
    font-size: 24px;
    font-weight: 800;
    color: #ffffff;
}}

QLabel#heroTitle {{
    font-size: 30px;
    font-weight: 850;
    color: #ffffff;
}}

QLabel#sectionTitle {{
    font-size: 15px;
    font-weight: 800;
    color: #f7fbff;
}}

QLabel#bodyText {{
    font-size: 14px;
    line-height: 1.45;
    color: #c8d3df;
}}

QLabel#statusStrong {{
    color: {success};
    font-weight: 800;
}}

QLabel#statusLine {{
    color: #d9e8f6;
    font-weight: 700;
}}

QLabel#statusPill, QLabel#statusPillAlt {{
    background: #111d29;
    border: 1px solid #2b3d51;
    border-radius: 8px;
    padding: 8px 10px;
    color: #dce8f4;
    font-weight: 700;
}}

QLabel#statusPillAlt {{
    color: #b7c8d9;
}}

QFrame#sidebarStatus, QFrame#card, QFrame#heroCard, QFrame#remoteBody, QFrame#emulatorHost {{
    background: {card_background};
    border: 1px solid {border_color};
    border-radius: 8px;
}}

QFrame#heroCard {{
    background: #121d29;
    border-color: #2d4258;
}}

QFrame#emulatorHost {{
    background: #05080d;
    border-color: #263446;
}}

QFrame#pageHeader {{
    background: transparent;
    border: none;
}}

QScrollArea, QScrollArea > QWidget, QScrollArea > QWidget > QWidget, QWidget#pageContent {{
    background: transparent;
    border: none;
}}

QWidget#pageContent {{
    background: {app_background};
}}

QScrollBar:vertical {{
    background: #0b1118;
    width: 10px;
    margin: 2px;
    border-radius: 5px;
}}

QScrollBar::handle:vertical {{
    background: #2c3b4e;
    border-radius: 5px;
    min-height: 36px;
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}

QPushButton {{
    background: #172231;
    border: 1px solid #2d4055;
    border-radius: 8px;
    padding: 10px 14px;
    font-weight: 700;
    color: {text_primary};
    text-align: center;
}}

QPushButton:hover {{
    background: #1f2e40;
    border-color: #45627f;
}}

QPushButton:pressed {{
    background: #111b27;
}}

QPushButton:disabled {{
    color: #637184;
    background: #101720;
    border-color: #1b2634;
}}

QPushButton#navButton {{
    text-align: left;
    padding: 8px 11px;
    background: transparent;
    border: 1px solid transparent;
    color: #afbdcc;
}}

QPushButton#navButton:hover {{
    background: #121d29;
    border-color: #263446;
    color: #ffffff;
}}

QPushButton#navButton:checked {{
    background: #172536;
    border-color: {border_strong};
    color: #ffffff;
}}

QPushButton#primaryButton {{
    background: {accent_color};
    border-color: #36d6a6;
    color: #04120e;
}}

QPushButton#primaryButton:hover {{
    background: {accent_hover};
}}

QPushButton#accentButton {{
    background: {accent_warm};
    border-color: #f5d57b;
    color: #161103;
}}

QPushButton#accentButton:hover {{
    background: #ffd66f;
}}

QPushButton#secondaryButton {{
    background: #182536;
    border-color: #33495f;
    color: #e9f2fb;
}}

QPushButton#dangerButton {{
    background: #552231;
    border-color: {danger};
    color: #ffffff;
}}

QPushButton#dangerButton:hover {{
    background: #6a293d;
}}

QPushButton#tvCard {{
    text-align: left;
    background: #111a24;
    border: 1px solid #2b3d50;
    border-radius: 8px;
    padding: 18px;
    font-size: 15px;
    color: #edf5ff;
}}

QPushButton#tvCard:hover {{
    background: #162232;
    border-color: #42617e;
}}

QPushButton#tvCard:checked {{
    background: #112a2d;
    border: 2px solid {accent_color};
}}

QPushButton#remoteDpadButton {{
    min-width: 72px;
    min-height: 72px;
    max-width: 72px;
    max-height: 72px;
    border-radius: 36px;
    background: #1b2a3d;
    border: 1px solid #3b5672;
}}

QPushButton#remoteOkButton {{
    min-width: 84px;
    min-height: 84px;
    max-width: 84px;
    max-height: 84px;
    border-radius: 42px;
    background: {accent_color};
    border: 2px solid #57e1b8;
    color: #04120e;
    font-size: 16px;
}}

QPushButton#remoteAuxButton {{
    min-height: 42px;
    background: #172231;
    border-color: #33495f;
}}

QLineEdit, QComboBox {{
    background: {input_background};
    border: 1px solid #2b3d51;
    border-radius: 8px;
    color: #f6fbff;
    padding: 9px 12px;
    selection-background-color: #2d6f9f;
    min-height: 38px;
}}

QLineEdit:focus, QComboBox:focus {{
    border-color: {accent_color};
}}

QLineEdit:disabled, QComboBox:disabled {{
    color: #657386;
    background: #101720;
}}

QComboBox::drop-down {{
    border-left: 1px solid #2b3d51;
    width: 28px;
}}

QComboBox QAbstractItemView {{
    background: #101821;
    border: 1px solid #2b3d51;
    selection-background-color: #172536;
}}

QSpinBox {{
    background: {input_background};
    border: 1px solid #2b3d51;
    border-radius: 8px;
    color: #f6fbff;
    padding: 8px 10px;
    min-height: 38px;
}}

QSpinBox:focus {{
    border-color: {accent_color};
}}

QSpinBox::up-button, QSpinBox::down-button {{
    background: #172231;
    border-left: 1px solid #2b3d51;
    width: 24px;
}}

QSpinBox::up-button:hover, QSpinBox::down-button:hover {{
    background: #1f2e40;
}}

QPlainTextEdit {{
    background: {input_background};
    border: 1px solid #263649;
    border-radius: 8px;
    color: #c9d6e4;
    padding: 10px;
    selection-background-color: #2d6f9f;
}}

QProgressBar {{
    background: {input_background};
    border: 1px solid #2b3d51;
    border-radius: 8px;
    color: {text_primary};
    text-align: center;
    min-height: 24px;
}}

QProgressBar::chunk {{
    background: {accent_color};
    border-radius: 7px;
}}

QTabWidget::pane {{
    border: 1px solid #263649;
    border-radius: 8px;
    top: -1px;
}}

QTabBar::tab {{
    background: #101720;
    border: 1px solid #263649;
    padding: 9px 16px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
}}

QTabBar::tab:selected {{
    background: #172536;
    border-color: {border_strong};
}}

QLabel#progressLabel {{
    background: #0c131b;
    border: 1px solid #1d2a39;
    border-radius: 8px;
    padding: 8px 10px;
    color: #9faebe;
}}

QCheckBox {{
    color: #b8c6d5;
    spacing: 8px;
}}

QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border-radius: 5px;
    border: 1px solid #3b5672;
    background: {input_background};
}}

QCheckBox::indicator:checked {{
    background: {accent_color};
    border-color: #57e1b8;
}}

QStatusBar {{
    background: {app_background};
    color: {text_secondary};
    border-top: 1px solid {border_color};
}}
""".format(**THEME)
