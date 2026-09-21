"""Standard-library-only startup boundary: usable even when Qt cannot import."""
from __future__ import annotations

import ctypes
import json
import logging
import os
import platform
import sys
import tempfile
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import __app_name__, __version__
from .config import APP_LOGS, atomic_json, resource_path
from .services.compatibility import require_supported
from .services.support import sanitize

_dll_directories: list[object] = []
_configured = False
_preflight_done = False


def configure_logging() -> Path:
    global _configured
    folder = APP_LOGS
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:
        folder = Path(tempfile.gettempdir()) / "Salem-startup"
        folder.mkdir(parents=True, exist_ok=True)
    path = folder / "app.log"
    if not _configured:
        class SanitizedFormatter(logging.Formatter):
            def format(self, record):
                return sanitize(super().format(record))
        formatter = SanitizedFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        handler = RotatingFileHandler(path, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        handler.setFormatter(formatter)
        logging.getLogger().addHandler(handler)
        logging.getLogger().setLevel(logging.INFO)
        for name, filename in [("salem.setup", "setup.log"), ("salem.update", "update.log"), ("salem.crash", "crash.log")]:
            target = RotatingFileHandler(folder / filename, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
            target.setFormatter(formatter)
            logging.getLogger(name).addHandler(target)
        _configured = True
    return path


def preflight() -> None:
    global _preflight_done
    configure_logging()
    if _preflight_done or not getattr(sys, "frozen", False):
        return
    require_supported()
    root = Path(sys._MEIPASS)
    manifest_path = root / "runtime-manifest.json"
    if not manifest_path.exists():
        raise RuntimeError("Package manifest is missing. Extract the complete Portable.zip or reinstall with Setup.exe.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    missing = [name for name, size in manifest["files"].items()
               if not (root / name).is_file() or (root / name).stat().st_size != size]
    if missing:
        raise RuntimeError("Application files are missing or incomplete:\n" + "\n".join(missing[:16]) +
                           "\n\nExtract the entire portable folder, or reinstall using Setup.exe. Check antivirus quarantine if files disappear again.")
    # Frozen Qt must use its bundled plugin tree, never another application's Qt.
    for name in ("QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH", "QML2_IMPORT_PATH", "QML_IMPORT_PATH"):
        os.environ.pop(name, None)
    for folder in (root, root / "shiboken6", root / "PySide6"):
        _dll_directories.append(os.add_dll_directory(str(folder)))
    os.environ["QT_PLUGIN_PATH"] = str(root / "PySide6" / "plugins")
    os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(root / "PySide6" / "plugins" / "platforms")
    for name in ("shiboken6/shiboken6.abi3.dll", "PySide6/Qt6Core.dll", "PySide6/Qt6Gui.dll", "PySide6/Qt6Widgets.dll"):
        try:
            ctypes.WinDLL(str(root / name))
        except OSError as exc:
            raise RuntimeError(f"Windows could not load the bundled {name}: {exc}.\nReinstall the complete package and send the startup log to support.") from exc
    _preflight_done = True


def failure(error: BaseException, *, report: Path | None = None, show_dialog: bool = True) -> int:
    path = configure_logging()
    details = "".join(traceback.format_exception(error))
    logging.getLogger("salem.crash").error("Startup failure\n%s", details)
    if report:
        atomic_json(report, {"ok": False, "error": str(error), "traceback": details, "log": str(path)})
    if show_dialog and sys.platform == "win32":
        ctypes.windll.user32.MessageBoxW(None, f"Salem could not start.\n\n{error}\n\nDiagnostics: {path}\nSupport: 1salembot.support@gmail.com", __app_name__, 0x10)
    return 1


def main() -> int:
    report = None
    if "--self-test" in sys.argv:
        index = sys.argv.index("--self-test")
        report = Path(sys.argv[index + 1]) if len(sys.argv) > index + 1 else Path.cwd() / "startup-report.json"
    try:
        preflight()
        logging.getLogger(__name__).info("Starting %s %s; Python %s; %s; executable=%s", __app_name__, __version__, platform.python_version(), platform.platform(), sys.executable)
        if sys.platform == "win32":
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Salem.GoogleTVEmulator.1.0")
        if report:
            return self_test(report)
        from .app import main as run_app
        sys.excepthook = lambda _kind, exc, _tb: failure(exc)
        return run_app()
    except Exception as exc:
        return failure(exc, report=report, show_dialog=report is None)


def self_test(report: Path) -> int:
    from PySide6 import QtCore
    from PySide6.QtGui import QImage, QImageReader
    from PySide6.QtWidgets import QApplication
    from .config import SettingsStore
    from .ui.window import SalemMainWindow

    app = QApplication([])
    app.setStyle("Fusion")
    with tempfile.TemporaryDirectory(prefix="salem-smoke-") as folder:
        window = SalemMainWindow(auto_discover=False, settings_store=SettingsStore(Path(folder) / "settings.json"))
        window.show()
        app.processEvents()
        if QImage(str(resource_path("assets/salem_google_tv_emulator.png"))).isNull():
            raise RuntimeError("Bundled application image cannot be loaded.")
        screenshots = report.parent / "screenshots"
        screenshots.mkdir(parents=True, exist_ok=True)
        for key in window.pages:
            window.navigate(key)
            app.processEvents()
            if not window.grab().save(str(screenshots / f"{key}.png")):
                raise RuntimeError("Could not save UI smoke screenshot.")
        window.open_remote()
        app.processEvents()
        window.remote_window.grab().save(str(screenshots / "remote-popout.png"))
        window.remote_window.close()
        window.close()
        app.processEvents()
        result = {"ok": True, "version": __version__, "qt": QtCore.qVersion(), "python": platform.python_version(),
                  "platform": platform.platform(), "executable": sys.executable, "plugin_paths": QtCore.QCoreApplication.libraryPaths(),
                  "image_formats": [bytes(fmt).decode() for fmt in QImageReader.supportedImageFormats()],
                  "pages": list(window.pages), "dpi_ratio": app.devicePixelRatio()}
        atomic_json(report, result)
    return 0
