"""
DUT 连接设置对话框

参考 CMWrun Connection 页面，配置被测设备与仪器之间的通信方式：
- 硬件接口（HW Interface）
- RS232 / USB 参数
- EUT 初始化选项
- 信号特性（PHY / Pattern / Payload）
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QGroupBox, QLabel, QComboBox, QSpinBox, QDoubleSpinBox,
    QCheckBox, QPushButton, QWidget, QSizePolicy
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont


class DUTSettingsDialog(QDialog):
    """DUT 连接设置对话框"""

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.dut_cfg = config.get("dut_connection", {})
        self._init_ui()
        self._load_settings()

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

        self.combo_port = QComboBox()
        self.combo_port.setFont(input_font)
        self.combo_port.setEditable(True)
        self.combo_port.addItems(["COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM31"])
        rs232_layout.addRow("Virtual COM Port：", self.combo_port)

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

        # ---- 按钮 ----
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

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

        self._on_hw_changed(hw)

    def _on_ok(self):
        """保存设置到配置字典"""
        self.dut_cfg["hw_interface"] = self.combo_hw_interface.currentText()
        self.dut_cfg["comm_protocol"] = self.combo_comm_protocol.currentText()

        self.dut_cfg["rs232"] = {
            "port": self.combo_port.currentText(),
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

        self.config["dut_connection"] = self.dut_cfg
        self.accept()

    def get_config(self):
        """返回更新后的配置"""
        return self.config
