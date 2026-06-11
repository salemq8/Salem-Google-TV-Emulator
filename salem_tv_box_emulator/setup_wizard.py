from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .android_backend import (
    CREATE_NO_WINDOW,
    SALEM_JDK_ROOT,
    SALEM_SDK_ROOT,
    apply_salem_sdk_environment,
    detect_android_tools,
)


COMMANDLINE_TOOLS_PAGE = "https://developer.android.com/studio"
DEFAULT_CMDLINE_TOOLS_URL = "https://dl.google.com/android/repository/commandlinetools-win-14742923_latest.zip"
MICROSOFT_OPENJDK_PAGE = "https://learn.microsoft.com/en-us/java/openjdk/download"
DEFAULT_JDK21_URL = "https://aka.ms/download-jdk/microsoft-jdk-21-windows-x64.zip"
SYSTEM_IMAGE_PATTERN = re.compile(r"system-images;android-(?P<api>\d+);(?P<tag>[^;\s|]+);(?P<abi>[^;\s|]+)")
ABI_TIE_BREAKER = {
    "x86_64": 40,
    "x86": 30,
    "arm64-v8a": 20,
    "aarch64": 20,
}

SETUP_STAGES = [
    "Downloading tools",
    "Installing Portable JDK 21",
    "Installing SDK packages",
    "Accepting licenses",
    "Creating Google TV AVD",
    "Setup complete",
]


@dataclass(frozen=True)
class SetupProgress:
    stage: str
    status: str
    message: str = ""
    diagnostics: "ImageDetectionDiagnostics | None" = None
    diagnostic_text: str = ""


@dataclass
class SetupRuntimeDiagnostics:
    portable_jdk_path: Path | None = None
    java_version: str = ""
    sdkmanager_exit_codes: list[int] = field(default_factory=list)
    avdmanager_exit_codes: list[int] = field(default_factory=list)

    def to_text(self) -> str:
        return "\n".join(
            [
                "Runtime Diagnostics",
                "===================",
                f"Portable JDK path: {self.portable_jdk_path or 'Not installed yet'}",
                "Portable java -version:",
                self.java_version.strip() or "Not checked yet",
                f"sdkmanager exit code(s): {_format_exit_codes(self.sdkmanager_exit_codes)}",
                f"avdmanager exit code(s): {_format_exit_codes(self.avdmanager_exit_codes)}",
            ]
        )


@dataclass(frozen=True)
class SystemImagePackage:
    package: str
    api_level: int
    tag: str
    abi: str
    tv_type: str | None
    description: str = ""

    @property
    def tv_label(self) -> str:
        if self.tv_type == "google_tv":
            return "Google TV"
        return "System Image"

    def detail(self) -> str:
        description = f" | {self.description}" if self.description else ""
        return f"{self.tv_label}: API {self.api_level}, {self.tag}, {self.abi} -> {self.package}{description}"


@dataclass(frozen=True)
class ImageDetectionDiagnostics:
    sdkmanager_list_output: str
    all_system_images: list[SystemImagePackage]
    detected_tv_images: list[SystemImagePackage]
    selected_google_tv: SystemImagePackage | None
    portable_jdk_path: Path | None = None
    portable_java_version: str = ""
    sdkmanager_exit_codes: tuple[int, ...] = ()
    avdmanager_exit_codes: tuple[int, ...] = ()
    manual_google_tv: str | None = None

    def to_text(self) -> str:
        lines = [
            "Runtime Diagnostics",
            "===================",
            f"Portable JDK path: {self.portable_jdk_path or 'Not installed yet'}",
            "Portable java -version:",
            self.portable_java_version.strip() or "Not checked yet",
            f"sdkmanager exit code(s): {_format_exit_codes(self.sdkmanager_exit_codes)}",
            f"avdmanager exit code(s): {_format_exit_codes(self.avdmanager_exit_codes)}",
            "",
            "Detected TV Images",
            "==================",
        ]
        if self.detected_tv_images:
            lines.extend(image.detail() for image in self.detected_tv_images)
        else:
            lines.append("No TV system images detected automatically.")

        lines.extend(
            [
                "",
                "Selected Images",
                "===============",
                f"Google TV: {self.selected_google_tv.package if self.selected_google_tv else 'Not selected'}",
            ]
        )
        if self.manual_google_tv:
            lines.extend(
                [
                    "",
                    "Manual Packages",
                    "===============",
                    f"Google TV: {self.manual_google_tv or 'Not provided'}",
                ]
            )

        lines.extend(
            [
                "",
                "All Parsed System Images",
                "========================",
            ]
        )
        if self.all_system_images:
            lines.extend(image.detail() for image in self.all_system_images)
        else:
            lines.append("No full system-image package paths were parsed.")

        lines.extend(
            [
                "",
                "sdkmanager --list Output",
                "========================",
                self.sdkmanager_list_output.strip() or "No output captured.",
            ]
        )
        return "\n".join(lines)


