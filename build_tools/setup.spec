from pathlib import Path
ROOT = Path(SPECPATH).parent
a = Analysis([str(ROOT / 'build_tools/installer.py')], pathex=[str(ROOT)],
             datas=[(str(ROOT / 'build/release-stage/Portable.zip'), '.'), (str(ROOT / 'VERSION'), '.')],
             excludes=['PySide6', 'PyQt6', 'PyQt5', 'tkinter'], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='SetupHelper', console=False, upx=False, strip=False,
          icon=str(ROOT / 'assets/salem_google_tv_emulator.ico'), version=str(ROOT / 'build_tools/version_info_installer.txt'))
