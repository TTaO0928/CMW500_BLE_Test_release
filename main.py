"""
CMW500 自动化测试工具 - 程序入口

功能说明：
    本程序用于控制 R&S CMW500 无线通信测试仪，
    实现蓝牙 BLE TX 调制自动化测试、数据采集与导出。

启动方式：
    python main.py          —— 启动 PyQt6 图形界面（默认）
    python main.py --cli    —— 启动命令行交互模式

作者：自动化测试团队
"""

import sys
import os
import traceback
import multiprocessing


def get_app_dir():
    """
    获取程序所在目录（兼容 PyInstaller 打包后的路径）

    正常 Python 运行时：返回 main.py 所在目录
    PyInstaller exe 运行时：返回 exe 文件所在目录

    返回:
        str: 程序根目录的绝对路径
    """
    if getattr(sys, 'frozen', False):
        # PyInstaller 打包后运行：sys.executable 是 exe 路径
        return os.path.dirname(sys.executable)
    else:
        # 正常 Python 运行：__file__ 是当前脚本路径
        return os.path.dirname(os.path.abspath(__file__))


# 程序根目录（全局常量，供其他模块使用）
APP_DIR = get_app_dir()


def show_error_dialog(title, message):
    """
    显示错误弹窗（兼容多种 GUI 方案）

    优先使用 PyQt6，失败则用 tkinter，最后写入日志文件。

    参数:
        title:   弹窗标题
        message: 错误信息
    """
    # 方案1：尝试 PyQt6 弹窗
    try:
        from PyQt6.QtWidgets import QApplication, QMessageBox
        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)
        QMessageBox.critical(None, title, message)
        return
    except Exception:
        pass

    # 方案2：尝试 tkinter 弹窗（Python 自带）
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(title, message)
        root.destroy()
        return
    except Exception:
        pass

    # 方案3：写入错误日志文件（最后手段）
    try:
        log_path = os.path.join(APP_DIR, "error_log.txt")
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(f"错误标题: {title}\n")
            f.write(f"错误信息: {message}\n")
    except Exception:
        pass


def load_config(config_path=None):
    """
    加载 YAML 配置文件

    优先从 exe 同目录加载 config.yaml，
    支持 PyInstaller 打包后运行。

    参数:
        config_path: 配置文件路径，默认为 APP_DIR/config.yaml

    返回:
        配置字典对象
    """
    import yaml

    if config_path is None:
        config_path = os.path.join(APP_DIR, "config.yaml")

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        print(f"[信息] 配置文件加载成功：{config_path}")
        return config
    except FileNotFoundError:
        raise RuntimeError(
            f"找不到配置文件：{config_path}\n"
            f"请将 config.yaml 放到与程序同一目录下"
        )
    except yaml.YAMLError as e:
        raise RuntimeError(f"配置文件解析失败：{e}")


def run_cli(config, cmw500):
    """
    命令行交互模式

    参数:
        config: 配置字典
        cmw500: CMW500Connection 实例
    """
    from test_executor import BLETxModulationTest
    from data_exporter import DataExporter

    print("=" * 50)
    print("   CMW500 BLE TX 调制自动化测试工具 [命令行模式]")
    print("=" * 50)

    # 打印测试配置摘要
    test_params = config["test_params"]
    inst = config["instrument"]
    print(f"[信息] 默认接口：{inst['interface_type']}")
    print(f"[信息]   LAN IP：{inst['lan']['ip_address']}")
    print(f"[信息]   GPIB  ：Board={inst['gpib']['board']}, Addr={inst['gpib']['address']}")
    print(f"[信息]   USB   ：VID={inst['usb']['vendor_id']}, PID={inst['usb']['product_id']}")
    print(f"[信息] 测试标准：{test_params['standard']} ({test_params['phy_type']})")
    print(f"[信息] 信道范围：Channel {test_params['channel_start']} ~ {test_params['channel_end']}")
    print(f"[信息] 统计次数：{test_params['statistic_count']}")
    print("=" * 50)

    # 创建测试执行器和导出器
    test_executor = None
    exporter = DataExporter(config)

    # 命令行交互循环
    print("\n可用命令：")
    print("  connect    - 连接仪器")
    print("  disconnect - 断开仪器")
    print("  serial     - 读取序列号")
    print("  test       - 开始测试")
    print("  stop       - 停止测试")
    print("  quit       - 退出程序")

    while True:
        cmd = input("\n请输入命令 > ").strip().lower()

        if cmd == "connect":
            success, message = cmw500.connect()
            print(f"[{'成功' if success else '失败'}] {message}")
            if success:
                test_executor = BLETxModulationTest(cmw500, config)

        elif cmd == "disconnect":
            success, message = cmw500.disconnect()
            print(f"[{'成功' if success else '提示'}] {message}")
            test_executor = None

        elif cmd == "serial":
            success, result = cmw500.get_serial_number()
            if success:
                print(f"[信息] 仪器序列号：{result}")
            else:
                print(f"[错误] {result}")

        elif cmd == "test":
            if not cmw500.connected:
                print("[错误] 请先连接仪器")
                continue
            if test_executor is None:
                test_executor = BLETxModulationTest(cmw500, config)

            print("\n--- 开始 BLE TX 调制测试 ---")
            results = test_executor.run()

            if results:
                total = len(results)
                all_pass = sum(
                    1 for r in results
                    if "pass_fail" in r and all(v == "PASS" for v in r["pass_fail"].values())
                )
                print(f"\n--- 测试摘要 ---")
                print(f"总信道数：{total}")
                print(f"全部通过：{all_pass}")
                print(f"有失败项：{total - all_pass}")

                try:
                    excel_path = exporter.export_to_excel(results, test_params)
                    print(f"[成功] 测试结果已导出至：{excel_path}")
                except Exception as e:
                    print(f"[错误] 导出 Excel 失败：{e}")

        elif cmd == "stop":
            if test_executor and test_executor.is_running:
                test_executor.stop()
                print("[信息] 已发送停止信号")
            else:
                print("[提示] 当前没有正在执行的测试")

        elif cmd == "quit":
            if cmw500.connected:
                cmw500.disconnect()
            print("[信息] 程序已退出")
            break

        else:
            print("[提示] 未知命令，请重新输入")


