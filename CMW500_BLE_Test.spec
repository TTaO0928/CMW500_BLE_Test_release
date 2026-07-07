# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('config.yaml', '.')],
    hiddenimports=['pyvisa_py', 'pyvisa_py.protocols', 'pyvisa_py.protocols.rpc', 'pyvisa_py.protocols.usb', 'pyvisa_py.protocols.tcpip', 'pyvisa_py.protocols.gpib', 'pyvisa_py.protocols.serial', 'usb', 'usb.core', 'usb.util', 'serial', 'serial.tools'],
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
    name='CMW500_BLE_Test',
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
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='CMW500_BLE_Test',
)
