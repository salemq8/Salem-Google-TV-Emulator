"""Build, relocate, test and only then promote a matched Local/Release artifact set."""
from __future__ import annotations

import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from .bundle import copy_notices, sha256, verify_binary_closure, write_manifests
from .nsis import build as build_installer
from .validation import privacy_scan, sign_optional, verify_metadata

ROOT = Path(__file__).resolve().parent.parent
APP = "Salem Google TV Emulator"
VERSION = (ROOT / "VERSION").read_text().strip()
STAGE = ROOT / "build/release-stage"
VALIDATION = ROOT / "validation/build"
DOCS = ("README.md", "CHANGELOG.md", "RELEASE.md", "VERSION", "version.json", "THIRD_PARTY_NOTICES.md", "toolchain_manifest.json")


def reset(path: Path) -> None:
    resolved = path.resolve()
    if not resolved.is_relative_to(ROOT) or resolved == ROOT:
        raise ValueError(f"Refusing to remove {resolved}")
    if resolved.exists():
        shutil.rmtree(resolved)
    resolved.mkdir(parents=True)


def run(args: list[str] | str, **kwargs) -> None:
    print(args if isinstance(args, str) else subprocess.list2cmdline(args), flush=True)
    env = os.environ.copy()
    env["PATH"] = os.pathsep.join([str(Path(sys.executable).parent), sys.base_prefix, str(Path(os.environ["SystemRoot"]) / "System32"), os.environ["SystemRoot"]])
    for name in ("PYTHONPATH", "PYTHONHOME", "QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH", "QML2_IMPORT_PATH"):
        env.pop(name, None)
    kwargs.setdefault("env", env)
    subprocess.run(args, check=True, cwd=ROOT, **kwargs)


def archive_tree(folder: Path, output: Path) -> None:
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for file in sorted(folder.rglob("*")):
            if file.is_file():
                archive.write(file, file.relative_to(folder.parent))


def smoke(exe: Path, report: Path, scale: str = "1") -> dict:
    env = os.environ.copy()
    env.update(PATH=str(Path(os.environ["SystemRoot"]) / "System32"), PYTHONPATH="", PYTHONHOME="",
               QT_PLUGIN_PATH="C:/nonexistent-foreign-qt/plugins", QT_SCALE_FACTOR=scale)
    result = subprocess.run([str(exe), "--self-test", str(report)], cwd=exe.parent,
                            env=env, timeout=90, creationflags=subprocess.CREATE_NO_WINDOW)
    data = json.loads(report.read_text(encoding="utf-8")) if report.exists() else {}
    if result.returncode or data.get("ok") is not True:
        raise RuntimeError(f"Packaged smoke test failed: {data}; exit={result.returncode}")
    return data


