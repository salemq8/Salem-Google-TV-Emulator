"""TV Mode lifecycle, with saved state retained until restoration succeeds."""
from __future__ import annotations

from dataclasses import dataclass

from .. import windows_embed as windows


@dataclass
class TVMode:
    state: windows.TVModeState | None = None
    restored: windows.WindowRect | None = None
    message: str = "TV Mode is off."

    @property
    def active(self) -> bool:
        return self.state is not None

    def enter(self, pid: int | None, avd: str | None) -> None:
        if self.active:
            return
        hwnd = windows.find_emulator_window(pid, avd)
        if not hwnd:
            raise RuntimeError("Google TV window was not found. Wait for the emulator window to open.")
        self.state = windows.enter_tv_mode(hwnd)
        self.message = "TV Mode is on."
        if not self.state.final_rect_matches_monitor:
            self.message = "TV Mode bounds differ from the monitor. See Diagnostics."

    def restore(self) -> None:
        if self.state is None:
            return
        self.restored = windows.exit_tv_mode(self.state)
        self.state = None
        self.message = "Original window restored."
