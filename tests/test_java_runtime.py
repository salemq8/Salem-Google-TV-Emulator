import struct
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from salem_tv_box_emulator.services import package_manager, setup_engine
from salem_tv_box_emulator.services.java_runtime import JavaVersion


RELEASE = '''IMPLEMENTOR="Microsoft"
IMPLEMENTOR_VERSION="Microsoft-14941484"
JAVA_RUNTIME_VERSION="21.0.12.1+1-LTS"
JAVA_VERSION="21.0.12.1"
JAVA_VERSION_DATE="2026-08-18"
OS_ARCH="x86_64"
OS_NAME="Windows"
'''
VERSION_OUTPUT = '''openjdk version "21.0.12.1" 2026-08-18 LTS
OpenJDK Runtime Environment Microsoft-14941484 (build 21.0.12.1+1-LTS)
OpenJDK 64-Bit Server VM Microsoft-14941484 (build 21.0.12.1+1-LTS, mixed mode, sharing)
'''


def pe_image(machine=0x8664):
    image = bytearray(134)
    image[:2] = b"MZ"
    struct.pack_into("<I", image, 0x3C, 128)
    image[128:132] = b"PE\0\0"
    struct.pack_into("<H", image, 132, machine)
    return image


@pytest.fixture
def java_engine(tmp_path, monkeypatch):
    engine = setup_engine.SetupEngine(Mock(), jdk=tmp_path / "JDK21", sdk=tmp_path / "sdk",
                                      state_path=tmp_path / "state.json")
    (engine.jdk / "bin").mkdir(parents=True)
    (engine.jdk / "bin/java.exe").write_bytes(pe_image())
    (engine.jdk / "release").write_text(RELEASE, encoding="utf-8")
    # Exercise the real ToolRunner, including return-code enforcement and stderr capture.
    process = Mock(return_value=subprocess.CompletedProcess([], 0, stdout="", stderr=VERSION_OUTPUT))
    monkeypatch.setattr(package_manager.subprocess, "run", process)
    return engine, process


def test_live_microsoft_four_component_version_on_stderr(java_engine, caplog):
    engine, process = java_engine
    assert engine.manifest["jdk"]["version"] == "21.0.12.1"
    with caplog.at_level("INFO"):
        assert engine.validate_java()
    assert engine.java_validation_error == ""
    assert "exit_code=0" in caplog.text
    assert "Microsoft-14941484" in caplog.text
    args, kwargs = process.call_args
    assert args[0] == [str(engine.jdk / "bin/java.exe"), "-version"]
    assert kwargs["capture_output"] is True
    assert kwargs["env"]["JAVA_HOME"] == str(engine.jdk)
    assert kwargs["env"]["PATH"].split(setup_engine.os.pathsep)[0] == str(engine.jdk / "bin")


def test_healthy_jdk_skips_download_and_reinstallation(java_engine, monkeypatch, caplog):
    engine, process = java_engine
    engine.acquire = Mock(side_effect=AssertionError("Healthy JDK must not download"))
    install = Mock(side_effect=AssertionError("Healthy JDK must not reinstall"))
    monkeypatch.setattr(setup_engine, "install_zip", install)
    with caplog.at_level("INFO"):
        engine.java()
    engine.acquire.assert_not_called()
    install.assert_not_called()
    process.assert_called_once()
    assert "installation skipped" in caplog.text


@pytest.mark.parametrize("version", ["21.0.12", "21.0.12.2", "21.0.12.10", "21.0.13", "25.0.1", "21.0.12.1-ea"])
def test_wrong_runtime_version_rejected(java_engine, version):
    engine, process = java_engine
    process.return_value.stderr = VERSION_OUTPUT.replace("21.0.12.1", version)
    assert not engine.validate_java()
    assert engine.java_validation_error


@pytest.mark.parametrize("stdout,stderr", [
    ("", "WARNING: a version string is not a runtime banner: \"21.0.12.1\""),
    (VERSION_OUTPUT, VERSION_OUTPUT),
    ("", VERSION_OUTPUT.replace("Microsoft-14941484", "Eclipse Adoptium")),
    ("", VERSION_OUTPUT.replace("Microsoft-14941484", "Microsoft-99999")),
    ("", VERSION_OUTPUT.replace("+1-LTS", "+2-LTS")),
    ("", VERSION_OUTPUT.replace("+1-LTS", "+1-other")),
])
def test_ambiguous_or_inconsistent_runtime_output_rejected(java_engine, stdout, stderr):
    engine, process = java_engine
    process.return_value.stdout, process.return_value.stderr = stdout, stderr
    assert not engine.validate_java()


