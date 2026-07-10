"""
CMW500 BLE 自动化测试工具 - 测试结果弹窗

用于在独立窗口中按测试类型分页显示测试进度、结果表格，并提供导出 Excel 功能。
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QProgressBar,
    QLabel, QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox,
    QWidget, QTabWidget
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QColor

from test_executor import MODULATION_ITEMS, POWER_ITEMS


class TestResultDialog(QDialog):
    """测试结果展示弹窗（非模态，可实时更新）"""

    TAB_ORDER = ["tx_power", "rx_per", "tx_modulation"]
    TAB_LABELS = {
        "tx_power": "TX 功率测试",
        "rx_per": "RX PER 测试",
        "tx_modulation": "TX 调制测试",
    }

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self._last_results = {}
        self._current_test_type = "tx_power"
        self._tab_tables = {}
        self._tab_columns = {}
        self._tab_keys = {}

        self.setWindowTitle("测试结果")
        self.setMinimumSize(900, 500)
        self.resize(1000, 600)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # 进度条
        progress_layout = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFixedHeight(22)
        self.progress_label = QLabel("进度：0 / 0")
        self.progress_label.setFont(QFont("Microsoft YaHei", 10))
        progress_layout.addWidget(self.progress_bar, 1)
        progress_layout.addWidget(self.progress_label)
        layout.addLayout(progress_layout)

        # 分页表格
        self.tabs = QTabWidget()
        for test_type in self.TAB_ORDER:
            table = QTableWidget()
            table.setColumnCount(0)
            table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            table.setAlternatingRowColors(True)
            table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
            header = table.horizontalHeader()
            header.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
            header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
            self.tabs.addTab(table, self.TAB_LABELS[test_type])
            self._tab_tables[test_type] = table
            self._tab_columns[test_type] = []
            self._tab_keys[test_type] = []

        layout.addWidget(self.tabs)

        # 底部按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.btn_export = QPushButton("导出 Excel")
        self.btn_export.setEnabled(False)
        self.btn_export.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_export.setStyleSheet(
            "QPushButton { background-color: #9C27B0; color: white; padding: 6px 14px; border-radius: 4px; }"
            "QPushButton:hover { background-color: #7B1FA2; }"
            "QPushButton:disabled { background-color: #CE93D8; }"
        )
        self.btn_export.clicked.connect(self._on_export)
        btn_layout.addWidget(self.btn_export)

        btn_close = QPushButton("关闭")
        btn_close.setStyleSheet(
            "QPushButton { background-color: #607D8B; color: white; padding: 6px 14px; border-radius: 4px; }"
            "QPushButton:hover { background-color: #455A64; }"
        )
        btn_close.clicked.connect(self.close)
        btn_layout.addWidget(btn_close)

        layout.addLayout(btn_layout)

    def reset(self):
        """新一轮测试开始前重置弹窗状态"""
        self._last_results = {}
        self.progress_bar.setValue(0)
        self.progress_label.setText("进度：0 / 0")
        self.btn_export.setEnabled(False)
        for table in self._tab_tables.values():
            table.setRowCount(0)
        self.tabs.setCurrentIndex(0)
        self._current_test_type = "tx_power"

    def set_test_config(self, config):
        """更新当前使用的配置"""
        self.config = config

    def _build_tx_columns(self, enabled_keys, test_type):
        """构建 TX 调制或 TX 功率表格列定义"""
        cfg = self.config.get("test_params", {})
        if test_type == "tx_modulation":
            item_map = MODULATION_ITEMS
            item_cfg = cfg.get("modulation_measurements", {})
        else:
            item_map = POWER_ITEMS
            item_cfg = cfg.get("power_measurements", {})

        cols = ["信道"]
        ordered_keys = []
        ordered_entries = []
        for key, info in item_map.items():
            if key not in enabled_keys:
                continue
            name, unit = info[2], info[3]
            cols.append(f"{name}\n({unit})" if unit else name)
            item_setting = item_cfg.get(key, {})
            has_limit = bool(
                item_setting.get("upper_limit") is not None
                or item_setting.get("lower_limit") is not None
            )
            ordered_keys.append(key)
            ordered_entries.append({
                "key": key,
                "name": name,
                "unit": unit,
                "has_limit": has_limit,
            })

        self._tab_columns[test_type] = cols
        self._tab_keys[test_type] = ordered_entries

    def build_table_columns(self, enabled_mod_keys, enabled_pow_keys, test_type):
        """根据当前勾选项动态构建表格列定义"""
        if test_type == "rx_per":
            self._tab_columns["rx_per"] = ["信道", "最佳灵敏度(dBm)", "PER阈值(%)", "最后通过功率(dBm)"]
            self._tab_keys["rx_per"] = []
        elif test_type == "tx_modulation":
            self._build_tx_columns(enabled_mod_keys, "tx_modulation")
        elif test_type == "tx_power":
            self._build_tx_columns(enabled_pow_keys, "tx_power")

    def _apply_columns(self, test_type):
        """应用列定义到对应分页表格"""
        table = self._tab_tables[test_type]
        cols = self._tab_columns[test_type]
        table.setColumnCount(len(cols))
        table.setHorizontalHeaderLabels(cols)
        table.setRowCount(0)

    def on_switch_table(self, test_type, mod_keys=None, pow_keys=None):
        """测试阶段切换时更新表格列并跳转到对应分页"""
        self._current_test_type = test_type
        self.build_table_columns(mod_keys or set(), pow_keys or set(), test_type)
        self._apply_columns(test_type)
        idx = self.TAB_ORDER.index(test_type)
        self.tabs.setCurrentIndex(idx)

    def on_channel_result(self, channel, result):
        """接收单个信道测试结果，根据 test_type 写入对应分页"""
        test_type = result.get("test_type", self._current_test_type)
        table = self._tab_tables[test_type]
        cols = self._tab_columns[test_type]
        row = table.rowCount()
        table.insertRow(row)

        if test_type == "rx_per":
            self._set_cell(table, row, 0, str(channel))
            sensitivity = result.get("sensitivity")
            self._set_cell(table, row, 1, f"{sensitivity:.1f}" if sensitivity is not None else "未找到")
            per_threshold = result.get("per_threshold", 30.8)
            self._set_cell(table, row, 2, f"{per_threshold:.1f}" if per_threshold is not None else "N/A")
            last_pass = result.get("last_pass_power")
            self._set_cell(table, row, 3, f"{last_pass:.1f}" if last_pass is not None else "N/A")
        else:
            self._set_cell(table, row, 0, str(channel))
            col = 1
            pass_fail = result.get("pass_fail", {})
            for entry in self._tab_keys[test_type]:
                key = entry["key"]
                value = result.get(key)
                text = f"{value:.3f}" if isinstance(value, (int, float)) else (str(value) if value is not None else "N/A")
                pf = pass_fail.get(key, "--")
                color = None
                if test_type == "tx_modulation" and pf in ("FAIL", "ERROR"):
                    color = QColor("#f44336")
                self._set_cell(table, row, col, text, color=color)
                col += 1
                if test_type == "tx_power" and entry["has_limit"]:
                    self._set_cell(table, row, col, pf, is_pass_fail=True)
                    col += 1

        table.scrollToBottom()

    def _set_cell(self, table, row, col, text, is_pass_fail=False, color=None):
        """设置单元格内容，并根据 PASS/FAIL 或指定颜色上色"""
        item = QTableWidgetItem(str(text))
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        if color is not None:
            item.setForeground(color)
            item.setFont(QFont("Microsoft YaHei", 9, QFont.Weight.Bold))
        elif is_pass_fail:
            color = QColor("#4CAF50") if text == "PASS" else QColor("#f44336")
            item.setForeground(color)
            item.setFont(QFont("Microsoft YaHei", 9, QFont.Weight.Bold))
        table.setItem(row, col, item)

    def on_progress_update(self, current, total):
        """更新进度条"""
        percent = int(current / total * 100) if total > 0 else 0
        self.progress_bar.setValue(percent)
        self.progress_label.setText(f"进度：{current} / {total}")

    def on_test_finished(self, results):
        """测试完成处理"""
        self._last_results = results
        self.btn_export.setEnabled(bool(results))

    def _on_export(self):
        """点击导出 Excel 按钮"""
        if not self._last_results:
            QMessageBox.information(self, "提示", "没有可导出的测试数据")
            return

        try:
            from data_exporter import DataExporter
            exporter = DataExporter(self.config)
            filepath = exporter.export_to_excel(self._last_results, self.config.get("test_params", {}))
            QMessageBox.information(self, "导出成功", f"文件已保存至：\n{filepath}")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", f"导出 Excel 时发生错误：\n{str(e)}")
