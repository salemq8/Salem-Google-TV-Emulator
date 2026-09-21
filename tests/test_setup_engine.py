import hashlib
import json
import subprocess
import zipfile
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from salem_tv_box_emulator.services import package_manager, setup_engine, toolchain
from salem_tv_box_emulator.services.compatibility import WindowsInfo
from salem_tv_box_emulator.services.errors import SalemError
from salem_tv_box_emulator.services.support import sanitize


def test_manifest_pins_packages_and_official_artifacts():
    manifest = toolchain.load_manifest()
    assert manifest["image"]["package"] in manifest["packages"]
    assert all("latest" not in name for name in manifest["packages"])
    for key in ("jdk", "android_cli", "commandline_tools"):
        toolchain.Artifact.parse(manifest[key])


@pytest.mark.parametrize("url", ["http://dl.google.com/file", "https://evil.example/file"])
def test_unofficial_bootstrap_rejected(url):
    with pytest.raises(ValueError):
        toolchain.Artifact.parse(dict(version="1", url=url, digest="a" * 64))


def test_completed_partial_download_recovers_without_network(tmp_path, monkeypatch):
    content = b"verified payload"
    digest = hashlib.sha256(content).hexdigest()
    artifact = toolchain.Artifact("1", "https://dl.google.com/tool.zip", digest, "sha256")
    (tmp_path / f"{digest[:16]}-tool.zip.part").write_bytes(content)
    network = Mock(side_effect=AssertionError("Must not redownload verified content"))
    monkeypatch.setattr(toolchain.urllib.request, "urlopen", network)
    assert toolchain.download(artifact, tmp_path, Mock()).read_bytes() == content


def test_extract_blocks_traversal_and_preserves_existing(tmp_path):
    destination = tmp_path / "tools"
    destination.mkdir()
    (destination / "good.txt").write_text("original")
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("../../escaped.txt", "bad")
    with pytest.raises(SalemError, match="Unsafe"):
        toolchain.install_zip(archive, destination)
    assert (destination / "good.txt").read_text() == "original"


def test_java_warning_exit_zero_is_not_failure(monkeypatch, caplog):
    monkeypatch.setattr(subprocess, "run", Mock(return_value=SimpleNamespace(returncode=0, stdout="installed", stderr="WARNING: telemetry unavailable")))
    with caplog.at_level("INFO"):
        output = package_manager.ToolRunner({"SystemRoot": "C:/Windows"})(["tool.exe", "install"])
    assert "installed" in output and "exit_code=0" in caplog.text


def test_nonzero_reports_exact_exit_and_stderr(monkeypatch, caplog):
    monkeypatch.setattr(subprocess, "run", Mock(return_value=SimpleNamespace(returncode=9, stdout="", stderr="repository unavailable")))
    with caplog.at_level("INFO"), pytest.raises(SalemError) as error:
        package_manager.ToolRunner({"SystemRoot": "C:/Windows"})(["sdkmanager.bat", "--install", "emulator"])
    assert "sdkmanager.bat exited with code 9" in str(error.value)
    assert "repository unavailable" in error.value.details
    assert "exit_code=9" in caplog.text


def test_modern_failure_uses_explicit_validated_fallback():
    modern, legacy, report = Mock(), Mock(), Mock()
    modern.probe.side_effect = SalemError("Failed", "native exit failure")
    assert package_manager.select_manager(modern, legacy, report) is legacy
    legacy.probe.assert_called_once()
    assert "compatibility" in report.call_args.args[0]


def test_modern_install_pins_revision(tmp_path):
    run = Mock()
    manager = package_manager.AndroidCLI(tmp_path / "android.exe", tmp_path / "sdk", run)
    manager.install("system-images;android-36;google-tv;x86_64", "4.0.0")
    assert run.call_args.args[0][-1] == "system-images/android-36/google-tv/x86_64@4.0.0"


def engine(tmp_path):
    sdk = tmp_path / "sdk"
    sdk.mkdir()
    instance = setup_engine.SetupEngine(Mock(), sdk=sdk, jdk=tmp_path / "jdk", state_path=tmp_path / "state.json")
    instance.manager = Mock()
    return instance


def test_package_repair_rolls_back_failed_install(tmp_path):
    instance = engine(tmp_path)
    package = instance.sdk / "platform-tools"
    package.mkdir()
    (package / "original").write_text("preserved")
    def install(*_):
        assert not package.exists()
        package.mkdir()
        (package / "broken").write_text("partial")
        raise SalemError("Failed", "network interrupted")
    instance.manager.install.side_effect = install
    with pytest.raises(SalemError, match="network interrupted"):
        instance.install_package("platform-tools")
    assert (package / "original").read_text() == "preserved"
    assert not (package / "broken").exists()


def test_healthy_package_skipped(tmp_path, monkeypatch):
    instance = engine(tmp_path)
    monkeypatch.setattr(setup_engine, "package_healthy", lambda *_: True)
    instance.install_package("emulator")
    instance.manager.install.assert_not_called()


def test_setup_failure_persists_stage_and_error(tmp_path, monkeypatch):
    instance = engine(tmp_path)
    monkeypatch.setattr(setup_engine, "require_supported", Mock())
    monkeypatch.setattr(setup_engine, "require_disk", Mock())
    instance.java = Mock(side_effect=SalemError("Failed", "JDK download timeout"))
    with pytest.raises(SalemError):
        instance.execute(True)
    state = json.loads(instance.state_path.read_text())
    assert state["stage"] == "Portable JDK" and state["status"] == "error"
    assert "JDK download timeout" in state["message"]


@pytest.mark.parametrize("build,arch,bits,expected", [(9600, "AMD64", 64, False), (17763, "AMD64", 64, True), (19044, "AMD64", 64, True), (26200, "ARM64", 64, False), (19044, "x86", 32, False)])
def test_os_compatibility(build, arch, bits, expected):
    assert WindowsInfo("Windows", "test", build, arch, bits).supported is expected


def test_support_report_redacts_credentials():
    output = sanitize("token=private-value\nhttps://name:secret@example.com/x?api_key=hidden")
    assert "private-value" not in output and "secret" not in output and "hidden" not in output
