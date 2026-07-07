"""
CMW500 自动化测试工具 - 测试执行模块

功能说明：
    实现蓝牙 BLE LE 1Msps 全信道（Channel 0~39）测试，支持：
    ── TX 调制测试（BV-06-C 载波频率偏移和漂移）
         - 频率准确度 (Frequency Accuracy)          ±150 kHz
         - 频率漂移   (Frequency Drift)              ±50 kHz
         - 频率偏移   (Frequency Offset)             ±150 kHz
         - 初始频率漂移 (Initial Frequency Drift)    ±23 kHz
         - 最大漂移速率 (Max Drift Rate per 50µs)   ±20 kHz
    ── TX 调制测试（BV-05-C 调制特性）
         - 频率偏差 df1 avg                         225~275 kHz
         - 频率偏差 df2 99.9%                        ≥185 kHz
         - df2/df1 比例                                ≥0.80
    ── TX 功率测试（BV-01-C 输出功率）
         - 平均功率 (Average Power)                 -20 ~ +10 dBm
         - 峰均功率差 (Peak-Average Power)          ≤4 dBm
         - 泄漏功率 (Leakage Power)                 无限值（仅记录）

    测试套件和各测量项均可通过 enabled_suites / enabled_items 控制。

SCPI 指令说明：
    使用 CMW500 蓝牙信令 TX 测量接口。
    具体指令可根据仪器固件版本调整。
"""

import random
import time
from datetime import datetime

import pyvisa


# ============================================================
# 调制测量项定义：key → (SCPI查询命令, 默认名称, 单位)
# BV-06-C: 载波频率偏移和漂移
# BV-05-C: 调制特性
# ============================================================
MODULATION_ITEMS = {
    # BV-06-C
    "frequency_accuracy":      ("FETC:BT:TX:FACC? AVER",      "Frequency Accuracy",        "kHz"),
    "frequency_drift":         ("FETC:BT:TX:FDR? AVER",       "Frequency Drift",          "kHz"),
    "frequency_offset":        ("FETC:BT:TX:FOFF? AVER",      "Frequency Offset",          "kHz"),
    "initial_frequency_drift": ("FETC:BT:TX:FDR:INIT? AVER",  "Initial Frequency Drift",      "kHz"),
    "max_drift_rate":           ("FETC:BT:TX:FDR:RATE? AVER",  "Max Drift Rate",      "kHz"),
    # BV-05-C
    "df1_avg":                  ("FETC:BT:TX:DF1:AVER? AVER",  "Frequency Deviation df1 avg",   "kHz"),
    "df2_99pct":                ("FETC:BT:TX:DF2:P999? AVER",  "Frequency Deviation df2 99.9%", "kHz"),
    "df2_df1_ratio":            ("FETC:BT:TX:DF2:RAT? AVER",   "df2/df1 Ratio",          ""),
}

# ============================================================
# 功率测量项定义：key → (SCPI查询命令, 默认名称, 单位)
# BV-01-C: 输出功率
# ============================================================
POWER_ITEMS = {
    "average_power":  ("FETC:BT:TX:POW:AVER? AVER",  "Average Power",   "dBm"),
    "peak_power":     ("FETC:BT:TX:POW:PEAK? AVER",   "Peak Power", "dBm"),  # Peak Power
    "leakage_power":  ("FETC:BT:TX:POW:LEAK? AVER",  "Leakage Power",   "dBm"),
}


