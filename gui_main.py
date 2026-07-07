"""
CMW500 自动化测试工具 - PyQt6 上位机界面

功能说明：
    提供图形化操作界面，包含：
    - 接口配置区：LAN/GPIB/USB 自适应布局
    - 测试项配置区：勾选测试套件（TX调制/TX功率）和具体测量项
    - 操作按钮区：连接、断开、开始测试、停止测试、导出 Excel
    - 实时结果表格：逐信道显示测量数值和 PASS/FAIL 判定
    - 日志窗口：实时显示操作日志
    - 状态栏：显示连接状态和进度信息
    - 进度条：显示测试进度

线程安全说明：
    测试在独立 QThread 中执行，通过 Qt 信号机制更新界面，
    避免阻塞 GUI 主线程。
"""

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QProgressBar, QTextEdit, QLabel,
    QMessageBox, QGroupBox, QSplitter,
    QComboBox, QLineEdit, QFormLayout, QSpinBox, QStackedWidget, QSizePolicy,
    QCheckBox, QScrollArea, QFrame, QMenuBar, QMenu
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QCursor, QAction

# 兼容不同 PyQt6/5 版本的 QSizePolicy 枚举写法
try:
    QSizePolicy_Expanding = QSizePolicy.Policy.Expanding
    QSizePolicy_Maximum   = QSizePolicy.Policy.Maximum
    QSizePolicy_Fixed     = QSizePolicy.Policy.Fixed
except AttributeError:
    QSizePolicy_Expanding = QSizePolicy.Expanding
    QSizePolicy_Maximum   = QSizePolicy.Maximum
    QSizePolicy_Fixed     = QSizePolicy.Fixed

from dut_settings_dialog import DUTSettingsDialog
from instrument_connection import CMW500Connection
from test_executor import MODULATION_ITEMS, POWER_ITEMS, BLERxPerTest


class TestWorker(QThread):
    """
    测试工作线程

    在独立线程中执行 BLE 测试，支持 TX 调制、TX 功率、RX PER 按顺序执行。
    通过信号向主线程发送日志、结果、进度和阶段切换通知。
    """
    log_signal          = pyqtSignal(str)
    result_signal       = pyqtSignal(int, dict)
    progress_signal     = pyqtSignal(int, int)
    finished_signal     = pyqtSignal(list)
    error_signal        = pyqtSignal(str)
    switch_table_signal = pyqtSignal(str, set, set)  # test_type, mod_keys, pow_keys

    def __init__(self, cmw500, config, enabled_suites=None, enabled_items=None):
        super().__init__()
        self.cmw500          = cmw500
        self.config          = config
        self.enabled_suites  = enabled_suites
        self.enabled_items   = enabled_items
        self.test_executor   = None

    def run(self):
        """线程执行入口：按顺序执行 TX 测试和 RX PER 测试"""
        try:
            enabled_suites = set(self.enabled_suites or [])
            enabled_items  = set(self.enabled_items or [])
            mod_keys = enabled_items & set(MODULATION_ITEMS.keys())
            pow_keys = enabled_items & set(POWER_ITEMS.keys())

            do_tx = "tx_modulation" in enabled_suites or "tx_power" in enabled_suites
            do_rx = "rx_per" in enabled_suites
            results = []

            # 阶段1：TX 调制 / TX 功率测试
            if do_tx and (mod_keys or pow_keys):
                self.switch_table_signal.emit("tx", mod_keys, pow_keys)
                from test_executor import BLETxModulationTest
                self.test_executor = BLETxModulationTest(
                    self.cmw500, self.config,
                    enabled_suites=self.enabled_suites,
                    enabled_items=self.enabled_items,
                )
                self.test_executor.set_callbacks(
                    log_cb=lambda msg: self.log_signal.emit(msg),
                    progress_cb=lambda cur, total: self.progress_signal.emit(cur, total),
                    result_cb=lambda ch, data: self.result_signal.emit(ch, data),
                )
                tx_results = self.test_executor.run()
                results.extend(tx_results)

            # 阶段2：RX PER 灵敏度搜索
            if do_rx and not self.isInterruptionRequested():
                if not (self.test_executor and self.test_executor.is_stopped):
                    self.switch_table_signal.emit("rx_per", set(), set())
                    self.test_executor = BLERxPerTest(self.cmw500, self.config)
                    self.test_executor.set_callbacks(
                        log_cb=lambda msg: self.log_signal.emit(msg),
                        progress_cb=lambda cur, total: self.progress_signal.emit(cur, total),
                        result_cb=lambda ch, data: self.result_signal.emit(ch, data),
                    )
                    rx_results = self.test_executor.run()
                    results.extend(rx_results)

            self.finished_signal.emit(results)
        except Exception as e:
            self.error_signal.emit(str(e))

    def stop_test(self):
        """请求停止测试"""
        if self.test_executor:
            self.test_executor.stop()


class GPIBScanThread(QThread):
    """
    GPIB 地址扫描线程

    在独立线程中扫描 GPIB 板卡上的可用地址，
    避免阻塞 GUI 主线程导致界面卡死。
    """
    finished_signal = pyqtSignal(list)
    error_signal    = pyqtSignal(str)

    def __init__(self, board=0, timeout=1000):
        super().__init__()
        self.board = board
        self.timeout = timeout

    def run(self):
        """线程执行入口"""
        try:
            found = CMW500Connection.scan_gpib_address(self.board, self.timeout)
            self.finished_signal.emit(found)
        except Exception as e:
            self.error_signal.emit(str(e))