@dataclass(frozen=True)
class SetupResult:
    sdk_root: Path
    google_tv_image: str | None
    google_tv_created: bool
    diagnostics: ImageDetectionDiagnostics | None = None

    @property
    def google_tv_available(self) -> bool:
        return bool(self.google_tv_image and self.google_tv_created)

    def summary(self) -> str:
        lines = [
            "Setup complete.",
            f"SDK root: {self.sdk_root}",
        ]
        if self.google_tv_available:
            lines.append(f"Google TV image: {self.google_tv_image}")
        else:
            lines.append("Google TV image was unavailable.")
        return "\n".join(lines)


ProgressCallback = Callable[[SetupProgress], None]


class SetupError(RuntimeError):
    pass


def install_tv_emulator_engine(
    accept_licenses: bool,
    progress: ProgressCallback,
    manual_google_tv_package: str | None = None,
) -> SetupResult:
    if sys.platform != "win32":
        raise SetupError("Automatic setup is currently implemented for Windows 10/11.")
    if not accept_licenses:
        raise SetupError("SDK license acceptance was not confirmed.")

    runtime = SetupRuntimeDiagnostics()
    current_stage = "Downloading tools"
    SALEM_SDK_ROOT.mkdir(parents=True, exist_ok=True)
    try:
        apply_salem_sdk_environment(force=True)

        progress(SetupProgress("Downloading tools", "active", f"Installing into {SALEM_SDK_ROOT}"))
        bootstrap_sdkmanager = _ensure_commandline_tools(progress)
        progress(SetupProgress("Downloading tools", "complete", "Official Android command-line tools are ready."))

        current_stage = "Installing Portable JDK 21"
        progress(SetupProgress("Installing Portable JDK 21", "active", f"Installing into {SALEM_JDK_ROOT}"))
        jdk_root = _ensure_portable_jdk(progress)
        runtime.portable_jdk_path = jdk_root
        runtime.java_version = _portable_java_version(jdk_root)
        progress(
            SetupProgress(
                "Installing Portable JDK 21",
                "complete",
                "Portable Microsoft OpenJDK 21 is ready.",
                diagnostic_text=runtime.to_text(),
            )
        )

        env = _sdk_environment(bootstrap_sdkmanager, jdk_root)

        current_stage = "Installing SDK packages"
        progress(
            SetupProgress(
                "Installing SDK packages",
                "active",
                "Installing platform-tools, emulator, cmdline-tools;latest, and TV system images. This can take a while.",
                diagnostic_text=runtime.to_text(),
            )
        )
        _run_tool(
            bootstrap_sdkmanager,
            [
                f"--sdk_root={SALEM_SDK_ROOT}",
                "platform-tools",
                "emulator",
                "cmdline-tools;latest",
            ],
            env=env,
            input_text=_yes_stream(),
            timeout=3600,
            runtime=runtime,
        )

        tools = detect_android_tools(SALEM_SDK_ROOT)
        sdkmanager = tools.sdkmanager or bootstrap_sdkmanager
        env = _sdk_environment(sdkmanager, jdk_root)

        progress(SetupProgress("Installing SDK packages", "active", "Updating SDK packages before searching TV images.", diagnostic_text=runtime.to_text()))
        _run_tool(
            sdkmanager,
            [f"--sdk_root={SALEM_SDK_ROOT}", "--update"],
            env=env,
            input_text=_yes_stream(),
            timeout=3600,
            runtime=runtime,
        )

        available_output = _sdkmanager_list_output(sdkmanager, env, runtime)
        all_images = _parse_system_images(available_output)
        tv_images = [image for image in all_images if image.tv_type == "google_tv"]
        manual_google_tv = _manual_system_image(manual_google_tv_package, "google_tv")
        google_tv = manual_google_tv or _select_system_image(tv_images, "google_tv")

        diagnostics = _build_image_diagnostics(
            available_output,
            all_images,
            tv_images,
            google_tv,
            runtime,
            manual_google_tv_package,
        )
        progress(SetupProgress("Installing SDK packages", "active", "TV image detection complete.", diagnostics, runtime.to_text()))

        if not google_tv:
            raise SetupError(
                "No Google TV system image was detected in sdkmanager. "
                "Open the Diagnostics tab, copy a full TV system-image package path, paste it into Manual Package Selection, and retry setup."
            )

        image_packages = [google_tv.package]
        progress(SetupProgress("Installing SDK packages", "active", f"Selected Google TV image: {google_tv.package}", diagnostics))

        _run_tool(
            sdkmanager,
            [f"--sdk_root={SALEM_SDK_ROOT}", *image_packages],
            env=env,
            input_text=_yes_stream(),
            timeout=7200,
            runtime=runtime,
        )
        progress(
            SetupProgress(
                "Installing SDK packages",
                "complete",
                "SDK packages and the Google TV system image are installed.",
                _build_image_diagnostics(available_output, all_images, tv_images, google_tv, runtime, manual_google_tv_package),
            )
        )

        current_stage = "Accepting licenses"
        progress(SetupProgress("Accepting licenses", "active", "Running sdkmanager --licenses with confirmed acceptance."))
        _run_tool(
            sdkmanager,
            [f"--sdk_root={SALEM_SDK_ROOT}", "--licenses"],
            env=env,
            input_text=_yes_stream(),
            timeout=900,
            runtime=runtime,
        )
        progress(SetupProgress("Accepting licenses", "complete", "SDK licenses accepted."))

        tools = detect_android_tools(SALEM_SDK_ROOT)
        if not tools.avdmanager:
            raise SetupError("avdmanager was not found after SDK setup.")

        current_stage = "Creating Google TV AVD"
        progress(SetupProgress("Creating Google TV AVD", "active", "Creating Salem_Google_TV."))
        google_created = _create_avd(tools.avdmanager, "Salem_Google_TV", google_tv.package, env, runtime)
        progress(SetupProgress("Creating Google TV AVD", "complete", "Salem_Google_TV is ready."))

        diagnostics = _build_image_diagnostics(
            available_output,
            all_images,
            tv_images,
            google_tv,
            runtime,
            manual_google_tv_package,
        )
        progress(SetupProgress("Setup complete", "complete", "Google TV is ready. Press Launch Google TV.", diagnostics, runtime.to_text()))
        return SetupResult(
            sdk_root=SALEM_SDK_ROOT,
            google_tv_image=google_tv.package if google_tv else None,
            google_tv_created=google_created,
            diagnostics=diagnostics,
        )
    except Exception as exc:
        progress(SetupProgress(current_stage, "error", str(exc), diagnostic_text=runtime.to_text()))
        raise


