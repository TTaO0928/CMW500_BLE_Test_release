---
kind: build_system
name: PyInstaller 桌面应用打包构建系统
category: build_system
scope:
    - '**'
source_files:
    - build.bat
    - build_exe.py
    - CMW500_BLE_Test.spec
    - build_exe.spec
    - requirements.txt
---

本项目采用基于 PyInstaller 的 Windows 桌面应用打包方案，将 PyQt6 GUI + PyVISA 仪器控制程序打包为独立可执行文件，无需目标机器安装 Python 环境。

## 构建工具与流程
- 打包工具：PyInstaller（requirements.txt 中声明）
- 入口文件：main.py（GUI 主程序）
- 输出产物：dist/CMW500_BLE_Test/ 目录下的单文件夹发布包（非单文件模式），包含 CMW500_BLE_Test.exe 及所有依赖资源
- 压缩策略：启用 UPX 压缩以减小体积

## 核心构建文件
- build.bat — 一键构建脚本，自动检测 Python 环境、安装依赖、清理旧构建、调用 PyInstaller 并打开输出目录
- build_exe.py — 使用 PyInstaller API 编程式定义打包配置（Analysis/EXE/COLLECT 三段式）
- CMW500_BLE_Test.spec / build_exe.spec — PyInstaller 标准 spec 配置文件，提供命令行方式构建的等价配置
- requirements.txt — 项目运行时依赖清单

## 关键构建约定
1. Python 环境探测：build.bat 按优先级尝试 python → py → python3 → 固定路径（Python 3.9~3.12），未找到则提示安装
2. 依赖安装：构建前通过 pip install -r requirements.txt 自动安装依赖
3. 数据文件打包：config.yaml 通过 --add-data / datas=[('config.yaml', '.')] 注入到 exe 同级目录，支持运行时修改
4. 隐藏导入：显式声明 pyvisa_py 及其子协议模块（usb/tcpip/gpib/serial）、usb.core、serial.tools 等动态加载模块
5. 构建模式：目录模式（exclude_binaries=True）+ UPX 压缩，而非单文件模式，以获得更快的启动速度
6. 控制台窗口：GUI 应用设置 console=False，无控制台弹窗；辅助构建脚本保留 console=True

## 构建产物结构
dist/CMW500_BLE_Test/
├── CMW500_BLE_Test.exe          # 主程序
├── config.yaml                  # 配置文件（运行时可编辑）
└── _internal/                   # PyInstaller 打包的依赖库

## 开发者注意事项
- 修改依赖后需重新运行 build.bat 完整构建
- 新增动态导入的第三方库需在 hiddenimports 或 --hidden-import 参数中补充
- 新增随包发布的静态资源需同步更新 datas 列表
- 当前仅支持 Windows 平台打包，无跨平台构建配置