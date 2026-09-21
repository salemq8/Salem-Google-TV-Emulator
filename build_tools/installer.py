"""Per-user installer with verified staging and rollback. Never modifies engine data."""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

APP_NAME = "Salem Google TV Emulator"
VERSION = "1.0"


def extract_verified(archive_path: Path, stage: Path) -> Path:
    with zipfile.ZipFile(archive_path) as archive:
        for item in archive.infolist():
            path = (stage / item.filename).resolve()
            if not path.is_relative_to(stage.resolve()) or item.filename.startswith(("/", "\\")):
                raise ValueError(f"Unsafe package entry: {item.filename}")
        archive.extractall(stage)
    app = stage / APP_NAME
    manifest = json.loads((app / "payload-manifest.json").read_text(encoding="utf-8"))
    for name, expected in manifest.items():
        path = (app / name).resolve()
        if not path.is_relative_to(app.resolve()) or not path.is_file():
            raise ValueError(f"Missing/invalid package file: {name}")
        with path.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != expected:
            raise ValueError(f"Package integrity check failed: {name}")
    if not (app / f"{APP_NAME}.exe").is_file():
        raise ValueError("The application executable is missing.")
    return app


def install(archive_path: Path, target: Path) -> Path:
    target = target.resolve()
    if target == Path(target.anchor) or target == Path.home().resolve():
        raise ValueError("Invalid installation directory.")
    target.parent.mkdir(parents=True, exist_ok=True)
    app = target / APP_NAME
    if target.exists() and any(target.iterdir()) and not (app / f"{APP_NAME}.exe").is_file():
        raise ValueError("Installation directory contains unrelated files. Choose an empty folder.")
    # Stage on the same volume. A locked/running old EXE leaves the previous install intact.
    with tempfile.TemporaryDirectory(prefix=".salem-install-", dir=target.parent) as temp:
        stage = Path(temp)
        extract_verified(archive_path, stage)
        backup = stage / "previous"
        target.mkdir(exist_ok=True)
        if app.exists():
            app.rename(backup)
        try:
            (stage / APP_NAME).rename(app)
        except OSError:
            if backup.exists():
                backup.rename(app)
            raise
    return app / f"{APP_NAME}.exe"


def create_shortcuts(exe: Path) -> None:
    # WScript.Shell resolves redirected/OneDrive Desktop and per-user Start Menu.
    quoted = str(exe).replace("'", "''")
    directory = str(exe.parent).replace("'", "''")
    script = f"""$ErrorActionPreference = 'Stop'
$shell = New-Object -ComObject WScript.Shell
foreach ($folder in @($shell.SpecialFolders.Item('Desktop'), $shell.SpecialFolders.Item('Programs'))) {{
    $link = $shell.CreateShortcut((Join-Path $folder '{APP_NAME}.lnk'))
    $link.TargetPath = '{quoted}'
    $link.WorkingDirectory = '{directory}'
    $link.IconLocation = '{quoted},0'
    $link.Save()
}}
"""
    powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    result = subprocess.run([str(powershell), "-NoProfile", "-NonInteractive", "-Command", script],
                            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError("Application installed, but Windows could not create shortcuts: " + result.stderr.strip())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--silent", action="store_true")
    parser.add_argument("--target", type=Path)
    parser.add_argument("--no-shortcuts", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    target = args.target or Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Programs" / APP_NAME
    if not args.silent:
        consent = ctypes.windll.user32.MessageBoxW(None, f"Install {APP_NAME} v{VERSION}?\n\nLocation: {target}\n\nClose Salem before updating. Engine files and settings will be preserved.", APP_NAME, 0x24)
        if consent != 6:
            return 0
    result = {"ok": False, "version": VERSION, "target": str(target)}
    try:
        exe = install(root / "Portable.zip", target)
        if not args.no_shortcuts:
            create_shortcuts(exe)
        result.update(ok=True, executable=str(exe))
        message = f"{APP_NAME} v{VERSION} installed.\n\n{exe}\n\nOpen Salem from the Desktop or Start Menu."
    except Exception as exc:
        result["error"] = str(exc)
        message = f"Setup could not finish.\n\n{exc}\n\nClose Salem and retry. Your engine data has not been removed."
    log = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / APP_NAME / "logs/installer.json"
    for path in (log, args.report):
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    if not args.silent:
        ctypes.windll.user32.MessageBoxW(None, message, APP_NAME, 0x40 if result["ok"] else 0x10)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