class CMW500MainWindow(QMainWindow):
    """CMW500 自动化测试主窗口"""

    def __init__(self, config, cmw500):
        super().__init__()
        self.config = config
        self.cmw500 = cmw500
        self.test_worker = None
        self.scan_thread = None

        # 表格列定义：动态生成，依据选中项更新
        self.TABLE_COLUMNS   = []
        self.MEASUREMENT_KEYS = []

        self.setWindowTitle("CMW500 BLE 自动化测试工具")
        self.setMinimumSize(900, 680)
        self.resize(1280, 800)

        self._init_ui()
        self.statusBar().showMessage("就绪 - 请先连接仪器")

    # ============================================================
    #                    界面初始化
    # ============================================================

    def _init_ui(self):
        """构建整体界面布局"""
        # ----- 菜单栏 -----
        menubar = self.menuBar()
        settings_menu = menubar.addMenu("设置")
        action_dut = QAction("DUT 连接设置", self)
        action_dut.triggered.connect(self._open_dut_settings)
        settings_menu.addAction(action_dut)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(8)

        # ----- 顶部：接口配置 + 测试项配置 垂直排列 -----
        top_layout = QVBoxLayout()
        top_layout.setSpacing(8)
        top_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        top_layout.addWidget(self._create_interface_group())
        top_layout.addWidget(self._create_test_items_group())
        main_layout.addLayout(top_layout)

        # ----- 按钮操作区 -----
        main_layout.addWidget(self._create_button_group())

        # ----- 中部：结果表格 + 进度条 -----
        main_layout.addWidget(self._create_result_group(), stretch=3)

        # ----- 底部：日志窗口 -----
        main_layout.addWidget(self._create_log_group(), stretch=1)

    def _open_dut_settings(self):
        """打开 DUT 连接设置对话框"""
        dialog = DUTSettingsDialog(self.config, parent=self)
        if dialog.exec() == DUTSettingsDialog.DialogCode.Accepted:
            self.config = dialog.get_config()
            self._append_log("DUT 连接设置已更新")
            self.statusBar().showMessage("DUT 连接设置已保存到内存，如需永久保存请同步 config.yaml")

    def _create_interface_group(self):
        """创建接口配置区（选择 LAN/GPIB/USB + 可编辑地址，自适应布局）"""
        group = QGroupBox("接口配置")
        group.setSizePolicy(QSizePolicy_Expanding, QSizePolicy_Maximum)

        # 垂直布局：内容靠顶部，下方弹性空间
        v_layout = QVBoxLayout(group)
        v_layout.setContentsMargins(10, 8, 10, 8)
        v_layout.setSpacing(0)

        outer_layout = QHBoxLayout()
        outer_layout.setSpacing(12)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        v_layout.addLayout(outer_layout)
        v_layout.addStretch()

        label_font = QFont("微软雅黑", 10)
        input_font = QFont("Consolas", 10)

        # ---- 接口类型下拉框 ----
        lbl_type = QLabel("接口类型：")
        lbl_type.setFont(label_font)
        lbl_type.setSizePolicy(QSizePolicy_Fixed, QSizePolicy_Fixed)
        outer_layout.addWidget(lbl_type)

        self.combo_interface = QComboBox()
        self.combo_interface.addItems([
            "LAN (TCP/IP)", "GPIB (IEEE-488)"
        ])
        self.combo_interface.setFont(input_font)
        self.combo_interface.setMinimumWidth(150)
        self.combo_interface.setMaximumWidth(180)
        self.combo_interface.setSizePolicy(QSizePolicy_Fixed, QSizePolicy_Fixed)
        self.combo_interface.setStyleSheet(
            "QComboBox { padding: 4px 8px; }"
        )
        self.combo_interface.currentIndexChanged.connect(self._on_interface_changed)
        outer_layout.addWidget(self.combo_interface)

        # ====== 用 QStackedWidget 切换不同接口的参数区 ======
        self.iface_stack = QStackedWidget()
        self.iface_stack.setSizePolicy(QSizePolicy_Expanding, QSizePolicy_Fixed)

        # -- Page 0: LAN --
        lan_page = QWidget()
        lan_layout = QHBoxLayout(lan_page)
        lan_layout.setContentsMargins(0, 0, 0, 0)
        lan_layout.setSpacing(8)
        self.lbl_lan = QLabel("IP 地址：")
        self.lbl_lan.setFont(label_font)
        self.edit_lan_ip = QLineEdit()
        self.edit_lan_ip.setFont(input_font)
        self.edit_lan_ip.setPlaceholderText("例如：192.168.1.100")
        self.edit_lan_ip.setText(self.config["instrument"]["lan"]["ip_address"])
        self.edit_lan_ip.setSizePolicy(QSizePolicy_Expanding, QSizePolicy_Fixed)
        lan_layout.addWidget(self.lbl_lan)
        lan_layout.addWidget(self.edit_lan_ip)
        lan_layout.addStretch()
        self.iface_stack.addWidget(lan_page)

        # -- Page 1: GPIB --
        gpib_page = QWidget()
        gpib_layout = QHBoxLayout(gpib_page)
        gpib_layout.setContentsMargins(0, 0, 0, 0)
        gpib_layout.setSpacing(8)
        self.lbl_gpib_board = QLabel("板号：")
        self.lbl_gpib_board.setFont(label_font)
        self.spin_gpib_board = QSpinBox()
        self.spin_gpib_board.setFont(input_font)
        self.spin_gpib_board.setRange(0, 10)
        self.spin_gpib_board.setValue(self.config["instrument"]["gpib"]["board"])
        self.spin_gpib_board.setMinimumWidth(60)
        self.spin_gpib_board.setMaximumWidth(80)
        self.lbl_gpib_addr = QLabel("地址：")
        self.lbl_gpib_addr.setFont(label_font)
        self.spin_gpib_addr = QSpinBox()
        self.spin_gpib_addr.setFont(input_font)
        self.spin_gpib_addr.setRange(0, 30)
        self.spin_gpib_addr.setValue(self.config["instrument"]["gpib"]["address"])
        self.spin_gpib_addr.setMinimumWidth(60)
        self.spin_gpib_addr.setMaximumWidth(80)
        gpib_layout.addWidget(self.lbl_gpib_board)
        gpib_layout.addWidget(self.spin_gpib_board)
        gpib_layout.addSpacing(16)
        gpib_layout.addWidget(self.lbl_gpib_addr)
        gpib_layout.addWidget(self.spin_gpib_addr)

        self.btn_scan_gpib = QPushButton("自动识别")
        self.btn_scan_gpib.setFont(label_font)
        self.btn_scan_gpib.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_scan_gpib.setStyleSheet(
            "QPushButton { background-color: #607D8B; color: white; "
            "padding: 4px 10px; border-radius: 4px; }"
            "QPushButton:hover { background-color: #455A64; }"
        )
        self.btn_scan_gpib.clicked.connect(self._on_scan_gpib)
        gpib_layout.addWidget(self.btn_scan_gpib)

        gpib_layout.addStretch()
        self.iface_stack.addWidget(gpib_page)

        outer_layout.addWidget(self.iface_stack, stretch=1)

        # 根据默认接口类型设置初始显示状态
        default_type = self.config["instrument"]["interface_type"]
        index_map = {"LAN": 0, "GPIB": 1}
        init_index = index_map.get(default_type, 0)
        self.combo_interface.setCurrentIndex(init_index)
        self.iface_stack.setCurrentIndex(init_index)

        return group

    def _on_interface_changed(self, index):
        """
        接口类型切换时，切换 StackedWidget 到对应页面

        参数:
            index: 下拉框当前索引（0=LAN, 1=GPIB）
        """
        self.iface_stack.setCurrentIndex(index)

    def _set_interface_inputs_enabled(self, enabled):
        """批量设置所有接口输入控件的启用/禁用状态"""
        # LAN
        self.edit_lan_ip.setEnabled(enabled)
        # GPIB
        self.spin_gpib_board.setEnabled(enabled)
        self.spin_gpib_addr.setEnabled(enabled)
        self.btn_scan_gpib.setEnabled(enabled)
        # 接口类型下拉框
        self.combo_interface.setEnabled(enabled)

    # ============================================================
    #              测试项配置区
    # ============================================================

    def _create_test_items_group(self):
        """创建测试项配置区：测试套件 + 各项勾选"""
        group = QGroupBox("测试项配置")
        group.setSizePolicy(QSizePolicy_Expanding, QSizePolicy_Expanding)
        outer = QVBoxLayout(group)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(6)

        label_font = QFont("微软雅黑", 11)
        cb_font    = QFont("微软雅黑", 11)

        cfg_tp = self.config["test_params"]
        mod_cfg = cfg_tp.get("modulation_measurements", {})
        pow_cfg = cfg_tp.get("power_measurements", {})
        suite_cfg = cfg_tp.get("test_suites", {})

        # ---- 测试套件行： TX调制 / TX功率 ----
        suite_row = QHBoxLayout()
        suite_row.setSpacing(16)
        suite_lbl = QLabel("套件：")
        suite_lbl.setFont(label_font)
        suite_row.addWidget(suite_lbl)

        self.chk_suite_mod = QCheckBox("TX 调制测试")
        self.chk_suite_mod.setFont(cb_font)
        self.chk_suite_mod.setChecked(suite_cfg.get("tx_modulation", {}).get("enabled", True))
        self.chk_suite_mod.toggled.connect(self._on_suite_toggled)
        suite_row.addWidget(self.chk_suite_mod)

        self.chk_suite_pow = QCheckBox("TX 功率测试")
        self.chk_suite_pow.setFont(cb_font)
        self.chk_suite_pow.setChecked(suite_cfg.get("tx_power", {}).get("enabled", True))
        self.chk_suite_pow.toggled.connect(self._on_suite_toggled)
        suite_row.addWidget(self.chk_suite_pow)

        self.chk_suite_rx = QCheckBox("RX PER 测试")
        self.chk_suite_rx.setFont(cb_font)
        self.chk_suite_rx.setChecked(suite_cfg.get("rx_per", {}).get("enabled", False))
        self.chk_suite_rx.toggled.connect(self._on_suite_toggled)
        suite_row.addWidget(self.chk_suite_rx)
        suite_row.addStretch()

        # 全选/反选按钮
        btn_all = QPushButton("全选")
        btn_all.setFont(cb_font)
        btn_all.setFixedWidth(60)
        btn_all.clicked.connect(self._select_all_items)
        suite_row.addWidget(btn_all)
        btn_none = QPushButton("全不选")
        btn_none.setFont(cb_font)
        btn_none.setFixedWidth(70)
        btn_none.clicked.connect(self._deselect_all_items)
        suite_row.addWidget(btn_none)

        outer.addLayout(suite_row)

        # 分隔线
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        outer.addWidget(line)

        # ---- 具体测量项勾选（垂直堆叠卡片式布局）----
        items_widget = QWidget()
        items_layout = QVBoxLayout(items_widget)
        items_layout.setContentsMargins(0, 0, 0, 0)
        items_layout.setSpacing(8)

        # 调制项：标题 + 左右两列（每列4项）
        mod_widget = QWidget()
        mod_outer = QVBoxLayout(mod_widget)
        mod_outer.setContentsMargins(0, 0, 0, 0)
        mod_outer.setSpacing(4)

        mod_title = QLabel("📊 TX 调制测试")
        mod_title.setFont(QFont("微软雅黑", 12, QFont.Weight.Bold))
        mod_title.setStyleSheet("color: #1565C0;")
        mod_outer.addWidget(mod_title)

        # 信道选择
        mod_ch_layout = QHBoxLayout()
        mod_ch_layout.setSpacing(8)
        mod_ch_lbl = QLabel("信道:")
        mod_ch_lbl.setFont(QFont("微软雅黑", 10))
        mod_ch_layout.addWidget(mod_ch_lbl)
        self._combo_tx_channel_mod = QComboBox()
        self._combo_tx_channel_mod.setFont(QFont("微软雅黑", 10))
        self._combo_tx_channel_mod.addItems(["全部 (0~39)"] + [str(i) for i in range(40)])
        self._combo_tx_channel_mod.setCurrentIndex(0)
        self._combo_tx_channel_mod.setFixedWidth(120)
        mod_ch_layout.addWidget(self._combo_tx_channel_mod)
        mod_ch_layout.addStretch()
        mod_outer.addLayout(mod_ch_layout)

        self._mod_checkboxes = {}   # key -> QCheckBox
        mod_items = list(MODULATION_ITEMS.items())
        half = (len(mod_items) + 1) // 2  # 左列4个，右列4个

        mod_cols = QHBoxLayout()
        mod_cols.setSpacing(16)
        mod_left  = QVBoxLayout()
        mod_left.setSpacing(4)
        mod_right = QVBoxLayout()
        mod_right.setSpacing(4)

        for i, (key, (_, name, unit)) in enumerate(mod_items):
            chk = QCheckBox(f"{name}  ({unit})")
            chk.setFont(cb_font)
            chk.setChecked(mod_cfg.get(key, {}).get("enabled", True))
            self._mod_checkboxes[key] = chk
            if i < half:
                mod_left.addWidget(chk)
            else:
                mod_right.addWidget(chk)
        mod_left.addStretch()
        mod_right.addStretch()
        mod_cols.addLayout(mod_left)
        mod_cols.addLayout(mod_right)
        mod_cols.addStretch()
        mod_outer.addLayout(mod_cols)
        self._mod_widget = mod_widget
        mod_widget.setSizePolicy(QSizePolicy_Expanding, QSizePolicy_Expanding)
        items_layout.addWidget(mod_widget)

        # 水平分隔线
        hline1 = QFrame()
        hline1.setFrameShape(QFrame.Shape.HLine)
        hline1.setFrameShadow(QFrame.Shadow.Sunken)
        self._hline_mod_pow = hline1
        items_layout.addWidget(hline1)

        # 功率项：标题 + 子项
        pow_widget = QWidget()
        pow_widget.setSizePolicy(QSizePolicy_Expanding, QSizePolicy_Expanding)
        pow_outer = QVBoxLayout(pow_widget)
        pow_outer.setContentsMargins(0, 0, 0, 0)
        pow_outer.setSpacing(4)

        pow_title = QLabel("⚡ TX 功率测试")
        pow_title.setFont(QFont("微软雅黑", 12, QFont.Weight.Bold))
        pow_title.setStyleSheet("color: #558B2F;")
        pow_outer.addWidget(pow_title)

        # 信道选择
        pow_ch_layout = QHBoxLayout()
        pow_ch_layout.setSpacing(8)
        pow_ch_lbl = QLabel("信道:")
        pow_ch_lbl.setFont(QFont("微软雅黑", 10))
        pow_ch_layout.addWidget(pow_ch_lbl)
        self._combo_tx_channel_pow = QComboBox()
        self._combo_tx_channel_pow.setFont(QFont("微软雅黑", 10))
        self._combo_tx_channel_pow.addItems(["全部 (0~39)"] + [str(i) for i in range(40)])
        self._combo_tx_channel_pow.setCurrentIndex(0)
        self._combo_tx_channel_pow.setFixedWidth(120)
        pow_ch_layout.addWidget(self._combo_tx_channel_pow)
        pow_ch_layout.addStretch()
        pow_outer.addLayout(pow_ch_layout)

        self._pow_checkboxes = {}   # key -> QCheckBox
        for key, (_, name, unit) in POWER_ITEMS.items():
            chk = QCheckBox(f"{name}  ({unit})")
            chk.setFont(cb_font)
            chk.setChecked(pow_cfg.get(key, {}).get("enabled", True))
            self._pow_checkboxes[key] = chk
            pow_outer.addWidget(chk)
        pow_outer.addStretch()
        self._pow_widget = pow_widget
        items_layout.addWidget(pow_widget)

        # 水平分隔线
        hline2 = QFrame()
        hline2.setFrameShape(QFrame.Shape.HLine)
        hline2.setFrameShadow(QFrame.Shadow.Sunken)
        self._hline_pow_rx = hline2
        items_layout.addWidget(hline2)

        # RX PER 配置编辑区
        rx_widget = QWidget()
        rx_widget.setSizePolicy(QSizePolicy_Expanding, QSizePolicy_Expanding)
        rx_outer = QVBoxLayout(rx_widget)
        rx_outer.setContentsMargins(0, 0, 0, 0)
        rx_outer.setSpacing(4)

        rx_title = QLabel("🔍 RX PER 测试")
        rx_title.setFont(QFont("微软雅黑", 12, QFont.Weight.Bold))
        rx_title.setStyleSheet("color: #C62828;")
        rx_outer.addWidget(rx_title)

        rx_cfg = cfg_tp.get("rx_per", {})
        self._rx_inputs = {}

        form = QGridLayout()
        form.setContentsMargins(0, 4, 0, 0)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        form.setColumnStretch(1, 1)

        def add_row(row, label, widget):
            lbl = QLabel(label)
            lbl.setFont(QFont("微软雅黑", 10))
            form.addWidget(lbl, row, 0, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            form.addWidget(widget, row, 1, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        # 搜索范围：起止功率
        start_edit = QLineEdit(str(rx_cfg.get("start_power", -90.0)))
        end_edit = QLineEdit(str(rx_cfg.get("end_power", -100.0)))
        for ed in (start_edit, end_edit):
            ed.setFont(QFont("微软雅黑", 10))
            ed.setMinimumWidth(80)
            ed.setMaximumWidth(100)
        range_layout = QHBoxLayout()
        range_layout.setSpacing(4)
        range_layout.addWidget(start_edit)
        range_layout.addWidget(QLabel("→"))
        range_layout.addWidget(end_edit)
        range_layout.addWidget(QLabel("dBm"))
        range_layout.addStretch()
        range_widget = QWidget()
        range_widget.setLayout(range_layout)
        add_row(0, "搜索范围:", range_widget)
        self._rx_inputs["start_power"] = start_edit
        self._rx_inputs["end_power"] = end_edit

        # 功率步进
        step_edit = QLineEdit(str(rx_cfg.get("step_size", 0.5)))
        step_edit.setFont(QFont("微软雅黑", 10))
        step_edit.setMinimumWidth(80)
        step_edit.setMaximumWidth(100)
        step_layout = QHBoxLayout()
        step_layout.addWidget(step_edit)
        step_layout.addWidget(QLabel("dB"))
        step_layout.addStretch()
        step_widget = QWidget()
        step_widget.setLayout(step_layout)
        add_row(1, "功率步进:", step_widget)
        self._rx_inputs["step_size"] = step_edit

        # PER 阈值
        per_edit = QLineEdit(str(rx_cfg.get("per_threshold", 30.8)))
        per_edit.setFont(QFont("微软雅黑", 10))
        per_edit.setMinimumWidth(80)
        per_edit.setMaximumWidth(100)
        per_layout = QHBoxLayout()
        per_layout.addWidget(per_edit)
        per_layout.addWidget(QLabel("%"))
        per_layout.addStretch()
        per_widget = QWidget()
        per_widget.setLayout(per_layout)
        add_row(2, "PER 阈值:", per_widget)
        self._rx_inputs["per_threshold"] = per_edit

        # 每点包数
        pkt_edit = QLineEdit(str(rx_cfg.get("packet_count", 1500)))
        pkt_edit.setFont(QFont("微软雅黑", 10))
        pkt_edit.setMinimumWidth(80)
        pkt_edit.setMaximumWidth(100)
        add_row(3, "每点包数:", pkt_edit)
        self._rx_inputs["packet_count"] = pkt_edit

        # PHY
        phy_combo = QComboBox()
        phy_combo.setFont(QFont("微软雅黑", 10))
        phy_combo.addItems(["LE1M", "LE2M", "LE500K", "LE125K"])
        phy_combo.setCurrentText(rx_cfg.get("phy_type", "LE1M"))
        add_row(4, "PHY:", phy_combo)
        self._rx_inputs["phy_type"] = phy_combo

        # 包型
        pkt_type_combo = QComboBox()
        pkt_type_combo.setFont(QFont("微软雅黑", 10))
        pkt_type_combo.addItems(["PRBS9", "PRBS15", "11110000", "10101010"])
        pkt_type_combo.setCurrentText(rx_cfg.get("packet_type", "PRBS9"))
        add_row(5, "包型:", pkt_type_combo)
        self._rx_inputs["packet_type"] = pkt_type_combo

        # 期望灵敏度
        exp_edit = QLineEdit(str(rx_cfg.get("expected_sensitivity", -95.0)))
        exp_edit.setFont(QFont("微软雅黑", 10))
        exp_edit.setMinimumWidth(80)
        exp_edit.setMaximumWidth(100)
        exp_layout = QHBoxLayout()
        exp_layout.addWidget(exp_edit)
        exp_layout.addWidget(QLabel("dBm（用于 PASS/FAIL 判定）"))
        exp_layout.addStretch()
        exp_widget = QWidget()
        exp_widget.setLayout(exp_layout)
        add_row(6, "期望灵敏度:", exp_widget)
        self._rx_inputs["expected_sensitivity"] = exp_edit

        rx_outer.addLayout(form)
        rx_outer.addStretch()

        self._rx_widget = rx_widget
        items_layout.addWidget(rx_widget)

        # 同步两个 TX 信道选择下拉框
        def sync_tx_channel(source):
            target = self._combo_tx_channel_pow if source == self._combo_tx_channel_mod else self._combo_tx_channel_mod
            if target.currentIndex() != source.currentIndex():
                target.blockSignals(True)
                target.setCurrentIndex(source.currentIndex())
                target.blockSignals(False)

        self._combo_tx_channel_mod.currentIndexChanged.connect(lambda: sync_tx_channel(self._combo_tx_channel_mod))
        self._combo_tx_channel_pow.currentIndexChanged.connect(lambda: sync_tx_channel(self._combo_tx_channel_pow))

        outer.addWidget(items_widget, stretch=1)

        # 初始化一次可见性
        self._on_suite_toggled()

        return group

    def _on_suite_toggled(self):
        """套件勾选状态变化时，同步更新对应列的勾选框可用状态和区域可见性"""
        mod_on = self.chk_suite_mod.isChecked()
        pow_on = self.chk_suite_pow.isChecked()
        rx_on  = self.chk_suite_rx.isChecked()

        for chk in self._mod_checkboxes.values():
            chk.setEnabled(mod_on)
        for chk in self._pow_checkboxes.values():
            chk.setEnabled(pow_on)

        # 切换各套件配置区域的可见性（垂直堆叠，可同时展开多个）
        self._mod_widget.setVisible(mod_on)
        self._pow_widget.setVisible(pow_on)
        self._rx_widget.setVisible(rx_on)

        # 分隔线：只在相邻两个区域都显示时出现
        self._hline_mod_pow.setVisible(mod_on and pow_on)
        self._hline_pow_rx.setVisible((mod_on or pow_on) and rx_on)

    def _sync_rx_per_config_from_ui(self):
        """将 RX PER 界面输入框的值同步到 self.config"""
        def to_float(text, name):
            try:
                return float(text.strip())
            except ValueError:
                raise ValueError(f"{name} 必须是数字")

        def to_int(text, name):
            try:
                return int(float(text.strip()))
            except ValueError:
                raise ValueError(f"{name}必须是整数")

        rx_cfg = self.config.setdefault("test_params", {}).setdefault("rx_per", {})

        rx_cfg["start_power"] = to_float(self._rx_inputs["start_power"].text(), "搜索起始功率")
        rx_cfg["end_power"] = to_float(self._rx_inputs["end_power"].text(), "搜索结束功率")
        rx_cfg["step_size"] = abs(to_float(self._rx_inputs["step_size"].text(), "功率步进"))
        rx_cfg["per_threshold"] = to_float(self._rx_inputs["per_threshold"].text(), "PER 阈值")
        rx_cfg["packet_count"] = to_int(self._rx_inputs["packet_count"].text(), "每点包数")
        rx_cfg["phy_type"] = self._rx_inputs["phy_type"].currentText()
        rx_cfg["packet_type"] = self._rx_inputs["packet_type"].currentText()

        exp_text = self._rx_inputs["expected_sensitivity"].text().strip()
        if exp_text.lower() in ("", "null", "none", "未设置"):
            rx_cfg["expected_sensitivity"] = None
        else:
            rx_cfg["expected_sensitivity"] = to_float(exp_text, "期望灵敏度")

    def _select_all_items(self):
        """全选全部测量项"""
        self.chk_suite_mod.setChecked(True)
        self.chk_suite_pow.setChecked(True)
        self.chk_suite_rx.setChecked(True)
        for chk in list(self._mod_checkboxes.values()) + list(self._pow_checkboxes.values()):
            chk.setChecked(True)

    def _deselect_all_items(self):
        """取消全部测量项"""
        self.chk_suite_mod.setChecked(False)
        self.chk_suite_pow.setChecked(False)
        self.chk_suite_rx.setChecked(False)
        for chk in list(self._mod_checkboxes.values()) + list(self._pow_checkboxes.values()):
            chk.setChecked(False)

    def _get_enabled_suites_and_items(self):
        """
        从勾选框读取当前启用的套件和测量项

        返回:
            (enabled_suites: list, enabled_items: set)
        """
        suites = []
        if self.chk_suite_mod.isChecked():
            suites.append("tx_modulation")
        if self.chk_suite_pow.isChecked():
            suites.append("tx_power")
        if self.chk_suite_rx.isChecked():
            suites.append("rx_per")

        items = set()
        if self.chk_suite_mod.isChecked():
            for k, chk in self._mod_checkboxes.items():
                if chk.isChecked():
                    items.add(k)
        if self.chk_suite_pow.isChecked():
            for k, chk in self._pow_checkboxes.items():
                if chk.isChecked():
                    items.add(k)
        return suites, items

    def _build_table_columns(self, enabled_mod_keys, enabled_pow_keys, test_type="tx"):
        """根据当前勾选项动态构建表格列定义"""
        self._current_test_type = test_type

        if test_type == "rx_per":
            self.TABLE_COLUMNS = [
                "信道",
                "灵敏度\n(dBm)",
                "PER 阈值\n(%)",
                "最后通过功率\n(dBm)",
                "最后失败功率\n(dBm)",
                "判定",
            ]
            self.MEASUREMENT_KEYS = []
            return

        cfg = self.config["test_params"]
        mod_cfg = cfg.get("modulation_measurements", {})
        pow_cfg = cfg.get("power_measurements", {})

        cols   = ["信道"]
        keys   = []

        # 调制项：按 MODULATION_ITEMS 顺序
        for key in MODULATION_ITEMS:
            if key in enabled_mod_keys:
                info = mod_cfg.get(key, {})
                name = info.get("name", key)
                unit = info.get("unit", "")
                cols.append(f"{name}\n({unit})")
                cols.append("判定")
                keys.append(key)

        # 功率项：按 POWER_ITEMS 顺序
        for key in POWER_ITEMS:
            if key in enabled_pow_keys:
                info = pow_cfg.get(key, {})
                name = info.get("name", key)
                unit = info.get("unit", "")
                cols.append(f"{name}\n({unit})")
                has_limit = info.get("upper_limit") is not None or info.get("lower_limit") is not None
                if has_limit:
                    cols.append("判定")
                    keys.append((key, True))
                else:
                    keys.append((key, False))

        self.TABLE_COLUMNS    = cols
        # 展平：调制项用 str，功率项用 tuple(key, has_limit)
        self.MEASUREMENT_KEYS = (
            list(enabled_mod_keys & set(MODULATION_ITEMS))
            + [(k, v) for k, v in [q for q in
               [(kk, pow_cfg.get(kk, {}).get("upper_limit") is not None
                 or pow_cfg.get(kk, {}).get("lower_limit") is not None)
                for kk in POWER_ITEMS if kk in enabled_pow_keys]]]
        )
        # 调制项保持 MODULATION_ITEMS 顺序
        mod_ordered  = [k for k in MODULATION_ITEMS if k in enabled_mod_keys]
        pow_ordered  = [(k, pow_cfg.get(k, {}).get("upper_limit") is not None
                          or pow_cfg.get(k, {}).get("lower_limit") is not None)
                        for k in POWER_ITEMS if k in enabled_pow_keys]
        self.MEASUREMENT_KEYS = mod_ordered + pow_ordered

    def _create_button_group(self):
        """创建按钮操作区"""
        group = QGroupBox("操作面板")
        layout = QHBoxLayout(group)
        layout.setSpacing(12)
        layout.setContentsMargins(10, 8, 10, 8)

        # 字体统一设置
        btn_font = QFont("微软雅黑", 10)

        # ---- 连接按钮 ----
        btn_style_map = [
            ("btn_connect",    "连接仪器",   "#4CAF50", "#45a049", "#A5D6A7", True),
            ("btn_disconnect", "断开仪器",   "#f44336", "#da190b", "#EF9A9A", False),
        ]
        for attr, label, bg, hover, dis, enabled in btn_style_map:
            btn = QPushButton(label)
            btn.setFont(btn_font)
            btn.setEnabled(enabled)
            btn.setSizePolicy(QSizePolicy_Expanding, QSizePolicy_Fixed)
            btn.setMinimumWidth(90)
            btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn.setStyleSheet(
                f"QPushButton {{ background-color: {bg}; color: white; "
                f"padding: 8px 12px; border-radius: 4px; }}"
                f"QPushButton:hover {{ background-color: {hover}; }}"
                f"QPushButton:disabled {{ background-color: {dis}; }}"
            )
            setattr(self, attr, btn)
            layout.addWidget(btn)
        self.btn_connect.clicked.connect(self._on_connect)
        self.btn_disconnect.clicked.connect(self._on_disconnect)

        layout.addSpacing(12)

        btn_style_map2 = [
            ("btn_start",  "开始测试",  "#2196F3", "#1976D2", "#90CAF9",  False),
            ("btn_stop",   "停止测试",  "#FF9800", "#F57C00", "#FFCC80",  False),
        ]
        for attr, label, bg, hover, dis, enabled in btn_style_map2:
            btn = QPushButton(label)
            btn.setFont(btn_font)
            btn.setEnabled(enabled)
            btn.setSizePolicy(QSizePolicy_Expanding, QSizePolicy_Fixed)
            btn.setMinimumWidth(90)
            btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn.setStyleSheet(
                f"QPushButton {{ background-color: {bg}; color: white; "
                f"padding: 8px 12px; border-radius: 4px; }}"
                f"QPushButton:hover {{ background-color: {hover}; }}"
                f"QPushButton:disabled {{ background-color: {dis}; }}"
            )
            setattr(self, attr, btn)
            layout.addWidget(btn)
        self.btn_start.clicked.connect(self._on_start_test)
        self.btn_stop.clicked.connect(self._on_stop_test)

        layout.addSpacing(12)

        # ---- 导出 Excel 按钮 ----
        self.btn_export = QPushButton("导出 Excel")
        self.btn_export.setFont(btn_font)
        self.btn_export.setEnabled(False)
        self.btn_export.setSizePolicy(QSizePolicy_Expanding, QSizePolicy_Fixed)
        self.btn_export.setMinimumWidth(90)
        self.btn_export.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_export.setStyleSheet(
            "QPushButton { background-color: #9C27B0; color: white; "
            "padding: 8px 12px; border-radius: 4px; }"
            "QPushButton:hover { background-color: #7B1FA2; }"
            "QPushButton:disabled { background-color: #CE93D8; }"
        )
        self.btn_export.clicked.connect(self._on_export)
        layout.addWidget(self.btn_export)

        # 弹性空间
        layout.addStretch()

        # ---- 连接状态标签 ----
        self.label_status = QLabel("● 未连接")
        self.label_status.setFont(QFont("微软雅黑", 11, QFont.Weight.Bold))
        self.label_status.setStyleSheet("color: #999999;")
        layout.addWidget(self.label_status)

        return group

    def _create_result_group(self):
        """创建结果表格和进度条区域"""
        group = QGroupBox("测试结果")
        layout = QVBoxLayout(group)

        # 进度条
        progress_layout = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFixedHeight(25)
        self.progress_label = QLabel("进度：0 / 0")
        self.progress_label.setFont(QFont("微软雅黑", 10))
        progress_layout.addWidget(self.progress_bar, stretch=1)
        progress_layout.addWidget(self.progress_label)
        layout.addLayout(progress_layout)

        # 结果表格
        self.table = QTableWidget()
        self.table.setColumnCount(len(self.TABLE_COLUMNS))
        self.table.setHorizontalHeaderLabels(self.TABLE_COLUMNS)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)  # 禁止编辑
        self.table.setAlternatingRowColors(True)  # 交替行颜色
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)

        # 设置表头样式
        header = self.table.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setFont(QFont("微软雅黑", 9))
        self.table.horizontalHeader().setFont(QFont("微软雅黑", 9, QFont.Weight.Bold))

        layout.addWidget(self.table)
        return group

    def _create_log_group(self):
        """创建日志窗口"""
        group = QGroupBox("运行日志")
        layout = QVBoxLayout(group)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 9))
        self.log_text.setStyleSheet(
            "QTextEdit { background-color: #1e1e1e; color: #cccccc; }"
        )
        layout.addWidget(self.log_text)
        return group

    # ============================================================
    #                    按钮事件处理
    # ============================================================

    def _on_connect(self):
        """点击"连接仪器"按钮 —— 从界面读取当前接口参数后连接"""
        # 从 UI 读取当前接口设置，更新到 cmw500 实例
        idx = self.combo_interface.currentIndex()
        if idx == 0:
            # LAN 模式
            self.cmw500.interface_type = "LAN"
            self.cmw500.lan_ip = self.edit_lan_ip.text().strip()
        elif idx == 1:
            # GPIB 模式
            self.cmw500.interface_type = "GPIB"
            self.cmw500.gpib_board = self.spin_gpib_board.value()
            self.cmw500.gpib_address = self.spin_gpib_addr.value()
        else:
            self._append_log("[错误] 未知的接口类型")
            QMessageBox.warning(self, "连接失败", "未知的接口类型")
            return

        # 连接期间禁用接口配置（防止误改）
        self._set_interface_inputs_enabled(False)

        self._append_log("正在连接仪器...")
        success, message = self.cmw500.connect()

        if success:
            self._append_log(message)
            # 更新按钮状态
            self.btn_connect.setEnabled(False)
            self.btn_disconnect.setEnabled(True)
            self.btn_start.setEnabled(True)
            # 更新状态标签
            self.label_status.setText("● 已连接")
            self.label_status.setStyleSheet("color: #4CAF50;")
            self.statusBar().showMessage("仪器已连接")
        else:
            self._append_log(f"[错误] {message}")
            QMessageBox.warning(self, "连接失败", message)
            self.statusBar().showMessage("连接失败")
            # 连接失败时恢复接口配置可编辑
            self._set_interface_inputs_enabled(True)

    def _on_scan_gpib(self):
        """点击 GPIB 自动识别按钮 —— 在独立线程中扫描可用地址"""
        board = self.spin_gpib_board.value()
        self._append_log(f"正在扫描 GPIB 板卡 {board} 的地址 ...")
        self.btn_scan_gpib.setEnabled(False)
        self.btn_scan_gpib.setText("扫描中...")
        self.btn_connect.setEnabled(False)

        self.scan_thread = GPIBScanThread(board=board, timeout=3000)
        self.scan_thread.finished_signal.connect(self._on_gpib_scan_finished)
        self.scan_thread.error_signal.connect(self._on_gpib_scan_error)
        self.scan_thread.start()

    def _on_gpib_scan_finished(self, found):
        """GPIB 扫描完成回调"""
        self.btn_scan_gpib.setEnabled(True)
        self.btn_scan_gpib.setText("自动识别")
        self.btn_connect.setEnabled(True)

        if not found:
            self._append_log("[提示] 未找到任何 GPIB 仪器，请检查线缆连接")
            QMessageBox.information(self, "自动识别", "未找到 GPIB 仪器，请检查线缆连接")
            return

        if len(found) == 1:
            addr, idn = found[0]
            self.spin_gpib_addr.setValue(addr)
            self._append_log(f"识别到地址 {addr}：{idn}")
            QMessageBox.information(self, "自动识别", f"识别到地址 {addr}\n{idn}")
        else:
            lines = [f"地址 {addr}：{idn}" for addr, idn in found]
            self._append_log("发现多个 GPIB 仪器：" + "；".join(lines))
            QMessageBox.information(self, "自动识别",
                                    "发现多个 GPIB 仪器：\n\n" + "\n".join(lines) +
                                    "\n\n请手动选择地址")

    def _on_gpib_scan_error(self, error_msg):
        """GPIB 扫描出错回调"""
        self.btn_scan_gpib.setEnabled(True)
        self.btn_scan_gpib.setText("自动识别")
        self.btn_connect.setEnabled(True)
        self._append_log(f"[错误] GPIB 扫描失败：{error_msg}")
        QMessageBox.warning(self, "扫描失败", f"GPIB 扫描失败：{error_msg}")

    def _on_disconnect(self):
        """点击"断开仪器"按钮"""
        success, message = self.cmw500.disconnect()
        self._append_log(message)

        # 更新按钮状态
        self.btn_connect.setEnabled(True)
        self.btn_disconnect.setEnabled(False)
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(False)
        # 更新状态标签
        self.label_status.setText("● 未连接")
        self.label_status.setStyleSheet("color: #999999;")
        self.statusBar().showMessage("仪器已断开")

        # 恢复接口配置可编辑
        self._set_interface_inputs_enabled(True)

    def _on_start_test(self):
        """点击"开始测试"按钮"""
        if not self.cmw500.connected:
            QMessageBox.warning(self, "提示", "请先连接仪器")
            return

        # 获取当前勾选的套件和测量项
        suites, items = self._get_enabled_suites_and_items()
        if not suites:
            QMessageBox.warning(self, "提示", "请至少勾选一个测试套件")
            return

        is_rx_per = "rx_per" in suites
        has_tx = "tx_modulation" in suites or "tx_power" in suites

        # 同步 RX PER 配置（如有）
        if is_rx_per:
            try:
                self._sync_rx_per_config_from_ui()
            except ValueError as e:
                QMessageBox.warning(self, "参数错误", str(e))
                return

        # 应用 TX 信道选择（如有）
        if has_tx:
            if not items:
                QMessageBox.warning(self, "提示", "请至少勾选一个测量项")
                return
            channel_text = self._combo_tx_channel_mod.currentText()
            if channel_text == "全部 (0~39)":
                self.config["test_params"]["channel_start"] = 0
                self.config["test_params"]["channel_end"] = 39
            else:
                ch = int(channel_text)
                self.config["test_params"]["channel_start"] = ch
                self.config["test_params"]["channel_end"] = ch

        # 根据首个执行的套件初始化表格列
        mod_keys = items & set(MODULATION_ITEMS.keys())
        pow_keys = items & set(POWER_ITEMS.keys())
        if has_tx:
            self._build_table_columns(mod_keys, pow_keys, test_type="tx")
        else:
            self._build_table_columns(set(), set(), test_type="rx_per")

        # 应用新表头
        self.table.setColumnCount(len(self.TABLE_COLUMNS))
        self.table.setHorizontalHeaderLabels(self.TABLE_COLUMNS)
        self.table.setRowCount(0)
        self.progress_bar.setValue(0)

        # 创建工作线程
        self.test_worker = TestWorker(
            self.cmw500, self.config,
            enabled_suites=suites,
            enabled_items=items,
        )
        self.test_worker.log_signal.connect(self._append_log)
        self.test_worker.switch_table_signal.connect(self._on_switch_table)
        self.test_worker.result_signal.connect(self._on_channel_result)
        self.test_worker.progress_signal.connect(self._on_progress_update)
        self.test_worker.finished_signal.connect(self._on_test_finished)
        self.test_worker.error_signal.connect(self._on_test_error)

        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.btn_export.setEnabled(False)
        self.btn_disconnect.setEnabled(False)
        self.statusBar().showMessage("测试执行中...")
        self.test_worker.start()

    def _on_stop_test(self):
        """点击"停止测试"按钮"""
        if self.test_worker:
            self.test_worker.stop_test()
            self._append_log("已发送停止信号，等待当前信道完成...")
            self.btn_stop.setEnabled(False)

    def _on_export(self):
        """点击"导出 Excel"按钮"""
        if not hasattr(self, '_last_results') or not self._last_results:
            QMessageBox.information(self, "提示", "没有可导出的测试数据")
            return

        try:
            from data_exporter import DataExporter
            exporter = DataExporter(self.config)
            filepath = exporter.export_to_excel(
                self._last_results,
                self.config["test_params"]
            )
            self._append_log(f"测试结果已导出：{filepath}")
            self.statusBar().showMessage(f"导出成功：{filepath}")
            QMessageBox.information(self, "导出成功", f"文件已保存至：\n{filepath}")
        except Exception as e:
            self._append_log(f"[错误] 导出失败：{e}")
            QMessageBox.critical(self, "导出失败", str(e))

    # ============================================================
    #                    信号槽函数（线程安全）
    # ============================================================

    def _on_switch_table(self, test_type, mod_keys, pow_keys):
        """测试阶段切换时更新表格列（由工作线程信号触发）"""
        if test_type == "rx_per":
            self._build_table_columns(set(), set(), test_type="rx_per")
        else:
            self._build_table_columns(mod_keys, pow_keys, test_type="tx")

        self.table.setColumnCount(len(self.TABLE_COLUMNS))
        self.table.setHorizontalHeaderLabels(self.TABLE_COLUMNS)
        self.table.setRowCount(0)

    def _on_channel_result(self, channel, result):
        """接收单个信道测试结果（由工作线程信号触发）"""
        row = self.table.rowCount()
        self.table.insertRow(row)
        self._set_cell(row, 0, str(channel))

        if getattr(self, "_current_test_type", "tx") == "rx_per":
            # RX PER 结果：灵敏度、PER 阈值、最后通过功率、最后失败功率、判定
            self._set_cell(row, 1, f"{result.get('sensitivity'):.1f}" if result.get('sensitivity') is not None else "N/A")
            self._set_cell(row, 2, f"{result.get('per_threshold', ''):.1f}")
            self._set_cell(row, 3, f"{result.get('last_pass_power'):.1f}" if result.get('last_pass_power') is not None else "N/A")
            self._set_cell(row, 4, f"{result.get('last_fail_power'):.1f}" if result.get('last_fail_power') is not None else "N/A")
            pf = result.get("pass_fail", "--")
            self._set_cell(row, 5, pf, is_pass_fail=True)
            self.table.scrollToBottom()
            return

        col = 1
        cfg = self.config["test_params"]
        pow_cfg = cfg.get("power_measurements", {})

        for entry in self.MEASUREMENT_KEYS:
            if isinstance(entry, str):
                # 调制项：数值 + 判定
                key = entry
                value = result.get(key)
                self._set_cell(row, col, str(value) if value is not None else "N/A")
                col += 1
                pf = result.get("pass_fail", {}).get(key, "N/A")
                self._set_cell(row, col, pf, is_pass_fail=True)
                col += 1
            else:
                # 功率项：(key, has_limit)
                key, has_limit = entry
                value = result.get(key)
                self._set_cell(row, col, str(value) if value is not None else "N/A")
                col += 1
                if has_limit:
                    pf = result.get("pass_fail", {}).get(key, "N/A")
                    self._set_cell(row, col, pf, is_pass_fail=True)
                    col += 1

        self.table.scrollToBottom()

    def _on_progress_update(self, current, total):
        """更新进度条（由工作线程信号触发）"""
        percent = int(current / total * 100) if total > 0 else 0
        self.progress_bar.setValue(percent)
        self.progress_label.setText(f"进度：{current} / {total}")

    def _on_test_finished(self, results):
        """测试完成处理（由工作线程信号触发）"""
        self._last_results = results  # 保存结果供导出使用

        # 恢复按钮状态
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.btn_export.setEnabled(len(results) > 0)
        self.btn_disconnect.setEnabled(True)

        tx_results = [r for r in results if r.get("test_type") != "rx_per"]
        rx_results = [r for r in results if r.get("test_type") == "rx_per"]

        messages = []
        if tx_results:
            total_tx = len(tx_results)
            all_pass = sum(
                1 for r in tx_results
                if "pass_fail" in r and all(v == "PASS" for v in r["pass_fail"].values())
            )
            self._append_log(f"=== TX 测试完成：{all_pass}/{total_tx} 个信道全部通过 ===")
            messages.append(f"TX 通过 {all_pass}/{total_tx}")

        if rx_results:
            total_rx = len(rx_results)
            found = sum(1 for r in rx_results if r.get("sensitivity") is not None)
            all_pass = sum(1 for r in rx_results if r.get("pass_fail") == "PASS")
            self._append_log(f"=== RX PER 测试完成：{found}/{total_rx} 个信道找到灵敏度点，通过 {all_pass}/{total_rx} 个信道 ===")
            messages.append(f"RX PER 找到 {found}/{total_rx}，通过 {all_pass}/{total_rx}")

        self.statusBar().showMessage("；".join(messages) if messages else "测试完成")

    def _on_test_error(self, error_msg):
        """测试异常处理（由工作线程信号触发）"""
        self._append_log(f"[严重错误] {error_msg}")
        # 恢复按钮状态
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.btn_disconnect.setEnabled(True)
        self.statusBar().showMessage("测试异常终止")
        QMessageBox.critical(self, "测试错误", error_msg)

    # ============================================================
    #                    辅助方法
    # ============================================================

    def _append_log(self, message):
        """向日志窗口追加一条消息"""
        self.log_text.append(message)
        # 自动滚动到底部
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _set_cell(self, row, col, text, is_pass_fail=False):
        """
        设置表格单元格内容和样式

        参数:
            row:          行号
            col:          列号
            text:         单元格文本
            is_pass_fail: 是否为判定列（用于着色）
        """
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

        if is_pass_fail:
            if text == "PASS":
                item.setBackground(QColor("#C6EFCE"))  # 浅绿色
                item.setForeground(QColor("#006100"))  # 深绿色文字
            elif text == "FAIL":
                item.setBackground(QColor("#FFC7CE"))  # 浅红色
                item.setForeground(QColor("#9C0006"))  # 深红色文字
            elif text == "ERROR":
                item.setBackground(QColor("#FFEB9C"))  # 浅黄色
                item.setForeground(QColor("#9C6500"))  # 深黄色文字

        self.table.setItem(row, col, item)
