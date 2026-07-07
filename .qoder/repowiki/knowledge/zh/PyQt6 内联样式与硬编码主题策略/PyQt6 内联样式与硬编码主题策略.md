---
kind: frontend_style
name: PyQt6 内联样式与硬编码主题策略
category: frontend_style
scope:
    - '**'
source_files:
    - gui_main.py
---

本仓库为基于 PyQt6 的桌面测试工具，前端风格完全由 Python 代码内联控制，未使用任何外部 CSS/SCSS/QSS 文件或独立主题系统。所有视觉样式均通过 `setStyleSheet()` 和 Qt 组件属性在 `gui_main.py` 中直接声明，属于典型的“代码即样式”（code-as-style）模式。

**核心实现位置**：
- `gui_main.py` 是唯一的前端样式来源，包含按钮、下拉框、日志区、状态标签等全部 UI 样式定义
- 无独立的样式文件、资源目录或主题配置文件

**样式组织方式**：
1. **QSS 内联字符串**：通过 `setStyleSheet()` 方法以多行字符串形式注入样式，如按钮背景色、悬停态、禁用态分别用 `QPushButton { background-color: ... }` / `QPushButton:hover { ... }` / `QPushButton:disabled { ... }` 三段规则描述
2. **Python 对象属性设置**：字体使用 `QFont("微软雅黑", 10)`、颜色使用 `QColor("#4CAF50")`、对齐使用 `Qt.AlignmentFlag.AlignCenter` 等原生 API
3. **布局约束**：通过 `setMinimumWidth()`、`setMaximumWidth()`、`setFixedHeight()`、`setContentsMargins()`、`setSpacing()` 等硬性数值控制尺寸与间距

**设计决策与约定**：
- **颜色体系**：采用 Material Design 色系（`#4CAF50` 绿色=连接/成功、`#f44336` 红色=断开/失败、`#2196F3` 蓝色=开始、`#FF9800` 橙色=停止、`#9C27B0` 紫色=导出），但颜色值以硬编码散落在各处，未抽象为常量
- **字体统一**：界面文本使用「微软雅黑」，输入/日志区域使用「Consolas」等宽字体
- **表格着色**：PASS/FAIL/ERROR 判定列使用浅绿/浅红/浅黄背景 + 深色文字，通过 `_set_cell()` 辅助方法集中处理
- **日志区暗色主题**：`background-color: #1e1e1e; color: #cccccc` 模拟终端风格
- **交互反馈**：按钮 hover 态提供浅色变体，禁用态使用对应颜色的浅灰版本

**开发者应遵循的规则**：
1. 新增 UI 控件时，如需自定义样式，应在对应 `_create_xxx_group()` 方法内以 `setStyleSheet()` 字符串形式声明，保持与现有按钮样式一致的三段式结构（正常/hover/disabled）
2. 表格单元格样式统一通过 `_set_cell()` 方法设置，不要直接操作 `QTableWidgetItem` 的颜色属性
3. 避免在业务逻辑文件中混入样式代码，所有 UI 相关样式应集中在 `gui_main.py` 的 CMW500MainWindow 类中
4. 当前无全局样式变量，若需调整主题色，需逐个修改硬编码的十六进制颜色值