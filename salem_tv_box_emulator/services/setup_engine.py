"""Resumable setup: validate every step, never infer health from a saved stage flag."""
from __future__ import annotations

import json
import logging
import os
import shutil
import struct
import tempfile
import time
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

from ..android_backend import SALEM_BASE_DIR, SALEM_JDK_ROOT, SALEM_SDK_ROOT, detect_android_tools, find_google_tv_avd, list_avds
from ..config import APP_LOGS, atomic_json
from ..setup_wizard import SetupProgress, SetupResult
from .compatibility import require_supported
from .errors import SalemError
from .java_runtime import MicrosoftJdkRelease
from .package_manager import AndroidCLI, SdkManager, ToolRunner, select_manager
from .support import sanitize
from .toolchain import Artifact, checksum, download, install_zip, load_manifest, require_disk

STAGES = ["Preflight", "Portable JDK", "Android tools", "SDK repository", "Platform tools", "Android Emulator", "Google TV image", "SDK licenses", "Google TV device", "Engine validation", "Setup complete"]
STATE_PATH = SALEM_BASE_DIR / "setup-state.json"


def normalized_revision(value: str) -> tuple[int, ...]:
    parts = [int(part) for part in value.strip().split(".")]
    return tuple((parts + [0, 0, 0])[:3])


def package_revision(sdk: Path, package: str) -> str | None:
    path = sdk.joinpath(*package.split(";"))
    properties = path / "source.properties"
    if properties.is_file():
        for line in properties.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.strip().startswith("Pkg.Revision="):
                return line.split("=", 1)[1].strip()
    xml = path / "package.xml"
    if xml.exists():
        try:
            revision = ET.parse(xml).getroot().find(".//localPackage/revision")
            if revision is not None:
                return ".".join(revision.findtext(part, "0") for part in ("major", "minor", "micro"))
        except ET.ParseError:
            return None
    return None


def package_healthy(sdk: Path, package: str, revision: str) -> bool:
    found = package_revision(sdk, package)
    if found is None or normalized_revision(found) != normalized_revision(revision):
        return False
    files = {"platform-tools": ["adb.exe", "AdbWinApi.dll"], "emulator": ["emulator.exe", "qemu/windows-x86_64/qemu-system-x86_64.exe"]}
    required = files.get(package, ["system.img", "ramdisk.img"])
    root = sdk.joinpath(*package.split(";"))
    return all((root / name).is_file() and (root / name).stat().st_size > 0 for name in required)


def repository_versions(url: str) -> dict[str, str]:
    try:
        with urllib.request.urlopen(url, timeout=45) as response:
            root = ET.fromstring(response.read(20 * 1024 * 1024))
        result = {}
        for package in root.findall("remotePackage"):
            channel = package.find("channelRef")
            if channel is not None and channel.get("ref") != "channel-0":
                continue
            result[package.attrib["path"]] = ".".join(package.findtext(f"revision/{part}", "0") for part in ("major", "minor", "micro"))
        return result
    except (OSError, ET.ParseError) as exc:
        raise SalemError("SdkRepositoryUnavailable", "Google's SDK repository is unavailable. Check your network and retry.", str(exc)) from exc


def subprocess_environment(jdk: Path, sdk: Path) -> dict[str, str]:
    env = os.environ.copy()
    windows = os.environ.get("SystemRoot", "C:/Windows")
    env["SystemRoot"] = windows
    env.update(JAVA_HOME=str(jdk), JDK_HOME=str(jdk), ANDROID_HOME=str(sdk), ANDROID_SDK_ROOT=str(sdk),
               ANDROID_SDK_ROOT_HOME=str(sdk))
    env["PATH"] = os.pathsep.join([str(jdk / "bin"), str(sdk / "platform-tools"), str(sdk / "emulator"), str(Path(windows) / "System32"), windows])
    for name in ("JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS", "JDK_JAVA_OPTIONS", "QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH"):
        env.pop(name, None)
    return env


def is_x64_executable(path: Path) -> bool:
    with path.open("rb") as stream:
        if stream.read(2) != b"MZ":
            return False
        stream.seek(0x3C)
        stream.seek(struct.unpack("<I", stream.read(4))[0])
        return stream.read(6) == b"PE\0\0\x64\x86"


