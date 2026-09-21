from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from .services.session import EmulatorSession, SessionBinder, SessionState, RemoteSessionUnavailable


CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
CREATE_NEW_PROCESS_GROUP = 0x00000200 if sys.platform == "win32" else 0
# DETACHED_PROCESS makes Android Emulator's qemu child open a visible Windows Terminal
# window on Windows 11. CREATE_NO_WINDOW keeps the console hidden while the process
# remains long-running and independently stoppable through ADB/taskkill.
EMULATOR_CREATION_FLAGS = CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP


REMOTE_KEYCODES = {
    "up": "19",
    "down": "20",
    "left": "21",
    "right": "22",
    "ok": "23",
    "back": "4",
    "home": "3",
    "menu": "82",
    "volume_up": "24",
    "volume_down": "25",
    "mute": "164",
    "paste": "279",
}

SALEM_BASE_DIR = Path(os.environ.get("PUBLIC", r"C:\Users\Public")) / "SalemTVBox"
SALEM_SDK_ROOT = SALEM_BASE_DIR / "AndroidSDK"
SALEM_JDK_ROOT = SALEM_BASE_DIR / "JDK21"
SALEM_LOG_DIR = SALEM_BASE_DIR / "logs"
EMULATOR_LOG_PATH = SALEM_LOG_DIR / "emulator.log"
AUDIO_BACKEND_LABEL = "default (enabled; -no-audio not used)"
GOOGLE_TV_AVD_NAME = "Salem_Google_TV"


def apply_salem_sdk_environment(force: bool = False) -> None:
    """Point this process at Salem's bundled SDK when it exists."""
    if not SALEM_SDK_ROOT.exists() or not _sdk_root_has_tools(SALEM_SDK_ROOT):
        return
    if force or not os.environ.get("ANDROID_HOME"):
        os.environ["ANDROID_HOME"] = str(SALEM_SDK_ROOT)
    if force or not os.environ.get("ANDROID_SDK_ROOT"):
        os.environ["ANDROID_SDK_ROOT"] = str(SALEM_SDK_ROOT)


@dataclass(frozen=True)
class ToolPaths:
    sdk_root: Path | None
    emulator: Path | None
    adb: Path | None
    avdmanager: Path | None
    sdkmanager: Path | None

    @property
    def ready(self) -> bool:
        return bool(self.emulator and self.adb)

    def status_lines(self) -> list[str]:
        return [
            f"SDK root: {self.sdk_root or 'Not detected'}",
            f"emulator: {self.emulator or 'Missing'}",
            f"adb: {self.adb or 'Missing'}",
            f"avdmanager: {self.avdmanager or 'Missing'}",
            f"sdkmanager: {self.sdkmanager or 'Missing'}",
        ]


@dataclass(frozen=True)
class AvdInfo:
    name: str
    avd_dir: Path | None
    config: dict[str, str]
    tv_type: str | None

    @property
    def display_name(self) -> str:
        return self.config.get("avd.ini.displayname") or self.name

    @property
    def api_level(self) -> int:
        text = " ".join(
            [
                self.config.get("target", ""),
                self.config.get("image.sysdir.1", ""),
                self.config.get("tag.id", ""),
            ]
        )
        match = re.search(r"android[-_ ](\d+)", text, re.IGNORECASE)
        return int(match.group(1)) if match else 0

    @property
    def detail(self) -> str:
        device = self.config.get("hw.device.name") or self.config.get("hw.device.manufacturer")
        target = self.config.get("target") or self.config.get("image.sysdir.1")
        pieces = [self.name]
        if device:
            pieces.append(device)
        if target:
            pieces.append(target)
        return " | ".join(pieces)


@dataclass(frozen=True)
class AdbDevice:
    serial: str
    state: str
    details: str


@dataclass(frozen=True)
class LaunchInfo:
    pid: int
    command: list[str]
    command_line: str
    log_path: Path
    cwd: Path
    avd_name: str
    audio_backend: str
    serial: str | None = None


@dataclass(frozen=True)
class PerformanceSettings:
    ram_mb: int
    cpu_cores: int
    gpu_host: bool = True

    def normalized(self) -> "PerformanceSettings":
        return PerformanceSettings(
            ram_mb=max(1024, min(8192, int(self.ram_mb))),
            cpu_cores=max(1, min(8, int(self.cpu_cores))),
            gpu_host=bool(self.gpu_host),
        )