def _ensure_commandline_tools(progress: ProgressCallback) -> Path:
    bootstrap_dir = SALEM_SDK_ROOT / "cmdline-tools" / "bootstrap"
    bootstrap_sdkmanager = bootstrap_dir / "bin" / "sdkmanager.bat"
    if bootstrap_sdkmanager.exists():
        progress(SetupProgress("Downloading tools", "active", "Bootstrap command-line tools already exist."))
        return bootstrap_sdkmanager

    download_dir = SALEM_SDK_ROOT / "_downloads"
    extract_dir = SALEM_SDK_ROOT / "_extract_cmdline_tools"
    download_dir.mkdir(parents=True, exist_ok=True)

    url = _resolve_commandline_tools_url()
    zip_path = download_dir / Path(url).name
    _download_file(url, zip_path, progress, source_label="Android command-line tools from Google")

    if extract_dir.exists():
        shutil.rmtree(extract_dir)
    extract_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(extract_dir)

    source_dir = extract_dir / "cmdline-tools"
    if not source_dir.exists():
        raise SetupError("Downloaded command-line tools archive did not contain a cmdline-tools folder.")

    bootstrap_dir.parent.mkdir(parents=True, exist_ok=True)
    if bootstrap_dir.exists():
        shutil.rmtree(bootstrap_dir)
    shutil.move(str(source_dir), str(bootstrap_dir))
    shutil.rmtree(extract_dir)

    if not bootstrap_sdkmanager.exists():
        raise SetupError("sdkmanager.bat was not found after extracting command-line tools.")
    return bootstrap_sdkmanager


