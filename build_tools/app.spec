# Build from pinned wheels. All paths derive from this spec, not a developer profile.
from pathlib import Path
import sys

ROOT = Path(SPECPATH).parent
sys.path.insert(0, str(ROOT))
from build_tools.bundle import qt_binaries

a = Analysis([str(ROOT / 'main.py')], pathex=[str(ROOT)], binaries=qt_binaries(),
             datas=[(str(ROOT / 'assets'), 'assets'), (str(ROOT / 'toolchain_manifest.json'), '.')],
             hiddenimports=['PySide6.QtCore', 'PySide6.QtGui', 'PySide6.QtWidgets'],
             runtime_hooks=[str(ROOT / 'build_tools/runtime_hook.py')],
             excludes=['PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtWebEngineCore', 'PySide6.QtVirtualKeyboard',
                       'PyQt5', 'PyQt6', 'tkinter', 'pytest', 'mypy'], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='Salem Google TV Emulator', console=False,
          upx=False, strip=False, icon=str(ROOT / 'assets/salem_google_tv_emulator.ico'),
          version=str(ROOT / 'build_tools/version_info_app.txt'))
coll = COLLECT(exe, a.binaries, a.datas, name='Salem Google TV Emulator', upx=False, strip=False)
