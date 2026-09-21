"""Preferences, update and support actions, independent of emulator lifecycle."""
from __future__ import annotations

import os
import logging
import platform
import re
import time
from typing import TYPE_CHECKING
from urllib.parse import urlencode

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication

from .. import __app_name__, __version__
from ..android_backend import SALEM_LOG_DIR
from ..config import APP_LOGS, RELEASE_API, RELEASE_URL, SUPPORT_EMAIL
from ..services.updates import UpdateResult, check_for_updates
from ..styles import stylesheet

if TYPE_CHECKING:
    from .window import SalemMainWindow


class PreferencesController:
    def __init__(self, window: SalemMainWindow) -> None:
        self.window = window
        self.release_url = RELEASE_URL
        self.checking = False

    def save(self) -> None:
        w = self.window
        w.settings.theme = w.preferences.theme.currentText()
        w.settings.auto_update = w.preferences.auto_update.isChecked()
        w.settings.log_retention_days = w.preferences.retention.value()
        w.settings.remote_always_on_top = w.preferences.top.isChecked()
        w.settings.support_email = w.help.email.text().strip() or SUPPORT_EMAIL
        try:
            w.settings_store.save(w.settings)
        except OSError as exc:
            w.fail(exc)
            return
        QApplication.instance().setStyleSheet(stylesheet(w.settings.theme))
        if w.remote_window:
            w.remote_window.top.setChecked(w.settings.remote_always_on_top)
        w.preferences.status.setText("Preferences saved.")
        w.notify("Preferences saved.")

    def reset(self) -> None:
        w = self.window
        try:
            w.settings = w.settings_store.reset()
        except OSError as exc:
            w.fail(exc)
            return
        w.preferences.load(w.settings)
        w.help.email.setText(w.settings.support_email)
        self.save()
        w.preferences.status.setText("Default preferences restored.")

    def cleanup(self) -> None:
        w = self.window
        cutoff = time.time() - w.preferences.retention.value() * 86400
        count = 0
        errors = []
        for folder in (SALEM_LOG_DIR, APP_LOGS):
            for path in folder.glob("*.log*"):
                if path.name in {"emulator.log", "startup.log", "application.log", "app.log", "setup.log", "update.log", "crash.log"}:
                    continue
                try:
                    if path.stat().st_mtime < cutoff:
                        path.unlink()
                        count += 1
                except OSError as exc:
                    errors.append(f"{path.name}: {exc}")
        message = f"Removed {count} old logs. Active logs preserved."
        if errors:
            message += "\n" + "\n".join(errors)
        w.preferences.status.setText(message)
        w.notify(message)

    def check(self) -> None:
        if self.checking:
            return
        self.checking = True
        page = self.window.help
        page.check.setEnabled(False)
        page.progress.setRange(0, 0)
        page.update_status.setText("Checking GitHub release...")
        api = os.environ.get("SALEM_UPDATE_RELEASE_API_URL", RELEASE_API)
        direct = os.environ.get("SALEM_UPDATE_VERSION_URL", "")
        self.window.tasks.submit("updates", lambda: check_for_updates(api, direct), self.checked, self.check_failed, engine=False)

    def checked(self, result: UpdateResult) -> None:
        self.finish_check()
        self.release_url = result.release_url
        text = f"Version {result.version} is available on GitHub." if result.newer else f"You're up to date. Installed version: {__version__}."
        self.window.help.update_status.setText(text)
        self.window.notify(text)
        logging.getLogger("salem.update").info(text)

    def check_failed(self, error: Exception) -> None:
        self.finish_check()
        self.window.help.progress.setValue(0)
        self.window.help.update_status.setText(f"Update check failed: {error}")
        self.window.notify(f"Update check failed: {error}")
        logging.getLogger("salem.update").warning("Update check failed: %s", error)

    def finish_check(self) -> None:
        self.checking = False
        self.window.help.check.setEnabled(True)
        self.window.help.progress.setRange(0, 100)
        self.window.help.progress.setValue(100)

    def open_release(self) -> None:
        self.open_url(QUrl(self.release_url))

    def open_url(self, url: QUrl) -> bool:
        if not QDesktopServices.openUrl(url):
            self.window.notify("Windows could not open the link. Check your default browser or mail app.")
            return False
        return True

    def support(self) -> None:
        w = self.window
        email = w.help.email.text().strip() or SUPPORT_EMAIL
        if not re.fullmatch(r"[^\s@?&#]+@[^\s@?&#]+\.[^\s@?&#]+", email):
            w.help.support_status.setText("Enter a valid support email address.")
            return
        query = urlencode({"subject": f"{__app_name__} v{__version__} support",
                           "body": f"Issue:\n\nVersion: {__version__}\nWindows: {platform.platform()}\nSetup status: {w.setup_actions.stage or 'not started'}\nGoogle TV: {w.controller.session.state.value}\n\nAttach diagnostics only after reviewing them."})
        opened = self.open_url(QUrl(f"mailto:{email}?{query}"))
        w.help.support_status.setText("Support draft requested. Review before sending." if opened else "No mail app opened. Copy the support address and diagnostics instead.")
