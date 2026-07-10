"""
CMW500 BLE 自动化测试工具 - 下拉式信道选择器

为 TX 调制 / TX 功率 / RX PER 三个套件提供统一的信道选择 UI：
- 下拉按钮显示当前已选信道数量
- 点击按钮弹出选择面板
- 面板内 4 列 × 10 行共 40 个信道勾选框
- 顶部提供"全选""清空"快捷按钮
- 点击面板外部自动关闭
"""

from PyQt6.QtWidgets import (
    QWidget, QFrame, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QCheckBox, QLabel
)
from PyQt6.QtCore import Qt, pyqtSignal, QPoint
from PyQt6.QtGui import QFont


class ChannelSelectorPopup(QFrame):
    """信道选择下拉面板（Popup 弹窗）"""

    selection_changed = pyqtSignal()

    def __init__(self, parent=None, default_channels=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Popup)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setFrameShadow(QFrame.Shadow.Raised)
        self._checkboxes = {}
        self._init_ui(default_channels)

    def _init_ui(self, default_channels):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        btn_font = QFont("Microsoft YaHei", 9)
        ch_font = QFont("Microsoft YaHei", 9)

        # 顶部快捷按钮
        header = QHBoxLayout()
        btn_all = QPushButton("全选")
        btn_none = QPushButton("清空")
        btn_all.setFont(btn_font)
        btn_none.setFont(btn_font)
        btn_all.setFixedWidth(60)
        btn_none.setFixedWidth(60)
        btn_all.clicked.connect(self.select_all)
        btn_none.clicked.connect(self.select_none)
        header.addWidget(btn_all)
        header.addWidget(btn_none)
        header.addStretch()
        layout.addLayout(header)

        # 4 列 × 10 行网格
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)

        target = set(default_channels) if default_channels else set(range(40))
        for ch in range(40):
            chk = QCheckBox(str(ch))
            chk.setFont(ch_font)
            chk.setChecked(ch in target)
            chk.stateChanged.connect(lambda _: self.selection_changed.emit())
            col = ch // 10
            row = ch % 10
            grid.addWidget(chk, row, col)
            self._checkboxes[ch] = chk

        layout.addLayout(grid)

    def select_all(self):
        for chk in self._checkboxes.values():
            chk.setChecked(True)
        self.selection_changed.emit()

    def select_none(self):
        for chk in self._checkboxes.values():
            chk.setChecked(False)
        self.selection_changed.emit()

    def get_selected_channels(self):
        return sorted(ch for ch, chk in self._checkboxes.items() if chk.isChecked())

    def set_selected_channels(self, channels):
        target = set(channels)
        for ch, chk in self._checkboxes.items():
            chk.setChecked(ch in target)


class ChannelSelector(QWidget):
    """
    下拉式信道选择器主控件

    公开接口：
      - get_selected_channels() -> list[int]
      - set_selected_channels(list[int])
      - setEnabled(bool)
    """

    def __init__(self, parent=None, default_channels=None, label="信道选择"):
        super().__init__(parent)
        self._label_text = label
        self._default_channels = default_channels or list(range(40))
        self._popup = None
        self._init_ui()

    def _init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        lbl = QLabel(self._label_text)
        lbl.setFont(QFont("Microsoft YaHei", 10))
        layout.addWidget(lbl)

        self._btn = QPushButton("信道选择 ▼（已选 40/40）")
        self._btn.setFont(QFont("Microsoft YaHei", 9))
        self._btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn.setFixedWidth(150)
        self._btn.clicked.connect(self._show_popup)
        layout.addWidget(self._btn)
        layout.addStretch()

        self._update_button_text()

    def _show_popup(self):
        if self._popup is None:
            self._popup = ChannelSelectorPopup(self, self._default_channels)
            self._popup.selection_changed.connect(self._update_button_text)

        self._popup.set_selected_channels(self.get_selected_channels())
        pos = self._btn.mapToGlobal(QPoint(0, self._btn.height()))
        self._popup.move(pos)
        self._popup.show()
        self._popup.setFocus()

    def _update_button_text(self):
        count = len(self.get_selected_channels())
        self._btn.setText(f"信道选择 ▼（已选 {count}/40）")

    def get_selected_channels(self):
        if self._popup is None:
            return list(self._default_channels)
        return self._popup.get_selected_channels()

    def set_selected_channels(self, channels):
        self._default_channels = list(channels)
        if self._popup is not None:
            self._popup.set_selected_channels(channels)
        self._update_button_text()

    def setEnabled(self, enabled):
        super().setEnabled(enabled)
        self._btn.setEnabled(enabled)
