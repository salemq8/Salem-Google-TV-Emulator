"""Product identity, resource paths and validated, atomic local preferences."""
from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from . import __app_name__

SUPPORT_EMAIL = "1salembot.support@gmail.com"
REPOSITORY = "salemq8/Salem-Google-TV-Emulator"
RELEASE_URL = f"https://github.com/{REPOSITORY}/releases/latest"
RELEASE_API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
APP_DATA = Path(os.environ.get("APPDATA", str(Path.home()))) / __app_name__
APP_LOGS = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / __app_name__ / "logs"


def resource_path(name: str) -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])) / name


@dataclass
class Settings:
    theme: str = "Dark"
    language: str = "System default"
    auto_update: bool = False
    log_retention_days: int = 14
    support_email: str = SUPPORT_EMAIL
    remote_always_on_top: bool = False

    @classmethod
    def parse(cls, value: object) -> Settings:
        defaults = cls()
        if not isinstance(value, dict):
            raise ValueError("Settings must contain a JSON object.")
        for field in fields(defaults):
            item = value.get(field.name)
            expected = type(getattr(defaults, field.name))
            if type(item) is expected:
                setattr(defaults, field.name, item)
        defaults.theme = defaults.theme if defaults.theme in {"Dark", "Light", "System"} else "Dark"
        defaults.log_retention_days = max(1, min(365, defaults.log_retention_days))
        if not defaults.support_email.strip() or defaults.support_email == "support@salemgtv.com":
            defaults.support_email = SUPPORT_EMAIL
        return defaults


class SettingsStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or APP_DATA / "settings.json"
        self.warning = ""

    def load(self) -> Settings:
        if not self.path.exists():
            return Settings()
        try:
            return Settings.parse(json.loads(self.path.read_text(encoding="utf-8-sig")))
        except (OSError, ValueError) as exc:
            self.warning = f"Preferences could not be read. Defaults are in use; original file preserved. {exc}"
            logging.getLogger(__name__).warning(self.warning)
            return Settings()

    def save(self, settings: Settings) -> None:
        atomic_json(self.path, asdict(settings))

    def reset(self) -> Settings:
        defaults = Settings()
        self.save(defaults)
        return defaults


def atomic_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=2, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)