@dataclass(frozen=True)
class AdbCommandResult:
    command: list[str]
    returncode: int
    output: str


def detect_android_tools(preferred_sdk_root: Path | None = None) -> ToolPaths:
    sdk_candidates = _sdk_root_candidates()
    if preferred_sdk_root:
        sdk_candidates.insert(0, preferred_sdk_root)
    adb_on_path = _which("adb")
    emulator_on_path = _which("emulator")

    for tool in (adb_on_path, emulator_on_path):
        root = _infer_sdk_root_from_tool(tool)
        if root:
            sdk_candidates.append(root)

    sdk_root = _first_existing_unique(sdk_candidates)
    emulator = _find_tool(sdk_root, "emulator", "emulator.exe", [("emulator",)])
    adb = _find_tool(sdk_root, "adb", "adb.exe", [("platform-tools",)])
    avdmanager = _find_manager(sdk_root, "avdmanager")
    sdkmanager = _find_manager(sdk_root, "sdkmanager")

    return ToolPaths(
        sdk_root=sdk_root,
        emulator=emulator or emulator_on_path,
        adb=adb or adb_on_path,
        avdmanager=avdmanager,
        sdkmanager=sdkmanager,
    )


def list_avds(tools: ToolPaths) -> list[AvdInfo]:
    names: list[str] = []
    if tools.emulator:
        result = _run([str(tools.emulator), "-list-avds"], timeout=12)
        if result.returncode == 0:
            names = [line.strip() for line in result.stdout.splitlines() if line.strip()]

    avd_root = _avd_root()
    for ini in avd_root.glob("*.ini") if avd_root.exists() else []:
        if ini.stem not in names:
            names.append(ini.stem)

    avds = [_read_avd(name, avd_root) for name in names]
    return sorted(avds, key=lambda avd: (avd.tv_type or "zzz", -avd.api_level, avd.name.lower()))


def choose_avd(avds: Iterable[AvdInfo], selected_type: str) -> AvdInfo | None:
    matching = [avd for avd in avds if avd.tv_type == selected_type]
    if not matching:
        return None
    return sorted(
        matching,
        key=lambda avd: (
            0 if avd.name.lower().startswith("salem") else 1,
            -avd.api_level,
            avd.name.lower(),
        ),
    )[0]


