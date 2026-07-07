---
kind: error_handling
name: Python 异常处理与用户错误提示体系
category: error_handling
scope:
    - '**'
source_files:
    - main.py
    - instrument_connection.py
    - gui_main.py
    - test_executor.py
---

本仓库采用 Python 原生 try/except 加标准异常类型进行错误处理，未引入第三方错误框架或自定义异常类。整体呈现分层兜底、用户可见的风格：底层连接层抛出具体异常，上层通过返回值元组或 GUI 弹窗向用户反馈，顶层入口提供全局异常保护。

1. 采用的系统与方法
- 异常类型：仅使用 Python 内置异常（ConnectionError、RuntimeError）和第三方库异常（pyvisa.VisaIOError），未定义业务专用异常类。
- 错误传播方式：
  - 仪器连接层（instrument_connection.py）对 I/O 操作使用 try/except pyvisa.VisaIOError 捕获通信错误，并以 (bool, str) 元组返回；对未连接时调用命令的场景直接 raise ConnectionError。
  - 配置加载（main.py::load_config）将文件缺失/解析失败包装为 RuntimeError 向上抛出。
  - GUI 线程（gui_main.py::TestWorker.run）用 except Exception as e 捕获所有异常，并通过 error_signal 信号回传主线程。
- 用户可见的错误展示：
  - main.py::show_error_dialog 实现三级降级：PyQt6 QMessageBox.critical -> tkinter messagebox.showerror -> 写入 error_log.txt。
  - GUI 中通过 QMessageBox.warning/critical/information 和状态栏 statusBar().showMessage 即时反馈。
  - CLI 模式统一以 [错误] / [成功] / [信息] 前缀打印到控制台。

2. 关键文件与位置
- main.py：全局异常保护（if __name__ == "__main__" 中的 try/except Exception）、show_error_dialog 降级弹窗、load_config 的 RuntimeError 抛错。
- instrument_connection.py：CMW500Connection.connect/disconnect/get_serial_number 中对 pyvisa.VisaIOError 的分类捕获；send_command/query 在 connected=False 时 raise ConnectionError。
- gui_main.py：TestWorker.run 中 except Exception 捕获并 error_signal.emit(str(e))；各按钮回调中对连接失败、导出失败等场景弹出 QMessageBox。
- test_executor.py：单信道测量时对每个 query 单独 try/except，失败字段置 None 并在判定阶段标记为 ERROR，外层 run() 再捕获整信道异常记录到结果列表。

3. 架构与约定
- I/O 层不吞异常：send_command/query 在未连接时直接 raise ConnectionError，强制调用方显式检查连接状态或自行捕获。
- 高层方法偏好返回值而非异常：connect()/disconnect()/get_serial_number 返回 (bool, str)，由调用方决定是弹窗还是写日志，避免 GUI 线程被异常打断。
- GUI 与后台解耦：测试逻辑运行在独立 QThread，异常经 Qt 信号跨线程传递，主线程统一通过 _on_test_error 槽函数处理。
- 容错优先于中断：单信道测量逐项 try/except，单个指标读取失败不影响其他指标继续采集，最终在 pass/fail 列显示 ERROR。

4. 开发者应遵循的规则
- 仪器 I/O 调用前先检查 cmw500.connected，或直接让 send_command/query 抛出 ConnectionError 由上层捕获。
- 涉及外部资源的方法（网络、文件、VISA）必须包裹 try/except，对已知异常类型做分支处理，未知异常用 except Exception 兜底。
- 面向用户的 API 优先返回 (bool, str) 元组，不要直接向 GUI 抛异常；需要中断流程时使用异常（如 ConnectionError）。
- GUI 线程内禁止裸抛异常，一律通过 error_signal 或返回值交由主线程统一弹窗/写日志。
- CLI 模式下所有错误输出以 [错误] 前缀开头，便于脚本化解析。
- 新增异常路径时同步更新 show_error_dialog 的降级策略，确保无 GUI 环境也能落盘错误信息。