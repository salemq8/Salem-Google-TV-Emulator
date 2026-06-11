# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['C:\\Users\\Asrok\\Desktop\\TV\\main.py'],
    pathex=[],
    binaries=[],
    datas=[('C:\\Users\\Asrok\\Desktop\\TV\\assets', 'assets')],
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
    [],
    exclude_binaries=True,
    name='Salem Google TV Emulator',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version='C:\\Users\\Asrok\\Desktop\\TV\\build_tools\\version_info_app.txt',
    icon=['C:\\Users\\Asrok\\Desktop\\TV\\assets\\salem_google_tv_emulator.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Salem Google TV Emulator',
)
