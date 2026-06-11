# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['C:\\Users\\Asrok\\Desktop\\TV\\build_tools\\installer.py'],
    pathex=[],
    binaries=[],
    datas=[('C:\\Users\\Asrok\\Desktop\\TV\\release_github\\Portable.zip', '.')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Setup',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version='C:\\Users\\Asrok\\Desktop\\TV\\build_tools\\version_info_installer.txt',
    icon=['C:\\Users\\Asrok\\Desktop\\TV\\assets\\salem_google_tv_emulator.ico'],
)
