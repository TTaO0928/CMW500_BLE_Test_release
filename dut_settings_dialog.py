"""
DUT 连接设置对话框

参考 CMWrun Connection 页面，配置被测设备与仪器之间的通信方式：
- 硬件接口（HW Interface）
- RS232 / USB 参数
- EUT 初始化选项
- 信号特性（PHY / Pattern / Payload）
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGridLayout,
    QGroupBox, QLabel, QComboBox, QSpinBox, QDoubleSpinBox,
    QCheckBox, QPushButton, QWidget, QSizePolicy, QMessageBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

import serial.tools.list_ports
import time
import pyvisa


class DUTSettingsDialog(QDialog):
    """DUT 连接设置对话框"""

    def __init__(self, config, cmw500=None, parent=None):
        super().__init__(parent)
        self.config = config
        self.cmw500 = cmw500
        self.dut_cfg = config.get("dut_connection", {})
        self._cmw_port_index_map = {}  # COM port name -> CMW index
        self._init_ui()
        self._load_settings()
        # 只扫描系统串口，不在打开时连接 CMW（避免卡顿）
        self._refresh_com_ports_local()

    def _init_ui(self):
        self.setWindowTitle("DUT 连接设置")
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        label_font = QFont("微软雅黑", 10)
        input_font = QFont("Consolas", 10)

        # ---- 顶层：硬件接口 + 通信协议 ----
        top_row = QHBoxLayout()
        top_row.setSpacing(16)

        self.combo_hw_interface = QComboBox()
        self.combo_hw_interface.setFont(input_font)
        self.combo_hw_interface.addItems(["RS232", "USB"])
        self.combo_hw_interface.currentTextChanged.connect(self._on_hw_changed)
        top_row.addWidget(QLabel("HW Interface："))
        top_row.addWidget(self.combo_hw_interface)
        top_row.addSpacing(24)

        self.combo_comm_protocol = QComboBox()
        self.combo_comm_protocol.setFont(input_font)
        self.combo_comm_protocol.addItems(["2Wire", "HCI"])
        top_row.addWidget(QLabel("EUT Comm. Protocol："))
        top_row.addWidget(self.combo_comm_protocol)
        top_row.addStretch()
        layout.addLayout(top_row)

        # ---- RS232 Configuration ----
        self.group_rs232 = QGroupBox("RS232 Configuration")
        self.group_rs232.setFont(label_font)
        rs232_layout = QFormLayout(self.group_rs232)
        rs232_layout.setSpacing(8)

        port_row = QHBoxLayout()
        port_row.setSpacing(8)
        self.combo_port = QComboBox()
        self.combo_port.setFont(input_font)
        self.combo_port.setEditable(True)
        self.combo_port.setMinimumWidth(140)
        port_row.addWidget(self.combo_port, 1)

        self.btn_auto_port = QPushButton("自动识别")
        self.btn_auto_port.setFont(label_font)
        self.btn_auto_port.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_auto_port.setStyleSheet(
            "QPushButton { background-color: #607D8B; color: white; "
            "padding: 4px 10px; border-radius: 4px; }"
            "QPushButton:hover { background-color: #455A64; }"
        )
        self.btn_auto_port.clicked.connect(self._on_auto_detect_port)
        port_row.addWidget(self.btn_auto_port)
        rs232_layout.addRow("Virtual COM Port：", port_row)

        self.combo_baud = QComboBox()
        self.combo_baud.setFont(input_font)
        self.combo_baud.setEditable(True)
        self.combo_baud.addItems(["9600", "19200", "38400", "57600", "115200"])
        rs232_layout.addRow("Baud Rate：", self.combo_baud)

        self.combo_data_bits = QComboBox()
        self.combo_data_bits.setFont(input_font)
        self.combo_data_bits.addItems(["7", "8"])
        rs232_layout.addRow("Data Bits：", self.combo_data_bits)

        self.combo_stop_bits = QComboBox()
        self.combo_stop_bits.setFont(input_font)
        self.combo_stop_bits.addItems(["1", "1.5", "2"])
        rs232_layout.addRow("Stop Bits：", self.combo_stop_bits)

        self.combo_parity = QComboBox()
        self.combo_parity.setFont(input_font)
        self.combo_parity.addItems(["None", "Even", "Odd", "Mark", "Space"])
        rs232_layout.addRow("Parity：", self.combo_parity)

        self.combo_flow = QComboBox()
        self.combo_flow.setFont(input_font)
        self.combo_flow.addItems(["None", "RTS/CTS", "XON/XOFF"])
        rs232_layout.addRow("Flow Control：", self.combo_flow)

        layout.addWidget(self.group_rs232)

        # ---- USB Configuration ----
        self.group_usb = QGroupBox("USB Configuration")
        self.group_usb.setFont(label_font)
        usb_layout = QFormLayout(self.group_usb)
        usb_layout.setSpacing(8)

        self.spin_usb_device = QSpinBox()
        self.spin_usb_device.setFont(input_font)
        self.spin_usb_device.setRange(0, 10)
        self.spin_usb_device.setValue(0)
        usb_layout.addRow("USB Device：", self.spin_usb_device)

        layout.addWidget(self.group_usb)

        # ---- EUT Initialization ----
        group_init = QGroupBox("EUT Initialization")
        group_init.setFont(label_font)
        init_layout = QHBoxLayout(group_init)
        init_layout.setSpacing(16)

        self.chk_reset_eut = QCheckBox("Reset EUT")
        self.chk_reset_eut.setFont(label_font)
        init_layout.addWidget(self.chk_reset_eut)

        self.spin_reset_delay = QDoubleSpinBox()
        self.spin_reset_delay.setFont(input_font)
        self.spin_reset_delay.setRange(0, 10)
        self.spin_reset_delay.setDecimals(1)
        self.spin_reset_delay.setSingleStep(0.1)
        self.spin_reset_delay.setSuffix(" s")
        init_layout.addWidget(QLabel("Reset Delay："))
        init_layout.addWidget(self.spin_reset_delay)
        init_layout.addStretch()

        layout.addWidget(group_init)

        # ---- Signal Characteristics ----
        group_signal = QGroupBox("Signal Characteristics")
        group_signal.setFont(label_font)
        signal_layout = QFormLayout(group_signal)
        signal_layout.setSpacing(8)

        self.combo_phy = QComboBox()
        self.combo_phy.setFont(input_font)
        self.combo_phy.addItems(["LE 1Msps", "LE 2Msps", "LE 500ksps", "LE 125ksps"])
        signal_layout.addRow("PHY Type：", self.combo_phy)

        self.combo_pattern = QComboBox()
        self.combo_pattern.setFont(input_font)
        self.combo_pattern.addItems(["PRBS9", "PRBS15", "11110000", "10101010"])
        signal_layout.addRow("Pattern Type：", self.combo_pattern)

        self.spin_payload = QSpinBox()
        self.spin_payload.setFont(input_font)
        self.spin_payload.setRange(0, 255)
        signal_layout.addRow("Payload Length (bytes)：", self.spin_payload)

        layout.addWidget(group_signal)

        # ---- RF 功率补偿 ----
        group_rf = QGroupBox("RF 功率补偿")
        group_rf.setFont(label_font)
        rf_hbox = QHBoxLayout(group_rf)
        rf_hbox.setSpacing(16)
        rf_hbox.setContentsMargins(10, 6, 10, 6)

        def _make_att_spin():
            spin = QDoubleSpinBox()
            spin.setFont(input_font)
            spin.setRange(-100, 100)
            spin.setDecimals(1)
            spin.setSuffix(" dB")
            spin.setSingleStep(0.5)
            spin.setFixedWidth(90)
            return spin

        self.spin_att_output = _make_att_spin()
        self.spin_att_input  = _make_att_spin()

        lbl_out = QLabel("RF Output："); lbl_out.setFont(label_font)
        lbl_in  = QLabel("RF Input：");  lbl_in.setFont(label_font)
        rf_hbox.addWidget(lbl_out)
        rf_hbox.addWidget(self.spin_att_output)
        rf_hbox.addSpacing(24)
        rf_hbox.addWidget(lbl_in)
        rf_hbox.addWidget(self.spin_att_input)
        rf_hbox.addStretch()

        layout.addWidget(group_rf)

        # ---- 连接测试状态 ----
        self.lbl_test_status = QLabel("点击「连接测试」验证 DUT 通信状态")
        self.lbl_test_status.setFont(QFont("微软雅黑", 10))
        self.lbl_test_status.setWordWrap(True)
        self.lbl_test_status.setStyleSheet("color: #666666;")
        layout.addWidget(self.lbl_test_status)

        # ---- 按钮 ----
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.btn_test_conn = QPushButton("连接测试")
        self.btn_test_conn.setFont(label_font)
        self.btn_test_conn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_test_conn.setStyleSheet(
            "QPushButton { background-color: #4CAF50; color: white; "
            "padding: 6px 14px; border-radius: 4px; }"
            "QPushButton:hover { background-color: #45a049; }"
        )
        self.btn_test_conn.clicked.connect(self._on_test_connection)
        btn_layout.addWidget(self.btn_test_conn)

        btn_ok = QPushButton("确定")
        btn_ok.setFont(label_font)
        btn_ok.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_ok.clicked.connect(self._on_ok)
        btn_layout.addWidget(btn_ok)

        btn_cancel = QPushButton("取消")
        btn_cancel.setFont(label_font)
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)

        layout.addLayout(btn_layout)

    def _on_hw_changed(self, text):
        """硬件接口切换时，显示/隐藏对应配置区"""
        self.group_rs232.setVisible(text == "RS232")
        self.group_usb.setVisible(text == "USB")

    def _ensure_signaling_on(self):
        """若已连接 CMW500，确保 BLE 信令模式已开启"""
        if self.cmw500 is None or not getattr(self.cmw500, "connected", False):
            return False
        try:
            state = self.cmw500.query("SOUR:BLU:SIGN:STATe?").strip().upper()
            if state == "ON":
                return True
            self.cmw500.send_command("SOUR:BLU:SIGN:STATe ON")
            # 等待开启完成（最长 15 秒，冷启动可能需要更久）
            self.cmw500.query("*OPC?")
            for _ in range(150):
                time.sleep(0.1)
                try:
                    state = self.cmw500.query("SOUR:BLU:SIGN:STATe?").strip().upper()
                    if state == "ON":
                        return True
                except pyvisa.VisaIOError:
                    pass
            return False
        except Exception:
            return False

    def _query_cmw_com_ports(self):
        """从 CMW500 查询虚拟串口列表（需先开启信令）
        返回: [(port_name, index), ...] 如 [("COM31", 0)]
        """
        if not self._ensure_signaling_on():
            return []
        try:
            resp = self.cmw500.query("CONF:BLU:SIGN:COMSettings:PORTs:CATalog?")
            # 响应格式: count,index1,"name1",index2,"name2"...
            parts = [p.strip().strip('"').strip("'") for p in resp.split(",")]
            ports = []
            i = 0
            while i < len(parts):
                try:
                    idx = int(parts[i])
                    if i + 1 < len(parts) and parts[i+1].upper().startswith("COM"):
                        ports.append((parts[i+1], idx))
                        i += 2
                    else:
                        i += 1
                except ValueError:
                    i += 1
            return ports
        except Exception:
            return []

    def _refresh_com_ports_local(self):
        """仅扫描系统串口（无 CMW 通信，不卡顿），初始化时调用"""
        current = self.combo_port.currentText()
        self.combo_port.clear()

        port_infos = list(serial.tools.list_ports.comports())
        sys_ports  = [p.device for p in port_infos]
        sys_port_desc = {p.device: p.description for p in port_infos}

        keywords = ("CMW", "R&S", "VIRTUAL COM", "VCP", "SERIAL")
        matched = [p for p in sys_ports if any(
            k in p.upper() or k in sys_port_desc.get(p, "").upper() for k in keywords)]
        others  = [p for p in sys_ports if p not in matched]
        ordered = []
        seen = set()
        for p in matched + others:
            if p not in seen:
                ordered.append(p)
                seen.add(p)

        self.combo_port.addItems(ordered)
        saved_port = self.dut_cfg.get("rs232", {}).get("port", "")
        if current in ordered:
            self.combo_port.setCurrentText(current)
        elif saved_port in ordered:
            self.combo_port.setCurrentText(saved_port)
        elif not ordered:
            self.combo_port.setCurrentText("")

    def _refresh_com_ports(self):
        """刷新串口：先扫描系统，若 CMW 已连接则追加虚拟串口（点自动识别时调用）"""
        current = self.combo_port.currentText()
        self.combo_port.clear()

        port_infos = list(serial.tools.list_ports.comports())
        sys_ports  = [p.device for p in port_infos]
        sys_port_desc = {p.device: p.description for p in port_infos}

        cmw_port_tuples = self._query_cmw_com_ports()  # [(name, index), ...]
        cmw_names = [t[0] for t in cmw_port_tuples]
        # 保存 CMW 端口名→索引映射
        self._cmw_port_index_map = {t[0]: t[1] for t in cmw_port_tuples}

        keywords = ("CMW", "R&S", "VIRTUAL COM", "VCP", "SERIAL")
        matched = [p for p in sys_ports if any(
            k in p.upper() or k in sys_port_desc.get(p, "").upper() for k in keywords)]
        others  = [p for p in sys_ports if p not in matched]

        # 区分：同时在系统和 CMW 中出现的端口为“就绪”，仅在 CMW 中的为“已配置”
        ready_ports = [p for p in cmw_names if p in sys_ports]
        cfg_only_ports = [p for p in cmw_names if p not in sys_ports]

        ordered = []
        seen = set()
        for p in ready_ports + matched + others:
            if p not in seen:
                ordered.append(p)
                seen.add(p)
        # 仅在 CMW 中配置的端口（系统未检测到，可能未插入）放在末尾
        for p in cfg_only_ports:
            if p not in seen:
                ordered.append(p)
                seen.add(p)

        self.combo_port.addItems(ordered)
        if current in ordered:
            self.combo_port.setCurrentText(current)
        elif self.dut_cfg.get("rs232", {}).get("port") in ordered:
            self.combo_port.setCurrentText(self.dut_cfg["rs232"]["port"])
        elif ready_ports:
            self.combo_port.setCurrentText(ready_ports[0])
        elif cmw_names:
            self.combo_port.setCurrentText(cmw_names[0])
        elif not ordered:
            self.combo_port.setCurrentText("")

    def _on_auto_detect_port(self):
        """点击串口自动识别按钮"""
        self._refresh_com_ports()
        ports = [self.combo_port.itemText(i) for i in range(self.combo_port.count())]
        selected = self.combo_port.currentText()
        sys_ports = {p.device for p in serial.tools.list_ports.comports()}
        ready = [p for p in ports if p in sys_ports]
        if ports:
            detail = f"系统检测到 {len(ready)} 个，CMW 配置 {len(ports) - len(ready)} 个（可能未插入）" if len(ports) > len(ready) else f"检测到 {len(ready)} 个串口"
            self.lbl_test_status.setText(f"{detail}，已选：{selected}")
            self.lbl_test_status.setStyleSheet("color: #4CAF50;")
        else:
            self.lbl_test_status.setText("未检测到任何串口，请检查设备连接")
            self.lbl_test_status.setStyleSheet("color: #f44336;")

    def _on_test_connection(self):
        """点击连接测试按钮：通过 CMW500 检查 DUT 连接状态"""
        if self.cmw500 is None or not getattr(self.cmw500, "connected", False):
            self.lbl_test_status.setText("[未连接] 请先连接 CMW500 仪器，再测试 DUT 通信")
            self.lbl_test_status.setStyleSheet("color: #f44336;")
            QMessageBox.warning(self, "连接测试", "请先连接 CMW500 仪器")
            return

        hw_if = self.combo_hw_interface.currentText()
        protocol = self.combo_comm_protocol.currentText()
        self.lbl_test_status.setText("正在测试 DUT 连接，请稍候...")
        self.lbl_test_status.setStyleSheet("color: #FF9800;")

        try:
            # 先清除仪器状态，避免之前操作留下的 GPIB 总线错误影响本次测试
            try:
                self.cmw500.send_command("*CLS")
            except pyvisa.VisaIOError:
                pass

            # 应用当前界面设置到仪器
            # 首次连接或仪器刚启动时，先配置信令路由（不影响已运行状态）
            self.cmw500.send_command('ROUT:BLU:MEAS:SCEN:CSP "Bluetooth SIG1"')
            self.cmw500.send_command("ROUT:BLU:SIGN:SCEN:OTRX RF1C,RX1,RF1C,TX1")
            self.cmw500.send_command("SYST:BASE:REF:FREQ:SOUR INT")

            self.cmw500.send_command(f"CONF:BLU:SIGN:HWINterface {hw_if}")
            self.cmw500.send_command(f"CONF:BLU:SIGN:CPRotocol {protocol}")
            if hw_if == "RS232":
                baud = int(self.combo_baud.currentText())
                baud_map = {9600: "B9K6", 19200: "B19K", 38400: "B38K4",
                            57600: "B57K6", 115200: "B115K"}
                # 用 COMPort 整数索引
                port_name = self.combo_port.currentText()
                port_index = getattr(self, '_cmw_port_index_map', {}).get(port_name, 0)
                self.cmw500.send_command(f'CONF:BLU:SIGN:COMSettings:COMPort {port_index}')
                self.cmw500.send_command(f'CONF:BLU:SIGN:COMSettings:BAUDrate {baud_map.get(baud, "B115K")}')
                # 补齐 COM 参数
                stop = self.combo_stop_bits.currentText()
                stop_map = {"1": "S1", "1.5": "S15", "2": "S2"}
                self.cmw500.send_command(f'CONF:BLU:SIGN:COMSettings:STOPbits {stop_map.get(stop, "S1")}')
                par = self.combo_parity.currentText()
                par_map = {"None": "NONE", "Even": "EVEN", "Odd": "ODD", "Mark": "MARK", "Space": "SPAC"}
                self.cmw500.send_command(f'CONF:BLU:SIGN:COMSettings:PARity {par_map.get(par, "NONE")}')
                flow = self.combo_flow.currentText()
                flow_map = {"None": "NONE", "RTS/CTS": "RTS", "XON/XOFF": "XON"}
                self.cmw500.send_command(f'CONF:BLU:SIGN:COMSettings:PROTocol {flow_map.get(flow, "NONE")}')
                self.cmw500.send_command("CONF:BLU:SIGN:COMSettings:ERESet ON")
                self.cmw500.send_command("CONF:BLU:SIGN:LEN:RESet:DELay 0")

            # 下发 RF 补偿
            rf = self.dut_cfg.get("rf_settings", {})
            att_output = rf.get("att_output", 0.0)
            att_input  = rf.get("att_input",  0.0)
            self.cmw500.send_command(f"CONF:BLU:SIGN:RFSettings:EATT:OUTP {att_output:.1f}")
            self.cmw500.send_command(f"CONF:BLU:SIGN:RFSettings:EATT:INP {att_input:.1f}")

            # 开启信令并等待就绪
            if not self._ensure_signaling_on():
                self.lbl_test_status.setText("[失败] BLE 信令模式启动失败")
                self.lbl_test_status.setStyleSheet("color: #f44336;")
                QMessageBox.warning(self, "连接测试", "BLE 信令模式启动失败，请检查仪器连接")
                return

            # 连接参数
            self.cmw500.send_command("CONF:BLU:SIGN:CONN:BTYP LE")
            signal_cfg = self.dut_cfg.get("signal", {})
            phy = signal_cfg.get("phy_type", "LE 1Msps")
            phy_map = {"LE 1Msps": "LE1M", "LE 2Msps": "LE2M", "LE 500ksps": "LE500K", "LE 125ksps": "LE125K"}
            self.cmw500.send_command(f'CONF:BLU:SIGN:CONN:PHY:LEN {phy_map.get(phy, "LE1M")}')
            self.cmw500.send_command("CONF:BLU:SIGN:RFSettings:CHAN:DTMode 0")
            payload = signal_cfg.get("payload_length", 37)
            self.cmw500.send_command(f"CONF:BLU:SIGN:CONN:PACK:PLEN:LEN:LE1M {payload}")
            pattern = signal_cfg.get("pattern_type", "PRBS9")
            self.cmw500.send_command(f"CONF:BLU:SIGN:CONN:PACK:PATT:LEN:LE1M {pattern}")

            # 若启用 Reset EUT，等待更长时间让 DUT 完成上电/进入测试模式
            #（CMW500 已在 COMSettings 中设置 EReset ON，连接检查时会自动复位 DUT）
            reset_eut = self.chk_reset_eut.isChecked()
            reset_delay = self.spin_reset_delay.value()
            if reset_eut:
                wait_s = max(reset_delay, 2.0)
                self.lbl_test_status.setText(f"Reset EUT 已启用，等待 DUT 就绪（约 {wait_s:.1f} s）...")
                time.sleep(wait_s)
            else:
                # 最小等待，确保指令生效
                time.sleep(1.0)

            # 等待所有指令生效
            self.cmw500.query("*OPC?")

            # 执行连接检查（冷启动时放宽超时并允许一次重试）
            original_timeout = self.cmw500.instrument.timeout
            state = ""
            try:
                self.cmw500.instrument.timeout = 20000  # 20s
                for attempt in range(2):
                    try:
                        state = self.cmw500.query("CALL:BLU:SIGN:CONN:CHECk:LEN?").strip().upper()
                        break
                    except pyvisa.VisaIOError:
                        if attempt == 0:
                            self.lbl_test_status.setText("连接检查首次超时，2 秒后重试...")
                            time.sleep(2.0)
                        else:
                            raise
            finally:
                self.cmw500.instrument.timeout = original_timeout

            if state == "PASS":
                self.lbl_test_status.setText("[通过] 连接测试成功：CMW500与DUT连接正常")
                self.lbl_test_status.setStyleSheet("color: #4CAF50;")
                QMessageBox.information(self, "连接测试", "连接测试成功：CMW500与DUT连接正常")
            else:
                self.lbl_test_status.setText(f"[失败] DUT连接检查未通过：{state}")
                self.lbl_test_status.setStyleSheet("color: #f44336;")
                QMessageBox.warning(self, "连接测试",
                    f"DUT连接检查未通过：{state}\n\n"
                    "请确认：\n"
                    "1. DUT已上电\n"
                    "2. DUT已进入测试模式\n"
                    "3. COM口配置正确\n"
                    "4. 若首次打开软件，请尝试勾选 Reset EUT 并设置 2~5 秒 Reset Delay")
        except Exception as e:
            self.lbl_test_status.setText(f"[错误] 测试失败：{e}")
            self.lbl_test_status.setStyleSheet("color: #f44336;")
            QMessageBox.critical(self, "连接测试", f"测试失败：{e}")

    def _load_settings(self):
        """从配置字典加载设置到界面"""
        hw = self.dut_cfg.get("hw_interface", "RS232")
        self.combo_hw_interface.setCurrentText(hw)
        self.combo_comm_protocol.setCurrentText(self.dut_cfg.get("comm_protocol", "2Wire"))

        rs232 = self.dut_cfg.get("rs232", {})
        self.combo_port.setCurrentText(rs232.get("port", "COM1"))
        self.combo_baud.setCurrentText(str(rs232.get("baud_rate", 115200)))
        self.combo_data_bits.setCurrentText(str(rs232.get("data_bits", 8)))
        self.combo_stop_bits.setCurrentText(str(rs232.get("stop_bits", 1)))
        self.combo_parity.setCurrentText(rs232.get("parity", "None"))
        self.combo_flow.setCurrentText(rs232.get("flow_control", "None"))

        usb = self.dut_cfg.get("usb", {})
        self.spin_usb_device.setValue(usb.get("device", 0))

        init = self.dut_cfg.get("eut_init", {})
        self.chk_reset_eut.setChecked(init.get("reset_eut", True))
        self.spin_reset_delay.setValue(init.get("reset_delay", 0.0))

        signal = self.dut_cfg.get("signal", {})
        self.combo_phy.setCurrentText(signal.get("phy_type", "LE 1Msps"))
        self.combo_pattern.setCurrentText(signal.get("pattern_type", "PRBS9"))
        self.spin_payload.setValue(signal.get("payload_length", 37))

        rf = self.dut_cfg.get("rf_settings", {})
        # 兼容旧字段（int/ext_att_*）：取外部补偿值作为新的统一值
        att_out = rf.get("att_output", rf.get("ext_att_output", rf.get("int_att_output", 0.0)))
        att_in  = rf.get("att_input",  rf.get("ext_att_input",  rf.get("int_att_input",  0.0)))
        self.spin_att_output.setValue(att_out)
        self.spin_att_input.setValue(att_in)

        self._on_hw_changed(hw)

    def _on_ok(self):
        """保存设置到配置字典"""
        self.dut_cfg["hw_interface"] = self.combo_hw_interface.currentText()
        self.dut_cfg["comm_protocol"] = self.combo_comm_protocol.currentText()

        self.dut_cfg["rs232"] = {
            "port": self.combo_port.currentText(),
            "cmw_port_index": self._cmw_port_index_map.get(self.combo_port.currentText(), 0),
            "baud_rate": int(self.combo_baud.currentText()),
            "data_bits": int(self.combo_data_bits.currentText()),
            "stop_bits": self.combo_stop_bits.currentText(),
            "parity": self.combo_parity.currentText(),
            "flow_control": self.combo_flow.currentText(),
        }

        self.dut_cfg["usb"] = {
            "device": self.spin_usb_device.value(),
        }

        self.dut_cfg["eut_init"] = {
            "reset_eut": self.chk_reset_eut.isChecked(),
            "reset_delay": self.spin_reset_delay.value(),
        }

        self.dut_cfg["signal"] = {
            "phy_type": self.combo_phy.currentText(),
            "pattern_type": self.combo_pattern.currentText(),
            "payload_length": self.spin_payload.value(),
        }

        self.dut_cfg["rf_settings"] = {
            "att_output": self.spin_att_output.value(),
            "att_input":  self.spin_att_input.value(),
        }

        self.config["dut_connection"] = self.dut_cfg
        self.accept()

    def get_config(self):
        """返回更新后的配置"""
        return self.config
