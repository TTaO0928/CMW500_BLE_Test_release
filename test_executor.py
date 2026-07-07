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

import time
from datetime import datetime


# ============================================================
# 调制测量项定义：key → (SCPI查询命令, 默认名称, 单位)
# BV-06-C: 载波频率偏移和漂移
# BV-05-C: 调制特性
# ============================================================
MODULATION_ITEMS = {
    # BV-06-C
    "frequency_accuracy":      ("FETC:BT:TX:FACC? AVER",      "频率准确度",        "kHz"),
    "frequency_drift":         ("FETC:BT:TX:FDR? AVER",       "频率漂移",          "kHz"),
    "frequency_offset":        ("FETC:BT:TX:FOFF? AVER",      "频率偏移",          "kHz"),
    "initial_frequency_drift": ("FETC:BT:TX:FDR:INIT? AVER",  "初始频率漂移",      "kHz"),
    "max_drift_rate":           ("FETC:BT:TX:FDR:RATE? AVER",  "最大漂移速率",      "kHz"),
    # BV-05-C
    "df1_avg":                  ("FETC:BT:TX:DF1:AVER? AVER",  "频率偏差 df1 avg",   "kHz"),
    "df2_99pct":                ("FETC:BT:TX:DF2:P999? AVER",  "频率偏差 df2 99.9%", "kHz"),
    "df2_df1_ratio":            ("FETC:BT:TX:DF2:RAT? AVER",   "df2/df1 比例",          ""),
}

# ============================================================
# 功率测量项定义：key → (SCPI查询命令, 默认名称, 单位)
# BV-01-C: 输出功率
# ============================================================
POWER_ITEMS = {
    "average_power":  ("FETC:BT:TX:POW:AVER? AVER",  "平均功率",   "dBm"),
    "peak_power":     ("FETC:BT:TX:POW:PAVE? AVER",   "峰均功率差", "dBm"),  # Peak - Avg
    "leakage_power":  ("FETC:BT:TX:POW:LEAK? AVER",  "泄漏功率",   "dBm"),
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
