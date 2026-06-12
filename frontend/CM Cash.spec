# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['C:\\_Almacen\\Develop\\pos-system\\frontend\\main.py'],
    pathex=['C:\\_Almacen\\Develop\\pos-system\\frontend\\.posvenv\\Lib\\site-packages'],
    binaries=[],
    datas=[],
    hiddenimports=['appdirs'],
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
    name='CM Cash',
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
    icon=['C:\\_Almacen\\Develop\\pos-system\\frontend\\assets\\CM_Cash.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='CM Cash',
)
