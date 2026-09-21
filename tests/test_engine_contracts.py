import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from salem_tv_box_emulator import android_backend as engine
from salem_tv_box_emulator import setup_wizard as setup
from salem_tv_box_emulator.services import tv_mode
from salem_tv_box_emulator.services.session import SessionState


@pytest.fixture
def controller():
    item = engine.EmulatorController(engine.ToolPaths(Path("sdk"), Path("sdk/emulator/emulator.exe"), Path("sdk/platform-tools/adb.exe"), None, None))
    item.session.serial = "emulator-5580"
    item.session.state = SessionState.READY
    item.session.adb_state = "device"
    item.session.boot_completed = True
    return item


@pytest.mark.parametrize("key,code", list(engine.REMOTE_KEYCODES.items()))
def test_remote_uses_detected_serial(controller, monkeypatch, key, code):
    calls = []
    def run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, "", "")
    monkeypatch.setattr(engine.subprocess, "run", run)
    controller.send_remote_key(key)
    assert calls[0][0][1:] == ["-s", "emulator-5580", "shell", "input", "keyevent", code]
    assert calls[0][1]["creationflags"] == engine.CREATE_NO_WINDOW


def test_remote_failure_not_success(controller, monkeypatch):
    monkeypatch.setattr(controller, "_run_adb", lambda *a, **k: engine.AdbCommandResult([], 1, "offline"))
    with pytest.raises(RuntimeError, match="offline"):
        controller.send_remote_key("up")


def test_english_text(controller, monkeypatch):
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        return engine.AdbCommandResult(args, 0, "")
    monkeypatch.setattr(controller, "_run_adb", run)
    assert "Text sent" in controller.send_text("Salem 123")
    assert "Salem%s123" in calls[0][-1]


def test_unicode_fallback_failure_reported(controller, monkeypatch):
    monkeypatch.setattr(controller, "_run_adb", lambda *a, **k: engine.AdbCommandResult([], 1, "clipboard unavailable"))
    with pytest.raises(RuntimeError, match="failed"):
        controller.send_text("مرحبا")
    assert "clipboard" in controller.last_adb_output.lower()


def test_clipboard_then_character_fallback(controller, monkeypatch):
    monkeypatch.setattr(controller, "_run_adb", lambda *a, **k: engine.AdbCommandResult([], 1, "failed"))
    monkeypatch.setattr(controller, "_paste_with_android_clipboard", lambda text: (False, "unsupported"))
    monkeypatch.setattr(controller, "_send_text_character_by_character", lambda text: (True, "sent"))
    assert "character" in controller.send_text("abc")


def test_no_console_launch_contract(controller, monkeypatch, tmp_path):
    controller.session.invalidate()
    monkeypatch.setattr(engine, "SALEM_LOG_DIR", tmp_path)
    monkeypatch.setattr(engine, "EMULATOR_LOG_PATH", tmp_path / "emulator.log")
    monkeypatch.setattr(controller, "_list_adb_devices_with_env", lambda: [])
    monkeypatch.setattr(controller, "_emulator_working_dir", lambda: tmp_path)
    calls = []
    process = SimpleNamespace(pid=456, poll=lambda: None)
    def popen(args, **kwargs):
        calls.append((args, kwargs))
        return process
    monkeypatch.setattr(engine.subprocess, "Popen", popen)
    avd = engine.AvdInfo("Salem_Google_TV", tmp_path, {}, "google_tv")
    info = controller.start_with_info(avd, wait_for_serial=False)
    assert info.command == [str(controller.tools.emulator), "-avd", "Salem_Google_TV", "-no-metrics"]
    options = calls[0][1]
    assert options["stdin"] == subprocess.DEVNULL
    assert options["stderr"] == subprocess.STDOUT
    assert options["stdout"].name == str(tmp_path / "emulator.log")
    assert options["creationflags"] == engine.CREATE_NO_WINDOW | engine.CREATE_NEW_PROCESS_GROUP
    assert not options.get("shell", False)
    assert controller.emulator_process is process
    controller._close_log_handle()


def test_dynamic_serial_filters_offline(monkeypatch, controller):
    output = "List of devices attached\nemulator-5554 offline\nemulator-5580 device product:Salem_Google_TV\n"
    monkeypatch.setattr(engine, "_run", lambda *a, **k: subprocess.CompletedProcess([], 0, output, ""))
    assert engine.find_device_for_avd(controller.tools, "Salem_Google_TV") == "emulator-5580"


@pytest.mark.parametrize("abi", ["x86", "x86_64", "arm64-v8a", "aarch64"])
def test_dynamic_image_detection(abi):
    output = f"system-images;android-35;google-tv;{abi} | 1 | Google TV System Image\nsystem-images;android-36;google-tv;{abi} | 1 | Google TV System Image"
    images = setup._parse_system_images(output)
    selected = setup._select_system_image(images, "google_tv")
    assert selected is not None
    assert "android-36" in selected.package


def test_tv_restore_failure_preserves_state(monkeypatch):
    mode = tv_mode.TVMode()
    state = SimpleNamespace(final_rect_matches_monitor=True)
    monkeypatch.setattr(tv_mode.windows, "find_emulator_window", lambda *args: 123)
    monkeypatch.setattr(tv_mode.windows, "enter_tv_mode", lambda hwnd: state)
    mode.enter(42, "Salem_Google_TV")
    def fail(saved):
        raise RuntimeError("restore failed")
    monkeypatch.setattr(tv_mode.windows, "exit_tv_mode", fail)
    with pytest.raises(RuntimeError):
        mode.restore()
    assert mode.active and mode.state is state
    monkeypatch.setattr(tv_mode.windows, "exit_tv_mode", lambda saved: (1, 2, 3, 4))
    mode.restore()
    assert not mode.active