def run_gui(config, cmw500):
    """
    PyQt6 图形界面模式

    参数:
        config: 配置字典
        cmw500: CMW500Connection 实例
    """
    from PyQt6.QtWidgets import QApplication, QMessageBox
    from gui_main import CMW500MainWindow

    # 创建 QApplication 实例
    app = QApplication(sys.argv)
    app.setStyle("Fusion")  # 使用 Fusion 主题，跨平台一致

    # 创建并显示主窗口
    window = CMW500MainWindow(config=config, cmw500=cmw500)
    window.show()

    # 进入事件循环
    sys.exit(app.exec())


def _normalize_config(config):
    """
    配置文件兼容性处理

    自动补全缺失的字段，兼容旧版 config.yaml 格式。
    确保 instrument 下包含 lan、gpib、usb 三个子节。
    """
    inst = config.get("instrument", {})

    # 兼容旧格式：如果 instrument 下直接有 ip_address，迁移到 lan 子节
    if "lan" not in inst:
        old_ip = inst.get("ip_address", "192.168.1.100")
        inst["lan"] = {"ip_address": old_ip}

    # 确保有 ip_address 字段
    if "ip_address" not in inst.get("lan", {}):
        inst["lan"]["ip_address"] = "192.168.1.100"

    # 确保有 gpib 子节
    if "gpib" not in inst:
        inst["gpib"] = {"board": 0, "address": 20}
    if "board" not in inst["gpib"]:
        inst["gpib"]["board"] = 0
    if "address" not in inst["gpib"]:
        inst["gpib"]["address"] = 20

    # 确保有 usb 子节
    if "usb" not in inst:
        inst["usb"] = {
            "vendor_id": "0x0AAD",
            "product_id": "0x0117",
            "serial_number": "",
        }
    for key, default in [("vendor_id", "0x0AAD"), ("product_id", "0x0117"),
                          ("serial_number", "")]:
        if key not in inst["usb"]:
            inst["usb"][key] = default

    # 确保有 interface_type
    if "interface_type" not in inst:
        inst["interface_type"] = "LAN"

    # 确保有 timeout
    if "timeout" not in inst:
        inst["timeout"] = 10000

    config["instrument"] = inst

    # 兼容旧版 rf_settings：eatt_output / eatt_input → int/ext_att_output / input
    dut = config.get("dut_connection", {})
    rf = dut.get("rf_settings", {})
    if "eatt_output" in rf or "eatt_input" in rf:
        rf.setdefault("int_att_output", 0.0)
        rf.setdefault("ext_att_output", rf.pop("eatt_output", 0.0))
        rf.setdefault("int_att_input", 0.0)
        rf.setdefault("ext_att_input", rf.pop("eatt_input", 0.0))
        dut["rf_settings"] = rf
        config["dut_connection"] = dut

    return config


def main():
    """程序主入口 - 全局异常保护"""

    # 加载配置文件
    config = load_config()

    # 兼容性处理：自动补全缺失字段（防止旧 config.yaml 导致崩溃）
    config = _normalize_config(config)

    # 读取仪器连接参数
    inst_config = config["instrument"]
    interface_type = inst_config["interface_type"]
    lan_ip = inst_config["lan"]["ip_address"]
    gpib_board = inst_config["gpib"]["board"]
    gpib_address = inst_config["gpib"]["address"]
    usb_vid = inst_config["usb"]["vendor_id"]
    usb_pid = inst_config["usb"]["product_id"]
    usb_sn = inst_config["usb"]["serial_number"]
    timeout = inst_config["timeout"]

    # 延迟导入仪器连接模块（避免顶层导入失败导致闪退）
    from instrument_connection import CMW500Connection

    # 创建仪器连接实例（不立即连接，地址可在 GUI 中修改）
    cmw500 = CMW500Connection(
        interface_type=interface_type,
        lan_ip=lan_ip,
        gpib_board=gpib_board,
        gpib_address=gpib_address,
        usb_vendor_id=usb_vid,
        usb_product_id=usb_pid,
        usb_serial_number=usb_sn,
        timeout=timeout,
    )

    # 根据命令行参数选择启动模式
    if "--cli" in sys.argv:
        # 命令行模式
        run_cli(config, cmw500)
    else:
        # 默认：图形界面模式
        run_gui(config, cmw500)


if __name__ == "__main__":
    # PyInstaller 打包后使用 multiprocessing spawn 时必须调用，
    # 否则子进程会重复执行主程序导致闪退/卡死
    multiprocessing.freeze_support()
    try:
        main()
    except Exception as e:
        # 全局异常捕获：确保 exe 无控制台时不会静默闪退
        error_detail = traceback.format_exc()
        error_msg = (
            f"程序启动失败！\n\n"
            f"错误类型：{type(e).__name__}\n"
            f"错误信息：{e}\n\n"
            f"详细堆栈：\n{error_detail}\n\n"
            f"请检查：\n"
            f"1. config.yaml 是否与程序在同一目录\n"
            f"2. config.yaml 格式是否正确\n"
            f"3. 程序目录：{APP_DIR}"
        )
        show_error_dialog("CMW500 测试工具 - 启动错误", error_msg)
        sys.exit(1)
