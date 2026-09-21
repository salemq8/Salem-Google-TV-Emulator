from __future__ import annotations

import platform
import struct
import sys
from dataclasses import asdict, dataclass

from .errors import SalemError

MIN_WINDOWS_BUILD = 17763


@dataclass(frozen=True)
class WindowsInfo:
    system: str
    release: str
    build: int
    architecture: str
    pointer_bits: int

    @property
    def supported(self) -> bool:
        return self.system == "Windows" and self.architecture.upper() in ("AMD64", "X86_64") and self.pointer_bits == 64 and self.build >= MIN_WINDOWS_BUILD


def windows_info() -> WindowsInfo:
    return WindowsInfo(platform.system(), platform.release(), sys.getwindowsversion().build if sys.platform == "win32" else 0,
                       platform.machine(), struct.calcsize("P") * 8)


def require_supported() -> WindowsInfo:
    info = windows_info()
    if not info.supported:
        raise SalemError("UnsupportedOS", "Salem requires Windows 10 build 17763 or later, or Windows 11, on an x64 PC. This Windows version/architecture is not supported.", str(asdict(info)))
    return info