def list_adb_devices(tools: ToolPaths) -> list[AdbDevice]:
    if not tools.adb:
        return []
    result = _run([str(tools.adb), "devices", "-l"], timeout=8)
    devices: list[AdbDevice] = []
    for line in result.stdout.splitlines()[1:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split(maxsplit=2)
        if len(parts) >= 2:
            details = parts[2] if len(parts) > 2 else ""
            devices.append(AdbDevice(parts[0], parts[1], details))
    return devices


def find_device_for_avd(tools: ToolPaths, avd_name: str) -> str | None:
    normalized = _normalize_name(avd_name)
    devices = [device for device in list_adb_devices(tools) if device.state == "device"]
    for device in devices:
        if normalized in _normalize_name(device.details):
            return device.serial
    emulator_devices = [device for device in devices if device.serial.startswith("emulator-")]
    if len(emulator_devices) == 1:
        return emulator_devices[0].serial
    return emulator_devices[0].serial if emulator_devices else None


def find_google_tv_avd(avds: Iterable[AvdInfo]) -> AvdInfo | None:
    named = [avd for avd in avds if avd.name == GOOGLE_TV_AVD_NAME]
    if named:
        return named[0]
    return choose_avd(avds, "google_tv")


def apply_google_tv_performance_settings(avd: AvdInfo, settings: PerformanceSettings) -> str:
    if not avd.avd_dir:
        raise RuntimeError(f"Google TV AVD directory was not found for {avd.name}.")
    config_path = avd.avd_dir / "config.ini"
    if not config_path.exists():
        raise RuntimeError(f"Google TV AVD config.ini was not found: {config_path}")

    normalized = settings.normalized()
    values = _read_key_values(config_path)
    backup_path = config_path.with_suffix(".ini.salem-v1-backup")
    if not backup_path.exists():
        shutil.copy2(config_path, backup_path)

    values["hw.ramSize"] = str(normalized.ram_mb)
    values["hw.cpu.ncore"] = str(normalized.cpu_cores)
    values["hw.gpu.enabled"] = "yes" if normalized.gpu_host else "no"
    values["hw.gpu.mode"] = "host" if normalized.gpu_host else "auto"
    values["runtime.network.speed"] = "full"
    values["runtime.network.latency"] = "none"
    _write_key_values(config_path, values)

    return (
        "Google TV performance settings applied.\n"
        f"AVD: {avd.name}\n"
        f"RAM: {normalized.ram_mb} MB\n"
        f"CPU cores: {normalized.cpu_cores}\n"
        f"GPU host mode: {'enabled' if normalized.gpu_host else 'disabled'}\n"
        "Network profile: full speed, no artificial latency\n"
        f"Backup: {backup_path}"
    )


class EmulatorController:
    def __init__(self, tools: ToolPaths) -> None:
        self.tools = tools
        self.process: subprocess.Popen[str] | None = None
        self.emulator_process: subprocess.Popen[str] | None = None
        self.current_avd: AvdInfo | None = None
        self.session = EmulatorSession()
        self.binder = SessionBinder(self.session, self._query_binding)
        self.launch_info: LaunchInfo | None = None
        self.last_adb_output = ""
        self._log_handle = None

    @property
    def is_running(self) -> bool:
        return bool(self.process and self.process.poll() is None)

    @property
    def device_serial(self) -> str | None:
        return self.session.serial

    def _query_binding(self, args: list[str], timeout: int) -> tuple[int, str]:
        if not self.tools.adb:
            return 1, "ADB unavailable"
        result = _run([str(self.tools.adb), *args], timeout, self._emulator_environment())
        return result.returncode, result.stdout.strip()

    def start(self, avd: AvdInfo, extra_args: list[str] | None = None) -> int:
        return self.start_with_info(avd, extra_args).pid

    def start_with_info(self, avd: AvdInfo, extra_args: list[str] | None = None, wait_for_serial: bool = True) -> LaunchInfo:
        if not self.tools.emulator:
            raise RuntimeError("Android Emulator executable was not detected.")
        if self.is_running:
            if self.launch_info:
                return self.launch_info
            pid = self.process.pid if self.process else 0
            return LaunchInfo(pid, [], "", EMULATOR_LOG_PATH, self._emulator_working_dir(), avd.name, AUDIO_BACKEND_LABEL, self.device_serial)

        SALEM_LOG_DIR.mkdir(parents=True, exist_ok=True)
        self._close_log_handle()
        prelaunch_serials = {
            device.serial
            for device in self._list_adb_devices_with_env()
            if device.serial.startswith("emulator-") and device.state == "device"
        }

        args = [
            str(self.tools.emulator),
            "-avd",
            avd.name,
            "-no-metrics",
        ]
        if extra_args:
            args.extend(extra_args)

        env = self._emulator_environment()
        cwd = self._emulator_working_dir()
        command_line = subprocess.list2cmdline(args)
        self._log_handle = EMULATOR_LOG_PATH.open("a", encoding="utf-8", errors="replace")
        self._log_handle.write("\n\n==== Salem emulator launch ====\n")
        self._log_handle.write(f"AVD: {avd.name}\n")
        self._log_handle.write(f"CWD: {cwd}\n")
        self._log_handle.write(f"Command: {command_line}\n")
        self._log_handle.flush()

        self.process = subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=self._log_handle,
            stderr=subprocess.STDOUT,
            cwd=str(cwd),
            env=env,
            creationflags=EMULATOR_CREATION_FLAGS,
            text=True,
        )
        self.emulator_process = self.process
        self.current_avd = avd
        self.session.begin(avd.name, self.process.pid, prelaunch_serials)
        self.launch_info = LaunchInfo(
            pid=self.process.pid,
            command=args,
            command_line=command_line,
            log_path=EMULATOR_LOG_PATH,
            cwd=cwd,
            avd_name=avd.name,
            audio_backend=AUDIO_BACKEND_LABEL,
        )
        if not wait_for_serial:
            self.last_adb_output = "Emulator process started. Waiting for ADB serial detection."
            return self.launch_info
        serial = self.wait_for_emulator_device(timeout_seconds=90, prelaunch_serials=prelaunch_serials)
        self.launch_info = LaunchInfo(
            pid=self.process.pid,
            command=args,
            command_line=command_line,
            log_path=EMULATOR_LOG_PATH,
            cwd=cwd,
            avd_name=avd.name,
            audio_backend=AUDIO_BACKEND_LABEL,
            serial=serial,
        )
        return self.launch_info

    def refresh_device_serial(self) -> str | None:
        serial = self.binder.poll()
        if serial and self.launch_info and self.launch_info.serial != serial:
            self.launch_info = LaunchInfo(
                pid=self.launch_info.pid,
                command=self.launch_info.command,
                command_line=self.launch_info.command_line,
                log_path=self.launch_info.log_path,
                cwd=self.launch_info.cwd,
                avd_name=self.launch_info.avd_name,
                audio_backend=self.launch_info.audio_backend,
                serial=serial,
            )
        return serial

    def wait_for_emulator_device(self, timeout_seconds: int = 90, prelaunch_serials: set[str] | None = None) -> str:
        deadline = time.monotonic() + timeout_seconds
        last_devices = ""
        while time.monotonic() < deadline:
            if self.process and self.process.poll() is not None:
                raise RuntimeError(
                    "Emulator process closed before ADB reported a ready device.\n\n"
                    f"Latest adb devices:\n{last_devices or 'No adb output yet.'}\n\n"
                    f"Latest emulator log:\n{self.emulator_log_tail(120)}"
                )
            devices_output = self.adb_devices_output()
            last_devices = devices_output
            serial = self.refresh_device_serial()
            if serial:
                self.last_adb_output = f"Bound ready Google TV session: {serial}\n\n{devices_output}"
                return serial
            time.sleep(2)
        raise RuntimeError(
            f"No emulator-* device appeared as 'device' after {timeout_seconds} seconds.\n\n"
            f"Latest adb devices:\n{last_devices or 'No adb output yet.'}\n\n"
            f"Latest emulator log:\n{self.emulator_log_tail(160)}"
        )

    def stop(self) -> None:
        serial = self.session.serial
        self.session.invalidate(SessionState.STOPPING)
        process_pid = self.process.pid if self.process else None
        if self.tools.adb and serial:
            _run([str(self.tools.adb), "-s", serial, "emu", "kill"], timeout=8)
            time.sleep(1)

        if self.process and self.process.poll() is None:
            try:
                self.process.terminate()
                self.process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.process.kill()
        if process_pid and sys.platform == "win32":
            subprocess.run(
                ["taskkill.exe", "/PID", str(process_pid), "/T", "/F"],
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=CREATE_NO_WINDOW,
                errors="replace",
            )
        self.process = None
        self.emulator_process = None
        self.current_avd = None
        self.session.invalidate()
        self.launch_info = None
        self._close_log_handle()

    def restart(self, avd: AvdInfo) -> int:
        return self.restart_with_info(avd).pid

    def restart_with_info(self, avd: AvdInfo, wait_for_serial: bool = True) -> LaunchInfo:
        self.stop()
        return self.start_with_info(avd, wait_for_serial=wait_for_serial)

    def send_remote_key(self, key_name: str) -> str:
        if not self.tools.adb:
            raise RuntimeError("ADB executable was not detected.")
        keycode = REMOTE_KEYCODES[key_name]
        result = self._run_adb(["shell", "input", "keyevent", keycode], timeout=8)
        if result.returncode != 0:
            raise RuntimeError(result.output or f"ADB keyevent failed: {keycode}")
        return result.output or f"Sent keyevent {keycode}"

    def send_text(self, text: str) -> str:
        if not text:
            return "No text to send."
        input_output = "Skipped adb input text for Unicode; using clipboard fallback."
        if not _needs_clipboard_fallback(text):
            escaped = _escape_adb_input_text(text)
            result = self._run_adb(["shell", "input", "text", escaped], timeout=12)
            input_output = _format_adb_result(result)
            if result.returncode == 0:
                return result.output or f"Text sent with adb input text on {self.device_serial or 'active emulator'}."

        clipboard_ok, clipboard_output = self._paste_with_android_clipboard(text)
        if clipboard_ok:
            self.last_adb_output = (
                "Send Text to TV succeeded with Android clipboard paste fallback.\n\n"
                f"input text: {input_output or 'No output'}\n"
                f"clipboard: {clipboard_output or 'No output'}"
            )
            return f"Text sent with Android clipboard paste fallback on {self.device_serial or 'active emulator'}."

        char_ok, char_output = self._send_text_character_by_character(text)
        if char_ok:
            self.last_adb_output = (
                "Send Text to TV fallback succeeded character-by-character.\n\n"
                f"input text: {input_output or 'No output'}\n"
                f"clipboard: {clipboard_output or 'No output'}\n"
                f"character fallback: {char_output or 'No output'}"
            )
            return f"Text sent character-by-character on {self.device_serial or 'active emulator'}."

        self.last_adb_output = (
            "Send Text to TV failed.\n\n"
            f"input text: {input_output or 'No output'}\n"
            f"clipboard: {clipboard_output or 'No output'}\n"
            f"character fallback: {char_output or 'No output'}"
        )
        raise RuntimeError(
            "ADB text input failed, clipboard paste failed, and character-by-character fallback failed.\n"
            f"input text: {input_output or 'No output'}\n"
            f"clipboard: {clipboard_output or 'No output'}\n"
            f"character fallback: {char_output or 'No output'}"
        )

    def test_sound(self) -> str:
        result = self._run_adb(["shell", "cmd", "media_session", "volume", "--show", "--set", "10"], timeout=10)
        if result.returncode != 0:
            raise RuntimeError(result.output or "Audio test command failed.")
        return result.output or "TV volume set to 10."

    def network_status(self) -> str:
        result = self._run_adb(
            [
                "shell",
                "sh",
                "-c",
                (
                    "echo 'Network routes:'; ip route; "
                    "echo; echo 'Network properties:'; getprop | grep -i 'net\\.dns\\|http\\.proxy\\|wifi' || true; "
                    "echo; echo 'Internet reachability:'; ping -c 1 -W 2 8.8.8.8 || true"
                ),
            ],
            timeout=20,
        )
        if result.returncode != 0:
            raise RuntimeError(result.output or "Network diagnostics command failed.")
        return result.output or "No network diagnostics output was returned."

    def install_apk(self, apk_path: Path) -> str:
        if not self.tools.adb:
            raise RuntimeError("ADB executable was not detected.")
        if not apk_path.exists():
            raise RuntimeError(f"APK does not exist: {apk_path}")
        serial = self._current_serial()
        if not serial:
            raise RuntimeError("No ready emulator serial detected. Launch a TV window first.")
        args = [str(self.tools.adb)]
        args.extend(["-s", serial])
        args.extend(["install", "-r", str(apk_path)])
        result = _run(args, timeout=180, env=self._emulator_environment())
        output = "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part)
        if result.returncode != 0:
            raise RuntimeError(output or "APK install failed.")
        return output or "APK installed."

    def adb_devices_output(self) -> str:
        if not self.tools.adb:
            return "ADB executable was not detected."
        result = _run([str(self.tools.adb), "devices", "-l"], timeout=8, env=self._emulator_environment())
        output = "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part)
        return output or f"adb devices exited with code {result.returncode}"

    def emulator_log_tail(self, lines: int = 80) -> str:
        if not EMULATOR_LOG_PATH.exists():
            return "No emulator log yet."
        try:
            content = EMULATOR_LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
            return "\n".join(content[-lines:]) or "Emulator log is empty."
        except OSError as exc:
            return f"Could not read emulator log: {exc}"

    def audio_log_tail(self, lines: int = 60) -> str:
        if not EMULATOR_LOG_PATH.exists():
            return "No emulator log yet."
        audio_pattern = re.compile(r"\b(audio|sound|volume|alsa|aaudio|opensl|wasapi|backend)\b", re.IGNORECASE)
        try:
            content = EMULATOR_LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            return f"Could not read emulator log: {exc}"
        matches = [line for line in content if audio_pattern.search(line)]
        return "\n".join(matches[-lines:]) if matches else "No audio-related emulator log messages found yet."

    def _list_adb_devices_with_env(self) -> list[AdbDevice]:
        if not self.tools.adb:
            return []
        result = _run([str(self.tools.adb), "devices", "-l"], timeout=8, env=self._emulator_environment())
        devices: list[AdbDevice] = []
        output = "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part)
        self.last_adb_output = f"$ {self.tools.adb} devices -l\nexit code: {result.returncode}\n{output}".strip()
        for line in result.stdout.splitlines()[1:]:
            line = line.strip()
            if not line:
                continue
            parts = line.split(maxsplit=2)
            if len(parts) >= 2:
                details = parts[2] if len(parts) > 2 else ""
                devices.append(AdbDevice(parts[0], parts[1], details))
        return devices

    def _current_serial(self) -> str | None:
        return self.session.serial if self.session.ready else None

    def _run_adb(self, args: list[str], timeout: int) -> AdbCommandResult:
        if not self.tools.adb:
            raise RuntimeError("ADB executable was not detected.")
        serial = self._current_serial()
        if not serial:
            raise RuntimeError("No ready emulator serial detected. Launch a TV window first.")
        command = [str(self.tools.adb)]
        command.extend(["-s", serial])
        command.extend(args)
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=timeout,
                                    creationflags=CREATE_NO_WINDOW, env=self._emulator_environment(), errors="replace")
        except (OSError, subprocess.TimeoutExpired) as exc:
            self.session.invalidate(SessionState.RECONNECTING)
            raise RemoteSessionUnavailable("ADB command interrupted. Reconnecting; the command was not replayed.") from exc
        output = "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part)
        self.last_adb_output = f"$ {subprocess.list2cmdline(command)}\nexit code: {result.returncode}\n{output}".strip()
        if result.returncode == 0:
            self.session.last_successful_command = " ".join(args[:3])
        elif any(word in output.lower() for word in ("device offline", "device not found", "no devices", "unauthorized", "device '", "transport error")):
            self.session.invalidate(SessionState.RECONNECTING)
        return AdbCommandResult(command, result.returncode, output)

    def _paste_with_android_clipboard(self, text: str) -> tuple[bool, str]:
        clipboard_result = self._run_adb(["shell", "cmd", "clipboard", "set", "text", text], timeout=12)
        if clipboard_result.returncode != 0:
            return False, _format_adb_result(clipboard_result)
        paste_result = self._run_adb(["shell", "input", "keyevent", REMOTE_KEYCODES["paste"]], timeout=8)
        if paste_result.returncode != 0:
            return False, "\n\n".join([_format_adb_result(clipboard_result), _format_adb_result(paste_result)])
        output = "\n\n".join([_format_adb_result(clipboard_result), _format_adb_result(paste_result)])
        return True, output or "Clipboard text pasted."

    def _send_text_character_by_character(self, text: str) -> tuple[bool, str]:
        outputs: list[str] = []
        failures: list[str] = []
        for index, char in enumerate(text, start=1):
            if char in "\r\n":
                result = self._run_adb(["shell", "input", "keyevent", "66"], timeout=8)
                label = "\\n"
            elif _needs_clipboard_fallback(char):
                ok, output = self._paste_with_android_clipboard(char)
                if ok:
                    outputs.append(f"{index}: pasted Unicode character")
                    continue
                failures.append(f"{index}: Unicode clipboard fallback failed for U+{ord(char):04X}: {output}")
                continue
            else:
                escaped = _escape_adb_input_text(char)
                result = self._run_adb(["shell", "input", "text", escaped], timeout=8)
                label = char if char != " " else "space"

            if result.returncode == 0:
                outputs.append(f"{index}: sent {label}")
            else:
                failures.append(f"{index}: failed {label}: {result.output or 'No output'}")

        summary = "\n".join([*outputs[-12:], *failures])
        return not failures, summary or "No characters were sent."

    def _emulator_working_dir(self) -> Path:
        if (SALEM_SDK_ROOT / "emulator").exists():
            return SALEM_SDK_ROOT / "emulator"
        if self.tools.sdk_root and (self.tools.sdk_root / "emulator").exists():
            return self.tools.sdk_root / "emulator"
        if self.tools.emulator:
            return self.tools.emulator.parent
        return SALEM_SDK_ROOT / "emulator"

    def _emulator_environment(self) -> dict[str, str]:
        env = os.environ.copy()
        sdk_root = SALEM_SDK_ROOT if (SALEM_SDK_ROOT / "emulator").exists() else (self.tools.sdk_root or SALEM_SDK_ROOT)
        env["ANDROID_HOME"] = str(sdk_root)
        env["ANDROID_SDK_ROOT"] = str(sdk_root)
        path_parts = [
            str(sdk_root / "emulator"),
            str(sdk_root / "platform-tools"),
        ]
        if SALEM_JDK_ROOT.exists():
            env["JAVA_HOME"] = str(SALEM_JDK_ROOT)
            env["JDK_HOME"] = str(SALEM_JDK_ROOT)
            path_parts.insert(0, str(SALEM_JDK_ROOT / "bin"))
        env["PATH"] = os.pathsep.join([*path_parts, env.get("PATH", "")])
        return env

    def _close_log_handle(self) -> None:
        if self._log_handle:
            try:
                self._log_handle.close()
            except OSError:
                pass
            self._log_handle = None


