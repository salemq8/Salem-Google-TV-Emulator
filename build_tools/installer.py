"""Simple Windows installer for Salem Google TV Emulator."""

from __future__ import annotations

import ctypes
import os
import shutil
import sys
import zipfile
from pathlib import Path


APP_NAME = "Salem Google TV Emulator"
VERSION = "1.0"


def main() -> int:
    silent = "--silent" in sys.argv
    try:
        portable_zip = _resource_path("Portable.zip")
        if not portable_zip.exists():
            raise FileNotFoundError(f"Portable package was not bundled: {portable_zip}")

        install_root = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Programs" / APP_NAME
        if install_root.exists():
            shutil.rmtree(install_root)
        install_root.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(portable_zip) as archive:
            archive.extractall(install_root)

        app_dir = install_root / APP_NAME
        exe_path = app_dir / f"{APP_NAME}.exe"
        if not exe_path.exists():
            raise FileNotFoundError(f"Installed EXE was not found: {exe_path}")

        _create_desktop_shortcut(exe_path)
        _create_start_menu_shortcut(exe_path)
        if not silent:
            _message(
                f"{APP_NAME} v{VERSION} installed successfully.\n\n"
                f"Location:\n{app_dir}\n\n"
                "Use the desktop shortcut, Start Menu shortcut, or run the EXE directly."
            )
        return 0
    except Exception as exc:  # noqa: BLE001 - installer should show a user-readable error.
        if not silent:
            _message(f"{APP_NAME} setup failed:\n\n{exc}", error=True)
        else:
            print(f"{APP_NAME} setup failed: {exc}", file=sys.stderr)
        return 1


def _resource_path(name: str) -> Path:
    bundle_dir = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return bundle_dir / name


def _create_desktop_shortcut(exe_path: Path) -> None:
    desktop = Path(os.environ.get("PUBLIC", Path.home())) / "Desktop"
    if not desktop.exists():
        desktop = Path(os.environ.get("USERPROFILE", Path.home())) / "Desktop"
    _create_shortcut(exe_path, desktop / f"{APP_NAME}.lnk")


def _create_start_menu_shortcut(exe_path: Path) -> None:
    start_menu = (
        Path(os.environ.get("APPDATA", Path.home()))
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
    )
    start_menu.mkdir(parents=True, exist_ok=True)
    _create_shortcut(exe_path, start_menu / f"{APP_NAME}.lnk")


def _create_shortcut(exe_path: Path, shortcut: Path) -> None:
    ps_script = (
        "$shell = New-Object -ComObject WScript.Shell; "
        f"$shortcut = $shell.CreateShortcut('{_ps_escape(shortcut)}'); "
        f"$shortcut.TargetPath = '{_ps_escape(exe_path)}'; "
        f"$shortcut.WorkingDirectory = '{_ps_escape(exe_path.parent)}'; "
        f"$shortcut.IconLocation = '{_ps_escape(exe_path)},0'; "
        "$shortcut.Save()"
    )
    try:
        import subprocess

        subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
            creationflags=0x08000000,
        )
    except Exception:
        return


def _ps_escape(path: Path) -> str:
    return str(path).replace("'", "''")


def _message(text: str, error: bool = False) -> None:
    flags = 0x10 if error else 0x40
    ctypes.windll.user32.MessageBoxW(None, text, APP_NAME, flags)


if __name__ == "__main__":
    raise SystemExit(main())
