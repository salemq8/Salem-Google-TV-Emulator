"""Stable setup entry point and progress contract; installation lives in services."""
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .services.image_catalog import _parse_system_images, _select_system_image  # noqa: F401

SETUP_STAGES = ["Preflight", "Portable JDK", "Android tools", "SDK repository", "Platform tools",
                "Android Emulator", "Google TV image", "SDK licenses", "Google TV device",
                "Engine validation", "Setup complete"]


@dataclass(frozen=True)
class SetupProgress:
    stage: str
    status: str
    message: str = ""
    diagnostics: object | None = None
    diagnostic_text: str = ""


@dataclass(frozen=True)
class SetupResult:
    sdk_root: Path
    google_tv_image: str | None
    google_tv_created: bool
    diagnostics: object | None = None

    @property
    def google_tv_available(self) -> bool:
        return bool(self.google_tv_image and self.google_tv_created)

    def summary(self) -> str:
        return f"Google TV engine verified.\nSDK root: {self.sdk_root}"


ProgressCallback = Callable[[SetupProgress], None]


def install_tv_emulator_engine(accept_licenses: bool, progress: ProgressCallback,
                               manual_google_tv_package: str | None = None) -> SetupResult:
    from .services.setup_engine import SetupEngine
    engine = SetupEngine(progress)
    if manual_google_tv_package and manual_google_tv_package != engine.manifest["image"]["package"]:
        raise ValueError("Production setup only installs the reviewed manifest image. An override requires a reviewed toolchain manifest.")
    return engine.execute(accept_licenses)
