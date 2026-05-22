import json
import os
import shutil
import time
from dataclasses import dataclass
from typing import Optional, Set

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from src.core.log_manager import get_logger
from src.core.theme_manager import ThemeManager
from src.core.uv_manager import UVManager
from src.core.workflow_executor import WorkflowExecutor, write_workflow_file
from src.core.workflow_run_worker import WorkflowRunWorker
from src.views.toast_widget import ToastWidget

from .workflow_canvas import WorkflowCanvas, WorkflowGraphicsScene

logger = get_logger("workflow_tab_widget")


@dataclass
class ConnectionInfo:
    """连接信息 - 包含端口级信息"""

    from_node_id: str
    from_port_name: str
    to_node_id: str
    to_port_name: str


class SaveWorkflowWorker(QThread):
    """在后台线程中保存工作流文件，避免阻塞UI"""

    saved = Signal(str)
    error = Signal(str)

    def __init__(self, save_path: str, workflow_data: dict, parent=None):
        super().__init__(parent)
        self.save_path = save_path
        self.workflow_data = workflow_data

    def run(self):
        try:
            write_workflow_file(self.save_path, self.workflow_data)
            self.saved.emit(self.save_path)
        except Exception as e:
            self.error.emit(str(e))


class WorkflowTabWidget(QWidget):
    # 信号：工作流修改状态改变
    modified_changed = Signal(bool)  # is_modified

    def __init__(self, workflow_name="新工作流", parent=None):
        super().__init__(parent)
        self.workflow_name = workflow_name
        self.main_window = parent

        # 修改状态标记
        self._is_modified = False

        # 创建工作流执行器
        self.uv_manager = UVManager()
        self.executor = WorkflowExecutor(workflow_name, self.uv_manager)

        # 节点数据字典 {node_id: node_graphics_item}
        self.nodes = {}
        # 连接数据 [ConnectionInfo]
        self.connections = []

        # 后台执行 Worker
        self._run_worker = None

        # 后台保存 Worker
        self._save_worker = None

        # 执行状态跟踪
        self._execution_status = "idle"  # idle/running/completed/error
        self._execution_log = []  # 节点执行日志
        self._last_execution_report = None  # 最后一次执行报告

        # 工作流级别变量
        self._variables = {}

        # 断点集合
        self._breakpoints = set()

        # UI组件引用
        self.name_label = None

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 工具栏
        toolbar = QWidget()
        toolbar.setStyleSheet(f"""
            QWidget {{
                background-color: {ThemeManager.COLORS["surface_light"]};
                border-bottom: 1px solid {ThemeManager.COLORS["border"]};
            }}
        """)
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(10, 5, 10, 5)

        # 工作流名称和重命名按钮
        name_widget = QWidget()
        name_layout = QHBoxLayout(name_widget)
        name_layout.setContentsMargins(0, 0, 0, 0)
        name_layout.setSpacing(5)

        # 标题标签
        self.name_label = QLabel(self.workflow_name)
        name_font = QFont()
        name_font.setPointSize(10)
        name_font.setBold(True)
        self.name_label.setFont(name_font)
        self.name_label.setStyleSheet(f"color: {ThemeManager.COLORS['text']};")
        name_layout.addWidget(self.name_label)

        # 重命名输入框 (默认隐藏)
        self.name_edit = QLineEdit()
        self.name_edit.setFont(name_font)
        self.name_edit.setStyleSheet(ThemeManager.get_input_style())
        self.name_edit.hide()
        self.name_edit.editingFinished.connect(self._on_rename_finished)
        name_layout.addWidget(self.name_edit)

        # 重命名按钮
        self.rename_btn = QPushButton("✏️")
        self.rename_btn.setStyleSheet(ThemeManager.get_button_style("icon"))
        self.rename_btn.setToolTip("重命名工作流")
        self.rename_btn.clicked.connect(self.rename_workflow)
        name_layout.addWidget(self.rename_btn)

        toolbar_layout.addWidget(name_widget)

        toolbar_layout.addStretch()

        # 执行按钮
        self.run_btn = QPushButton("▶ 执行工作流")
        self.run_btn.setStyleSheet(ThemeManager.get_button_style("primary"))
        self.run_btn.clicked.connect(self._execute_workflow)
        toolbar_layout.addWidget(self.run_btn)

        self.stop_btn = QPushButton("⏹ 停止")
        self.stop_btn.setStyleSheet(ThemeManager.get_button_style("danger"))
        self.stop_btn.setToolTip("停止正在执行的工作流")
        self.stop_btn.clicked.connect(self._stop_workflow)
        self.stop_btn.hide()
        toolbar_layout.addWidget(self.stop_btn)

        # 保存按钮
        self.save_btn = QPushButton("💾 保存")
        self.save_btn.setStyleSheet(ThemeManager.get_button_style("secondary"))
        self.save_btn.clicked.connect(self._save_workflow)
        self.save_btn.setEnabled(False)
        toolbar_layout.addWidget(self.save_btn)

        # 同步按钮
        self.sync_btn = QPushButton("☁️ 同步")
        self.sync_btn.setStyleSheet(ThemeManager.get_button_style("secondary"))
        self.sync_btn.setToolTip("同步到 GitHub")
        self.sync_btn.clicked.connect(self._on_sync_clicked)
        toolbar_layout.addWidget(self.sync_btn)

        layout.addWidget(toolbar)

        # Create a new scene
        scene = WorkflowGraphicsScene(self)
        self.canvas = WorkflowCanvas(scene, self)
        self.canvas.node_added.connect(self._on_node_added)
        self.canvas.node_selected.connect(self._on_node_selected)
        self.canvas.node_deleted.connect(self._on_node_deleted)
        self.canvas.connection_created.connect(self._on_connection_created)
        self.canvas.zoom_changed.connect(self._on_zoom_changed)

        # 应用全局默认缩放比例
        self.canvas.apply_default_zoom()

        layout.addWidget(self.canvas)
        self.setLayout(layout)

    def _on_node_added(self, node_item):
        """节点被添加到画布"""
        from src.core.node_registry import get_registry

        if not node_item.config:
            node_item.config = get_registry().build_default_config(node_item.node_type)

        self.nodes[node_item.node_id] = node_item
        node_type_val = (
            node_item.node_type.value
            if hasattr(node_item.node_type, "value")
            else str(node_item.node_type)
        )
        logger.info("节点已添加: %s (%s)", node_item.node_id, node_type_val)
        self._set_modified(True)

    def _on_node_selected(self, node_item):
        """节点被选中"""
        if self.main_window and hasattr(self.main_window, "execution_results"):
            self.main_window.execution_results.show_node_result(node_item.node_id)
            if not self.main_window.execution_results_dock.isVisible():
                from src.core.theme_manager import ThemeManager

                dock_style = ThemeManager.get_dock_widget_style()
                self.main_window.execution_results_dock.setStyleSheet(dock_style)
                self.main_window.execution_results_dock.show()

        if self.main_window and hasattr(self.main_window, "node_properties"):
            right_dock = getattr(self.main_window, "_right_dock", None)
            node_properties = self.main_window.node_properties
            if (
                right_dock
                and right_dock.isVisible()
                and node_properties.current_node_id == node_item.node_id
            ):
                right_dock.hide()
                return

            self.main_window.node_properties.load_node_properties(
                node_item.node_id, node_item.node_type, node_item.config
            )
            if hasattr(self.main_window, "_right_dock"):
                self.main_window._right_tab_widget.setCurrentIndex(0)
                if not self.main_window._right_dock.isVisible():
                    self.main_window._right_dock.show()

    def _on_node_deleted(self, node_id: str):
        """节点被删除"""
        if node_id in self.nodes:
            del self.nodes[node_id]
            logger.info("节点已删除: %s", node_id)

            # 删除相关连接
            self.connections = [
                conn
                for conn in self.connections
                if conn.from_node_id != node_id and conn.to_node_id != node_id
            ]

            # 清空属性面板（如果删除的是当前选中的节点）
            if self.main_window and hasattr(self.main_window, "node_properties"):
                if self.main_window.node_properties.current_node_id == node_id:
                    self.main_window.node_properties.clear_properties()

            self._set_modified(True)

    def _on_connection_created(
        self, from_node_id, from_port_name, to_node_id, to_port_name
    ):
        """连接被创建"""
        self.connections.append(
            ConnectionInfo(from_node_id, from_port_name, to_node_id, to_port_name)
        )
        logger.info(
            "连接已创建: %s.%s -> %s.%s",
            from_node_id,
            from_port_name,
            to_node_id,
            to_port_name,
        )
        self._set_modified(True)

    def update_node_config(self, node_id: str, config: dict):
        """更新节点配置"""
        if node_id in self.nodes:
            node_item = self.nodes[node_id]
            node_item.config = config
            logger.info("节点配置已更新: %s", node_id)
            self._set_modified(True)

    def _set_modified(self, modified: bool):
        """设置修改状态"""
        if self._is_modified != modified:
            self._is_modified = modified
            self.modified_changed.emit(modified)
        # 同步更新保存按钮状态
        if hasattr(self, "save_btn") and self.save_btn:
            self.save_btn.setEnabled(modified)

    def is_modified(self):
        """获取修改状态"""
        return self._is_modified

    def is_running(self):
        """工作流是否正在执行"""
        return self._run_worker is not None and self._run_worker.isRunning()

    def _sync_active_property_panel(self):
        """在执行或保存前同步右侧属性面板的未提交修改"""
        if not self.main_window or not hasattr(self.main_window, "node_properties"):
            return

        node_properties = self.main_window.node_properties
        # 属性面板允许先编辑、后点击保存工作流；这里统一兜底同步一次，
        # 避免节点已在画布上但最新表单值还没写回 self.nodes。
        if node_properties.current_node_id in self.nodes:
            node_properties.sync_current_config()

    def _create_runtime_node(self, node_id: str, node_item):
        """根据画布节点创建可执行节点实例 — 统一走 CustomNode + 注册表"""
        from src.core.node_base import CustomNode
        from src.core.node_registry import get_registry

        node_type_str = (
            node_item.node_type.value
            if hasattr(node_item.node_type, "value")
            else str(node_item.node_type)
        )
        node = CustomNode(node_id, node_type_str, node_item.config)
        node_def = get_registry().get_node(node_type_str)
        if node_def:
            node.source_code = node_def.source_code
        return node

    def _populate_executor(self, included_node_ids: Optional[Set[str]] = None):
        """根据画布状态重建执行器"""
        self.executor.nodes.clear()
        self.executor.edges.clear()

        # 单节点执行时只装配目标节点及其上游子图，整图执行时则装配全部节点。
        target_node_ids = included_node_ids or set(self.nodes.keys())
        for node_id in target_node_ids:
            node_item = self.nodes.get(node_id)
            if not node_item:
                continue
            self.executor.add_node(self._create_runtime_node(node_id, node_item))

        for conn in self.connections:
            if (
                conn.from_node_id in target_node_ids
                and conn.to_node_id in target_node_ids
            ):
                self.executor.add_edge(
                    conn.from_node_id,
                    conn.from_port_name,
                    conn.to_node_id,
                    conn.to_port_name,
                )

    def _collect_upstream_node_ids(self, target_node_id: str) -> set:
        """收集目标节点及其所有上游节点"""
        required = set()
        stack = [target_node_id]

        while stack:
            node_id = stack.pop()
            if node_id in required:
                continue

            required.add(node_id)
            for conn in self.connections:
                if conn.to_node_id == node_id and conn.from_node_id not in required:
                    stack.append(conn.from_node_id)

        return required

    def _reset_node_run_states(self):
        """清空节点运行状态"""
        for node_item in self.nodes.values():
            node_item.set_executing(False)
            node_item.set_error(False)
            if hasattr(node_item, "set_success"):
                node_item.set_success(False)
            if hasattr(node_item, "set_run_summary"):
                node_item.set_run_summary("")

    def _build_node_summary(self, node_report: dict) -> str:
        """构建节点 tooltip 摘要"""
        if node_report.get("success"):
            output = node_report.get("output", {})
            if isinstance(output, dict):
                keys = ", ".join(list(output.keys())[:6]) or "(空输出)"
            else:
                keys = str(output)
            return (
                f"最近运行: 成功\n"
                f"耗时: {node_report.get('duration_ms', 0)} ms\n"
                f"输出: {keys}"
            )

        parts = [
            "最近运行: 失败",
            f"耗时: {node_report.get('duration_ms', 0)} ms",
            f"错误: {node_report.get('error', '执行失败')}",
        ]
        traceback_text = node_report.get("traceback", "")
        if traceback_text:
            first_line = traceback_text.strip().splitlines()[-1]
            parts.append(f"异常: {first_line}")
        return "\n".join(parts)

    def _apply_run_report(self, report: dict):
        """将运行报告同步到节点状态和底部面板"""
        self._reset_node_run_states()

        executed_node_ids = set()
        for node_report in report.get("nodes", []):
            node_item = self.nodes.get(node_report.get("node_id"))
            if not node_item:
                continue

            executed_node_ids.add(node_report.get("node_id"))
            duration_ms = node_report.get("duration_ms", 0)
            if node_report.get("success"):
                if hasattr(node_item, "set_success"):
                    node_item.set_success(True, duration_ms)
                else:
                    node_item.set_error(False, duration_ms)
            else:
                node_item.set_error(True, duration_ms)

            if hasattr(node_item, "set_run_summary"):
                node_item.set_run_summary(self._build_node_summary(node_report))

        if self.main_window and hasattr(self.main_window, "show_execution_report"):
            self.main_window.show_execution_report(report)

        if report.get("stopped"):
            status_message = (
                f"已停止: {self.workflow_name} ({report.get('duration_ms', 0)} ms)"
            )
        elif report.get("success"):
            status_message = (
                f"运行成功: {self.workflow_name} ({report.get('duration_ms', 0)} ms)"
            )
        else:
            status_message = (
                f"运行失败: {self.workflow_name} - {report.get('error', '未知错误')}"
            )
        logger.info("%s", status_message)

    def _record_execution_history(self, report: dict, trigger_type: str = "manual"):
        """写入首页运行历史"""
        if not self.main_window or not hasattr(self.main_window, "config_manager"):
            return

        workflow_path = f"workflows/{self.workflow_name}/workflow.json"
        record = self.executor.build_execution_record(
            report, workflow_path=workflow_path, trigger_type=trigger_type
        )
        self.main_window.config_manager.add_execution_record(record)

    def execute_single_node(self, node_id: str):
        """执行单个节点及其必需上游节点（后台线程，不阻塞UI）"""
        if node_id not in self.nodes:
            QMessageBox.warning(self, "执行失败", f"未找到节点: {node_id}")
            return

        if self._run_worker and self._run_worker.isRunning():
            logger.warning("工作流正在执行中，请等待完成")
            return

        self._sync_active_property_panel()

        required_node_ids = self._collect_upstream_node_ids(node_id)
        target_node = self.nodes[node_id]

        self._reset_node_run_states()
        target_node.set_executing(True)

        self._populate_executor(required_node_ids)

        logger.info("\n执行单节点: %s", node_id)
        if not self.uv_manager.check_uv_installed():
            logger.warning("UV未安装，将使用当前Python环境")

        self.run_btn.hide()
        self.stop_btn.show()
        self.stop_btn.setEnabled(True)
        self.stop_btn.setText("⏹ 停止")

        initial_report = self.executor._create_run_report("manual")
        if self.main_window and hasattr(self.main_window, "execution_results"):
            self.main_window.execution_results.start_streaming(initial_report)
            self.main_window.execution_results_dock.show()

        self._run_worker = WorkflowRunWorker(
            self.executor,
            trigger_type="manual",
            prepare_env=True,
            skip_successful_nodes=True,
            parent=self,
        )
        self._run_worker.node_started.connect(self._on_node_started)
        self._run_worker.node_completed.connect(self._on_node_completed)
        self._run_worker.node_progress.connect(self._on_node_progress)
        self._run_worker.node_log.connect(self._on_node_log)
        self._run_worker.environment_preparing.connect(self._on_environment_preparing)
        self._run_worker.environment_ready.connect(self._on_environment_ready)
        self._run_worker.finished_with_report.connect(
            lambda report, nid=node_id, tn=target_node: self._on_single_node_finished(
                report, nid, tn
            )
        )
        self._run_worker.error.connect(
            lambda msg, tn=target_node: self._on_single_node_error(msg, tn)
        )
        self._run_worker.start()

    def _on_single_node_finished(self, report: dict, node_id: str, target_node):
        """单节点执行完成"""
        target_node.set_executing(False)
        self._apply_run_report(report)
        self._record_execution_history(report)

        if self.main_window and hasattr(self.main_window, "execution_results"):
            self.main_window.execution_results.finish_streaming(report)

        if report.get("stopped"):
            logger.info("单节点执行已被用户停止: %s", node_id)
        elif report.get("success"):
            logger.info("单节点执行完成: %s", node_id)
        else:
            logger.error(
                "单节点执行失败: %s -> %s", node_id, report.get("error", "未知错误")
            )
        logger.info(
            "结果摘要: %s",
            json.dumps(report.get("final_context", {}), ensure_ascii=False),
        )

        self._restore_run_button()
        self._run_worker = None

    def _on_single_node_error(self, error_msg: str, target_node):
        """单节点执行出错"""
        target_node.set_executing(False)
        target_node.set_error(True, 0)
        logger.error("单节点执行失败: %s", error_msg)

        self._restore_run_button()
        self._run_worker = None

    def _execute_workflow(self):
        """执行工作流（后台线程，不阻塞UI）"""
        if not self.nodes:
            QMessageBox.warning(self, "无法执行", "工作流中没有节点")
            return

        if self._run_worker and self._run_worker.isRunning():
            logger.warning("工作流正在执行中，请等待完成")
            return

        self._sync_active_property_panel()
        self._populate_executor()

        logger.info("\n执行工作流: %s", self.workflow_name)
        if not self.uv_manager.check_uv_installed():
            logger.warning("UV未安装，将使用当前Python环境")

        self._reset_node_run_states()

        self.run_btn.hide()
        self.stop_btn.show()
        self.stop_btn.setEnabled(True)
        self.stop_btn.setText("⏹ 停止")

        initial_report = self.executor._create_run_report("manual")
        if self.main_window and hasattr(self.main_window, "execution_results"):
            self.main_window.execution_results.start_streaming(initial_report)
            self.main_window.execution_results_dock.show()

        self._run_worker = WorkflowRunWorker(
            self.executor, trigger_type="manual", prepare_env=True, parent=self
        )
        self._run_worker.node_started.connect(self._on_node_started)
        self._run_worker.node_completed.connect(self._on_node_completed)
        self._run_worker.node_progress.connect(self._on_node_progress)
        self._run_worker.node_log.connect(self._on_node_log)
        self._run_worker.environment_preparing.connect(self._on_environment_preparing)
        self._run_worker.environment_ready.connect(self._on_environment_ready)
        self._run_worker.finished_with_report.connect(self._on_workflow_finished)
        self._run_worker.error.connect(self._on_workflow_error)
        self._run_worker.start()

    def _stop_workflow(self):
        """停止正在执行的工作流"""
        if self._run_worker and self._run_worker.isRunning():
            self.stop_btn.setEnabled(False)
            self.stop_btn.setText("正在停止...")
            logger.info("用户请求停止工作流: %s", self.workflow_name)
            self._run_worker.request_stop()

    def _restore_run_button(self):
        """恢复执行按钮状态"""
        self.stop_btn.hide()
        self.run_btn.show()
        self.run_btn.setEnabled(True)
        self.run_btn.setText("▶ 执行工作流")

    def _on_node_started(self, node_id: str):
        """单节点开始执行时的UI更新"""
        node_item = self.nodes.get(node_id)
        if node_item:
            node_item.set_executing(True)

    def _on_node_completed(self, node_report: dict):
        """单节点完成时的实时UI更新"""
        node_id = node_report.get("node_id")
        node_item = self.nodes.get(node_id)
        if node_item:
            node_item.set_executing(False)
            duration_ms = node_report.get("duration_ms", 0)
            if node_report.get("success"):
                if hasattr(node_item, "set_success"):
                    node_item.set_success(True, duration_ms)
                else:
                    node_item.set_error(False, duration_ms)
            else:
                node_item.set_error(True, duration_ms)
            if hasattr(node_item, "set_run_summary"):
                node_item.set_run_summary(self._build_node_summary(node_report))

        if self.main_window and hasattr(self.main_window, "execution_results"):
            self.main_window.execution_results.append_node_result(node_report)

    def _on_node_progress(self, node_id: str, percent: int, message: str):
        """节点进度更新时的UI更新"""
        node_item = self.nodes.get(node_id)
        if node_item and hasattr(node_item, "set_progress"):
            node_item.set_progress(percent, message)

    def _on_node_log(self, node_id: str, line: str):
        """实时日志行回调"""
        if self.main_window and hasattr(self.main_window, "execution_results"):
            self.main_window.execution_results.append_log_line(node_id, line)

    def _on_environment_preparing(self):
        """环境准备开始时的UI更新"""
        self.stop_btn.setText("准备环境中...")
        logger.info("正在准备执行环境，可能需要下载依赖包...")

    def _on_environment_ready(self, success: bool, error_msg: str):
        """环境准备完成时的UI更新"""
        if success:
            self.stop_btn.setText("执行中...")
            logger.info("环境准备完成，开始执行节点")
        else:
            self._restore_run_button()
            logger.error("环境准备失败: %s", error_msg)

    def _on_workflow_finished(self, report: dict):
        """工作流执行完成"""
        self._apply_run_report(report)
        self._record_execution_history(report)

        if self.main_window and hasattr(self.main_window, "execution_results"):
            self.main_window.execution_results.finish_streaming(report)

        if report.get("stopped"):
            logger.info("\n工作流已被用户停止")
        elif report.get("success"):
            logger.info("\n工作流执行成功")
        else:
            logger.error("\n工作流执行失败: %s", report.get("error", "未知错误"))
        logger.info(
            "结果: %s", json.dumps(report.get("final_context", {}), ensure_ascii=False)
        )

        self._restore_run_button()
        self._run_worker = None

        if report.get("stopped"):
            self._notify_if_hidden(
                "工作流已停止",
                f"{self.workflow_name} 已被用户停止",
            )
        elif report.get("success"):
            self._notify_if_hidden(
                "工作流执行成功",
                f"{self.workflow_name} 已完成",
            )
        else:
            self._notify_if_hidden(
                "工作流执行失败",
                f"{self.workflow_name} 执行失败: {report.get('error', '未知错误')}",
            )

    def _on_workflow_error(self, error_msg: str):
        """工作流执行出错"""
        logger.error("工作流执行出错: %s", error_msg)
        self._restore_run_button()
        self._run_worker = None

        self._notify_if_hidden("工作流执行出错", f"{self.workflow_name}: {error_msg}")

    def _notify_if_hidden(self, title: str, message: str):
        """当主窗口隐藏时通过系统托盘通知用户"""
        if (
            self.main_window
            and hasattr(self.main_window, "_tray_icon")
            and self.main_window.isHidden()
        ):
            self.main_window._tray_icon.showMessage(
                title, message, QSystemTrayIcon.Information, 5000
            )
            if not self.main_window._has_running_workflows():
                self.main_window._tray_icon.showMessage(
                    "LocalFlow",
                    "所有工作流已执行完毕，双击托盘图标恢复窗口",
                    QSystemTrayIcon.Information,
                    5000,
                )

    def _save_workflow(self):
        """保存工作流（异步，不阻塞UI）"""
        if self._save_worker and self._save_worker.isRunning():
            logger.warning("工作流正在保存中，请等待完成")
            return

        try:
            is_valid, error_msg = self._validate_workflow_name(
                self.workflow_name, exclude_current=True
            )
            if not is_valid:
                QMessageBox.warning(
                    self,
                    "名称无效",
                    f"无法保存工作流:\n\n{error_msg}\n\n请重命名工作流后再保存。",
                )
                return

            import os

            save_path = f"workflows/{self.workflow_name}/workflow.json"
            os.makedirs(os.path.dirname(save_path), exist_ok=True)

            self._sync_active_property_panel()

            self.executor.nodes.clear()
            self.executor.edges.clear()

            node_positions = {}
            for node_id, node_item in self.nodes.items():
                node = self._create_runtime_node(node_id, node_item)
                self.executor.add_node(node)
                pos = node_item.pos()
                node_positions[node_id] = {"x": pos.x(), "y": pos.y()}

            for conn in self.connections:
                self.executor.add_edge(
                    conn.from_node_id,
                    conn.from_port_name,
                    conn.to_node_id,
                    conn.to_port_name,
                )

            canvas_state = self.canvas.get_canvas_state()

            workflow_data = self.executor.build_workflow_data(
                node_positions, canvas_state
            )

            self.save_btn.setEnabled(False)

            self._save_worker = SaveWorkflowWorker(
                save_path, workflow_data, parent=self
            )
            self._save_worker.saved.connect(self._on_save_success)
            self._save_worker.error.connect(self._on_save_error)
            self._save_worker.start()

        except Exception as e:
            QMessageBox.critical(self, "保存失败", f"保存工作流时出错:\n\n{str(e)}")
            logger.error("保存失败: %s", e)
            self.save_btn.setEnabled(True)

    def _on_save_success(self, save_path: str):
        """保存成功回调（主线程）"""
        self._set_modified(False)
        logger.info("工作流已保存: %s", save_path)
        ToastWidget.show(self, f"工作流 '{self.workflow_name}' 保存成功！", "success")
        self.save_btn.setEnabled(True)
        self._save_worker = None

        if self.main_window:
            QTimer.singleShot(100, self._refresh_overview_list)

    def _on_save_error(self, error_msg: str):
        """保存失败回调（主线程）"""
        QMessageBox.critical(self, "保存失败", f"保存工作流时出错:\n\n{error_msg}")
        logger.error("保存失败: %s", error_msg)
        self.save_btn.setEnabled(True)
        self._save_worker = None

    def _save_workflow_sync(self):
        """同步保存工作流（用于关闭前检查等需要等待保存完成的场景）"""
        try:
            is_valid, error_msg = self._validate_workflow_name(
                self.workflow_name, exclude_current=True
            )
            if not is_valid:
                return

            import os

            save_path = f"workflows/{self.workflow_name}/workflow.json"
            os.makedirs(os.path.dirname(save_path), exist_ok=True)

            self._sync_active_property_panel()

            self.executor.nodes.clear()
            self.executor.edges.clear()

            node_positions = {}
            for node_id, node_item in self.nodes.items():
                node = self._create_runtime_node(node_id, node_item)
                self.executor.add_node(node)
                pos = node_item.pos()
                node_positions[node_id] = {"x": pos.x(), "y": pos.y()}

            for conn in self.connections:
                self.executor.add_edge(
                    conn.from_node_id,
                    conn.from_port_name,
                    conn.to_node_id,
                    conn.to_port_name,
                )

            canvas_state = self.canvas.get_canvas_state()
            self.executor.save_workflow(save_path, node_positions, canvas_state)
            self._set_modified(False)
            logger.info("工作流已保存(同步): %s", save_path)
        except Exception as e:
            logger.error("同步保存失败: %s", e)

    def _refresh_overview_list(self):
        """刷新首页工作流列表"""
        try:
            if self.main_window:
                overview_tab = self.main_window.tabs.widget(0)
                if overview_tab and hasattr(overview_tab, "refresh_workflows"):
                    overview_tab.refresh_workflows()
        except Exception as e:
            logger.error("刷新首页列表失败: %s", e)

    def _on_zoom_changed(self):
        """画布缩放比例变化时自动保存工作流"""
        # 只有已保存过的工作流才自动保存（workflow_name 不是默认的临时名称）
        save_path = f"workflows/{self.workflow_name}/workflow.json"
        if os.path.exists(save_path):
            try:
                self._save_workflow()
            except Exception as e:
                logger.error("自动保存工作流失败: %s", e)

    def get_workflow_name(self):
        return self.workflow_name

    def _validate_workflow_name(
        self, new_name: str, exclude_current: bool = True
    ) -> tuple[bool, str]:
        """验证工作流名称是否有效

        Args:
            new_name: 新的工作流名称
            exclude_current: 是否排除当前工作流名称（用于重命名时）

        Returns:
            tuple: (is_valid, error_message)
        """
        if not new_name or not new_name.strip():
            return False, "工作流名称不能为空"

        new_name = new_name.strip()

        # 检查名称中是否包含非法字符
        illegal_chars = ["/", "\\", ":", "*", "?", '"', "<", ">", "|"]
        for char in illegal_chars:
            if char in new_name:
                return False, f"工作流名称不能包含字符: {char}"

        # 检查名称是否已存在
        workflows_dir = "workflows"
        if os.path.exists(workflows_dir):
            for item in os.listdir(workflows_dir):
                item_path = os.path.join(workflows_dir, item)
                if os.path.isdir(item_path):
                    # 如果是重命名操作，排除当前工作流名称
                    if exclude_current and item == self.workflow_name:
                        continue
                    if item == new_name:
                        return False, f"工作流 '{new_name}' 已存在"

        return True, ""

    def rename_workflow(self):
        """进入重命名模式"""
        self.name_label.hide()
        self.rename_btn.hide()

        self.name_edit.setText(self.workflow_name)
        self.name_edit.show()
        self.name_edit.setFocus()
        self.name_edit.selectAll()

    def _on_rename_finished(self):
        """完成重命名"""
        # 如果输入框不可见，说明可能已经被处理过了（防止重复调用）
        if not self.name_edit.isVisible():
            return

        new_name = self.name_edit.text().strip()

        # 如果名称没有变化，或者为空，或者取消（失去焦点但未更改），则恢复原状
        if not new_name or new_name == self.workflow_name:
            self._cancel_rename()
            return

        # 验证名称
        is_valid, error_msg = self._validate_workflow_name(new_name)

        if not is_valid:
            QMessageBox.warning(self, "重命名失败", error_msg)
            self.name_edit.setFocus()
            self.name_edit.selectAll()
            return

        # 执行重命名
        if self._rename_workflow_files(new_name):
            self.workflow_name = new_name
            self.executor.workflow_name = new_name

            # 更新UI
            self.name_label.setText(new_name)

            # 如果当前工作流已保存，重置修改状态
            if not self._is_modified:
                self._set_modified(False)

            # 通知主窗口更新标签页名称
            if self.main_window:
                self.main_window.update_tab_name(self, new_name)

            # 刷新首页工作流列表
            QTimer.singleShot(100, self._refresh_overview_list)

            ToastWidget.show(self, f"工作流已重命名为 '{new_name}'", "success")

            self._cancel_rename()
        else:
            QMessageBox.critical(
                self, "重命名失败", "无法重命名工作流文件，请检查文件权限或是否被占用。"
            )
            self._cancel_rename()

    def _cancel_rename(self):
        """取消重命名，恢复显示"""
        self.name_edit.hide()
        self.name_label.show()
        self.rename_btn.show()

    def _on_sync_clicked(self):
        """打开同步对话框"""
        # 先保存当前工作流
        if self._is_modified:
            self._save_workflow()

        workflow_path = f"workflows/{self.workflow_name}/workflow.json"
        if not os.path.exists(workflow_path):
            # 工作流尚未保存，先保存
            self._save_workflow()

        if not os.path.exists(workflow_path):
            from src.views.toast_widget import ToastWidget
            ToastWidget.show(self, "请先保存工作流", "warning")
            return

        from src.dialogs.workflow_sync_dialog import WorkflowSyncDialog
        dialog = WorkflowSyncDialog(self.workflow_name, workflow_path, self)
        dialog.exec()

    def _rename_workflow_files(self, new_name: str) -> bool:
        """重命名工作流文件和目录

        Args:
            new_name: 新的工作流名称

        Returns:
            bool: 重命名是否成功
        """
        try:
            old_dir = f"workflows/{self.workflow_name}"
            new_dir = f"workflows/{new_name}"

            # 如果旧目录存在，重命名它
            if os.path.exists(old_dir):
                # 确保目标目录不存在
                if os.path.exists(new_dir):
                    return False

                shutil.move(old_dir, new_dir)

                # 更新工作流文件中的名称
                workflow_file = os.path.join(new_dir, "workflow.json")
                if os.path.exists(workflow_file):
                    self._update_workflow_name_in_file(workflow_file, new_name)

            return True

        except Exception as e:
            logger.error("重命名工作流文件失败: %s", e)
            return False

    def _update_workflow_name_in_file(self, file_path: str, new_name: str):
        """更新工作流文件中的名称字段（异步，不阻塞UI）

        Args:
            file_path: 工作流文件路径
            new_name: 新的工作流名称
        """
        import threading

        def _do_update():
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                if "workflow_name" in data:
                    data["workflow_name"] = new_name

                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.error("更新工作流文件名称失败: %s", e)

        threading.Thread(target=_do_update, daemon=True).start()

    # ========== 执行状态管理 ==========
    def get_execution_status(self) -> str:
        """获取当前工作流执行状态"""
        if self._run_worker and self._run_worker.isRunning():
            return "running"
        return self._execution_status

    def get_execution_log(self) -> list:
        """获取最近一次执行的详细日志"""
        return self._execution_log

    def _clear_execution_log(self):
        """清空执行日志"""
        self._execution_log = []

    def _append_execution_log(
        self,
        node_id: str,
        input_data: dict,
        output_data: dict,
        duration_ms: int,
        error: str = None,
    ):
        """添加节点执行记录到日志"""
        self._execution_log.append(
            {
                "node_id": node_id,
                "timestamp": time.time(),
                "input_data": input_data,
                "output_data": output_data,
                "duration_ms": duration_ms,
                "error": error,
                "success": error is None,
            }
        )

    # ========== 变量管理 ==========
    def set_variable(self, name: str, value, overwrite: bool = True) -> bool:
        """设置工作流级别变量

        Args:
            name: 变量名
            value: 变量值
            overwrite: 是否覆盖已存在的变量

        Returns:
            bool: 是否设置成功
        """
        if name in self._variables and not overwrite:
            return False
        self._variables[name] = value
        return True

    def get_variable(self, name: str):
        """获取工作流变量值"""
        return self._variables.get(name)

    def list_variables(self) -> dict:
        """列出所有工作流变量"""
        return dict(self._variables)

    # ========== 断点管理 ==========
    def set_breakpoint(self, node_id: str) -> bool:
        """设置断点"""
        if node_id in self._breakpoints:
            return False
        self._breakpoints.add(node_id)
        return True

    def remove_breakpoint(self, node_id: str) -> bool:
        """移除断点"""
        if node_id not in self._breakpoints:
            return False
        self._breakpoints.remove(node_id)
        return True

    def has_breakpoint(self, node_id: str) -> bool:
        """检查节点是否有断点"""
        return node_id in self._breakpoints

    def list_breakpoints(self) -> list:
        """列出所有断点"""
        return list(self._breakpoints)
