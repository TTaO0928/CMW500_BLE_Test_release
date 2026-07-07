"""
CMW500 自动化测试工具 - PyInstaller 打包配置

使用方法：
    pyinstaller build_exe.py

打包完成后，exe 文件位于：dist/CMW500_BLE_Test/CMW500_BLE_Test.exe

注意事项：
    - config.yaml 会被打包到 exe 同目录，运行时可修改
    - test_results 输出目录需要在 exe 所在目录下手动创建或自动创建
    - 首次打包可能需要几分钟，请耐心等待
"""

import sys
import os

# PyInstaller 打包分析模块
block_cipher = None

a = Analysis(
    # 入口文件
    ['main.py'],
    # 搜索路径（项目根目录）
    pathex=[],
    # 需要打包的 Python 模块
    binaries=[],
    # 需要打包的数据文件（配置文件）
    datas=[
        ('config.yaml', '.'),  # 将 config.yaml 打包到 exe 根目录
    ],
    # 隐藏导入（PyInstaller 无法自动检测到的模块）
    hiddenimports=[
        'pyvisa',
        'PyQt6',
        'PyQt6.QtWidgets',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'pandas',
        'openpyxl',
        'yaml',
        'matplotlib',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    # 使用目录模式（非单文件），启动更快
    exclude_binaries=True,
    name='CMW500_BLE_Test',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    # Windows 控制台设置：False = 纯 GUI 无控制台窗口
    console=False,
    # 禁用控制台
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