def _ensure_portable_jdk(progress: ProgressCallback) -> Path:
    java_exe = SALEM_JDK_ROOT / "bin" / "java.exe"
    if java_exe.exists():
        progress(SetupProgress("Installing Portable JDK 21", "active", "Portable JDK 21 already exists."))
        return SALEM_JDK_ROOT

    SALEM_JDK_ROOT.parent.mkdir(parents=True, exist_ok=True)
    download_dir = SALEM_SDK_ROOT / "_downloads"
    extract_dir = SALEM_SDK_ROOT / "_extract_jdk21"
    staging_dir = SALEM_JDK_ROOT.parent / "_JDK21_staging"
    download_dir.mkdir(parents=True, exist_ok=True)

    url = _resolve_jdk21_url()
    zip_path = download_dir / Path(url).name
    _download_file(url, zip_path, progress, stage="Installing Portable JDK 21", source_label="Microsoft OpenJDK 21")

    if extract_dir.exists():
        shutil.rmtree(extract_dir)
    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    extract_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(extract_dir)

    source_root = _find_extracted_jdk_root(extract_dir)
    if not source_root:
        raise SetupError("Downloaded Microsoft OpenJDK archive did not contain bin\\java.exe.")

    shutil.copytree(source_root, staging_dir)
    if SALEM_JDK_ROOT.exists():
        shutil.rmtree(SALEM_JDK_ROOT)
    shutil.move(str(staging_dir), str(SALEM_JDK_ROOT))
    shutil.rmtree(extract_dir)

    if not java_exe.exists():
        raise SetupError("Portable JDK 21 install finished, but bin\\java.exe was not found.")
    return SALEM_JDK_ROOT


def _find_extracted_jdk_root(extract_dir: Path) -> Path | None:
    direct_java = extract_dir / "bin" / "java.exe"
    if direct_java.exists():
        return extract_dir
    for java_exe in extract_dir.rglob("java.exe"):
        if java_exe.parent.name.lower() == "bin":
            return java_exe.parent.parent
    return None