def build_setup_instructions(selected_type: str, tools: ToolPaths, avds: list[AvdInfo]) -> str:
    missing: list[str] = []
    if not tools.sdk_root:
        missing.append("Android SDK root")
    if not tools.emulator:
        missing.append("emulator.exe")
    if not tools.adb:
        missing.append("adb.exe")

    lines = ["Google TV is not ready yet."]
    if missing:
        lines.append("")
        lines.append("Missing tools: " + ", ".join(missing))

    lines.extend(
        [
            "",
            "Automatic setup:",
            "Press Install Google TV Engine to download the official Android command-line tools and create Salem_Google_TV.",
            "",
            "Optional Android Studio fallback:",
            "1. Install Android Studio with Android Emulator and Platform Tools.",
            "2. Open More Actions > Virtual Device Manager.",
            "3. Create a TV device and choose a Google TV system image.",
            "4. Finish the AVD setup, then press Refresh in Salem.",
            "",
            "Command-line setup helpers:",
        ]
    )

    if tools.sdkmanager:
        lines.append(f'"{tools.sdkmanager}" --list | findstr /i "google-tv google_tv tv arm64 aarch64 x86"')
        lines.append(f'"{tools.sdkmanager}" --install "<system-image path from the list>"')
    else:
        lines.append("Install Android SDK Command-line Tools to get sdkmanager.")

    if tools.avdmanager:
        lines.append(f'"{tools.avdmanager}" create avd -n {GOOGLE_TV_AVD_NAME} -k "<system-image path>"')
    else:
        lines.append("Install Android SDK Command-line Tools to get avdmanager.")

    if avds:
        lines.append("")
        lines.append("Detected AVDs:")
        for avd in avds:
            tv = avd.tv_type or "not supported by Salem v1.0.1"
            lines.append(f"- {avd.detail} [{tv}]")
    return "\n".join(lines)


