"""
CMW500 自动化测试工具 - PyQt6 上位机界面

功能说明：
    提供图形化操作界面，包含：
    - 接口配置区：LAN/GPIB/USB 自适应布局
    - 测试项配置区：勾选测试套件（TX功率/RX PER/TX调制）和具体测量项
    - 操作按钮区：连接、断开、开始测试、停止测试、测试结果、导出 Excel
    - 结果弹窗：独立窗口按测试类型分页显示进度、表格和导出
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

import threading
import multiprocessing

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
from instrument_connection import CMW500Connection, _scan_gpib_worker
from test_executor import MODULATION_ITEMS, POWER_ITEMS, BLERxPerTest
from channel_selector import ChannelSelector
from result_dialog import TestResultDialog


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

    def __init__(self, cmw500, config, enabled_suites=None, enabled_items=None,
                 channels=None):
        super().__init__()
        self.cmw500          = cmw500
        self.config          = config
        self.enabled_suites  = enabled_suites
        self.enabled_items   = enabled_items
        self.channels        = channels or {}
        self.test_executor   = None

    def run(self):
        """线程执行入口：按固定顺序执行 TX 功率 / RX PER / TX 调制"""
        try:
            enabled_suites = set(self.enabled_suites or [])
            enabled_items  = set(self.enabled_items or [])
            mod_keys = enabled_items & set(MODULATION_ITEMS.keys())
            pow_keys = enabled_items & set(POWER_ITEMS.keys())
            channels = self.channels or {}

            results = []

            # 阶段1：TX 功率测试
            if "tx_power" in enabled_suites and pow_keys:
                self.switch_table_signal.emit("tx_power", set(), pow_keys)
                from test_executor import BLETxModulationTest
                self.test_executor = BLETxModulationTest(
                    self.cmw500, self.config,
                    enabled_suites=["tx_power"],
                    enabled_items=list(pow_keys),
                    channels=channels.get("tx_power"),
                )
                self.test_executor.set_callbacks(
                    log_cb=lambda msg: self.log_signal.emit(msg),
                    progress_cb=lambda cur, total: self.progress_signal.emit(cur, total),
                    result_cb=lambda ch, data: self.result_signal.emit(ch, data),
                )
                results.extend(self.test_executor.run())

            # 阶段2：RX PER 灵敏度搜索
            if "rx_per" in enabled_suites and not self.isInterruptionRequested():
                if not (self.test_executor and self.test_executor.is_stopped):
                    self.switch_table_signal.emit("rx_per", set(), set())
                    self.test_executor = BLERxPerTest(
                        self.cmw500, self.config,
                        channels=channels.get("rx_per"),
                    )
                    self.test_executor.set_callbacks(
                        log_cb=lambda msg: self.log_signal.emit(msg),
                        progress_cb=lambda cur, total: self.progress_signal.emit(cur, total),
                        result_cb=lambda ch, data: self.result_signal.emit(ch, data),
                    )
                    results.extend(self.test_executor.run())

            # 阶段3：TX 调制测试
            if "tx_modulation" in enabled_suites and mod_keys and not self.isInterruptionRequested():
                if not (self.test_executor and self.test_executor.is_stopped):
                    self.switch_table_signal.emit("tx_modulation", mod_keys, set())
                    from test_executor import BLETxModulationTest
                    self.test_executor = BLETxModulationTest(
                        self.cmw500, self.config,
                        enabled_suites=["tx_modulation"],
                        enabled_items=list(mod_keys),
                        channels=channels.get("tx_modulation"),
                    )
                    self.test_executor.set_callbacks(
                        log_cb=lambda msg: self.log_signal.emit(msg),
                        progress_cb=lambda cur, total: self.progress_signal.emit(cur, total),
                        result_cb=lambda ch, data: self.result_signal.emit(ch, data),
                    )
                    results.extend(self.test_executor.run())

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

    在独立子进程中执行 GPIB 扫描，子进程阻塞或卡死时
    可通过 terminate/kill 强制结束，避免 GUI 主线程卡死。
    """
    finished_signal = pyqtSignal(list)
    error_signal    = pyqtSignal(str)

    def __init__(self, board=0, timeout=3000, max_wait=35):
        super().__init__()
        self.board = board
        self.timeout = timeout
        self.max_wait = max_wait
        self._process = None
        self._cancelled = False

    def run(self):
        """线程执行入口：启动子进程并等待结果"""
        try:
            ctx = multiprocessing.get_context("spawn")
            result_queue = ctx.Queue()
            self._process = ctx.Process(
                target=_scan_gpib_worker,
                args=(self.board, self.timeout, None, result_queue)
            )
            self._process.start()

            # 每 0.5 秒检查一次，既给 GUI 刷新机会，也能及时响应取消
            waited = 0
            interval = 0.5
            while waited < self.max_wait and self._process.is_alive():
                if self._cancelled:
                    break
                self._process.join(timeout=interval)
                waited += interval

            if self._process.is_alive():
                self._process.terminate()
                self._process.join(timeout=2)
                if self._process.is_alive():
                    self._process.kill()
                    self._process.join(timeout=2)
                self.finished_signal.emit([])
                return

            try:
                status, payload = result_queue.get_nowait()
                if status == "found":
                    self.finished_signal.emit(payload)
                else:
                    self.error_signal.emit(str(payload))
            except Exception as e:
                self.error_signal.emit(str(e))
        except Exception as e:
            self.error_signal.emit(str(e))

    def cancel(self):
        """请求取消扫描"""
        self._cancelled = True
        if self._process is not None and self._process.is_alive():
            self._process.terminate()
            self._process.join(timeout=2)
            if self._process.is_alive():
                self._process.kill()
                self._process.join(timeout=2)