def _resolve_commandline_tools_url() -> str:
    try:
        request = urllib.request.Request(
            COMMANDLINE_TOOLS_PAGE,
            headers={"User-Agent": "SalemTVBoxEmulator/0.1"},
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            html = response.read().decode("utf-8", errors="ignore")
        matches = re.findall(
            r"(?:https://dl\.google\.com/android/repository/)?commandlinetools-win-\d+_latest\.zip",
            html,
        )
        if matches:
            match = matches[-1]
            if match.startswith("https://"):
                return match
            return f"https://dl.google.com/android/repository/{match}"
    except OSError:
        pass
    return DEFAULT_CMDLINE_TOOLS_URL


def _resolve_jdk21_url() -> str:
    try:
        request = urllib.request.Request(
            MICROSOFT_OPENJDK_PAGE,
            headers={"User-Agent": "SalemTVBoxEmulator/0.1"},
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            html = response.read().decode("utf-8", errors="ignore")
        matches = re.findall(
            r"https://aka\.ms/download-jdk/microsoft-jdk-21(?:\.\d+)*-windows-x64\.zip",
            html,
            flags=re.IGNORECASE,
        )
        if matches:
            return matches[0]
    except OSError:
        pass
    return DEFAULT_JDK21_URL


def _download_file(
    url: str,
    destination: Path,
    progress: ProgressCallback,
    stage: str = "Downloading tools",
    source_label: str = "download",
) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "SalemTVBoxEmulator/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            total = int(response.headers.get("Content-Length") or 0)
            downloaded = 0
            last_update = 0.0
            with destination.open("wb") as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
                    downloaded += len(chunk)
                    now = time.monotonic()
                    if now - last_update > 0.5:
                        progress(
                            SetupProgress(
                                stage,
                                "active",
                                _download_message(url, downloaded, total),
                            )
                        )
                        last_update = now
    except OSError as exc:
        raise SetupError(f"Could not download {source_label}: {exc}") from exc


def _download_message(url: str, downloaded: int, total: int) -> str:
    current_mb = downloaded / (1024 * 1024)
    if total:
        total_mb = total / (1024 * 1024)
        return f"Downloading {Path(url).name}: {current_mb:.1f} MB of {total_mb:.1f} MB"
    return f"Downloading {Path(url).name}: {current_mb:.1f} MB"


def _portable_java_version(jdk_root: Path) -> str:
    java_exe = jdk_root / "bin" / "java.exe"
    if not java_exe.exists():
        raise SetupError(f"Portable Java executable is missing: {java_exe}")
    result = subprocess.run(
        [str(java_exe), "-version"],
        capture_output=True,
        text=True,
        timeout=60,
        creationflags=CREATE_NO_WINDOW,
        errors="replace",
    )
    output = "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part)
    if result.returncode != 0:
        raise SetupError(output or f"Portable java -version exited with code {result.returncode}.")
    return output


def _sdk_environment(tool_path: Path, jdk_root: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["ANDROID_HOME"] = str(SALEM_SDK_ROOT)
    env["ANDROID_SDK_ROOT"] = str(SALEM_SDK_ROOT)
    env["JAVA_HOME"] = str(jdk_root)
    env["JDK_HOME"] = str(jdk_root)

    path_parts = [
        str(jdk_root / "bin"),
        str(tool_path.parent),
        str(SALEM_SDK_ROOT / "platform-tools"),
        str(SALEM_SDK_ROOT / "emulator"),
    ]
    env["PATH"] = os.pathsep.join([*path_parts, env.get("PATH", "")])
    return env


def _build_image_diagnostics(
    sdkmanager_list_output: str,
    all_images: list[SystemImagePackage],
    tv_images: list[SystemImagePackage],
    google_tv: SystemImagePackage | None,
    runtime: SetupRuntimeDiagnostics,
    manual_google_tv_package: str | None,
) -> ImageDetectionDiagnostics:
    return ImageDetectionDiagnostics(
        sdkmanager_list_output=sdkmanager_list_output,
        all_system_images=all_images,
        detected_tv_images=tv_images,
        selected_google_tv=google_tv,
        portable_jdk_path=runtime.portable_jdk_path,
        portable_java_version=runtime.java_version,
        sdkmanager_exit_codes=tuple(runtime.sdkmanager_exit_codes),
        avdmanager_exit_codes=tuple(runtime.avdmanager_exit_codes),
        manual_google_tv=manual_google_tv_package.strip() if manual_google_tv_package else None,
    )


def _format_exit_codes(exit_codes: list[int] | tuple[int, ...]) -> str:
    if not exit_codes:
        return "Not run yet"
    return ", ".join(str(code) for code in exit_codes)


def _sdkmanager_list_output(sdkmanager: Path, env: dict[str, str], runtime: SetupRuntimeDiagnostics) -> str:
    output = _run_tool(
        sdkmanager,
        [f"--sdk_root={SALEM_SDK_ROOT}", "--list"],
        env=env,
        timeout=900,
        return_output=True,
        runtime=runtime,
    )
    return "Command: sdkmanager --list\n\n" + output


def _parse_system_images(output: str) -> list[SystemImagePackage]:
    images: dict[str, SystemImagePackage] = {}
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        description = _description_from_sdkmanager_line(line)
        for match in SYSTEM_IMAGE_PATTERN.finditer(line):
            package = match.group(0).rstrip(".,;")
            api_level = int(match.group("api"))
            tag = match.group("tag").strip()
            abi = match.group("abi").strip().rstrip(".,;")
            images[package] = SystemImagePackage(
                package=package,
                api_level=api_level,
                tag=tag,
                abi=abi,
                tv_type=_classify_system_image(tag, description),
                description=description,
            )
    return sorted(images.values(), key=lambda image: (image.package, image.description))


def _description_from_sdkmanager_line(line: str) -> str:
    if "|" not in line:
        return ""
    parts = [part.strip() for part in line.split("|")]
    if len(parts) >= 3:
        return parts[-1]
    return ""


def _classify_system_image(tag: str, description: str) -> str | None:
    normalized_tag = _normalize_token(tag)
    normalized_description = _normalize_token(description)
    haystack = f"{normalized_tag} {normalized_description}"
    if "google" in haystack and "tv" in haystack:
        return "google_tv"
    return None


def _select_system_image(images: list[SystemImagePackage], tv_type: str) -> SystemImagePackage | None:
    candidates = [image for image in images if image.tv_type == tv_type]
    if not candidates:
        return None
    return sorted(candidates, key=lambda image: (image.api_level, _abi_score(image.abi), image.package), reverse=True)[0]


def _manual_system_image(package_text: str | None, tv_type: str) -> SystemImagePackage | None:
    package = (package_text or "").strip().strip('"').strip("'")
    if not package:
        return None
    match = SYSTEM_IMAGE_PATTERN.fullmatch(package)
    if not match:
        raise SetupError(f"Manual package is not a full system-image path: {package}")
    return SystemImagePackage(
        package=package,
        api_level=int(match.group("api")),
        tag=match.group("tag").strip(),
        abi=match.group("abi").strip(),
        tv_type=tv_type,
        description="Manual selection",
    )


def _abi_score(abi: str) -> int:
    return ABI_TIE_BREAKER.get(abi.lower(), 0)


def _normalize_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _create_avd(
    avdmanager: Path,
    name: str,
    image_package: str,
    env: dict[str, str],
    runtime: SetupRuntimeDiagnostics,
) -> bool:
    device = _select_tv_device(avdmanager, env, runtime)
    args = ["create", "avd", "--force", "-n", name, "-k", image_package]
    if device:
        args.extend(["-d", device])

    try:
        _run_tool(avdmanager, args, env=env, input_text="no\n", timeout=900, runtime=runtime)
        return True
    except SetupError:
        if not device:
            raise
        fallback_args = ["create", "avd", "--force", "-n", name, "-k", image_package]
        _run_tool(avdmanager, fallback_args, env=env, input_text="no\n", timeout=900, runtime=runtime)
        return True


def _select_tv_device(avdmanager: Path, env: dict[str, str], runtime: SetupRuntimeDiagnostics) -> str | None:
    try:
        output = _run_tool(avdmanager, ["list", "device"], env=env, timeout=120, return_output=True, runtime=runtime)
    except SetupError:
        return None

    current_id: str | None = None
    current_block: list[str] = []
    candidates: list[str] = []
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("id:"):
            if current_id and _block_mentions_tv(current_block):
                candidates.append(current_id)
            current_block = [stripped]
            match = re.search(r'"([^"]+)"', stripped)
            current_id = match.group(1) if match else stripped.split("id:", 1)[1].strip().split()[0]
        elif current_id:
            current_block.append(stripped)

    if current_id and _block_mentions_tv(current_block):
        candidates.append(current_id)

    preferred = [candidate for candidate in candidates if "1080" in candidate.lower()]
    return (preferred or candidates or [None])[0]


def _block_mentions_tv(block: list[str]) -> bool:
    haystack = " ".join(block).lower()
    return "tv" in haystack and "automotive" not in haystack


def _run_tool(
    executable: Path,
    args: list[str],
    env: dict[str, str],
    input_text: str | None = None,
    timeout: int = 600,
    return_output: bool = False,
    runtime: SetupRuntimeDiagnostics | None = None,
) -> str:
    command = [str(executable), *args]
    if executable.suffix.lower() in {".bat", ".cmd"}:
        command = ["cmd.exe", "/c", str(executable), *args]

    result = subprocess.run(
        command,
        input=input_text,
        capture_output=True,
        text=True,
        timeout=timeout,
        creationflags=CREATE_NO_WINDOW,
        env=env,
        errors="replace",
    )
    _record_exit_code(executable, result.returncode, runtime)
    output = "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part)
    if result.returncode != 0:
        raise SetupError(output or f"{executable.name} exited with code {result.returncode}.")
    return output if return_output else ""


def _record_exit_code(executable: Path, exit_code: int, runtime: SetupRuntimeDiagnostics | None) -> None:
    if not runtime:
        return
    name = executable.name.lower()
    if name.startswith("sdkmanager"):
        runtime.sdkmanager_exit_codes.append(exit_code)
    elif name.startswith("avdmanager"):
        runtime.avdmanager_exit_codes.append(exit_code)


def _yes_stream() -> str:
    return ("y\n" * 200) + "\n"