def _sdk_root_candidates() -> list[Path]:
    candidates: list[Path] = [SALEM_SDK_ROOT]
    for key in ("ANDROID_SDK_ROOT", "ANDROID_HOME"):
        value = os.environ.get(key)
        if value:
            candidates.append(Path(value))

    local_app_data = os.environ.get("LOCALAPPDATA")
    user_profile = os.environ.get("USERPROFILE")
    program_files = os.environ.get("ProgramFiles")
    program_files_x86 = os.environ.get("ProgramFiles(x86)")

    if local_app_data:
        candidates.append(Path(local_app_data) / "Android" / "Sdk")
    if user_profile:
        candidates.append(Path(user_profile) / "AppData" / "Local" / "Android" / "Sdk")
        candidates.append(Path(user_profile) / "Library" / "Android" / "sdk")
    if program_files:
        candidates.append(Path(program_files) / "Android" / "Android Studio" / "sdk")
    if program_files_x86:
        candidates.append(Path(program_files_x86) / "Android" / "android-sdk")
    return candidates


def _avd_root() -> Path:
    if os.environ.get("ANDROID_AVD_HOME"):
        return Path(os.environ["ANDROID_AVD_HOME"])
    if os.environ.get("ANDROID_SDK_HOME"):
        return Path(os.environ["ANDROID_SDK_HOME"]) / ".android" / "avd"
    return Path.home() / ".android" / "avd"


