"""Application entry point. Engine and views are owned by dedicated modules."""
import sys

from PySide6.QtWidgets import QApplication

from . import __app_name__
from .ui.window import SalemMainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(__app_name__)
    app.setStyle("Fusion")
    window = SalemMainWindow()
    window.show()
    return app.exec()