def source_package(output: Path) -> None:
    files = [ROOT / name for name in (*DOCS, "requirements.txt", "requirements-build.txt", "pyproject.toml", "main.py", "run.bat", ".gitignore")]
    for name in ("salem_tv_box_emulator", "build_tools", "assets", "docs", "tests"):
        files += [p for p in (ROOT / name).rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"]
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for file in sorted(files):
            archive.write(file, Path(f"{APP} Source") / file.relative_to(ROOT))


def promote(local: Path, release: Path) -> None:
    # Keep both previous sets until both replacements have moved successfully.
    candidate = ROOT / "candidate"
    candidate.mkdir(exist_ok=True)
    pairs = [(local, candidate / "build_local"), (release, candidate / "release_github")]
    previous = []
    placed = []
    try:
        for source, target in pairs:
            backup = STAGE / f"previous-{target.name}"
            if target.exists():
                target.rename(backup)
                previous.append((backup, target))
            source.rename(target)
            placed.append((target, source))
    except OSError:
        for target, source in reversed(placed):
            target.rename(source)
        for backup, target in reversed(previous):
            backup.rename(target)
        raise


def main() -> None:
    if platform.python_version() != "3.14.4" or platform.machine() != "AMD64":
        raise RuntimeError("Release builds require Python 3.14.4 x64. End users need no Python installation.")
    reset(STAGE)
    reset(VALIDATION)
    python = sys.executable
    for args in (["ruff", "check", "salem_tv_box_emulator", "build_tools", "tests", "main.py"],
                 ["mypy"], ["pytest"], ["compileall", "-q", "salem_tv_box_emulator", "build_tools", "tests", "main.py"]):
        run([python, "-m", *args])
    dist = STAGE / "dist"
    work = STAGE / "pyinstaller"
    flags = ["--noconfirm", "--clean", "--distpath", str(dist), "--workpath", str(work)]
    run([python, "-m", "PyInstaller", *flags, str(ROOT / "build_tools/app.spec")])
    app = dist / APP
    signed = sign_optional(app / f"{APP}.exe")
    app_metadata = verify_metadata(app / f"{APP}.exe", VERSION)
    for name in DOCS:
        shutil.copy2(ROOT / name, app / name)
    copy_notices(app)
    graph = verify_binary_closure(app)
    (VALIDATION / "binary-dependencies.json").write_text(json.dumps(graph, indent=2), encoding="utf-8")
    write_manifests(app)
    for scale in ("1", "1.5", "2"):
        smoke(app / f"{APP}.exe", VALIDATION / f"dpi-{scale}/startup.json", scale)
    portable = STAGE / "Portable.zip"
    archive_tree(app, portable)
    relocated = STAGE / "Relocated Portable - TV"
    with zipfile.ZipFile(portable) as archive:
        archive.extractall(relocated)
    smoke(relocated / APP / f"{APP}.exe", VALIDATION / "relocated/startup.json")
    # A deliberately incomplete copy must fail through our native startup boundary.
    damaged = relocated / APP / "_internal/PySide6/Qt6Core.dll"
    damaged.rename(damaged.with_suffix(".removed"))
    report = VALIDATION / "missing-qtcore.json"
    outcome = subprocess.run([str(relocated / APP / f"{APP}.exe"), "--self-test", str(report)],
                             timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
    error = json.loads(report.read_text(encoding="utf-8"))
    if outcome.returncode == 0 or error.get("ok") is not False or "Qt6Core.dll" not in error.get("error", ""):
        raise RuntimeError("Damaged package did not produce the expected actionable failure.")
    damaged.with_suffix(".removed").rename(damaged)
    run([python, "-m", "PyInstaller", *flags, str(ROOT / "build_tools/setup.spec")])
    build_installer(ROOT, STAGE, app)
    sign_optional(dist / "Setup.exe")
    installer_metadata = verify_metadata(dist / "Setup.exe", VERSION)
    install_target = STAGE / "Installer Test"
    for _ in range(2):
        # NSIS /D consumes the unquoted command-line remainder, including spaces.
        run(f'"{dist / "Setup.exe"}" /S /TEST /D={install_target}', timeout=150, creationflags=subprocess.CREATE_NO_WINDOW)
    smoke(install_target / APP / f"{APP}.exe", VALIDATION / "installed/startup.json")
    # Copy the uninstaller out so /_?= runs synchronously without its self-copy helper.
    uninstaller = STAGE / "Uninstall Test.exe"
    shutil.copy2(install_target / "Uninstall.exe", uninstaller)
    sentinel = install_target / "personal-file.txt"
    sentinel.write_text("Preserve user data", encoding="utf-8")
    run(f'"{uninstaller}" /S _?={install_target}', timeout=90, creationflags=subprocess.CREATE_NO_WINDOW)
    if (install_target / APP / f"{APP}.exe").exists() or not sentinel.exists():
        raise RuntimeError("Installer uninstall safety validation failed.")
    release = STAGE / "release_github"
    release.mkdir()
    shutil.copy2(portable, release / "Portable.zip")
    shutil.copy2(dist / "Setup.exe", release / "Setup.exe")
    source_package(release / "Source.zip")
    privacy = privacy_scan(release / "Source.zip", release / "Portable.zip")
    if json.loads((ROOT / "version.json").read_text())["version"] != VERSION:
        raise RuntimeError("Update version metadata does not match VERSION")
    for name in DOCS:
        shutil.copy2(ROOT / name, release / name)
    for name, branded in {"Setup.exe": f"Salem_Google_TV_Emulator_Setup_v{VERSION}.exe",
                          "Portable.zip": f"Salem_Google_TV_Emulator_Portable_v{VERSION}.zip",
                          "Source.zip": f"Salem_Google_TV_Emulator-v{VERSION}-source.zip"}.items():
        shutil.copy2(release / name, release / branded)
    manifest = {"version": VERSION, "candidate": "rework-2026-09-19", "production_ready": False,
                "signed": signed, "privacy_scan": privacy, "app_metadata": app_metadata, "installer_metadata": installer_metadata,
                "python": platform.python_version(), "platform": platform.platform(),
                "dependencies": {d.metadata["Name"]: d.version for d in importlib.metadata.distributions()},
                "source_sha256": sha256(release / "Source.zip"), "verified": ["PE x64 closure", "DPI 100/150/200%", "relocated portable", "missing DLL failure", "installed copy", "silent upgrade", "uninstall preserves unrelated files"],
                "not_verified": ["clean Windows 10 PC", "clean Windows 11 PC", "live emulator regression", "first-time SDK installation", "customer-specific QtCore traceback"]}
    (release / "build-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (release / "SHA256SUMS.txt").write_text("\n".join(f"{sha256(p)}  {p.name}" for p in sorted(release.iterdir()) if p.is_file()) + "\n", encoding="utf-8")
    local = STAGE / "local"
    local.mkdir()
    shutil.move(str(app), str(local / APP))
    promote(local, release)
    print("Staged candidate Local and Release artifacts regenerated; public v1.0 outputs unchanged.", flush=True)


if __name__ == "__main__":
    main()
