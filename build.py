#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CMW500 BLE 测试工具 - 一键打包脚本
用法：
    python build.py
功能：
    1. 自动检测 Python
    2. 安装/检查依赖
    3. 语法检查
    4. 清理旧构建目录
    5. 调用 PyInstaller 打包
    6. 复制最新 config.yaml 到输出目录
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
DIST_DIR = PROJECT_ROOT / "dist"
BUILD_DIR = PROJECT_ROOT / "build"
OUTPUT_EXE = DIST_DIR / "CMW500_BLE_Test" / "CMW500_BLE_Test.exe"
SPEC_FILE = PROJECT_ROOT / "build_exe.spec"


def run(cmd, **kwargs):
    """运行命令并实时输出。"""
    print(f"\n[RUN] {' '.join(str(c) for c in cmd)}")
    result = subprocess.run(cmd, **kwargs)
    return result.returncode


def find_python():
    """尝试找到可用的 Python 解释器。"""
    for cmd in ["python", "py", "python3"]:
        python_path = shutil.which(cmd)
        if python_path:
            return python_path
    # Windows 常见安装路径兜底
    for ver in ["312", "311", "310", "39"]:
        for base in [
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Python",
            Path("C:")
        ]:
            candidate = base / f"Python{ver}" / "python.exe"
            if candidate.exists():
                return str(candidate)
    return None


def ensure_pyinstaller(python):
    """确保 PyInstaller 已安装。"""
    print("\n[Step 0/4] Checking PyInstaller...")
    ret = run([python, "-c", "import PyInstaller"], cwd=PROJECT_ROOT)
    if ret != 0:
        print("[INFO] PyInstaller not found, installing...")
        ret = run([python, "-m", "pip", "install", "pyinstaller"], cwd=PROJECT_ROOT)
        if ret != 0:
            print("[ERROR] Failed to install PyInstaller")
            sys.exit(1)
    print("[OK] PyInstaller is ready.")


def install_dependencies(python):
    """安装 requirements.txt 中的依赖。"""
    print("\n[Step 1/4] Installing dependencies...")
    req_file = PROJECT_ROOT / "requirements.txt"
    if not req_file.exists():
        print(f"[WARN] {req_file} not found, skipping dependency install.")
        return
    ret = run([python, "-m", "pip", "install", "-r", str(req_file)], cwd=PROJECT_ROOT)
    if ret != 0:
        print("[ERROR] Failed to install dependencies")
        sys.exit(1)
    print("[OK] Dependencies installed.")


def syntax_check(python):
    """对所有核心 .py 文件做语法检查。"""
    print("\n[Step 2/4] Syntax check...")
    files = [
        "main.py",
        "gui_main.py",
        "test_executor.py",
        "data_exporter.py",
        "instrument_connection.py",
    ]
    cmd = [python, "-m", "py_compile"] + [str(PROJECT_ROOT / f) for f in files]
    ret = run(cmd, cwd=PROJECT_ROOT)
    if ret != 0:
        print("[ERROR] Syntax check failed, please fix the errors above.")
        sys.exit(1)
    print("[OK] Syntax check passed.")


def clean_old_build():
    """清理旧的 build/dist 目录。"""
    print("\n[Step 3/4] Cleaning old build directories...")
    for d in [BUILD_DIR, DIST_DIR]:
        if d.exists():
            print(f"  Removing {d} ...")
            shutil.rmtree(d, ignore_errors=True)
    print("[OK] Cleaned.")


def build_exe(python):
    """调用 PyInstaller 打包。"""
    print("\n[Step 4/4] Building exe...")
    if not SPEC_FILE.exists():
        print(f"[ERROR] Spec file not found: {SPEC_FILE}")
        sys.exit(1)
    ret = run(
        [python, "-m", "PyInstaller", str(SPEC_FILE), "--noconfirm", "--clean"],
        cwd=PROJECT_ROOT,
    )
    if ret != 0:
        print("[ERROR] Build failed")
        sys.exit(1)
    print("[OK] Build finished.")


def copy_config():
    """将最新 config.yaml 复制到输出目录。"""
    src = PROJECT_ROOT / "config.yaml"
    dst = DIST_DIR / "CMW500_BLE_Test" / "config.yaml"
    if src.exists():
        print(f"\n[INFO] Copying latest config.yaml to output...")
        shutil.copy2(src, dst)
        print("[OK] Config copied.")


def verify_output():
    """验证 exe 是否生成。"""
    if not OUTPUT_EXE.exists():
        print(f"\n[ERROR] Output exe not found: {OUTPUT_EXE}")
        sys.exit(1)
    print(f"\n[OK] Output exe verified: {OUTPUT_EXE}")


def open_output_dir():
    """在资源管理器中打开输出目录。"""
    output_dir = OUTPUT_EXE.parent
    if sys.platform == "win32" and output_dir.exists():
        subprocess.Popen(["explorer", str(output_dir)])


def main():
    print("=" * 50)
    print("  CMW500 BLE Test Tool - Build EXE")
    print("=" * 50)

    python = find_python()
    if not python:
        print("[ERROR] Python not found! Please install Python and add it to PATH.")
        sys.exit(1)
    print(f"\n[INFO] Python: {python}")
    subprocess.run([python, "--version"], cwd=PROJECT_ROOT)

    ensure_pyinstaller(python)
    install_dependencies(python)
    syntax_check(python)
    clean_old_build()
    build_exe(python)
    verify_output()
    copy_config()

    print("\n" + "=" * 50)
    print("  Build complete!")
    print(f"  EXE: {OUTPUT_EXE}")
    print("=" * 50)

    open_output_dir()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[ABORT] Build cancelled by user.")
        sys.exit(1)