class SetupEngine:
    def __init__(self, progress, *, manifest=None, sdk=SALEM_SDK_ROOT, jdk=SALEM_JDK_ROOT, state_path=STATE_PATH):
        self.progress, self.manifest = progress, manifest or load_manifest()
        self.sdk, self.jdk, self.state_path = sdk, jdk, state_path
        self.cache = sdk.parent / "downloads"
        self.run = ToolRunner(subprocess_environment(jdk, sdk))
        self.stage = "Preflight"
        self.completed = []
        self.logger = logging.getLogger("salem.setup")
        self.java_validation_error = ""

    def emit(self, status: str, message: str) -> None:
        self.logger.info("stage=%s status=%s message=%s", self.stage, status, sanitize(message))
        state = {"stage": self.stage, "status": status, "message": sanitize(message), "completed": self.completed,
                 "updated": time.time(), "manifest": self.manifest["candidate"]}
        atomic_json(self.state_path, state)
        self.progress(SetupProgress(self.stage, status, message))

    def step(self, name: str, work) -> None:
        self.stage = name
        self.emit("active", f"{name} in progress...")
        work()
        self.completed.append(name)
        self.emit("complete", f"{name} verified.")

    def acquire(self, key: str) -> Path:
        artifact = Artifact.parse(self.manifest[key])
        last_update = [0.0]
        def progress(done, total):
            if time.monotonic() - last_update[0] < 0.4 and done != total:
                return
            last_update[0] = time.monotonic()
            self.emit("active", f"Downloading {key}: {done / 2**20:.1f} MB" + (f" / {total / 2**20:.1f} MB" if total else ""))
        return download(artifact, self.cache, progress)

    def validate_java(self) -> bool:
        java = self.jdk / "bin/java.exe"
        self.java_validation_error = ""
        try:
            if not is_x64_executable(java):
                raise ValueError("Portable java.exe is not an x64 PE executable")
            release = MicrosoftJdkRelease.parse(
                (self.jdk / "release").read_text(encoding="utf-8"), self.manifest["jdk"]["version"])
            # ToolRunner combines stdout/stderr and raises on nonzero exit; stderr is normal for Java.
            release.verify_output(self.run([str(java), "-version"]))
            self.logger.info("Portable JDK verified: version=%s distribution=%s architecture=x64",
                             self.manifest["jdk"]["version"], release.distribution)
            return True
        except (OSError, SalemError, struct.error, ValueError, KeyError, TypeError) as exc:
            self.java_validation_error = str(exc)
            self.logger.warning("Portable JDK validation failed: %s", sanitize(self.java_validation_error))
            return False

    def java(self) -> None:
        if self.validate_java():
            self.logger.info("Existing portable JDK is healthy; download and installation skipped.")
            return
        install_zip(self.acquire("jdk"), self.jdk)
        if not self.validate_java():
            raise SalemError("JavaUnavailable", "Portable JDK verification failed. Open Setup Log and retry.",
                             self.java_validation_error)

    def tools(self) -> None:
        version = self.manifest["commandline_tools"]["version"]
        folder = self.sdk / "cmdline-tools" / version
        self.sdkmanager = folder / "bin/sdkmanager.bat"
        self.avdmanager = folder / "bin/avdmanager.bat"
        if not self.sdkmanager.is_file() or not self.avdmanager.is_file():
            install_zip(self.acquire("commandline_tools"), folder, "cmdline-tools")
        self.compat = SdkManager(self.sdkmanager, self.sdk, self.run)
        try:
            self.compat.probe()
        except SalemError:
            install_zip(self.acquire("commandline_tools"), folder, "cmdline-tools")
            self.compat.probe()
        cli = self.sdk.parent / "AndroidCLI" / self.manifest["android_cli"]["version"] / "android-cli.exe"
        if not cli.is_file() or checksum(cli, "sha256") != self.manifest["android_cli"]["digest"]:
            artifact = self.acquire("android_cli")
            cli.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(artifact, cli)
        self.manager = select_manager(AndroidCLI(cli, self.sdk, self.run), SdkManager(self.sdkmanager, self.sdk, self.run),
                                      lambda message: self.emit("active", message))

    def repository(self) -> None:
        self.available = {}
        for source in self.manifest["sources"][:2]:
            self.available.update(repository_versions(source))

    def install_package(self, package: str) -> None:
        revision = self.manifest["packages"][package]
        if package_healthy(self.sdk, package, revision):
            return
        if isinstance(self.manager, SdkManager) and normalized_revision(self.available.get(package, "0")) != normalized_revision(revision):
            raise SalemError("ToolchainRevisionUnavailable", f"Google no longer offers the reviewed {package} revision {revision} through the compatibility tool. Salem needs a reviewed toolchain update; an untested latest version was not installed.")
        # Move damaged packages outside the SDK so package managers cannot skip repair.
        target = self.sdk.joinpath(*package.split(";"))
        with tempfile.TemporaryDirectory(prefix=".salem-repair-", dir=self.sdk.parent) as temporary:
            backup = Path(temporary) / "previous"
            if target.exists():
                target.rename(backup)
            try:
                self.manager.install(package, revision)
                if not package_healthy(self.sdk, package, revision):
                    raise SalemError("PackageValidationFailed", f"The {package} files/version did not pass validation after installation.")
            except Exception:
                if target.exists():
                    target.rename(Path(temporary) / "failed")
                if backup.exists():
                    backup.rename(target)
                raise

    def avd(self) -> None:
        tools = detect_android_tools(self.sdk)
        avd = find_google_tv_avd(list_avds(tools))
        image = self.manifest["image"]["package"]
        if avd and avd.name == "Salem_Google_TV" and avd.avd_dir and (avd.avd_dir / "config.ini").is_file():
            sysdir = avd.config.get("image.sysdir.1", "").replace("\\", "/").strip("/")
            if sysdir.endswith(image.replace(";", "/")):
                return
            raise SalemError("AvdRepairNeedsConfirmation", "The existing Google TV profile uses a different image. Its user data has been preserved. Contact support before replacing this profile.")
        self.run([str(self.avdmanager), "create", "avd", "-n", "Salem_Google_TV", "-k", image, "-d", "tv_1080p"],
                 timeout=900, input_text="no\n")

    def health(self) -> None:
        for package, version in self.manifest["packages"].items():
            if not package_healthy(self.sdk, package, version):
                raise SalemError("PackageValidationFailed", f"Required package is incomplete: {package}")
        names = self.run([str(self.sdk / "emulator/emulator.exe"), "-list-avds"])
        if "Salem_Google_TV" not in names.splitlines():
            raise SalemError("AvdCreationFailed", "The official emulator cannot resolve Salem_Google_TV.")
        self.run([str(self.sdk / "platform-tools/adb.exe"), "version"])
        self.run([str(self.sdk / "emulator/emulator.exe"), "-version"])

    def execute(self, accept_licenses: bool) -> SetupResult:
        if not accept_licenses:
            raise SalemError("LicenseConsentRequired", "Confirm Google's SDK license terms before installing the engine.")
        try:
            def preflight():
                require_supported()
                require_disk(self.sdk, self.manifest["required_free_bytes"])
                self.sdk.mkdir(parents=True, exist_ok=True)
            self.step("Preflight", preflight)
            self.step("Portable JDK", self.java)
            self.step("Android tools", self.tools)
            self.step("SDK repository", self.repository)
            for stage, package in [("Platform tools", "platform-tools"), ("Android Emulator", "emulator"), ("Google TV image", self.manifest["image"]["package"])]:
                self.step(stage, lambda package=package: self.install_package(package))
            self.step("SDK licenses", self.compat.licenses)
            self.step("Google TV device", self.avd)
            self.step("Engine validation", self.health)
            self.stage = "Setup complete"
            self.emit("complete", "Google TV engine verified. Launch Google TV when Windows virtualization is ready.")
            return SetupResult(self.sdk, self.manifest["image"]["package"], True)
        except Exception as exc:
            self.logger.exception("stage=%s result=failed", self.stage)
            self.emit("error", f"Failed component: {self.stage}. {exc}\nRetry the failed step or open {APP_LOGS / 'setup.log'}.")
            raise


def setup_summary() -> str:
    try:
        return STATE_PATH.read_text(encoding="utf-8")
    except OSError:
        return json.dumps({"status": "not started"})

