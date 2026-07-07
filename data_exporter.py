"""
CMW500 自动化测试工具 - 数据导出模块

功能说明：
    将 BLE TX 调制测试结果导出为 Excel 文件。
    使用 pandas 处理数据，openpyxl 设置样式。
    文件名自动包含日期时间戳，避免覆盖历史数据。

输出内容：
    - Sheet 1 "测试数据"：逐信道测量数值 + 判定结果
    - Sheet 2 "测试摘要"：汇总统计信息
"""

import os
import sys
from datetime import datetime

import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side


class DataExporter:
    """测试结果数据导出类"""

    # 预定义样式常量
    PASS_FILL = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")   # 浅绿色
    FAIL_FILL = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")   # 浅红色
    HEADER_FILL = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid") # 蓝色
    HEADER_FONT = Font(name="微软雅黑", bold=True, color="FFFFFF", size=11)                 # 白色加粗
    NORMAL_FONT = Font(name="微软雅黑", size=10)
    BOLD_FONT = Font(name="微软雅黑", bold=True, size=10)
    CENTER_ALIGN = Alignment(horizontal="center", vertical="center")
    THIN_BORDER = Border(
        left=Side(style="thin"),
        right=Side(style="thin"),
        top=Side(style="thin"),
        bottom=Side(style="thin"),
    )

    def __init__(self, config):
        """
        初始化数据导出器

        参数:
            config: 从 config.yaml 加载的配置字典
        """
        self.export_config = config["export"]
        self.file_prefix = self.export_config["file_prefix"]

        # 解析输出目录路径：相对路径基于程序所在目录（兼容 exe 打包）
        raw_output_dir = self.export_config["output_dir"]
        if os.path.isabs(raw_output_dir):
            self.output_dir = raw_output_dir
        else:
            # 获取程序根目录（兼容 PyInstaller 打包）
            if getattr(sys, 'frozen', False):
                app_dir = os.path.dirname(sys.executable)
            else:
                app_dir = os.path.dirname(os.path.abspath(__file__))
            self.output_dir = os.path.join(app_dir, raw_output_dir)

    def _ensure_output_dir(self):
        """确保输出目录存在，不存在则创建"""
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)

    def _generate_filename(self):
        """
        生成带日期时间戳的文件名

        格式示例：BLE_TX_Modulation_Test_20260702_164643.xlsx

        返回:
            str: 完整的文件路径
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{self.file_prefix}_{timestamp}.xlsx"
        return os.path.join(self.output_dir, filename)

    def export_to_excel(self, results, test_params):
        """
        将测试结果导出为格式化的 Excel 文件

        参数:
            results:     测试结果列表（来自 BLETxModulationTest.get_results()）
            test_params: 测试参数配置字典

        返回:
            str: 导出文件的完整路径
        """
        self._ensure_output_dir()
        filepath = self._generate_filename()

        # ========== Sheet 1：测试数据 ==========
        # 构建 DataFrame 数据
        rows = []
        for r in results:
            row = {
                "信道 (Channel)": r.get("channel", ""),
                "测量时间": r.get("timestamp", ""),
            }

            # 遍历配置中的各项测量指标
            measurement_keys = [
                "frequency_accuracy",
                "frequency_drift",
                "frequency_offset",
                "initial_frequency_drift",
                "max_drift_rate",
            ]
            for key in measurement_keys:
                name = test_params["measurements"][key]["name"]
                unit = test_params["measurements"][key]["unit"]
                # 测量数值列
                row[f"{name} ({unit})"] = r.get(key, "N/A")
                # 判定结果列
                if "pass_fail" in r:
                    row[f"{name} 判定"] = r["pass_fail"].get(key, "N/A")
                else:
                    row[f"{name} 判定"] = "ERROR"

            rows.append(row)

        df = pd.DataFrame(rows)

        # ========== Sheet 2：测试摘要 ==========
        summary_data = self._build_summary(results, test_params)
        df_summary = pd.DataFrame(summary_data)

        # 写入 Excel
        with pd.ExcelWriter(filepath, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="测试数据", index=False)
            df_summary.to_excel(writer, sheet_name="测试摘要", index=False)

        # 对 Excel 进行样式美化
        self._apply_styles(filepath, len(rows), len(df.columns))

        return filepath

    def _build_summary(self, results, test_params):
        """
        构建测试摘要数据

        参数:
            results:     测试结果列表
            test_params: 测试参数配置

        返回:
            list[dict]: 摘要行列表
        """
        total_channels = len(results)

        # 统计各指标通过/失败数量
        measurement_keys = [
            "frequency_accuracy",
            "frequency_drift",
            "frequency_offset",
            "initial_frequency_drift",
            "max_drift_rate",
        ]

        summary_rows = [
            {"项目": "测试时间", "数值": datetime.now().strftime("%Y-%m-%d %H:%M:%S")},
            {"项目": "测试标准", "数值": f"{test_params['standard']} ({test_params['phy_type']})"},
            {"项目": "信道范围", "数值": f"Ch {test_params['channel_start']} ~ Ch {test_params['channel_end']}"},
            {"项目": "统计次数", "数值": test_params["statistic_count"]},
            {"项目": "总测试信道数", "数值": total_channels},
            {"项目": "———", "数值": "———"},
        ]

        # 各项指标的通过/失败统计
        for key in measurement_keys:
            name = test_params["measurements"][key]["name"]
            upper = test_params["measurements"][key]["upper_limit"]
            unit = test_params["measurements"][key]["unit"]

            pass_count = 0
            fail_count = 0
            for r in results:
                if "pass_fail" in r:
                    if r["pass_fail"].get(key) == "PASS":
                        pass_count += 1
                    else:
                        fail_count += 1

            summary_rows.append({
                "项目": f"{name} (上限: {upper} {unit})",
                "数值": f"通过 {pass_count} / 失败 {fail_count}",
            })

        # 总体通过/失败信道数
        all_pass = sum(
            1 for r in results
            if "pass_fail" in r and all(v == "PASS" for v in r["pass_fail"].values())
        )
        summary_rows.append({"项目": "———", "数值": "———"})
        summary_rows.append({"项目": "全部通过信道数", "数值": all_pass})
        summary_rows.append({"项目": "有失败项信道数", "数值": total_channels - all_pass})
        summary_rows.append({"项目": "总体判定", "数值": "PASS" if all_pass == total_channels else "FAIL"})

        return summary_rows

    def _apply_styles(self, filepath, row_count, col_count):
        """
        对导出的 Excel 文件应用样式美化

        参数:
            filepath:  Excel 文件路径
            row_count: 数据行数
            col_count: 数据列数
        """
        wb = load_workbook(filepath)

        # ========== 处理 "测试数据" Sheet ==========
        ws_data = wb["测试数据"]

        # 设置表头样式
        for cell in ws_data[1]:
            cell.font = self.HEADER_FONT
            cell.fill = self.HEADER_FILL
            cell.alignment = self.CENTER_ALIGN
            cell.border = self.THIN_BORDER

        # 设置数据区域样式
        for row_idx in range(2, row_count + 2):  # +2 因为表头占第 1 行
            for col_idx in range(1, col_count + 1):
                cell = ws_data.cell(row=row_idx, column=col_idx)
                cell.font = self.NORMAL_FONT
                cell.alignment = self.CENTER_ALIGN
                cell.border = self.THIN_BORDER

                # 对判定列（包含 "PASS" 或 "FAIL" 的列）着色
                if cell.value == "PASS":
                    cell.fill = self.PASS_FILL
                elif cell.value == "FAIL":
                    cell.fill = self.FAIL_FILL

        # 自动调整列宽
        for col_idx in range(1, col_count + 1):
            max_length = 0
            col_letter = ws_data.cell(row=1, column=col_idx).column_letter
            for row_idx in range(1, row_count + 2):
                cell_value = str(ws_data.cell(row=row_idx, column=col_idx).value or "")
                # 中文字符按 2 个字符宽度计算
                cell_length = sum(2 if ord(c) > 127 else 1 for c in cell_value)
                max_length = max(max_length, cell_length)
            ws_data.column_dimensions[col_letter].width = min(max_length + 4, 30)

        # ========== 处理 "测试摘要" Sheet ==========
        ws_summary = wb["测试摘要"]

        # 设置表头样式
        for cell in ws_summary[1]:
            cell.font = self.HEADER_FONT
            cell.fill = self.HEADER_FILL
            cell.alignment = self.CENTER_ALIGN
            cell.border = self.THIN_BORDER

        # 设置数据区域样式
        for row in ws_summary.iter_rows(min_row=2, max_row=ws_summary.max_row):
            for cell in row:
                cell.font = self.NORMAL_FONT
                cell.border = self.THIN_BORDER
                cell.alignment = self.CENTER_ALIGN

        # 摘要 Sheet 的 "总体判定" 行着色
        last_row = ws_summary.max_row
        verdict_cell = ws_summary.cell(row=last_row, column=2)
        if verdict_cell.value == "PASS":
            verdict_cell.fill = self.PASS_FILL
            verdict_cell.font = Font(name="微软雅黑", bold=True, size=12, color="006100")
        elif verdict_cell.value == "FAIL":
            verdict_cell.fill = self.FAIL_FILL
            verdict_cell.font = Font(name="微软雅黑", bold=True, size=12, color="9C0006")

        # 调整摘要列宽
        ws_summary.column_dimensions["A"].width = 35
        ws_summary.column_dimensions["B"].width = 30

        # 保存样式
        wb.save(filepath)