class CMW500MainWindow(QMainWindow):
    """CMW500 自动化测试主窗口"""

    def __init__(self, config, cmw500):
        super().__init__()
        self.config = config
        self.cmw500 = cmw500
        self.test_worker = None
        self.scan_thread = None
        self.result_dialog = None
        self._last_results = []

        self.setWindowTitle("CMW500 BLE 自动化测试工具")
        self.setMinimumSize(800, 560)
        self.resize(900, 650)

        self._init_ui()
        self.statusBar().showMessage("就绪 - 请先连接仪器")

    # ============================================================
    #                    界面初始化
    # ============================================================

    def _init_ui(self):
        """构建整体界面布局"""
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
        top_layout.addWidget(self._create_test_items_group(), stretch=1)
        main_layout.addLayout(top_layout, stretch=1)

        # ----- 按钮操作区 -----
        main_layout.addWidget(self._create_button_group())

        # ----- 底部：日志窗口（固定高度） -----
        main_layout.addWidget(self._create_log_group())

    def _open_dut_settings(self):
        """打开 DUT 连接设置对话框"""
        dialog = DUTSettingsDialog(self.config, self.cmw500, parent=self)
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
        btn_font = QFont("微软雅黑", 10)

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

        # ---- DUT 设置按钮 ----
        self.btn_dut_settings = QPushButton("DUT 设置")
        self.btn_dut_settings.setFont(btn_font)
        self.btn_dut_settings.setSizePolicy(QSizePolicy_Expanding, QSizePolicy_Fixed)
        self.btn_dut_settings.setMinimumWidth(90)
        self.btn_dut_settings.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_dut_settings.setStyleSheet(
            "QPushButton { background-color: #FF9800; color: white; "
            "padding: 8px 12px; border-radius: 4px; }"
            "QPushButton:hover { background-color: #F57C00; }"
            "QPushButton:disabled { background-color: #FFCC80; }"
        )
        self.btn_dut_settings.clicked.connect(self._open_dut_settings)
        outer_layout.addWidget(self.btn_dut_settings)

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

        # ---- 测试套件行 ----
        suite_row = QHBoxLayout()
        suite_row.setSpacing(16)
        suite_lbl = QLabel("套件：")
        suite_lbl.setFont(label_font)
        suite_row.addWidget(suite_lbl)

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

        self.chk_suite_mod = QCheckBox("TX 调制测试")
        self.chk_suite_mod.setFont(cb_font)
        self.chk_suite_mod.setChecked(suite_cfg.get("tx_modulation", {}).get("enabled", False))
        self.chk_suite_mod.toggled.connect(self._on_suite_toggled)
        suite_row.addWidget(self.chk_suite_mod)
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

        # ---- 具体测量项勾选（垂直堆叠卡片式布局，外加滚动条）----
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setMinimumHeight(120)

        items_widget = QWidget()
        items_layout = QVBoxLayout(items_widget)
        items_layout.setContentsMargins(0, 0, 0, 0)
        items_layout.setSpacing(8)
        items_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        # 1) TX 功率项
        pow_widget = QWidget()
        pow_widget.setSizePolicy(QSizePolicy_Expanding, QSizePolicy_Expanding)
        pow_outer = QVBoxLayout(pow_widget)
        pow_outer.setContentsMargins(0, 0, 0, 0)
        pow_outer.setSpacing(4)

        pow_title_row = QHBoxLayout()
        pow_title_row.setSpacing(6)
        pow_icon = QLabel("⚡")
        pow_icon.setFont(QFont("Segoe UI Emoji", 12))
        pow_title = QLabel("TX 功率测试")
        pow_title.setFont(QFont("微软雅黑", 12, QFont.Weight.Bold))
        pow_title.setStyleSheet("color: #558B2F;")
        pow_title_row.addWidget(pow_icon)
        pow_title_row.addWidget(pow_title)
        pow_title_row.addStretch()
        pow_outer.addLayout(pow_title_row)

        default_channels = cfg_tp.get("selected_channels", {}).get("tx_power", list(range(40)))
        self._channel_selector_pow = ChannelSelector(default_channels=default_channels, label="信道选择")
        pow_outer.addWidget(self._channel_selector_pow)

        self._pow_checkboxes = {}
        for key, (_, _, name, unit) in POWER_ITEMS.items():
            chk = QCheckBox(f"{name}  ({unit})")
            chk.setFont(cb_font)
            chk.setChecked(pow_cfg.get(key, {}).get("enabled", True))
            self._pow_checkboxes[key] = chk
            pow_outer.addWidget(chk)
        pow_outer.addStretch()
        self._pow_widget = pow_widget

        # 2) RX PER 配置编辑区
        rx_widget = QWidget()
        rx_widget.setSizePolicy(QSizePolicy_Expanding, QSizePolicy_Expanding)
        rx_outer = QVBoxLayout(rx_widget)
        rx_outer.setContentsMargins(0, 0, 0, 0)
        rx_outer.setSpacing(6)

        rx_title_row = QHBoxLayout()
        rx_title_row.setSpacing(6)
        rx_icon = QLabel("🔍")
        rx_icon.setFont(QFont("Segoe UI Emoji", 12))
        rx_title_lbl = QLabel("RX PER 测试")
        rx_title_lbl.setFont(QFont("微软雅黑", 12, QFont.Weight.Bold))
        rx_title_lbl.setStyleSheet("color: #C62828;")
        rx_title_row.addWidget(rx_icon)
        rx_title_row.addWidget(rx_title_lbl)
        rx_title_row.addStretch()
        rx_outer.addLayout(rx_title_row)

        default_channels = cfg_tp.get("selected_channels", {}).get("rx_per", list(range(40)))
        self._channel_selector_rx = ChannelSelector(default_channels=default_channels, label="信道选择")
        rx_outer.addWidget(self._channel_selector_rx)

        rx_cfg = cfg_tp.get("rx_per", {})
        self._rx_inputs = {}

        # 4列表单：col0=左标签  col1=左控件  col2=空  col3=右标签  col4=右控件
        form = QGridLayout()
        form.setContentsMargins(0, 6, 0, 0)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)
        form.setColumnMinimumWidth(0, 68)   # 左标签
        form.setColumnMinimumWidth(3, 68)   # 右标签
        form.setColumnMinimumWidth(2, 24)   # 中间分隔
        form.setColumnStretch(1, 1)
        form.setColumnStretch(4, 1)

        fnt_lbl  = QFont("微软雅黑", 10)
        fnt_inp  = QFont("微软雅黑", 10)
        fnt_unit = QFont("微软雅黑", 9)

        def _lbl(text, align_right=True):
            w = QLabel(text)
            w.setFont(fnt_lbl)
            if align_right:
                w.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            return w

        def _edit(val, width=90):
            ed = QLineEdit(str(val))
            ed.setFont(fnt_inp)
            ed.setFixedWidth(width)
            return ed

        def _combo(items, current, width=110):
            cb = QComboBox()
            cb.setFont(fnt_inp)
            cb.addItems(items)
            cb.setCurrentText(current)
            cb.setFixedWidth(width)
            return cb

        def _with_unit(widget, unit_text):
            row = QHBoxLayout()
            row.setSpacing(3)
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(widget)
            u = QLabel(unit_text)
            u.setFont(fnt_unit)
            u.setStyleSheet("color: #888;")
            row.addWidget(u)
            row.addStretch()
            w = QWidget()
            w.setLayout(row)
            return w

        # Row 0: 搜索范围  |  包型
        start_edit = _edit(rx_cfg.get("start_power", -90.0), 68)
        end_edit   = _edit(rx_cfg.get("end_power",   -100.0), 68)
        arrow_lbl  = QLabel("→"); arrow_lbl.setFont(fnt_lbl)
        range_hbox = QHBoxLayout(); range_hbox.setSpacing(4); range_hbox.setContentsMargins(0, 0, 0, 0)
        range_hbox.addWidget(start_edit); range_hbox.addWidget(arrow_lbl); range_hbox.addWidget(end_edit)
        u_dbm = QLabel("dBm"); u_dbm.setFont(fnt_unit); u_dbm.setStyleSheet("color: #888;")
        range_hbox.addWidget(u_dbm); range_hbox.addStretch()
        range_w = QWidget(); range_w.setLayout(range_hbox)
        pkt_type_combo = _combo(["PRBS9", "PRBS15", "11110000", "10101010"],
                                 rx_cfg.get("packet_type", "PRBS9"))
        form.addWidget(_lbl("搜索范围:"), 0, 0)
        form.addWidget(range_w,            0, 1)
        form.addWidget(_lbl("包型:"),     0, 3)
        form.addWidget(pkt_type_combo,     0, 4)
        self._rx_inputs["start_power"]  = start_edit
        self._rx_inputs["end_power"]    = end_edit
        self._rx_inputs["packet_type"]  = pkt_type_combo

        # Row 1: 功率步进  |  PER 阈值
        step_edit = _edit(rx_cfg.get("step_size", 0.5))
        per_edit  = _edit(rx_cfg.get("per_threshold", 30.8))
        form.addWidget(_lbl("功率步进:"), 1, 0)
        form.addWidget(_with_unit(step_edit, "dB"), 1, 1)
        form.addWidget(_lbl("PER 阈值:"),  1, 3)
        form.addWidget(_with_unit(per_edit, "%"),    1, 4)
        self._rx_inputs["step_size"]     = step_edit
        self._rx_inputs["per_threshold"] = per_edit

        # Row 2: 每点包数  |  PHY
        pkt_edit  = _edit(rx_cfg.get("packet_count", 1500))
        phy_combo = _combo(["LE1M", "LE2M", "LE500K", "LE125K"],
                           rx_cfg.get("phy_type", "LE1M"))
        form.addWidget(_lbl("每点包数:"), 2, 0)
        form.addWidget(pkt_edit,           2, 1)
        form.addWidget(_lbl("PHY:"),       2, 3)
        form.addWidget(phy_combo,          2, 4)
        self._rx_inputs["packet_count"] = pkt_edit
        self._rx_inputs["phy_type"]     = phy_combo

        rx_outer.addLayout(form)
        rx_outer.addStretch()
        self._rx_widget = rx_widget

        # 3) TX 调制项
        mod_widget = QWidget()
        mod_outer = QVBoxLayout(mod_widget)
        mod_outer.setContentsMargins(0, 0, 0, 0)
        mod_outer.setSpacing(4)

        mod_title_row = QHBoxLayout()
        mod_title_row.setSpacing(6)
        mod_icon = QLabel("\U0001f4ca")
        mod_icon.setFont(QFont("Segoe UI Emoji", 12))
        mod_title = QLabel("TX 调制测试")
        mod_title.setFont(QFont("微软雅黑", 12, QFont.Weight.Bold))
        mod_title.setStyleSheet("color: #1565C0;")
        mod_title_row.addWidget(mod_icon)
        mod_title_row.addWidget(mod_title)
        mod_title_row.addStretch()
        mod_outer.addLayout(mod_title_row)

        default_channels = cfg_tp.get("selected_channels", {}).get("tx_modulation", list(range(40)))
        self._channel_selector_mod = ChannelSelector(default_channels=default_channels, label="信道选择")
        mod_outer.addWidget(self._channel_selector_mod)

        self._mod_checkboxes = {}
        mod_items = list(MODULATION_ITEMS.items())
        half = (len(mod_items) + 1) // 2

        mod_cols = QHBoxLayout()
        mod_cols.setSpacing(16)
        mod_left  = QVBoxLayout()
        mod_left.setSpacing(4)
        mod_right = QVBoxLayout()
        mod_right.setSpacing(4)

        for i, (key, (_, _, name, unit, _)) in enumerate(mod_items):
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

        # 水平分隔线
        hline1 = QFrame()
        hline1.setFrameShape(QFrame.Shape.HLine)
        hline1.setFrameShadow(QFrame.Shadow.Sunken)
        self._hline_pow_rx = hline1

        hline2 = QFrame()
        hline2.setFrameShape(QFrame.Shape.HLine)
        hline2.setFrameShadow(QFrame.Shadow.Sunken)
        self._hline_rx_mod = hline2

        # 按顺序添加：TX功率、RX PER、TX调制
        items_layout.addWidget(pow_widget)
        items_layout.addWidget(hline1)
        items_layout.addWidget(rx_widget)
        items_layout.addWidget(hline2)
        items_layout.addWidget(mod_widget)

        scroll.setWidget(items_widget)
        outer.addWidget(scroll, stretch=1)

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
        self._hline_pow_rx.setVisible(pow_on and rx_on)
        self._hline_rx_mod.setVisible(rx_on and mod_on)

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

        # ---- 测试结果按钮 ----
        self.btn_results = QPushButton("测试结果")
        self.btn_results.setFont(btn_font)
        self.btn_results.setEnabled(True)
        self.btn_results.setSizePolicy(QSizePolicy_Expanding, QSizePolicy_Fixed)
        self.btn_results.setMinimumWidth(90)
        self.btn_results.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_results.setStyleSheet(
            "QPushButton { background-color: #9C27B0; color: white; "
            "padding: 8px 12px; border-radius: 4px; }"
            "QPushButton:hover { background-color: #7B1FA2; }"
            "QPushButton:disabled { background-color: #CE93D8; }"
        )
        self.btn_results.clicked.connect(self._on_show_results)
        layout.addWidget(self.btn_results)

        # 弹性空间
        layout.addStretch()

        # ---- 连接状态标签 ----
        self.label_status = QLabel("● 未连接")
        self.label_status.setFont(QFont("微软雅黑", 11, QFont.Weight.Bold))
        self.label_status.setStyleSheet("color: #999999;")
        layout.addWidget(self.label_status)

        return group

    def _create_log_group(self):
        """创建日志窗口"""
        group = QGroupBox("运行日志")
        group.setSizePolicy(QSizePolicy_Expanding, QSizePolicy_Maximum)
        layout = QVBoxLayout(group)
        layout.setContentsMargins(6, 4, 6, 6)
        layout.setSpacing(0)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 9))
        self.log_text.setFixedHeight(90)
        self.log_text.setStyleSheet(
            "QTextEdit { background-color: #1e1e1e; color: #cccccc; border: none; }"
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
            QMessageBox.information(self, "连接成功", message)
        else:
            self._append_log(f"[错误] {message}")
            QMessageBox.warning(self, "连接失败", message)
            self.statusBar().showMessage("连接失败")
            # 连接失败时恢复接口配置可编辑
            self._set_interface_inputs_enabled(True)

    def _on_scan_gpib(self):
        """点击 GPIB 自动识别按钮 —— 在独立子进程中扫描可用地址"""
        # 再次点击可取消正在进行的扫描
        if self.scan_thread is not None and self.scan_thread.isRunning():
            self.scan_thread.cancel()
            self._append_log("正在取消 GPIB 扫描...")
            return

        board = self.spin_gpib_board.value()
        self._append_log(f"正在扫描 GPIB 板卡 {board} 的地址（子进程，最长 35 秒）...")
        self.btn_scan_gpib.setText("停止扫描")
        self.btn_scan_gpib.setEnabled(True)
        self.btn_connect.setEnabled(False)

        self.scan_thread = GPIBScanThread(board=board, timeout=3000, max_wait=35)
        self.scan_thread.finished_signal.connect(self._on_gpib_scan_finished)
        self.scan_thread.error_signal.connect(self._on_gpib_scan_error)
        self.scan_thread.start()

    def _on_gpib_scan_finished(self, found):
        """GPIB 扫描完成回调"""
        self._reset_gpib_scan_button()
        self.scan_thread = None

        if not found:
            self._append_log("[提示] 未找到任何 GPIB 仪器，请检查线缆连接或手动输入地址")
            QMessageBox.information(self, "自动识别", "未找到 GPIB 仪器，请检查线缆连接或手动输入地址")
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
        self._reset_gpib_scan_button()
        self.scan_thread = None
        self._append_log(f"[错误] GPIB 扫描失败：{error_msg}")
        QMessageBox.warning(self, "扫描失败", f"GPIB 扫描失败：{error_msg}")

    def _reset_gpib_scan_button(self):
        """恢复 GPIB 扫描按钮状态"""
        self.btn_scan_gpib.setText("自动识别")
        self.btn_scan_gpib.setEnabled(True)
        self.btn_connect.setEnabled(True)

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

        # 收集各套件独立信道选择
        channels = {
            "tx_power": self._channel_selector_pow.get_selected_channels(),
            "rx_per": self._channel_selector_rx.get_selected_channels(),
            "tx_modulation": self._channel_selector_mod.get_selected_channels(),
        }

        # 根据首个执行的套件初始化弹窗表格列
        mod_keys = items & set(MODULATION_ITEMS.keys())
        pow_keys = items & set(POWER_ITEMS.keys())

        # 创建/复用结果弹窗
        if self.result_dialog is None:
            self.result_dialog = TestResultDialog(self.config, parent=self)
        self.result_dialog.set_test_config(self.config)
        self.result_dialog.reset()
        first_type = "tx_power"
        if "tx_power" in suites and pow_keys:
            first_type = "tx_power"
        elif "rx_per" in suites:
            first_type = "rx_per"
        elif "tx_modulation" in suites and mod_keys:
            first_type = "tx_modulation"
        self.result_dialog.on_switch_table(first_type, mod_keys, pow_keys)
        self.result_dialog.show()
        self.result_dialog.raise_()
        self.result_dialog.activateWindow()

        # 创建工作线程
        self.test_worker = TestWorker(
            self.cmw500, self.config,
            enabled_suites=suites,
            enabled_items=items,
            channels=channels,
        )
        self.test_worker.log_signal.connect(self._append_log)
        self.test_worker.switch_table_signal.connect(self.result_dialog.on_switch_table)
        self.test_worker.result_signal.connect(self.result_dialog.on_channel_result)
        self.test_worker.progress_signal.connect(self.result_dialog.on_progress_update)
        self.test_worker.finished_signal.connect(self.result_dialog.on_test_finished)
        self.test_worker.finished_signal.connect(self._on_test_finished)
        self.test_worker.error_signal.connect(self._on_test_error)

        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.btn_disconnect.setEnabled(False)
        self.statusBar().showMessage("测试执行中...")
        self.test_worker.start()

    def _on_stop_test(self):
        """点击"停止测试"按钮"""
        if self.test_worker:
            self.test_worker.stop_test()
            self._append_log("已发送停止信号，等待当前信道完成...")
            self.btn_stop.setEnabled(False)

    def _on_show_results(self):
        """点击"测试结果"按钮，打开/激活结果弹窗"""
        if self.result_dialog is None:
            self.result_dialog = TestResultDialog(self.config, parent=self)
            self.result_dialog.set_test_config(self.config)
        self.result_dialog.show()
        self.result_dialog.raise_()
        self.result_dialog.activateWindow()

    # ============================================================
    #                    信号槽函数（线程安全）
    # ============================================================

    def _on_test_finished(self, results):
        """测试完成处理（由工作线程信号触发）"""
        self._last_results = results  # 保存结果供导出使用

        # 恢复按钮状态
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
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
            self._append_log(f"=== RX PER 测试完成：{found}/{total_rx} 个信道找到灵敏度点 ===")
            messages.append(f"RX PER 找到 {found}/{total_rx}")

        self.statusBar().showMessage("；".join(messages) if messages else "测试完成")

        # 弹窗通知
        QMessageBox.information(self, "测试完成", "测试完成")

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

