"""One authoritative, generation-scoped binding to a positively identified Salem AVD."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Callable


class SessionState(StrEnum):
    DISCONNECTED = "Disconnected"
    CONNECTING = "Connecting"
    DETECTED = "ADB detected"
    BOOTING = "Google TV is booting"
    READY = "Remote connected"
    RECONNECTING = "ADB reconnecting"
    STOPPING = "Stopping"


class RemoteSessionUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class Transport:
    serial: str
    state: str
    details: str


def parse_devices(output: str) -> list[Transport]:
    transports = []
    for line in output.splitlines():
        parts = line.strip().split(maxsplit=2)
        if len(parts) >= 2 and parts[0].startswith("emulator-"):
            transports.append(Transport(parts[0], parts[1], parts[2] if len(parts) > 2 else ""))
    return transports


@dataclass
class EmulatorSession:
    generation: int = 0
    expected_avd: str = ""
    pid: int | None = None
    launched_at: float | None = None
    serial: str | None = None
    adb_state: str = "unknown"
    boot_completed: bool = False
    hwnd: int | None = None
    state: SessionState = SessionState.DISCONNECTED
    preexisting: set[str] = field(default_factory=set)
    last_successful_command: str = ""
    message: str = "Launch Google TV to connect the remote."

    @property
    def ready(self) -> bool:
        return bool(self.serial and self.adb_state == "device" and self.boot_completed and self.state == SessionState.READY)

    def invalidate(self, state: SessionState = SessionState.DISCONNECTED) -> None:
        self.generation += 1
        self.serial = None
        self.adb_state = "unknown"
        self.boot_completed = False
        self.hwnd = None
        self.state = state
        self.message = state.value

    def begin(self, avd: str, pid: int, existing: set[str]) -> None:
        self.invalidate(SessionState.CONNECTING)
        self.expected_avd, self.pid = avd, pid
        self.launched_at = time.time()
        self.preexisting = set(existing)

    def stopping(self) -> None:
        # Keep the verified identity only for graceful shutdown; queued input is invalid.
        self.generation += 1
        self.state = SessionState.STOPPING
        self.message = self.state.value

    def require(self, generation: int | None = None) -> str:
        if generation is not None and generation != self.generation:
            raise RemoteSessionUnavailable("Command discarded: Google TV session changed.")
        if not self.ready or self.serial is None:
            raise RemoteSessionUnavailable(f"Remote unavailable: {self.message}")
        return self.serial


class SessionBinder:
    def __init__(self, session: EmulatorSession, query: Callable[[list[str], int], tuple[int, str]]) -> None:
        self.session = session
        self.query = query

    def poll(self) -> str | None:
        session = self.session
        generation = session.generation
        if not session.expected_avd or session.state in (SessionState.DISCONNECTED, SessionState.STOPPING):
            return None
        code, output = self.query(["devices", "-l"], 8)
        matches = []
        offline = False
        if code == 0:
            for transport in parse_devices(output):
                if transport.serial in session.preexisting:
                    continue
                if transport.state != "device":
                    offline = offline or transport.serial == session.serial
                    continue
                status, avd = self.query(["-s", transport.serial, "emu", "avd", "name"], 5)
                names = [line.strip() for line in avd.splitlines() if line.strip() and line.strip() != "OK"]
                if status == 0 and names == [session.expected_avd]:
                    matches.append(transport)
        if generation != session.generation:
            return None
        if len(matches) != 1:
            was_bound = session.serial is not None
            if was_bound:
                session.generation += 1
            session.serial = None
            session.boot_completed = False
            session.adb_state = "offline" if offline else "unknown"
            session.state = SessionState.RECONNECTING if was_bound or code else SessionState.CONNECTING
            session.message = "Multiple matching devices; no commands will be sent." if len(matches) > 1 else "Waiting for a ready transport belonging to Salem Google TV."
            return None
        serial = matches[0].serial
        if session.serial and session.serial != serial:
            session.generation += 1
            generation = session.generation
        session.serial, session.adb_state, session.state = serial, "device", SessionState.DETECTED
        code, boot = self.query(["-s", serial, "shell", "getprop", "sys.boot_completed"], 5)
        if generation != session.generation:
            return None
        session.boot_completed = code == 0 and boot.strip() == "1"
        session.state = SessionState.READY if session.boot_completed else SessionState.BOOTING
        session.message = session.state.value
        return serial if session.ready else None


class RemoteService:
    """All views use the engine's single queue and this generation guard."""
    def __init__(self, controller) -> None:
        self.controller = controller
        self.session = controller.session

    def key(self, name: str, generation: int) -> str:
        self.session.require(generation)
        return self.controller.send_remote_key(name)

    def text(self, value: str, generation: int) -> str:
        self.session.require(generation)
        return self.controller.send_text(value)

    def sound(self, generation: int) -> str:
        self.session.require(generation)
        return self.controller.test_sound()
