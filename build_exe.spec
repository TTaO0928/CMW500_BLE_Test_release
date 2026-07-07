# -*- mode: python ; coding: utf-8 -*-
"""
CMW500 BLE 测试工具 - PyInstaller 打包 spec 文件
用法：
    pyinstaller build_exe.spec --noconfirm --clean
或双击 build.bat 自动完成依赖安装、清理、打包。
"""

import os
import sys

# 项目根目录（spec 文件所在目录）
PROJECT_ROOT = os.path.abspath(os.path.dirname(SPECPATH))

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[PROJECT_ROOT],
    binaries=[],
    datas=[
        ('config.yaml', '.'),
    ],
    hiddenimports=[
        'pyvisa',
        'pyvisa_py',
        'pyvisa_py.protocols',
        'pyvisa_py.protocols.rpc',
        'pyvisa_py.protocols.usb',
        'pyvisa_py.protocols.tcpip',
        'pyvisa_py.protocols.gpib',
        'pyvisa_py.protocols.serial',
        'usb',
        'usb.core',
        'usb.util',
        'serial',
        'serial.tools',
        'PyQt6',
        'PyQt6.QtWidgets',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'pandas',
        'pandas._libs.tslibs.base',
        'openpyxl',
        'yaml',
        'matplotlib',
        'matplotlib.backends.backend_qt5agg',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

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
    upx_exclude=[],
    runtime_tmpdir=None,
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
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='CMW500_BLE_Test',
)