class BLETxModulationTest:
    """BLE TX 全项目测试执行类（调制 + 功率，全信道）"""

    def __init__(self, cmw500, config, enabled_suites=None, enabled_items=None):
        """
        初始化测试执行器

        参数:
            cmw500:         CMW500Connection 实例（已建立连接）
            config:         从 config.yaml 加载的配置字典
            enabled_suites: 启用的测试套件列表，如 ['tx_modulation', 'tx_power']
                            为 None 时从 config 读取 enabled 字段
            enabled_items:  启用的具体测量项 key 集合（set），
                            为 None 时从 config 各 measurements 的 enabled 字段读取
        """
        self.cmw500 = cmw500
        self.test_params = config["test_params"]
        self.channel_start = self.test_params["channel_start"]
        self.channel_end   = self.test_params["channel_end"]
        self.statistic_count = self.test_params["statistic_count"]

        # ---- 确定启用的测试套件 ----
        suite_cfg = self.test_params.get("test_suites", {})
        if enabled_suites is not None:
            self.enabled_suites = set(enabled_suites)
        else:
            self.enabled_suites = {
                k for k, v in suite_cfg.items() if v.get("enabled", True)
            }

        # ---- 确定启用的调制测量项 ----
        mod_cfg = self.test_params.get("modulation_measurements", {})
        pow_cfg = self.test_params.get("power_measurements", {})
        if enabled_items is not None:
            self.enabled_mod_items  = set(enabled_items) & set(MODULATION_ITEMS)
            self.enabled_pow_items  = set(enabled_items) & set(POWER_ITEMS)
        else:
            self.enabled_mod_items = {
                k for k in MODULATION_ITEMS
                if mod_cfg.get(k, {}).get("enabled", True)
            }
            self.enabled_pow_items = {
                k for k in POWER_ITEMS
                if pow_cfg.get(k, {}).get("enabled", True)
            }

        # ---- 判定限值配置（调制 + 功率合并） ----
        self.limits = {}
        for k, v in mod_cfg.items():
            self.limits[k] = v
        for k, v in pow_cfg.items():
            self.limits[k] = v
        # 兼容旧 measurements 字段
        for k, v in self.test_params.get("measurements", {}).items():
            if k not in self.limits:
                self.limits[k] = v

        # 测试运行状态
        self.is_running = False
        self.is_stopped = False
        self.results = []

        # 回调函数
        self.log_callback      = None
        self.progress_callback = None
        self.result_callback   = None

    def set_callbacks(self, log_cb=None, progress_cb=None, result_cb=None):
        """设置回调函数（供 GUI 调用）"""
        if log_cb:      self.log_callback      = log_cb
        if progress_cb: self.progress_callback = progress_cb
        if result_cb:   self.result_callback   = result_cb

    def _log(self, message):
        """内部日志输出，同时触发回调"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_msg = f"[{timestamp}] {message}"
        print(log_msg)
        if self.log_callback:
            self.log_callback(log_msg)

    # ============================================================
    #               仪器配置（根据套件切换测量模式）
    # ============================================================

    def configure_instrument_modulation(self):
        """配置 CMW500 为 TX 调制测量模式"""
        self._log("配置 CMW500 → TX 调制测量模式...")
        self.cmw500.send_command("*RST")
        time.sleep(1)
        self.cmw500.send_command("CONF:BT:TX:MEAS:SEL TXMod")
        self.cmw500.send_command("CONF:BT:TX:BURSt:TYPE LEN")
        self.cmw500.send_command("CONF:BT:TX:PHY LE1M")
        self.cmw500.send_command(f"CONF:BT:TX:SCOUNt {self.statistic_count}")
        self.cmw500.send_command("CONF:BT:TX:PACK:TYPE RFP1")
        self._log("TX 调制测量模式配置完成")

    def configure_instrument_power(self):
        """配置 CMW500 为 TX 功率测量模式"""
        self._log("配置 CMW500 → TX 功率测量模式...")
        self.cmw500.send_command("*RST")
        time.sleep(1)
        self.cmw500.send_command("CONF:BT:TX:MEAS:SEL TXPow")
        self.cmw500.send_command("CONF:BT:TX:BURSt:TYPE LEN")
        self.cmw500.send_command("CONF:BT:TX:PHY LE1M")
        self.cmw500.send_command(f"CONF:BT:TX:SCOUNt {self.statistic_count}")
        self.cmw500.send_command("CONF:BT:TX:PACK:TYPE RFP1")
        self._log("TX 功率测量模式配置完成")

    # ============================================================
    #               单信道测量
    # ============================================================

    def _measure_channel_items(self, channel, items_dict, enabled_keys):
        """
        通用单信道测量方法

        参数:
            channel:      信道号
            items_dict:   MODULATION_ITEMS 或 POWER_ITEMS
            enabled_keys: 本次启用的 key 集合

        返回:
            dict: {key: float | None}
        """
        result = {}
        self.cmw500.send_command(f"CONF:BT:TX:FREQ:CHAN {channel}")
        self.cmw500.send_command("INIT:IMM")
        self.cmw500.query("*OPC?")

        for key in enabled_keys:
            scpi_cmd, _, _ = items_dict[key]
            try:
                value = float(self.cmw500.query(scpi_cmd))
                result[key] = round(value, 3)
            except Exception:
                result[key] = None
        return result

    def _judge_pass_fail(self, measurements):
        """对各测量项进行 PASS/FAIL 判定
    
        判定规则：
          - 如有上限和下限：直接比较原始値（频率类不再取绝对値，限制本身已包含正负号）
          - 如只有上限：比较原始値 ≤ upper_limit
          - 如只有下限：比较原始値 ≥ lower_limit
          - 无限値：标记 NO_LIMIT（仅记录，不判PASS/FAIL）
        """
        pass_fail = {}
        for key, value in measurements.items():
            if value is None:
                pass_fail[key] = "ERROR"
                continue
            limit = self.limits.get(key, {})
            upper = limit.get("upper_limit")
            lower = limit.get("lower_limit")
    
            # 无任何限値：仅记录
            if upper is None and lower is None:
                pass_fail[key] = "--"
                continue
    
            # 直接用原始値判定（限制本身已包含正负）
            fail = False
            if upper is not None and value > upper:
                fail = True
            if lower is not None and value < lower:
                fail = True
            pass_fail[key] = "FAIL" if fail else "PASS"
        return pass_fail

    # ============================================================
    #               主执行流程
    # ============================================================

    def run(self):
        """
        执行完整测试流程：
          1. 若启用 TX 调制测试 → 遍历全信道执行调制测量
          2. 若启用 TX 功率测试 → 遍历全信道执行功率测量
          两次扫描结果按信道合并后返回
        """
        self.is_running = True
        self.is_stopped = False
        self.results = []

        channels = list(range(self.channel_start, self.channel_end + 1))
        total_channels = len(channels)

        do_mod = "tx_modulation" in self.enabled_suites and len(self.enabled_mod_items) > 0
        do_pow = "tx_power"      in self.enabled_suites and len(self.enabled_pow_items) > 0

        suites_info = []
        if do_mod: suites_info.append("TX调制")
        if do_pow: suites_info.append("TX功率")
        self._log(f"开始 BLE TX 全信道测试，套件：{'/'.join(suites_info) or '无'}，"
                  f"信道：{self.channel_start}~{self.channel_end}")

        # 每信道结果暂存 {channel: dict}
        channel_results = {ch: {
            "channel":   ch,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        } for ch in channels}

        # ---- 阶段1：TX 调制测量 ----
        if do_mod and not self.is_stopped:
            self.configure_instrument_modulation()
            self._log(f"TX 调制测量项：{', '.join(self.enabled_mod_items)}")
            for idx, ch in enumerate(channels):
                if self.is_stopped:
                    self._log("测试已被用户停止")
                    break
                self._log(f"[调制] Channel {ch} ...")
                try:
                    data = self._measure_channel_items(ch, MODULATION_ITEMS, self.enabled_mod_items)
                    channel_results[ch].update(data)
                except Exception as e:
                    self._log(f"[调制] Channel {ch} 失败：{e}")
                    channel_results[ch]["error_mod"] = str(e)
                # 进度：调制阶段占前半（do_pow 时）或全程
                step = idx + 1
                total_steps = total_channels * (2 if do_pow else 1)
                if self.progress_callback:
                    self.progress_callback(step, total_steps)

        # ---- 阶段2：TX 功率测量 ----
        if do_pow and not self.is_stopped:
            self.configure_instrument_power()
            self._log(f"TX 功率测量项：{', '.join(self.enabled_pow_items)}")
            offset = total_channels if do_mod else 0
            total_steps = total_channels * (2 if do_mod else 1)
            for idx, ch in enumerate(channels):
                if self.is_stopped:
                    self._log("测试已被用户停止")
                    break
                self._log(f"[功率] Channel {ch} ...")
                try:
                    data = self._measure_channel_items(ch, POWER_ITEMS, self.enabled_pow_items)
                    channel_results[ch].update(data)
                except Exception as e:
                    self._log(f"[功率] Channel {ch} 失败：{e}")
                    channel_results[ch]["error_pow"] = str(e)
                if self.progress_callback:
                    self.progress_callback(offset + idx + 1, total_steps)

        # ---- 汇总结果 ----
        all_keys = set()
        if do_mod: all_keys |= self.enabled_mod_items
        if do_pow: all_keys |= self.enabled_pow_items

        for ch in channels:
            r = channel_results[ch]
            measurements = {k: r.get(k) for k in all_keys}
            r["pass_fail"] = self._judge_pass_fail(measurements)

            # 简要日志
            pf = r["pass_fail"]
            pass_cnt = sum(1 for v in pf.values() if v == "PASS")
            self._log(f"Channel {ch}: {pass_cnt}/{len(pf)} 项通过")

            self.results.append(r)
            if self.result_callback:
                self.result_callback(ch, r)

        self.is_running = False
        if not self.is_stopped:
            self._log(f"测试完成，共 {len(self.results)} 个信道")

        return self.results

    def stop(self):
        """停止正在执行的测试"""
        if self.is_running:
            self.is_stopped = True
            self._log("正在停止测试...")

    def get_results(self):
        """获取测试结果列表"""
        return self.results

    @staticmethod
    def get_all_modulation_keys():
        """返回所有调制测量项 key 列表"""
        return list(MODULATION_ITEMS.keys())

    @staticmethod
    def get_all_power_keys():
        """返回所有功率测量项 key 列表"""
        return list(POWER_ITEMS.keys())


class BLERxPerTest:
    """
    BLE RX PER 接收灵敏度搜索测试执行类（CMW500 BLE Signaling Loopback 模式）

    说明：
      - 该测试基于 CMWrun 抓取的 BLE Signaling Loopback 流程。
      - CMW500 与 DUT 建立 BLE 连接，DUT 进入 Loopback 回传数据。
      - CMW500 自己统计 PER，程序按阶梯降功率找到灵敏度点。
    """

    def __init__(self, cmw500, config):
        """
        初始化 RX PER 测试执行器

        参数:
            cmw500: CMW500Connection 实例（已建立连接）
            config: 从 config.yaml 加载的配置字典
        """
        self.cmw500 = cmw500
        self.config = config
        self.test_params = config["test_params"]
        self.rx_cfg = self.test_params.get("rx_per", {})
        self.dut_cfg = config.get("dut_connection", {})

        self.channel_start = self.test_params["channel_start"]
        self.channel_end   = self.test_params["channel_end"]

        # 测试运行状态
        self.is_running = False
        self.is_stopped = False
        self.results = []

        # 回调函数
        self.log_callback      = None
        self.progress_callback = None
        self.result_callback   = None

    def set_callbacks(self, log_cb=None, progress_cb=None, result_cb=None):
        """设置回调函数（供 GUI 调用）"""
        if log_cb:      self.log_callback      = log_cb
        if progress_cb: self.progress_callback = progress_cb
        if result_cb:   self.result_callback   = result_cb

    def _log(self, message):
        """内部日志输出，同时触发回调"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_msg = f"[{timestamp}] {message}"
        print(log_msg)
        if self.log_callback:
            self.log_callback(log_msg)

    # ============================================================
    #               通用辅助方法
    # ============================================================

    @staticmethod
    def channel_to_freq_hz(channel):
        """BLE 信道号转频率（Hz），Channel 0 = 2402 MHz"""
        return int((2402 + 2 * channel) * 1e6)

    def _wait_for_state(self, query_cmd, target_values, timeout_ms=30000, interval_ms=500):
        """
        循环查询仪器状态，直到返回目标值之一

        参数:
            query_cmd:    查询命令
            target_values: 目标状态值列表（字符串）
            timeout_ms:   总超时（毫秒）
            interval_ms:  每次查询间隔（毫秒）

        返回:
            str: 最终状态值，或 None 超时
        """
        target_set = {v.upper() for v in target_values}
        elapsed = 0
        while elapsed < timeout_ms and not self.is_stopped:
            try:
                state = self.cmw500.query(query_cmd).strip().upper()
                if state in target_set:
                    return state
            except pyvisa.VisaIOError:
                pass
            time.sleep(interval_ms / 1000.0)
            elapsed += interval_ms
        return None

    # ============================================================
    #               仪器初始化与连接
    # ============================================================

    def configure_instrument_rx(self):
        """配置 CMW500 为 BLE Signaling Loopback 模式"""
        self._log("配置 CMW500 → BLE Signaling Loopback 模式...")

        # 复位
        self.cmw500.send_command("SYST:RES:ALL; *OPC?")
        time.sleep(1)

        # 路由配置
        self.cmw500.send_command('ROUT:BLU:MEAS:SCEN:CSPath "Bluetooth SIG1"')
        self.cmw500.send_command("ROUT:BLU:SIGN:SCEN:OTRX RF1C,RX1,RF1C,TX1")
        self.cmw500.send_command("SYST:BASE:REF:FREQ:SOUR INT")

        # 打开蓝牙信令
        self.cmw500.send_command("CONF:BLU:SIGN:RFSettings:EATT:OUTP 0")
        self.cmw500.send_command("CONF:BLU:SIGN:RFSettings:EATT:INP 1")
        self.cmw500.send_command("CONF:BLU:SIGN:RFSettings:LEVel 0")
        self.cmw500.send_command("CONF:BLU:SIGN:RFSettings:ENPower 10")
        self.cmw500.send_command("CONF:BLU:SIGN:RFSettings:ARANging ON")

        self.cmw500.send_command("SOUR:BLU:SIGN:STATe ON")
        state = self._wait_for_state("SOUR:BLU:SIGN:STATe?", ["ON"], timeout_ms=30000)
        if state != "ON":
            raise RuntimeError("蓝牙信令模块未能正常启动")

        # 连接参数
        phy = self.rx_cfg.get("phy_type", "LE1M")
        pkt_type = self.rx_cfg.get("packet_type", "PRBS9")
        payload_len = self.rx_cfg.get("payload_length", 37)

        self.cmw500.send_command("CONF:BLU:SIGN:CONN:BTYP LE")
        self.cmw500.send_command(f"CONF:BLU:SIGN:CONN:PHY:LEN {phy}")
        self.cmw500.send_command("CONF:BLU:SIGN:RFSettings:CHAN:DTMode 0")
        self.cmw500.send_command(f"CONF:BLU:SIGN:CONN:PACK:PLEN:LEN:LE1M {payload_len}")
        self.cmw500.send_command(f'CONF:BLU:SIGN:CONN:PACK:PATT:LEN:LE1M {pkt_type}')

        # DUT 通信接口（从 dut_connection 配置读取）
        hw_if = self.dut_cfg.get("hw_interface", "RS232")
        protocol = self.dut_cfg.get("comm_protocol", "HCI")
        self.cmw500.send_command(f"CONF:BLU:SIGN:HWINterface {hw_if}")
        self.cmw500.send_command("CONF:BLU:SIGN:LEN:RESet:DELay 0")
        self.cmw500.send_command(f"CONF:BLU:SIGN:CPRotocol {protocol}")

        if hw_if == "RS232":
            rs232 = self.dut_cfg.get("rs232", {})
            self.cmw500.send_command("CONF:BLU:SIGN:COMSettings:PORTs:CATalog?")
            self.cmw500.send_command(f"CONF:BLU:SIGN:COMSettings:COMPort 0")
            baud = rs232.get("baud_rate", 115200)
            baud_map = {9600: "B9K6", 19200: "B19K", 38400: "B38K4",
                        57600: "B57K6", 115200: "B115K"}
            self.cmw500.send_command(f'CONF:BLU:SIGN:COMSettings:BAUDrate {baud_map.get(baud, "B115K")}')
            self.cmw500.send_command("CONF:BLU:SIGN:COMSettings:STOPbits S1")
            self.cmw500.send_command("CONF:BLU:SIGN:COMSettings:PARity NONE")
            self.cmw500.send_command("CONF:BLU:SIGN:COMSettings:PROTocol NONE")
            self.cmw500.send_command("CONF:BLU:SIGN:COMSettings:ERESet ON")

        self._log("BLE Signaling Loopback 模式配置完成")

    def ensure_connection(self):
        """确保 CMW500 与 DUT 建立 BLE 连接"""
        self._log("检查 BLE 连接状态...")
        state = self.cmw500.query("CALL:BLU:SIGN:CONN:CHECk:LEN?").strip()
        if state.upper() != "PASS":
            raise RuntimeError(f"BLE 连接检查失败：{state}，请确认 DUT 已上电并进入测试模式")
        self._log("BLE 连接正常")

    # ============================================================
    #               RX Quality 配置与测量
    # ============================================================

    def configure_rx_quality(self):
        """配置 RX Quality 测试参数"""
        phy = self.rx_cfg.get("phy_type", "LE1M")
        threshold = self.rx_cfg.get("per_threshold", 30.8)
        packet_count = self.rx_cfg.get("packet_count", 1500)
        timeout_s = self.rx_cfg.get("measurement_timeout", 20)

        self.cmw500.send_command(f"CONF:BLU:SIGN:RXQuality:LIMit:MPER:LEN:{phy} {threshold}")
        self.cmw500.send_command(f"CONF:BLU:SIGN:RXQuality:RINTegrity:LEN:{phy} OFF")
        self.cmw500.send_command(f"CONF:BLU:SIGN:RXQuality:PACK:LEN:{phy} {packet_count}")

        # 关闭 Dirty Transmitter 相关设置
        self.cmw500.send_command(f"CONF:BLU:SIGN:RFSettings:DTX:SING:MINDex:LEN:{phy} OFF")
        self.cmw500.send_command(f"CONF:BLU:SIGN:RFSettings:DTX:SING:FOFFset:LEN:{phy} OFF")
        self.cmw500.send_command(f"CONF:BLU:SIGN:RFSettings:DTX:SING:STERror:LEN:{phy} OFF")
        self.cmw500.send_command(f"CONF:BLU:SIGN:RFSettings:DTX:SING:FDRift:LEN:{phy} OFF")
        self.cmw500.send_command("CONF:BLU:SIGN:RFSettings:DTX OFF")

        self.cmw500.send_command(f"CONF:BLU:SIGN:RXQuality:TOUT {timeout_s}")

    def set_channel(self, channel):
        """设置测试信道（通过频率）"""
        freq_hz = self.channel_to_freq_hz(channel)
        self.cmw500.send_command(f"CONF:BLU:SIGN:RFSettings:FREQ:DTM {freq_hz}")
        self._log(f"[RX PER] 切换到 Channel {channel} ({freq_hz/1e6:.3f} MHz)")

    def set_power(self, power_dbm):
        """设置 CMW500 发射功率"""
        exp_pow = self.rx_cfg.get("exp_nom_pow", 10.0)
        self.cmw500.send_command(f"CONF:BLU:SIGN:RFSettings:LEVel {power_dbm:.2f}")
        self.cmw500.send_command(f"CONF:BLU:SIGN:RFSettings:ENPower {exp_pow:.2f}")

    def _measure_per_at_power(self, channel, power):
        """
        在指定信道和功率下测量 PER

        返回:
            tuple: (per, rx_count, tx_count)
        """
        # Demo 模式：生成模拟 PER 曲线，仅用于界面验证
        if self.rx_cfg.get("demo_mode", False):
            expected = self.rx_cfg.get("expected_sensitivity", -95.0)
            if power > expected + 3:
                base = 0.0
            elif power < expected - 5:
                base = 100.0
            else:
                base = ((expected + 3 - power) / 8.0) * 100.0
            per = min(100.0, max(0.0, base + random.uniform(-3, 3)))
            packet_count = self.rx_cfg.get("packet_count", 1500)
            rx_count = int(packet_count * (1 - per / 100.0))
            return round(per, 2), rx_count, packet_count

        self.set_power(power)

        # 确保测量状态为 OFF 后再启动
        self.cmw500.query("FETCH:BLU:SIGN:RXQuality:PER:STATe?")

        # 启动 RX Quality 测量
        self.cmw500.send_command("INIT:BLU:SIGN:RXQuality:PER")

        # 等待测量完成（RDY）
        state = self._wait_for_state(
            "FETC:BLU:SIGN:RXQ:PER:STAT?",
            ["RDY", "READY"],
            timeout_ms=self.rx_cfg.get("measurement_timeout", 20) * 1000,
            interval_ms=500
        )
        if state is None:
            raise RuntimeError("RX PER 测量超时，未返回 RDY 状态")

        # 读取结果
        phy = self.rx_cfg.get("phy_type", "LE1M")
        resp = self.cmw500.query(f"FETC:BLU:SIGN:RXQ:PER:LEN:{phy}?")
        parts = [p.strip() for p in resp.split(",")]

        # 返回值格式：state, PER(%), received_packets
        if len(parts) >= 3:
            per = float(parts[1])
            rx_count = int(float(parts[2]))
            packet_count = self.rx_cfg.get("packet_count", 1500)
            return per, rx_count, packet_count
        elif len(parts) >= 2:
            per = float(parts[1])
            return per, None, None
        else:
            raise RuntimeError(f"PER 结果格式异常：{resp}")

    # ============================================================
    #               单信道灵敏度搜索
    # ============================================================

    def search_channel(self, channel):
        """
        对单个信道执行阶梯降功率搜索，找到 PER 达到阈值的灵敏度点
        """
        start     = self.rx_cfg.get("start_power", -90.0)
        end       = self.rx_cfg.get("end_power", -100.0)
        step      = self.rx_cfg.get("step_size", 0.5)
        threshold = self.rx_cfg.get("per_threshold", 30.8)

        if step > 0:
            step = -step
        if start < end:
            start, end = end, start

        self.set_channel(channel)
        self.configure_rx_quality()
        self.ensure_connection()

        self._log(f"[RX PER] Ch{channel} 搜索：{start:.1f} dBm → {end:.1f} dBm，步进 {step:.1f} dBm，阈值 {threshold}%")

        current = start
        last_pass_power = None
        last_fail_power = None
        last_per = None

        while current >= end - 1e-9 and not self.is_stopped:
            per, rx_count, tx_count = self._measure_per_at_power(channel, current)
            last_per = per

            rx_info = f"，接收 {rx_count}/{tx_count}" if rx_count is not None and tx_count is not None else ""
            self._log(f"[RX PER] Ch{channel} @ {current:.1f} dBm：PER = {per:.2f}%{rx_info}")

            if per < threshold:
                last_pass_power = current
            else:
                last_fail_power = current
                break

            current += step

        sensitivity = last_pass_power

        result = {
            "channel":         channel,
            "timestamp":       datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "test_type":       "rx_per",
            "sensitivity":     sensitivity,
            "per_threshold":   threshold,
            "last_pass_power": last_pass_power,
            "last_fail_power": last_fail_power,
            "last_per":        last_per,
        }

        expected = self.rx_cfg.get("expected_sensitivity")
        if sensitivity is None:
            result["pass_fail"] = "FAIL"
        elif expected is None:
            result["pass_fail"] = "--"
        else:
            result["pass_fail"] = "PASS" if sensitivity <= expected else "FAIL"

        return result

    # ============================================================
    #               主执行流程
    # ============================================================

    def run(self):
        """
        执行完整 RX PER 全信道灵敏度搜索
        """
        self.is_running = True
        self.is_stopped = False
        self.results = []

        channels = list(range(self.channel_start, self.channel_end + 1))
        total_channels = len(channels)

        self._log(f"开始 BLE RX PER 全信道灵敏度搜索，信道：{self.channel_start}~{self.channel_end}")

        self.configure_instrument_rx()
        self.ensure_connection()

        for idx, ch in enumerate(channels):
            if self.is_stopped:
                self._log("测试已被用户停止")
                break

            result = self.search_channel(ch)
            self.results.append(result)

            sens = result.get("sensitivity")
            verdict = result.get("pass_fail", "--")
            self._log(f"[RX PER] Ch{ch} 灵敏度：{sens if sens is not None else '未找到'} dBm，判定：{verdict}")

            if self.result_callback:
                self.result_callback(ch, result)
            if self.progress_callback:
                self.progress_callback(idx + 1, total_channels)

        self.is_running = False
        if not self.is_stopped:
            self._log(f"RX PER 测试完成，共 {len(self.results)} 个信道")

        return self.results

    def stop(self):
        """停止正在执行的测试"""
        if self.is_running:
            self.is_stopped = True
            self._log("正在停止测试...")

    def get_results(self):
        """获取测试结果列表"""
        return self.results
