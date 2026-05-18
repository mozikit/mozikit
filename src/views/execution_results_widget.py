from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QHeaderView,
    QAbstractItemView,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from src.core.config_manager import ConfigManager
from src.core.theme_manager import ThemeManager


class ExecutionResultsWidget(QWidget):
    """非阻塞运行结果面板"""

    NODE_DATA_TABLE_KEY = "execution_results_node_data_table"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_report = None
        self._streaming_report = None
        self._display_mode = "report"
        self._current_node_id = None
        self._config_manager = ConfigManager()
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        header_layout = QHBoxLayout()
        header_layout.setSpacing(8)

        self.run_id_label = QLabel("运行ID: -")
        self.run_id_label.setStyleSheet(
            f"color: {ThemeManager.COLORS['text_secondary']};"
        )
        header_layout.addWidget(self.run_id_label)

        self.back_to_report_btn = QPushButton("← 返回汇总")
        self.back_to_report_btn.setStyleSheet(ThemeManager.get_button_style("secondary"))
        self.back_to_report_btn.clicked.connect(self._show_current_report)
        self.back_to_report_btn.hide()
        header_layout.addWidget(self.back_to_report_btn)

        header_layout.addStretch()

        self.copy_btn = QPushButton("复制调试信息")
        self.copy_btn.setStyleSheet(ThemeManager.get_button_style("secondary"))
        self.copy_btn.clicked.connect(self.copy_debug_payload)
        header_layout.addWidget(self.copy_btn)

        layout.addLayout(header_layout)

        meta_layout = QHBoxLayout()
        meta_layout.setSpacing(16)

        self.status_label = QLabel("状态: -")
        self.workflow_label = QLabel("工作流: -")
        self.duration_label = QLabel("耗时: -")
        self.path_label = QLabel("产物目录: -")

        for label in [
            self.status_label,
            self.workflow_label,
            self.duration_label,
            self.path_label,
        ]:
            label.setStyleSheet(f"color: {ThemeManager.COLORS['text_secondary']};")
            meta_layout.addWidget(label)

        meta_layout.addStretch()
        layout.addLayout(meta_layout)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(ThemeManager.get_tab_widget_style())

        self.summary_text = self._create_readonly_text()
        self.tabs.addTab(self.summary_text, "摘要")

        nodes_tab = QWidget()
        nodes_layout = QVBoxLayout(nodes_tab)
        nodes_layout.setContentsMargins(0, 0, 0, 0)

        self._nodes_splitter = QSplitter(Qt.Vertical)

        self.nodes_table = QTableWidget(0, 7)
        self.nodes_table.setHorizontalHeaderLabels(["节点", "类型", "状态", "耗时(ms)", "开始时间", "结束时间", "摘要"])
        self.nodes_table.verticalHeader().setVisible(False)
        self.nodes_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.nodes_table.setSelectionMode(QTableWidget.SingleSelection)
        self.nodes_table.setEditTriggers(QTableWidget.NoEditTriggers)
        # 设置列宽策略：节点ID、类型、状态、耗时使用自适应，时间和摘要使用拉伸
        self.nodes_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.nodes_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.nodes_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.nodes_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.nodes_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.nodes_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.nodes_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.Stretch)
        self.nodes_table.setStyleSheet(ThemeManager.get_table_style())
        self.nodes_table.itemSelectionChanged.connect(self._update_node_details)
        self._nodes_splitter.addWidget(self.nodes_table)

        # 节点详情区域使用 TabWidget 替代纯文本，支持多视图
        self.node_details_tabs = QTabWidget()
        self.node_details_tabs.setStyleSheet(ThemeManager.get_tab_widget_style())

        self.node_details_text = self._create_readonly_text()
        self.node_details_tabs.addTab(self.node_details_text, "原始 JSON")

        # 表格数据展示标签页
        self.node_data_table = QTableWidget()
        self.node_data_table.setStyleSheet(ThemeManager.get_table_style())
        self.node_data_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.node_data_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.node_data_table.verticalHeader().setVisible(False)
        self.node_data_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.node_data_table.horizontalHeader().setStretchLastSection(False)
        self.node_data_table.horizontalHeader().setDefaultAlignment(Qt.AlignLeft)
        self.node_data_table.horizontalHeader().sectionResized.connect(self._on_node_data_table_column_resized)
        self.node_details_tabs.addTab(self.node_data_table, "数据表格")

        self._nodes_splitter.addWidget(self.node_details_tabs)
        self._nodes_splitter.setSizes([100, 80])

        nodes_layout.addWidget(self._nodes_splitter)
        self.tabs.addTab(nodes_tab, "节点")

        self.logs_text = self._create_readonly_text()
        self.tabs.addTab(self.logs_text, "日志")

        self.traceback_text = self._create_readonly_text()
        self.tabs.addTab(self.traceback_text, "错误追踪")

        layout.addWidget(self.tabs)
        self.clear_report()

    def _create_readonly_text(self) -> QPlainTextEdit:
        editor = QPlainTextEdit()
        editor.setReadOnly(True)
        editor.setStyleSheet(
            f"""
            QPlainTextEdit {{
                background-color: {ThemeManager.COLORS["surface"]};
                color: {ThemeManager.COLORS["text"]};
                border: 1px solid {ThemeManager.COLORS["border"]};
                border-radius: 8px;
                padding: 10px;
                selection-background-color: {ThemeManager.COLORS["selection"]};
            }}
            """
        )
        return editor

    def clear_report(self):
        self.current_report = None
        self._streaming_report = None
        self._display_mode = "report"
        self._current_node_id = None
        self.back_to_report_btn.hide()
        self.run_id_label.setText("运行ID: -")
        self.status_label.setText("状态: -")
        self.workflow_label.setText("工作流: -")
        self.duration_label.setText("耗时: -")
        self.path_label.setText("产物目录: -")
        self.summary_text.setPlainText("暂无运行记录")
        self.logs_text.clear()
        self.traceback_text.clear()
        self.node_details_text.setPlainText("选择一个节点查看详细输入/输出")
        self.nodes_table.setRowCount(0)
        self._clear_data_table()
        self.tabs.setTabText(0, "摘要")
        self.tabs.setTabText(1, "节点")
        self._nodes_splitter.setSizes([100, 80])

    def _clear_data_table(self):
        """清空数据表格"""
        self.node_data_table.clear()
        self.node_data_table.setRowCount(0)
        self.node_data_table.setColumnCount(0)
        self.node_data_table.setHorizontalHeaderLabels([])

    def _render_data_table(self, data: list):
        """将 list[dict] 数据渲染到表格中"""
        self._clear_data_table()

        if not data or not isinstance(data, list):
            self.node_data_table.setRowCount(1)
            self.node_data_table.setColumnCount(1)
            item = QTableWidgetItem("(无表格数据)")
            item.setFlags(Qt.ItemIsEnabled)
            self.node_data_table.setItem(0, 0, item)
            return

        # 收集所有列名
        columns = []
        for row in data:
            if isinstance(row, dict):
                for key in row.keys():
                    if key not in columns:
                        columns.append(key)

        if not columns:
            self.node_data_table.setRowCount(1)
            self.node_data_table.setColumnCount(1)
            item = QTableWidgetItem("(数据项不是字典类型)")
            item.setFlags(Qt.ItemIsEnabled)
            self.node_data_table.setItem(0, 0, item)
            return

        self.node_data_table.setColumnCount(len(columns))
        self.node_data_table.setHorizontalHeaderLabels(columns)

        # 限制显示行数，避免大数据量卡顿
        max_rows = min(len(data), 1000)
        self.node_data_table.setRowCount(max_rows)

        for row_idx, row_data in enumerate(data[:max_rows]):
            if not isinstance(row_data, dict):
                continue
            for col_idx, col_name in enumerate(columns):
                value = row_data.get(col_name)
                if value is None:
                    text = ""
                elif isinstance(value, (list, dict)):
                    import json
                    text = json.dumps(value, ensure_ascii=False)
                else:
                    text = str(value)
                item = QTableWidgetItem(text)
                item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                self.node_data_table.setItem(row_idx, col_idx, item)

        # 调整列宽（先根据内容自适应）
        self.node_data_table.resizeColumnsToContents()
        # 恢复用户保存的列宽
        self._restore_node_data_table_column_widths()

    def _on_node_data_table_column_resized(self, logical_index: int, old_size: int, new_size: int):
        """列宽改变时保存列宽配置"""
        if new_size <= 0:
            return
        widths = {}
        for i in range(self.node_data_table.columnCount()):
            widths[str(i)] = self.node_data_table.columnWidth(i)
        self._config_manager.set_table_column_widths(self.NODE_DATA_TABLE_KEY, widths)

    def _restore_node_data_table_column_widths(self):
        """恢复用户保存的列宽"""
        saved_widths = self._config_manager.get_table_column_widths(self.NODE_DATA_TABLE_KEY)
        if not saved_widths:
            return
        # 临时断开信号，避免恢复时触发保存
        try:
            self.node_data_table.horizontalHeader().sectionResized.disconnect(
                self._on_node_data_table_column_resized
            )
        except Exception:
            pass
        for col_str, width in saved_widths.items():
            try:
                col_idx = int(col_str)
                if 0 <= col_idx < self.node_data_table.columnCount() and width > 0:
                    self.node_data_table.setColumnWidth(col_idx, width)
            except Exception:
                continue
        self.node_data_table.horizontalHeader().sectionResized.connect(
            self._on_node_data_table_column_resized
        )

    def _extract_table_data(self, node_report: dict) -> list:
        """从节点输出中提取表格数据（list[dict] 格式）"""
        output = node_report.get("output", {})
        if not isinstance(output, dict):
            return []

        # 尝试各种可能的表格数据结构
        # 1. 直接包含 rows 字段（table_reader / table_aggregate 等节点）
        if "rows" in output and isinstance(output["rows"], list):
            return output["rows"]

        # 2. 包含 result_rows 字段
        if "result_rows" in output and isinstance(output["result_rows"], list):
            return output["result_rows"]

        # 3. 输出本身就是 list[dict]
        for key, value in output.items():
            if isinstance(value, list) and value and isinstance(value[0], dict):
                return value

        return []

    def start_streaming(self, report: dict):
        self._display_mode = "report"
        self._current_node_id = None
        self.back_to_report_btn.hide()
        self._streaming_report = report.copy()
        self._streaming_report["nodes"] = []
        self._streaming_report.setdefault("stdout", "")
        self._streaming_report.setdefault("stderr", "")
        self.current_report = self._streaming_report

        self.run_id_label.setText(f"运行ID: {report.get('run_id', '-')}")
        self.status_label.setText("状态: 运行中...")
        self.status_label.setStyleSheet(
            f"color: {ThemeManager.COLORS['warning']}; font-weight: bold;"
        )
        self.workflow_label.setText(
            f"工作流: {report.get('workflow_name', '-')}"
        )
        self.duration_label.setText("耗时: ...")
        self.path_label.setText("产物目录: -")

        self.summary_text.setPlainText("正在执行...")
        self.logs_text.clear()
        self.traceback_text.clear()
        self.nodes_table.setRowCount(0)
        self.node_details_text.setPlainText("等待节点完成...")
        self.tabs.setTabText(0, "摘要")
        self.tabs.setTabText(1, "节点")
        self._nodes_splitter.setSizes([100, 80])
        self.tabs.setCurrentIndex(2)

    def append_log_line(self, node_id: str, line: str):
        """实时追加单行日志（流式更新）"""
        if not line:
            return
        prefix = f"[{node_id}] "
        self.logs_text.appendPlainText(prefix + line)
        self.logs_text.verticalScrollBar().setValue(
            self.logs_text.verticalScrollBar().maximum()
        )

    def append_node_result(self, node_report: dict):
        if not self._streaming_report:
            return

        self._streaming_report["nodes"].append(node_report)

        node_id = node_report.get("node_id", "-")
        node_type = node_report.get("node_type", "-")
        success = node_report.get("success", False)
        status = "成功" if success else "失败"
        started_at = node_report.get("started_at", "-")
        finished_at = node_report.get("finished_at", "-")

        row = self.nodes_table.rowCount()
        self.nodes_table.insertRow(row)

        summary = self._build_node_summary(node_report)
        items = [
            QTableWidgetItem(node_id),
            QTableWidgetItem(node_type),
            QTableWidgetItem(status),
            QTableWidgetItem(str(node_report.get("duration_ms", 0))),
            QTableWidgetItem(started_at),
            QTableWidgetItem(finished_at),
            QTableWidgetItem(summary),
        ]
        for column, item in enumerate(items):
            item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            if column == 2:
                color = QColor(
                    ThemeManager.COLORS["success"] if success else ThemeManager.COLORS["error"]
                )
                item.setForeground(color)
            self.nodes_table.setItem(row, column, item)

        if self._display_mode == "node":
            if node_report.get("node_id") == self._current_node_id:
                self._display_node_report(node_report)
            return

        if node_report.get("stderr"):
            existing = self.logs_text.toPlainText()
            prefix = f"[{node_id}] "
            lines = "\n".join(
                prefix + line if line else prefix
                for line in node_report["stderr"].splitlines()
            )
            new_text = (existing + "\n(stderr)\n" + lines).strip() if existing else "(stderr)\n" + lines
            self.logs_text.setPlainText(new_text)

        if not success and node_report.get("traceback"):
            existing_tb = self.traceback_text.toPlainText()
            tb_line = f"[{node_id}] {node_report.get('error', '')}\n{node_report['traceback']}".strip()
            new_tb = (existing_tb + "\n\n" + tb_line).strip() if existing_tb else tb_line
            self.traceback_text.setPlainText(new_tb)

        node_type = node_report.get("node_type", "")
        duration = node_report.get("duration_ms", 0)
        status_line = f"[{node_id}] {status}  {node_type}  ({duration}ms)"
        if not success:
            status_line += f"  错误: {node_report.get('error', '')}"
        existing = self.logs_text.toPlainText()
        new_text = (existing + "\n" + status_line) if existing else status_line
        self.logs_text.setPlainText(new_text)

        self.logs_text.verticalScrollBar().setValue(
            self.logs_text.verticalScrollBar().maximum()
        )

        if not success:
            self.tabs.setCurrentIndex(3)

    def finish_streaming(self, report: dict):
        """流式接收结束，用完整报告刷新"""
        self._streaming_report = None
        self.show_report(report)

    def show_report(self, report: dict):
        self.current_report = report or {}
        self._display_mode = "report"
        self._current_node_id = None
        self.back_to_report_btn.hide()

        success = bool(self.current_report.get("success"))
        status_text = "成功" if success else "失败"
        status_color = (
            ThemeManager.COLORS["success"] if success else ThemeManager.COLORS["error"]
        )

        self.run_id_label.setText(f"运行ID: {self.current_report.get('run_id', '-')}")
        self.status_label.setText(f"状态: {status_text}")
        self.status_label.setStyleSheet(f"color: {status_color}; font-weight: bold;")
        self.workflow_label.setText(
            f"工作流: {self.current_report.get('workflow_name', '-')}"
        )
        self.duration_label.setText(
            f"耗时: {self.current_report.get('duration_ms', 0)} ms"
        )
        self.path_label.setText(
            f"产物目录: {self.current_report.get('artifact_dir', '-') or '-'}"
        )

        node_count = len(self.current_report.get("nodes", []))
        success_count = sum(1 for n in self.current_report.get("nodes", []) if n.get("success"))
        summary_lines = [
            f"运行{'成功' if success else '失败'}: {success_count}/{node_count} 个节点成功",
            f"总耗时: {self.current_report.get('duration_ms', 0)} ms",
            "",
            "点击画布中的节点查看详细运行结果",
        ]
        error_text = self.current_report.get("error", "")
        if error_text:
            summary_lines.extend(["", "错误信息:", error_text])
        self.summary_text.setPlainText("\n".join(summary_lines))
        self.tabs.setTabText(0, "摘要")

        self._populate_nodes(self.current_report.get("nodes", []))
        self.tabs.setTabText(1, "节点")
        self._nodes_splitter.setSizes([100, 80])

        self.logs_text.setPlainText(self._build_logs_text(self.current_report))
        self.traceback_text.setPlainText(self._collect_tracebacks(self.current_report))

        if success:
            self.tabs.setCurrentIndex(0)
        elif self.traceback_text.toPlainText().strip():
            self.tabs.setCurrentIndex(3)
        else:
            self.tabs.setCurrentIndex(1)

    def _build_summary_text(self, report: dict) -> str:
        lines = [
            f"状态: {'成功' if report.get('success') else '失败'}",
            f"工作流: {report.get('workflow_name', '-')}",
            f"运行ID: {report.get('run_id', '-')}",
            f"触发方式: {report.get('trigger_type', '-')}",
            f"开始时间: {report.get('started_at', '-')}",
            f"结束时间: {report.get('finished_at', '-')}",
            f"总耗时: {report.get('duration_ms', 0)} ms",
            f"执行顺序: {', '.join(report.get('execution_order', [])) or '-'}",
            f"失败节点: {report.get('failed_node_id', '-') or '-'}",
            f"产物目录: {report.get('artifact_dir', '-') or '-'}",
        ]

        error_text = report.get("error", "")
        if error_text:
            lines.extend(["", "错误信息:", error_text])

        lines.extend(["", "最终上下文:", self._to_json_text(report.get("final_context", {}))])
        return "\n".join(lines)

    def _collect_tracebacks(self, report: dict) -> str:
        blocks = []
        for node_report in report.get("nodes", []):
            traceback_text = node_report.get("traceback", "")
            if traceback_text:
                blocks.append(
                    f"[{node_report.get('node_id', '-')}] {node_report.get('error', '')}\n{traceback_text}".strip()
                )
        return "\n\n".join(blocks)

    def _build_logs_text(self, report: dict) -> str:
        blocks = []
        stdout_text = report.get("stdout", "")
        stderr_text = report.get("stderr", "")
        if stdout_text:
            blocks.append("标准输出:\n" + stdout_text)
        if stderr_text:
            blocks.append("错误输出:\n" + stderr_text)
        return "\n\n".join(blocks).strip()

    def _populate_nodes(self, node_reports: list):
        self.nodes_table.setRowCount(0)
        self.node_details_text.setPlainText("选择一个节点查看详细输入/输出")

        for row, node_report in enumerate(node_reports):
            self.nodes_table.insertRow(row)

            node_id = node_report.get("node_id", "-")
            node_type = node_report.get("node_type", "-")
            status = "成功" if node_report.get("success") else "失败"
            started_at = node_report.get("started_at", "-")
            finished_at = node_report.get("finished_at", "-")
            summary = self._build_node_summary(node_report)

            items = [
                QTableWidgetItem(node_id),
                QTableWidgetItem(node_type),
                QTableWidgetItem(status),
                QTableWidgetItem(str(node_report.get("duration_ms", 0))),
                QTableWidgetItem(started_at),
                QTableWidgetItem(finished_at),
                QTableWidgetItem(summary),
            ]

            for column, item in enumerate(items):
                item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                if column == 2:  # 状态列
                    color = QColor(
                        ThemeManager.COLORS["success"]
                        if node_report.get("success")
                        else ThemeManager.COLORS["error"]
                    )
                    item.setForeground(color)
                self.nodes_table.setItem(row, column, item)

        if node_reports:
            self.nodes_table.selectRow(0)

    def _build_node_summary(self, node_report: dict) -> str:
        if node_report.get("success"):
            output = node_report.get("output", {})
            if isinstance(output, dict):
                keys = list(output.keys())
                return ", ".join(keys[:5]) or "(空输出)"
            return self._compact_text(self._to_json_text(output))

        return self._compact_text(node_report.get("error", "") or "执行失败")

    def _update_node_details(self):
        if self._display_mode == "node":
            return

        if not self.current_report:
            return

        row = self.nodes_table.currentRow()
        if row < 0:
            return

        node_reports = self.current_report.get("nodes", [])
        if row >= len(node_reports):
            return

        node_report = node_reports[row]
        sections = [
            f"节点: {node_report.get('node_id', '-')}",
            f"类型: {node_report.get('node_type', '-')}",
            f"状态: {'成功' if node_report.get('success') else '失败'}",
            f"耗时: {node_report.get('duration_ms', 0)} ms",
            f"脚本: {node_report.get('script_path', '-')}",
            "",
            "输入:",
            self._to_json_text(node_report.get("input", {})),
            "",
            "输出:",
            self._to_json_text(node_report.get("output", {})),
        ]

        if node_report.get("stdout"):
            sections.extend(["", "标准输出:", node_report["stdout"]])
        if node_report.get("stderr"):
            sections.extend(["", "错误输出:", node_report["stderr"]])
        if node_report.get("error"):
            sections.extend(["", "错误:", node_report["error"]])
        if node_report.get("traceback"):
            sections.extend(["", "堆栈追踪:", node_report["traceback"]])

        self.node_details_text.setPlainText("\n".join(sections))

        # 更新表格数据视图
        table_data = self._extract_table_data(node_report)
        if table_data:
            self._render_data_table(table_data)
            self.node_details_tabs.setTabText(1, f"数据表格 ({len(table_data)} 行)")
            self.node_details_tabs.setTabEnabled(1, True)
        else:
            self._clear_data_table()
            self.node_details_tabs.setTabText(1, "数据表格")
            self.node_details_tabs.setTabEnabled(1, False)

    def copy_debug_payload(self):
        if self._display_mode == "node" and self._current_node_id:
            node_report = self._find_node_report(self._current_node_id)
            if node_report:
                QApplication.clipboard().setText(self._to_json_text(node_report))
                return

        if not self.current_report:
            return

        # 复制结构化调试载荷，方便直接贴给 AI，而不是依赖截图或手工整理。
        payload = {
            "workflow_name": self.current_report.get("workflow_name"),
            "run_id": self.current_report.get("run_id"),
            "success": self.current_report.get("success"),
            "duration_ms": self.current_report.get("duration_ms"),
            "execution_order": self.current_report.get("execution_order", []),
            "failed_node_id": self.current_report.get("failed_node_id"),
            "error": self.current_report.get("error"),
            "artifact_dir": self.current_report.get("artifact_dir"),
            "nodes": self.current_report.get("nodes", []),
            "final_context": self.current_report.get("final_context", {}),
        }
        QApplication.clipboard().setText(self._to_json_text(payload))

    def _to_json_text(self, value) -> str:
        import json

        try:
            return json.dumps(value, ensure_ascii=False, indent=2)
        except TypeError:
            return str(value)

    def _compact_text(self, text: str, limit: int = 120) -> str:
        normalized = " ".join((text or "").split())
        if len(normalized) <= limit:
            return normalized
        return normalized[: limit - 3] + "..."

    def show_node_result(self, node_id: str):
        self._display_mode = "node"
        self._current_node_id = node_id
        self.back_to_report_btn.setVisible(bool(self.current_report))

        node_report = self._find_node_report(node_id)

        if not node_report:
            self._show_no_result_state(node_id)
            return

        self._display_node_report(node_report)

    def _find_node_report(self, node_id: str):
        if not self.current_report:
            return None
        for nr in self.current_report.get("nodes", []):
            if nr.get("node_id") == node_id:
                return nr
        return None

    def _show_no_result_state(self, node_id: str):
        self.run_id_label.setText(f"节点: {node_id}")
        self.status_label.setText("状态: 未运行")
        self.status_label.setStyleSheet(
            f"color: {ThemeManager.COLORS['text_secondary']}; font-weight: bold;"
        )
        self.workflow_label.setText("类型: -")
        self.duration_label.setText("耗时: -")
        run_id = self.current_report.get("run_id", "-") if self.current_report else "-"
        self.path_label.setText(f"运行ID: {run_id}")

        self.summary_text.setPlainText("该节点暂无运行结果")
        self.tabs.setTabText(0, "输出")

        self.node_details_text.setPlainText("该节点暂无运行结果")
        self._clear_data_table()
        self.node_details_tabs.setTabText(1, "数据表格")
        self.node_details_tabs.setTabEnabled(1, False)
        self.tabs.setTabText(1, "数据表格")
        self._nodes_splitter.setSizes([0, 1])

        self.logs_text.setPlainText("无日志输出")
        self.traceback_text.setPlainText("无错误信息")

        self.tabs.setCurrentIndex(0)

    def _display_node_report(self, node_report: dict):
        node_id = node_report.get("node_id", "-")
        success = node_report.get("success", False)
        status_text = "成功" if success else "失败"
        status_color = ThemeManager.COLORS["success"] if success else ThemeManager.COLORS["error"]

        self.run_id_label.setText(f"节点: {node_id}")
        self.status_label.setText(f"状态: {status_text}")
        self.status_label.setStyleSheet(f"color: {status_color}; font-weight: bold;")
        self.workflow_label.setText(f"类型: {node_report.get('node_type', '-')}")
        self.duration_label.setText(f"耗时: {node_report.get('duration_ms', 0)} ms")
        run_id = self.current_report.get("run_id", "-") if self.current_report else "-"
        self.path_label.setText(f"运行ID: {run_id}")

        output_sections = []
        input_data = node_report.get("input", {})
        if input_data:
            output_sections.extend(["输入:", self._to_json_text(input_data), ""])
        output_sections.extend(["输出:", self._to_json_text(node_report.get("output", {}))])
        self.summary_text.setPlainText("\n".join(output_sections))
        self.tabs.setTabText(0, "输出")

        self._update_node_details_content(node_report)
        self.tabs.setTabText(1, "数据表格")
        self._nodes_splitter.setSizes([0, 1])

        log_parts = []
        if node_report.get("stdout"):
            log_parts.append("标准输出:\n" + node_report["stdout"])
        if node_report.get("stderr"):
            log_parts.append("错误输出:\n" + node_report["stderr"])
        self.logs_text.setPlainText("\n\n".join(log_parts) if log_parts else "无日志输出")

        if node_report.get("traceback") or node_report.get("error"):
            error_parts = []
            if node_report.get("error"):
                error_parts.append(f"错误: {node_report['error']}")
            if node_report.get("traceback"):
                error_parts.append(node_report["traceback"])
            self.traceback_text.setPlainText("\n\n".join(error_parts))
        else:
            self.traceback_text.setPlainText("无错误信息")

        self.tabs.setCurrentIndex(0)

    def _update_node_details_content(self, node_report: dict):
        sections = [
            f"节点: {node_report.get('node_id', '-')}",
            f"类型: {node_report.get('node_type', '-')}",
            f"状态: {'成功' if node_report.get('success') else '失败'}",
            f"耗时: {node_report.get('duration_ms', 0)} ms",
            f"脚本: {node_report.get('script_path', '-')}",
            "",
            "输入:",
            self._to_json_text(node_report.get("input", {})),
            "",
            "输出:",
            self._to_json_text(node_report.get("output", {})),
        ]

        if node_report.get("stdout"):
            sections.extend(["", "标准输出:", node_report["stdout"]])
        if node_report.get("stderr"):
            sections.extend(["", "错误输出:", node_report["stderr"]])
        if node_report.get("error"):
            sections.extend(["", "错误:", node_report["error"]])
        if node_report.get("traceback"):
            sections.extend(["", "堆栈追踪:", node_report["traceback"]])

        self.node_details_text.setPlainText("\n".join(sections))

        table_data = self._extract_table_data(node_report)
        if table_data:
            self._render_data_table(table_data)
            self.node_details_tabs.setTabText(1, f"数据表格 ({len(table_data)} 行)")
            self.node_details_tabs.setTabEnabled(1, True)
        else:
            self._clear_data_table()
            self.node_details_tabs.setTabText(1, "数据表格")
            self.node_details_tabs.setTabEnabled(1, False)

    def _show_current_report(self):
        if self.current_report:
            self.show_report(self.current_report)