def _find_tool(
    sdk_root: Path | None,
    path_name: str,
    exe_name: str,
    relative_dirs: list[tuple[str, ...]],
) -> Path | None:
    if sdk_root:
        for relative_dir in relative_dirs:
            candidate = sdk_root.joinpath(*relative_dir) / exe_name
            if candidate.exists():
                return candidate
            candidate_no_ext = sdk_root.joinpath(*relative_dir) / path_name
            if candidate_no_ext.exists():
                return candidate_no_ext
    return _which(path_name)


def _find_manager(sdk_root: Path | None, manager_name: str) -> Path | None:
    names = [f"{manager_name}.bat", f"{manager_name}.exe", manager_name]
    roots: list[Path] = []
    if sdk_root:
        roots.extend(sorted((sdk_root / "cmdline-tools").glob("*"), reverse=True))
        roots.append(sdk_root / "tools")
    for root in roots:
        for name in names:
            candidate = root / "bin" / name
            if candidate.exists():
                return candidate
    return _which(manager_name)


def _which(name: str) -> Path | None:
    found = shutil.which(name)
    return Path(found) if found else None


def _infer_sdk_root_from_tool(path: Path | None) -> Path | None:
    if not path:
        return None
    parts = path.parts
    for marker in ("platform-tools", "emulator", "cmdline-tools", "tools"):
        if marker in parts:
            idx = parts.index(marker)
            return Path(*parts[:idx])
    return None


