"""
探测 CMW500 蓝牙 RX PER 相关 SCPI 命令的辅助脚本

运行前请修改下面的 INSTR_ADDRESS 为你的仪器地址。
脚本会尝试多种命令前缀，输出哪些命令能正常返回，帮助定位正确的 SCPI 语法。
"""

import pyvisa

# ===================== 修改这里 =====================
# INSTR_ADDRESS = "TCPIP0::192.168.1.100::inst0::INSTR"
INSTR_ADDRESS = "GPIB0::20::INSTR"
# ===================================================

# 可能的应用选择命令（用于激活蓝牙测量）
ACTIVATION_COMMANDS = [
    "INST:SEL BLU",
    "INST:SEL BLUetooth",
    "CONF:BASE:FDC:MEAS:APPL BLU",
    "CONF:BASE:FDC:MEAS:APPL BLUetooth",
    "ROUT:BLU:SIGN:SCEN:CSL \"Network1\"",
]

# 需要探测的命令前缀
COMMAND_PREFIXES = [
    "BT",
    "BLU",
    "BLUE",
    "BLUetooth",
]

# 需要探测的 RX 相关命令模板
COMMAND_TEMPLATES = [
    "CONF:{prefix}:RX:MEAS:SEL?",
    "CONF:{prefix}:RX:PHY?",
    "CONF:{prefix}:RX:PACK:TYPE?",
    "CONF:{prefix}:RX:FREQ:CHAN?",
    "SOUR:{prefix}:RX:POW:LEV?",
    "CONF:{prefix}:RX:PACK:COUNt?",
    "FETC:{prefix}:RX:PER?",
    "FETC:{prefix}:RX:PACK:ERR?",
]


def query_with_timeout(inst, cmd, timeout_ms=5000):
    """发送查询命令，超时返回错误信息"""
    original_timeout = inst.timeout
    inst.timeout = timeout_ms
    try:
        resp = inst.query(cmd).strip()
        return True, resp
    except Exception as e:
        return False, str(e)
    finally:
        inst.timeout = original_timeout


def main():
    rm = pyvisa.ResourceManager()
    print(f"正在连接: {INSTR_ADDRESS}")

    try:
        inst = rm.open_resource(INSTR_ADDRESS)
    except Exception as e:
        print(f"连接失败: {e}")
        return

    inst.timeout = 10000

    # 读取 IDN
    ok, idn = query_with_timeout(inst, "*IDN?")
    print(f"\n*IDN?: {idn if ok else idn}")

    # 清空错误队列
    inst.query("*CLS")

    print("\n=== 尝试激活蓝牙应用 ===")
    for cmd in ACTIVATION_COMMANDS:
        ok, resp = query_with_timeout(inst, cmd, 3000)
        status = "OK" if ok else f"FAIL ({resp})"
        print(f"{cmd}: {status}")
        if ok:
            break

    print("\n=== 探测 RX PER 相关命令 ===")
    found_any = False
    for prefix in COMMAND_PREFIXES:
        print(f"\n-- 前缀: {prefix} --")
        for tmpl in COMMAND_TEMPLATES:
            cmd = tmpl.format(prefix=prefix)
            ok, resp = query_with_timeout(inst, cmd, 3000)
            if ok:
                found_any = True
                print(f"  {cmd}: {resp}")
            else:
                print(f"  {cmd}: FAIL")

    if not found_any:
        print("\n未找到可用的蓝牙 RX 命令。请确认：")
        print("1. 前面板已经手动进入 BLE RX 测试界面")
        print("2. 仪器固件支持通过 SCPI 控制蓝牙测试")
        print("3. 尝试用 CMWrun 抓取手动操作对应的 SCPI 命令")


if __name__ == "__main__":
    main()