@pytest.mark.parametrize("stdout,stderr", [
    (VERSION_OUTPUT, ""),
    ("", "WARNING: harmless diagnostic\n" + VERSION_OUTPUT),
    ("WARNING: harmless diagnostic", VERSION_OUTPUT.replace("\n", "\r\n")),
])
def test_both_streams_warnings_and_crlf_supported(java_engine, stdout, stderr):
    engine, process = java_engine
    process.return_value.stdout, process.return_value.stderr = stdout, stderr
    assert engine.validate_java()


@pytest.mark.parametrize("release", [
    RELEASE.replace('IMPLEMENTOR="Microsoft"', 'IMPLEMENTOR="Eclipse Adoptium"'),
    RELEASE.replace('IMPLEMENTOR="Microsoft"', 'IMPLEMENTOR="Microsoft-other"'),
    RELEASE.replace('JAVA_VERSION="21.0.12.1"', 'JAVA_VERSION="21.0.12"'),
    RELEASE.replace('JAVA_RUNTIME_VERSION="21.0.12.1+1-LTS"', 'JAVA_RUNTIME_VERSION="25.0.1+1-LTS"'),
    RELEASE.replace('OS_ARCH="x86_64"', 'OS_ARCH="aarch64"'),
    RELEASE.replace('OS_NAME="Windows"', 'OS_NAME="Linux"'),
    RELEASE.replace('IMPLEMENTOR_VERSION="Microsoft-14941484"\n', ''),
    RELEASE.replace('JAVA_VERSION="21.0.12.1"\n', ''),
    RELEASE.replace('JAVA_VERSION="21.0.12.1"', 'JAVA_VERSION=21.0.12.1'),
    RELEASE.replace('JAVA_VERSION="21.0.12.1"', 'JAVA_VERSION=21'),
    RELEASE + 'IMPLEMENTOR="Microsoft"\n',
    RELEASE + '[other]\nVENDOR="Microsoft"\n',
    'malformed metadata',
    '',
])
def test_wrong_vendor_version_arch_or_malformed_release_rejected(java_engine, release):
    engine, process = java_engine
    (engine.jdk / "release").write_text(release, encoding="utf-8")
    assert not engine.validate_java()
    process.assert_not_called()


@pytest.mark.parametrize("image", [pe_image(0x14C), pe_image(0xAA64), b"not a PE", b"MZ"])
def test_non_x64_or_malformed_executable_rejected(java_engine, image):
    engine, process = java_engine
    (engine.jdk / "bin/java.exe").write_bytes(image)
    assert not engine.validate_java()
    process.assert_not_called()


def test_nonzero_java_exit_rejected_even_with_correct_version(java_engine, caplog):
    engine, process = java_engine
    process.return_value.returncode = 7
    with caplog.at_level("INFO"):
        assert not engine.validate_java()
    assert "exited with code 7" in engine.java_validation_error
    assert "exit_code=7" in caplog.text


def test_unreadable_release_rejected(java_engine, monkeypatch):
    engine, process = java_engine
    original = Path.read_text
    def read(path, *args, **kwargs):
        if path == engine.jdk / "release":
            raise PermissionError("release metadata is unreadable")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "read_text", read)
    assert not engine.validate_java()
    assert "unreadable" in engine.java_validation_error
    process.assert_not_called()


def test_invalid_utf8_release_rejected(java_engine):
    engine, process = java_engine
    (engine.jdk / "release").write_bytes(b"\xff\xfe")
    assert not engine.validate_java()
    process.assert_not_called()


def test_missing_release_rejected(java_engine):
    engine, process = java_engine
    (engine.jdk / "release").unlink()
    assert not engine.validate_java()
    process.assert_not_called()


def test_version_parser_keeps_patch_and_build_separate():
    version = JavaVersion.parse("21.0.12.1+1-LTS")
    assert version.number == (21, 0, 12, 1)
    assert version.build == 1
    assert version.optional == "LTS"
    assert JavaVersion.parse("21.0.12").number != version.number


@pytest.mark.parametrize("version", ["", "21.00.12", "21.0.12.0", "21.0.12.1-ea", "21.0.12.1+01-LTS", "x21.0.12.1", "21.0.12.1garbage"])
def test_malformed_or_prerelease_version_rejected(version):
    with pytest.raises(ValueError):
        JavaVersion.parse(version)