def _first_existing_unique(paths: Iterable[Path]) -> Path | None:
    seen: set[Path] = set()
    existing: list[Path] = []
    for path in paths:
        try:
            resolved = path.expanduser().resolve()
        except OSError:
            resolved = path.expanduser()
        if resolved in seen:
            continue
        seen.add(resolved)
        if resolved.exists():
            existing.append(resolved)
    for path in existing:
        if _sdk_root_has_tools(path):
            return path
    return existing[0] if existing else None


def _sdk_root_has_tools(path: Path) -> bool:
    direct_tools = any(
        candidate.exists()
        for candidate in (
            path / "platform-tools" / "adb.exe",
            path / "emulator" / "emulator.exe",
            path / "tools" / "bin" / "sdkmanager.bat",
        )
    )
    cmdline_tools = path / "cmdline-tools"
    has_manager = any(cmdline_tools.glob("*/bin/sdkmanager.bat")) if cmdline_tools.exists() else False
    return direct_tools or has_manager


def _read_avd(name: str, avd_root: Path) -> AvdInfo:
    ini_config = _read_key_values(avd_root / f"{name}.ini")
    avd_dir = Path(ini_config["path"]) if ini_config.get("path") else avd_root / f"{name}.avd"
    config = dict(ini_config)
    config.update(_read_key_values(avd_dir / "config.ini"))
    return AvdInfo(name=name, avd_dir=avd_dir if avd_dir.exists() else None, config=config, tv_type=_classify_avd(name, config))


def _read_key_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    try:
        for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    except OSError:
        return values
    return values


def _write_key_values(path: Path, values: dict[str, str]) -> None:
    lines = [f"{key}={values[key]}" for key in sorted(values)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _classify_avd(name: str, config: dict[str, str]) -> str | None:
    image_sysdir = config.get("image.sysdir.1", "").lower().replace("\\", "/")
    tag_id = " ".join(
        [
            config.get("tag.id", ""),
            config.get("tag.ids", ""),
            config.get("tag.display", ""),
            config.get("tag.displaynames", ""),
        ]
    ).lower()
    name_lower = name.lower()
    haystack = f"{name_lower} {image_sysdir} {tag_id}"
    if any(token in haystack for token in ("salem_google_tv", "google-tv", "google_tv", "/google-tv/", "tag.id=google-tv")):
        return "google_tv"
    return None


def _normalize_name(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _escape_adb_input_text(text: str) -> str:
    escaped = text.replace(" ", "%s")
    for char in ("\\", "&", "|", ";", "<", ">", "(", ")", "$", "`", '"', "'"):
        escaped = escaped.replace(char, "\\" + char)
    return escaped


def _needs_clipboard_fallback(text: str) -> bool:
    try:
        text.encode("ascii")
    except UnicodeEncodeError:
        return True
    return False


def _format_adb_result(result: AdbCommandResult) -> str:
    return (
        f"$ {subprocess.list2cmdline(result.command)}\n"
        f"exit code: {result.returncode}\n"
        f"{result.output or 'No output'}"
    )


def _run(args: list[str], timeout: int, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
        creationflags=CREATE_NO_WINDOW,
        env=env,
        errors="replace",
    )
