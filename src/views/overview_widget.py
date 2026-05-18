"""
Overview 页面组件
优化特性：
- 紧凑的信息密集型工作流列表
- 每行展示状态、运行历史、定时任务等多维度信息
- 双行文本布局，提升信息密度3-5倍
- 快捷操作图标，悬停显示
"""

import json
import os
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTimeEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.core.config_manager import ConfigManager
from src.core.log_manager import get_logger
from src.core.scheduler_manager import SchedulerManager
from src.core.theme_manager import ThemeManager
from src.views.toast_widget import ToastWidget

logger = get_logger("overview_widget")


class WorkflowListItem(QFrame):
    """工作流列表项 - 紧凑信息密集型设计

    每行高度仅48px，但包含：
    - 状态指示器（彩色圆点）
    - 工作流名称
    - 最后运行结果摘要
    - 下次触发时间
    - 创建时间和更新时间
    - 快捷操作按钮（悬停显示）
    """

    open_clicked = Signal(str, str)  # workflow_name, workflow_path
    run_clicked = Signal(str, str)  # workflow_name, workflow_path
    delete_clicked = Signal(str)  # workflow_name
    edit_clicked = Signal(str, str)  # workflow_name, workflow_path

    def __init__(
        self,
        workflow_name: str,
        workflow_path: str,
        last_run_info: dict = None,
        schedule_info: dict = None,
        created_at: str = None,
        updated_at: str = None,
        parent=None,
    ):
        super().__init__(parent)
        self.workflow_name = workflow_name
        self.workflow_path = workflow_path
        self.last_run_info = last_run_info or {}
        self.schedule_info = schedule_info or {}
        self.created_at = created_at
        self.updated_at = updated_at
        self._setup_ui()

    def _setup_ui(self):
        """设置紧凑的双行布局"""
        self.setFixedHeight(56)
        self.setCursor(Qt.PointingHandCursor)

        # 样式 - 悬停效果
        self.setStyleSheet(f"""
            WorkflowListItem {{
                background-color: {ThemeManager.COLORS["surface"]};
                border: 1px solid {ThemeManager.COLORS["border"]};
                border-radius: 8px;
            }}
            WorkflowListItem:hover {{
                border: 1px solid {ThemeManager.COLORS["accent"]};
                background-color: {ThemeManager.COLORS["surface_light"]};
            }}
        """)

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(12, 6, 12, 6)
        main_layout.setSpacing(12)

        # 左侧：状态指示器
        self.status_dot = QLabel("●")
        self.status_dot.setFixedSize(12, 12)
        self.status_dot.setStyleSheet(self._get_status_dot_style())
        main_layout.addWidget(self.status_dot, alignment=Qt.AlignVCenter)

        # 中间：信息区域（双行文本）
        info_container = QWidget()
        info_layout = QVBoxLayout(info_container)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(2)

        # 第一行：工作流名称
        name_row = QWidget()
        name_layout = QHBoxLayout(name_row)
        name_layout.setContentsMargins(0, 0, 0, 0)
        name_layout.setSpacing(8)

        self.name_label = QLabel(self.workflow_name)
        name_font = QFont()
        name_font.setPointSize(13)
        name_font.setWeight(QFont.Weight.Bold)
        self.name_label.setFont(name_font)
        self.name_label.setStyleSheet(f"color: {ThemeManager.COLORS['text']};")
        name_layout.addWidget(self.name_label)
        name_layout.addStretch()

        info_layout.addWidget(name_row)

        # 第二行：运行摘要 + 下次触发 + 时间信息
        meta_row = QWidget()
        meta_layout = QHBoxLayout(meta_row)
        meta_layout.setContentsMargins(0, 0, 0, 0)
        meta_layout.setSpacing(12)

        # 最后运行信息
        last_run_text = self._format_last_run()
        self.last_run_label = QLabel(last_run_text)
        self.last_run_label.setStyleSheet(
            f"color: {ThemeManager.COLORS['text_secondary']}; font-size: 11px;"
        )
        meta_layout.addWidget(self.last_run_label)

        # 分隔符
        separator = QLabel("|")
        separator.setStyleSheet(
            f"color: {ThemeManager.COLORS['border']}; font-size: 11px;"
        )
        meta_layout.addWidget(separator)

        # 下次触发时间
        next_run_text = self._format_next_run()
        self.next_run_label = QLabel(next_run_text)
        self.next_run_label.setStyleSheet(
            f"color: {ThemeManager.COLORS['text_secondary']}; font-size: 11px;"
        )
        meta_layout.addWidget(self.next_run_label)

        # 分隔符
        separator2 = QLabel("|")
        separator2.setStyleSheet(
            f"color: {ThemeManager.COLORS['border']}; font-size: 11px;"
        )
        meta_layout.addWidget(separator2)

        # 更新时间
        updated_text = self._format_updated_time()
        self.updated_label = QLabel(updated_text)
        self.updated_label.setStyleSheet(
            f"color: {ThemeManager.COLORS['text_secondary']}; font-size: 11px;"
        )
        meta_layout.addWidget(self.updated_label)

        meta_layout.addStretch()
        info_layout.addWidget(meta_row)

        main_layout.addWidget(info_container, stretch=1)

        # 右侧：操作按钮 + 创建时间（垂直布局）
        right_container = QWidget()
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        # 快捷操作按钮（悬停时显示）
        self.action_container = QWidget()
        action_layout = QHBoxLayout(self.action_container)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(4)

        # 运行按钮
        self.run_btn = QToolButton()
        self.run_btn.setText("▶")
        self.run_btn.setToolTip("运行工作流")
        self.run_btn.setFixedSize(28, 28)
        self.run_btn.setStyleSheet(self._get_action_btn_style())
        self.run_btn.clicked.connect(
            lambda: self.run_clicked.emit(self.workflow_name, self.workflow_path)
        )
        action_layout.addWidget(self.run_btn)

        # 编辑按钮
        self.edit_btn = QToolButton()
        self.edit_btn.setText("✎")
        self.edit_btn.setToolTip("编辑工作流")
        self.edit_btn.setFixedSize(28, 28)
        self.edit_btn.setStyleSheet(self._get_action_btn_style())
        self.edit_btn.clicked.connect(
            lambda: self.edit_clicked.emit(self.workflow_name, self.workflow_path)
        )
        action_layout.addWidget(self.edit_btn)

        # 更多菜单按钮
        self.more_btn = QToolButton()
        self.more_btn.setText("⋯")
        self.more_btn.setToolTip("更多操作")
        self.more_btn.setFixedSize(28, 28)
        self.more_btn.setStyleSheet(self._get_action_btn_style())

        # 创建菜单
        menu = QMenu(self)
        menu.addAction(
            "📂 打开工作流",
            lambda: self.open_clicked.emit(self.workflow_name, self.workflow_path),
        )
        menu.addSeparator()
        menu.addAction(
            "🗑️ 删除工作流", lambda: self.delete_clicked.emit(self.workflow_name)
        )
        self.more_btn.setMenu(menu)
        self.more_btn.setPopupMode(QToolButton.InstantPopup)
        action_layout.addWidget(self.more_btn)

        right_layout.addWidget(
            self.action_container, alignment=Qt.AlignTop | Qt.AlignRight
        )

        # 创建时间（显示在最右侧下角）
        created_text = self._format_created_time()
        self.created_label = QLabel(created_text)
        self.created_label.setStyleSheet(
            f"color: {ThemeManager.COLORS['text_secondary']}; font-size: 10px;"
        )
        self.created_label.setAlignment(Qt.AlignRight | Qt.AlignBottom)
        right_layout.addWidget(
            self.created_label, stretch=1, alignment=Qt.AlignRight | Qt.AlignBottom
        )

        main_layout.addWidget(right_container, alignment=Qt.AlignVCenter)

        # 初始隐藏操作按钮
        self.action_container.setVisible(False)

    def _get_status_dot_style(self) -> str:
        """获取状态圆点样式"""
        status = self.last_run_info.get("status", "unknown")
        color_map = {
            "success": ThemeManager.COLORS["success"],
            "failed": ThemeManager.COLORS["error"],
            "running": ThemeManager.COLORS["accent"],
            "unknown": ThemeManager.COLORS["text_secondary"],
        }
        color = color_map.get(status, ThemeManager.COLORS["text_secondary"])
        return f"color: {color}; font-size: 10px;"

    def _get_action_btn_style(self) -> str:
        """获取操作按钮样式"""
        return f"""
            QToolButton {{
                background-color: transparent;
                border: none;
                border-radius: 4px;
                color: {ThemeManager.COLORS["text_secondary"]};
                font-size: 14px;
            }}
            QToolButton:hover {{
                background-color: {ThemeManager.COLORS["border"]};
                color: {ThemeManager.COLORS["text"]};
            }}
        """

    def _format_last_run(self) -> str:
        """格式化最后运行信息"""
        if not self.last_run_info:
            return "从未运行"

        status = self.last_run_info.get("status", "unknown")
        timestamp = self.last_run_info.get("timestamp") or self.last_run_info.get(
            "finished_at"
        )

        if not timestamp:
            return "从未运行"

        # 解析时间
        try:
            if isinstance(timestamp, str):
                run_time = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            else:
                run_time = timestamp
            time_ago = self._format_time_ago(run_time)
        except:
            time_ago = "未知时间"

        status_map = {
            "success": "成功",
            "failed": "失败",
            "running": "运行中",
            "unknown": "未知",
        }
        status_text = status_map.get(status, "未知")

        return f"{time_ago} · {status_text}"

    def _format_next_run(self) -> str:
        """格式化下次触发时间"""
        if not self.schedule_info or not self.schedule_info.get("enabled"):
            return "无定时计划"

        next_run = self.schedule_info.get("next_run")
        cron_expr = self.schedule_info.get("cron_expression", "")

        if not next_run:
            # 尝试格式化 cron 表达式
            return self._format_cron_readable(cron_expr)

        try:
            if isinstance(next_run, str):
                next_time = datetime.fromisoformat(next_run.replace("Z", "+00:00"))
            else:
                next_time = next_run
            time_until = self._format_time_until(next_time)
            return f"下次: {time_until}"
        except:
            return self._format_cron_readable(cron_expr)

    def _format_cron_readable(self, cron_expr: str) -> str:
        """将 cron 表达式转换为可读文本"""
        if not cron_expr:
            return "无定时计划"

        cron_map = {
            "*/1 * * * *": "每分钟",
            "0 * * * *": "每小时",
            "0 0 * * *": "每天",
            "0 0 * * 0": "每周",
            "0 0 1 * *": "每月",
            "0 9 * * 1-5": "工作日",
        }

        return cron_map.get(cron_expr.strip(), "已计划")

    def _format_updated_time(self) -> str:
        """格式化更新时间"""
        if not self.updated_at:
            return "更新: 未知"

        try:
            if isinstance(self.updated_at, str):
                updated_time = datetime.fromisoformat(
                    self.updated_at.replace("Z", "+00:00")
                )
            else:
                updated_time = self.updated_at
            time_ago = self._format_time_ago(updated_time)
            return f"更新: {time_ago}"
        except:
            return "更新: 未知"

    def _format_created_time(self) -> str:
        """格式化创建时间"""
        if not self.created_at:
            return ""

        try:
            if isinstance(self.created_at, str):
                created_time = datetime.fromisoformat(
                    self.created_at.replace("Z", "+00:00")
                )
            else:
                created_time = self.created_at
            # 显示具体日期时间，格式：MM-DD HH:mm
            return created_time.strftime("%m-%d %H:%M")
        except:
            return ""

    def _format_time_ago(self, dt: datetime) -> str:
        """格式化时间为多久前"""
        now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
        diff = now - dt

        if diff < timedelta(minutes=1):
            return "刚刚"
        elif diff < timedelta(hours=1):
            minutes = int(diff.seconds / 60)
            return f"{minutes}分钟前"
        elif diff < timedelta(days=1):
            hours = int(diff.seconds / 3600)
            return f"{hours}小时前"
        elif diff < timedelta(days=7):
            days = diff.days
            return f"{days}天前"
        else:
            return dt.strftime("%m-%d")

    def _format_time_until(self, dt: datetime) -> str:
        """格式化时间为多久后"""
        now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
        diff = dt - now

        if diff < timedelta(minutes=1):
            return "即将"
        elif diff < timedelta(hours=1):
            minutes = int(diff.seconds / 60)
            return f"{minutes}分钟后"
        elif diff < timedelta(days=1):
            hours = int(diff.seconds / 3600)
            return f"{hours}小时后"
        elif diff < timedelta(days=7):
            days = diff.days
            return f"{days}天后"
        else:
            return dt.strftime("%m-%d %H:%M")

    def enterEvent(self, event):
        """鼠标进入时显示操作按钮"""
        self.action_container.setVisible(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        """鼠标离开时隐藏操作按钮"""
        self.action_container.setVisible(False)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        """点击时打开工作流"""
        if event.button() == Qt.LeftButton:
            # 检查是否点击了操作按钮区域
            if not self.action_container.geometry().contains(event.pos()):
                self.open_clicked.emit(self.workflow_name, self.workflow_path)
        super().mousePressEvent(event)

    def update_info(self, last_run_info: dict = None, schedule_info: dict = None):
        """更新显示信息"""
        if last_run_info:
            self.last_run_info = last_run_info
            self.last_run_label.setText(self._format_last_run())
            self.status_dot.setStyleSheet(self._get_status_dot_style())

        if schedule_info:
            self.schedule_info = schedule_info
            self.next_run_label.setText(self._format_next_run())


class WorkflowCard(QFrame):
    """工作流卡片 - 网格布局用（保留兼容）"""

    open_clicked = Signal(str, str)  # workflow_name, workflow_path
    delete_clicked = Signal(str)  # workflow_name

    def __init__(self, workflow_name: str, workflow_path: str, parent=None):
        super().__init__(parent)
        self.workflow_name = workflow_name
        self.workflow_path = workflow_path
        self._setup_ui()

    def _setup_ui(self):
        """设置UI - 优化版"""
        self.setFixedSize(260, 220)
        self.setCursor(Qt.PointingHandCursor)

        # 样式 - 带悬停效果
        self.setStyleSheet(f"""
            WorkflowCard {{
                background-color: {ThemeManager.COLORS["surface"]};
                border: 1px solid {ThemeManager.COLORS["border"]};
                border-radius: 14px;
            }}
            WorkflowCard:hover {{
                border: 2px solid {ThemeManager.COLORS["accent"]};
                background-color: {ThemeManager.COLORS["surface_light"]};
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        # 图标容器
        icon_container = QFrame()
        icon_container.setFixedSize(64, 64)
        icon_container.setStyleSheet(f"""
            QFrame {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 {ThemeManager.COLORS["accent"]},
                    stop:1 {ThemeManager.COLORS["accent_hover"]});
                border-radius: 16px;
            }}
        """)
        icon_layout = QVBoxLayout(icon_container)
        icon_layout.setContentsMargins(0, 0, 0, 0)

        icon_label = QLabel("📊")
        icon_font = QFont()
        icon_font.setPointSize(28)
        icon_label.setFont(icon_font)
        icon_label.setAlignment(Qt.AlignCenter)
        icon_label.setStyleSheet("background: transparent;")
        icon_layout.addWidget(icon_label)

        layout.addWidget(icon_container, alignment=Qt.AlignCenter)

        # 工作流名称
        name_label = QLabel(self.workflow_name)
        name_font = QFont()
        name_font.setPointSize(13)
        name_font.setWeight(QFont.Weight.Bold)
        name_label.setFont(name_font)
        name_label.setAlignment(Qt.AlignCenter)
        name_label.setStyleSheet(f"""
            color: {ThemeManager.COLORS["text"]};
            background: transparent;
            border: none;
        """)
        name_label.setWordWrap(True)
        layout.addWidget(name_label)

        # 按钮组
        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)

        # 打开按钮
        open_btn = QPushButton("打开")
        open_btn.setFixedHeight(38)
        open_btn.setStyleSheet(ThemeManager.get_button_style("primary"))
        open_btn.setCursor(Qt.PointingHandCursor)
        open_btn.clicked.connect(
            lambda: self.open_clicked.emit(self.workflow_name, self.workflow_path)
        )
        button_layout.addWidget(open_btn)

        # 删除按钮
        delete_btn = QPushButton("删除")
        delete_btn.setFixedHeight(38)
        delete_btn.setStyleSheet(ThemeManager.get_button_style("danger"))
        delete_btn.setCursor(Qt.PointingHandCursor)
        delete_btn.clicked.connect(lambda: self.delete_clicked.emit(self.workflow_name))
        button_layout.addWidget(delete_btn)

        layout.addLayout(button_layout)


class OverviewWidget(QWidget):
    """Overview 页面 - 优化版"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._main_window = parent
        self.config_manager = (
            parent.config_manager
            if parent and hasattr(parent, "config_manager")
            else ConfigManager()
        )
        self.scheduler = SchedulerManager(self.config_manager)

        self._setup_ui()
        self._load_workflows()
        self._load_scheduled_tasks()
        self._load_execution_history()

        # 自动刷新定时器
        self._refresh_timer = QTimer()
        self._refresh_timer.timeout.connect(self._refresh_data)
        self._refresh_timer.start(5000)

    def _refresh_data(self):
        """刷新数据"""
        self._load_scheduled_tasks()
        self._load_execution_history()

    def _setup_ui(self):
        """设置UI - 优化版"""
        from PySide6.QtWidgets import QTabWidget

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 24, 24, 24)
        main_layout.setSpacing(20)

        # 头部区域
        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(20)

        # Logo和标题
        title_container = QWidget()
        title_layout = QHBoxLayout(title_container)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(16)

        logo_label = QLabel()
        logo_pixmap = QPixmap(self._get_resource_path("assets/localflow_64.png"))
        logo_label.setPixmap(
            logo_pixmap.scaled(
                56,
                56,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        title_layout.addWidget(logo_label)

        text_container = QWidget()
        text_layout = QVBoxLayout(text_container)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(4)

        title_label = QLabel("LocalFlow")
        title_font = QFont()
        title_font.setPointSize(24)
        title_font.setWeight(QFont.Weight.Bold)
        title_label.setFont(title_font)
        title_label.setStyleSheet(f"color: {ThemeManager.COLORS['text']};")
        text_layout.addWidget(title_label)

        subtitle_label = QLabel("本地工作流自动化平台")
        subtitle_font = QFont()
        subtitle_font.setPointSize(11)
        subtitle_label.setFont(subtitle_font)
        subtitle_label.setStyleSheet(f"color: {ThemeManager.COLORS['text_secondary']};")
        text_layout.addWidget(subtitle_label)

        title_layout.addWidget(text_container)
        title_layout.addStretch()

        header_layout.addWidget(title_container, stretch=1)

        # 新建工作流按钮
        new_workflow_btn = QPushButton("➕ 新建工作流")
        new_workflow_btn.setFixedHeight(44)
        new_workflow_btn.setStyleSheet(ThemeManager.get_button_style("primary"))
        new_workflow_btn.setCursor(Qt.PointingHandCursor)
        new_workflow_btn.clicked.connect(self._on_add_workflow_clicked)
        header_layout.addWidget(new_workflow_btn)

        main_layout.addWidget(header_widget)

        # Tab控件
        tab_widget = QTabWidget()
        tab_widget.setStyleSheet(ThemeManager.get_tab_widget_style())

        workflows_tab = self._create_workflows_tab()
        scheduled_tab = self._create_scheduled_tab()
        history_tab = self._create_history_tab()

        tab_widget.addTab(workflows_tab, "📁 工作流")
        tab_widget.addTab(scheduled_tab, "⏰ 定时任务")
        tab_widget.addTab(history_tab, "📜 运行历史")

        main_layout.addWidget(tab_widget)

        self.setLayout(main_layout)

    def _get_resource_path(self, relative_path):
        """获取资源文件的绝对路径"""
        dev_path = Path(relative_path)
        if dev_path.exists():
            return str(dev_path)

        if hasattr(sys, "_MEIPASS"):
            base_path = Path(sys._MEIPASS)
            resource_path = base_path / relative_path
        else:
            base_path = Path(sys.executable).parent
            resource_path = base_path / relative_path

            if not resource_path.exists():
                internal_path = base_path.parent / "_internal" / relative_path
                if internal_path.exists():
                    resource_path = internal_path

        if resource_path.exists():
            return str(resource_path)

        return relative_path

    def _get_workflow_last_run(self, workflow_name: str) -> dict:
        """获取工作流的最后运行记录"""
        try:
            history = self.config_manager.get_execution_history(workflow_name, limit=1)
            if history:
                return history[0]
        except Exception as e:
            logger.error("获取工作流运行历史失败: %s", e)
        return None

    def _get_workflow_schedule(self, workflow_name: str) -> dict:
        """获取工作流的定时任务信息"""
        try:
            tasks = self.config_manager.get_scheduled_tasks()
            for task in tasks:
                if task.get("workflow_name") == workflow_name:
                    return task
        except Exception as e:
            logger.error("获取工作流定时任务失败: %s", e)
        return None

    def _load_workflows(self):
        """加载已保存的工作流 - 使用紧凑列表布局，按更新时间排序"""
        from src.core.workflow_scanner import scan_workflows
        workflow_list = scan_workflows()

        # 清空现有列表项
        widgets_to_remove = []
        for i in range(self.list_layout.count()):
            item = self.list_layout.itemAt(i)
            if item:
                widget = item.widget()
                if widget and widget != self.empty_label:
                    widgets_to_remove.append(widget)

        for widget in widgets_to_remove:
            self.list_layout.removeWidget(widget)
            widget.deleteLater()

        # 存储工作流项引用，用于搜索过滤
        self.workflow_items = {}

        if workflow_list:
            if self.empty_label.parent():
                self.empty_label.setParent(None)
            self.empty_label.hide()

            # 创建工作流列表项（紧凑布局）
            for workflow in workflow_list:
                # 获取运行历史和定时任务信息
                last_run = self._get_workflow_last_run(workflow["name"])
                schedule = self._get_workflow_schedule(workflow["name"])

                item = WorkflowListItem(
                    workflow["name"],
                    workflow["path"],
                    last_run_info=last_run,
                    schedule_info=schedule,
                    created_at=workflow.get("created_at"),
                    updated_at=workflow.get("updated_at"),
                    parent=self.list_container,
                )
                item.open_clicked.connect(self._on_open_workflow)
                item.run_clicked.connect(self._on_run_workflow)
                item.edit_clicked.connect(self._on_edit_workflow)
                item.delete_clicked.connect(self._on_delete_workflow)

                self.list_layout.addWidget(item)
                self.workflow_items[workflow["name"].lower()] = item
        else:
            self.list_layout.addWidget(self.empty_label)
            self.empty_label.show()

    def _filter_workflows(self, search_text: str):
        """根据搜索文本过滤工作流列表"""
        search_text = search_text.lower().strip()

        for name, item in self.workflow_items.items():
            if search_text in name:
                item.setVisible(True)
            else:
                item.setVisible(False)

    def _on_run_workflow(self, workflow_name: str, workflow_path: str):
        """运行工作流"""
        logger.info("运行工作流: %s", workflow_name)

        if not os.path.exists(workflow_path):
            QMessageBox.warning(
                self, "文件不存在", f"工作流 '{workflow_name}' 的文件不存在。"
            )
            return

        try:
            from src.core.uv_manager import UVManager
            from src.core.workflow_executor import WorkflowExecutor

            uv_manager = UVManager()
            executor = WorkflowExecutor.load_workflow(workflow_path, uv_manager)
            report = executor.execute(return_report=True, trigger_type="manual")

            # 添加执行记录
            record = executor.build_execution_record(
                report,
                workflow_path=workflow_path,
                trigger_type="manual",
            )
            self.config_manager.add_execution_record(record)

            # 刷新显示
            self._load_workflows()

            if report.get("success"):
                ToastWidget.show(
                    self, f"工作流 '{workflow_name}' 执行成功！", "success"
                )
            else:
                QMessageBox.warning(
                    self,
                    "执行失败",
                    f"工作流 '{workflow_name}' 执行失败:\n{report.get('error', '未知错误')}",
                )

        except Exception as e:
            logger.error("运行工作流失败: %s", e)
            QMessageBox.critical(self, "运行失败", f"无法运行工作流:\n{str(e)}")

    def _on_edit_workflow(self, workflow_name: str, workflow_path: str):
        """编辑工作流（打开工作流）"""
        self._on_open_workflow(workflow_name, workflow_path)

    def _on_open_workflow(self, workflow_name: str, workflow_path: str):
        """打开工作流"""
        logger.info("打开工作流: %s - %s", workflow_name, workflow_path)

        if not os.path.exists(workflow_path):
            logger.warning("工作流文件不存在: %s", workflow_path)
            self._load_workflows()
            QMessageBox.warning(
                self,
                "文件不存在",
                f"工作流 '{workflow_name}' 的文件不存在。\n\n可能已被重命名或删除。\n工作流列表已刷新。",
            )
            return

        if self._main_window:
            from src.core.uv_manager import UVManager
            from src.core.workflow_executor import WorkflowExecutor
            from src.views.workflow_tab_widget import WorkflowTabWidget

            try:
                with open(workflow_path, "r", encoding="utf-8") as f:
                    workflow_data = json.load(f)

                workflow_widget = WorkflowTabWidget(workflow_name, self._main_window)
                workflow_widget.modified_changed.connect(
                    self._main_window._on_workflow_modified
                )

                from src.core.node_registry import get_registry
                from src.views.node_graphics import NodeGraphicsItem

                registry = get_registry()

                for node_data in workflow_data.get("nodes", []):
                    node_id = node_data["node_id"]
                    node_type_str = node_data["node_type"]

                    # 从注册表获取节点信息
                    node_def = registry.get_node(node_type_str)
                    node_type = node_type_str  # 统一使用字符串
                    node_title = node_def.name if node_def else node_type_str

                    node_item = NodeGraphicsItem(
                        node_id,
                        node_type,
                        node_title,
                        node_def.input_schema if node_def else {},
                        node_def.output_schema if node_def else {},
                    )
                    node_item.config = node_data.get("config", {})

                    pos = node_data.get("position", {"x": 0, "y": 0})
                    node_item.setPos(pos.get("x", 0), pos.get("y", 0))

                    workflow_widget.canvas._scene.addItem(node_item)
                    workflow_widget.nodes[node_id] = node_item

                version = workflow_data.get("version", 1)
                for edge_data in workflow_data.get("edges", []):
                    # 解析边数据（兼容新旧格式）
                    if version >= 2 and isinstance(edge_data, dict):
                        from_id = edge_data["from_node"]
                        from_port_name = edge_data.get("from_port", "output")
                        to_id = edge_data["to_node"]
                        to_port_name = edge_data.get("to_port", "input")
                    else:
                        from_id, to_id = edge_data[0], edge_data[1]
                        from_port_name = "output"
                        to_port_name = "input"

                    from src.views.workflow_tab_widget import ConnectionInfo
                    workflow_widget.connections.append(
                        ConnectionInfo(from_id, from_port_name, to_id, to_port_name)
                    )

                    if (
                        from_id in workflow_widget.nodes
                        and to_id in workflow_widget.nodes
                    ):
                        from_node = workflow_widget.nodes[from_id]
                        to_node = workflow_widget.nodes[to_id]

                        if from_node.output_ports and to_node.input_ports:
                            from src.views.node_graphics import ConnectionGraphicsItem

                            # 优先按端口名匹配，找不到则回退到第一个端口
                            from_port = from_node.get_output_port(from_port_name) or from_node.output_ports[0]
                            to_port = to_node.get_input_port(to_port_name) or to_node.input_ports[0]

                            connection = ConnectionGraphicsItem(
                                from_port, to_port
                            )
                            workflow_widget.canvas._scene.addItem(connection)

                index = self._main_window.tabs.addTab(workflow_widget, workflow_name)
                self._main_window.tabs.setCurrentIndex(index)

                canvas_state = workflow_data.get("canvas_state")
                if canvas_state:
                    from PySide6.QtCore import QTimer

                    QTimer.singleShot(
                        100,
                        lambda: workflow_widget.canvas.set_canvas_state(canvas_state),
                    )
                else:
                    # 如果工作流没有保存画布状态，应用全局默认缩放比例
                    from PySide6.QtCore import QTimer

                    QTimer.singleShot(
                        100,
                        lambda: workflow_widget.canvas.apply_default_zoom(),
                    )

                workflow_widget._set_modified(False)

                logger.info(
                    "工作流已加载: %d 个节点", len(workflow_data.get("nodes", []))
                )

            except Exception as e:
                logger.error("加载工作流失败: %s", e)
                import traceback

                traceback.print_exc()

                QMessageBox.critical(self, "加载失败", f"无法加载工作流:\n{str(e)}")

    def _on_delete_workflow(self, workflow_name: str):
        """删除工作流"""
        reply = QMessageBox.question(
            self,
            "确认删除",
            f"确定要删除工作流 '{workflow_name}' 吗？\n此操作无法撤销。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if reply == QMessageBox.Yes:
            try:
                workflow_dir = Path("workflows") / workflow_name
                if workflow_dir.exists():
                    shutil.rmtree(workflow_dir)
                    logger.info("工作流已删除: %s", workflow_name)
                else:
                    QMessageBox.warning(
                        self, "删除失败", f"工作流 '{workflow_name}' 不存在"
                    )

            except Exception as e:
                logger.error("删除失败: %s", e)
                QMessageBox.critical(self, "删除失败", f"无法删除工作流:\n{str(e)}")
            finally:
                self._load_workflows()

    def refresh_workflows(self):
        """刷新工作流列表"""
        self._load_workflows()

    def _on_add_workflow_clicked(self):
        if self._main_window:
            self._main_window.add_workflow_tab()

    def _create_workflows_tab(self):
        """创建工作流标签页 - 紧凑列表布局"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # 工具栏
        toolbar = QWidget()
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(0, 0, 0, 0)

        # 搜索框 - 支持实时过滤
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 搜索工作流...")
        self.search_input.setFixedWidth(300)
        self.search_input.setStyleSheet(ThemeManager.get_input_style())
        self.search_input.textChanged.connect(self._filter_workflows)
        toolbar_layout.addWidget(self.search_input)

        toolbar_layout.addStretch()

        # 刷新按钮
        refresh_btn = QPushButton("🔄 刷新")
        refresh_btn.setStyleSheet(ThemeManager.get_button_style("secondary"))
        refresh_btn.clicked.connect(self._load_workflows)
        toolbar_layout.addWidget(refresh_btn)

        layout.addWidget(toolbar)

        # 滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setStyleSheet("background: transparent;")
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        # 列表容器 - 使用垂直布局
        self.list_container = QWidget()
        self.list_layout = QVBoxLayout(self.list_container)
        self.list_layout.setSpacing(8)
        self.list_layout.setAlignment(Qt.AlignTop)
        self.list_layout.setContentsMargins(0, 0, 0, 0)

        # 空状态标签
        self.empty_label = QLabel('暂无工作流\n点击右上角"新建工作流"按钮创建')
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setStyleSheet(f"""
            QLabel {{
                color: {ThemeManager.COLORS["text_secondary"]};
                font-size: 14px;
                padding: 60px;
            }}
        """)

        scroll_area.setWidget(self.list_container)
        layout.addWidget(scroll_area)

        return tab

    def _create_scheduled_tab(self):
        """创建定时任务标签页 - 优化版"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # 工具栏
        toolbar = QWidget()
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(0, 0, 0, 0)

        toolbar_layout.addStretch()

        # 新增定时任务按钮
        add_btn = QPushButton("➕ 新增定时任务")
        add_btn.setStyleSheet(ThemeManager.get_button_style("primary"))
        add_btn.setFixedHeight(36)
        add_btn.clicked.connect(self._on_add_scheduled_task_clicked)
        toolbar_layout.addWidget(add_btn)

        refresh_btn = QPushButton("🔄 刷新")
        refresh_btn.setStyleSheet(ThemeManager.get_button_style("secondary"))
        refresh_btn.clicked.connect(self._load_scheduled_tasks)
        toolbar_layout.addWidget(refresh_btn)

        layout.addWidget(toolbar)

        # 表格
        self.scheduled_table = QTableWidget(0, 5)
        self.scheduled_table.setHorizontalHeaderLabels(
            ["工作流", "启用", "执行时间", "下次执行", "操作"]
        )
        self.scheduled_table.verticalHeader().setVisible(False)
        self.scheduled_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.scheduled_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.scheduled_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch
        )
        self.scheduled_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeToContents
        )
        self.scheduled_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeToContents
        )
        self.scheduled_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeToContents
        )
        self.scheduled_table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.Fixed
        )
        self.scheduled_table.setColumnWidth(4, 160)
        self.scheduled_table.setStyleSheet(ThemeManager.get_table_style())

        layout.addWidget(self.scheduled_table)

        return tab

    def _create_history_tab(self):
        """创建运行历史标签页 - 优化版"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # 工具栏
        toolbar = QWidget()
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(0, 0, 0, 0)

        toolbar_layout.addStretch()

        clear_btn = QPushButton("清空历史")
        clear_btn.setStyleSheet(ThemeManager.get_button_style("danger"))
        toolbar_layout.addWidget(clear_btn)

        refresh_btn = QPushButton("🔄 刷新")
        refresh_btn.setStyleSheet(ThemeManager.get_button_style("secondary"))
        refresh_btn.clicked.connect(self._load_execution_history)
        toolbar_layout.addWidget(refresh_btn)

        layout.addWidget(toolbar)

        # 表格
        self.history_table = QTableWidget(0, 5)
        self.history_table.setHorizontalHeaderLabels(
            ["时间", "工作流", "状态", "耗时", "操作"]
        )
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.history_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.history_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeToContents
        )
        self.history_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch
        )
        self.history_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeToContents
        )
        self.history_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeToContents
        )
        self.history_table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeToContents
        )
        self.history_table.setStyleSheet(ThemeManager.get_table_style())

        layout.addWidget(self.history_table)

        return tab

    def _load_scheduled_tasks(self):
        """加载定时任务"""
        self.scheduled_table.setRowCount(0)

        try:
            tasks = self.scheduler.get_tasks()

            for task in tasks:
                row = self.scheduled_table.rowCount()
                self.scheduled_table.insertRow(row)

                # 工作流名称
                name_item = QTableWidgetItem(task.get("workflow_name", "未知"))
                self.scheduled_table.setItem(row, 0, name_item)

                # 启用状态
                enabled = task.get("enabled", False)
                enabled_text = "✅ 是" if enabled else "❌ 否"
                enabled_item = QTableWidgetItem(enabled_text)
                self.scheduled_table.setItem(row, 1, enabled_item)

                # 执行时间
                schedule = task.get("schedule", {})
                time_str = schedule.get("time", "--:--")
                time_item = QTableWidgetItem(time_str)
                self.scheduled_table.setItem(row, 2, time_item)

                # 下次执行
                next_run = task.get("next_run", "未知")
                next_run_item = QTableWidgetItem(str(next_run))
                self.scheduled_table.setItem(row, 3, next_run_item)

                # 操作按钮
                action_widget = QWidget()
                action_layout = QHBoxLayout(action_widget)
                action_layout.setContentsMargins(4, 4, 4, 4)
                action_layout.setSpacing(8)

                edit_btn = QPushButton("编辑")
                edit_btn.setStyleSheet(ThemeManager.get_button_style("secondary"))
                edit_btn.setMinimumSize(60, 28)
                edit_btn.clicked.connect(
                    lambda checked, t=task: self._on_edit_scheduled_task(t)
                )
                action_layout.addWidget(edit_btn)

                delete_btn = QPushButton("删除")
                delete_btn.setStyleSheet(ThemeManager.get_button_style("danger"))
                delete_btn.setMinimumSize(60, 28)
                delete_btn.clicked.connect(
                    lambda checked, t=task: self._on_delete_scheduled_task(t)
                )
                action_layout.addWidget(delete_btn)

                self.scheduled_table.setCellWidget(row, 4, action_widget)

        except Exception as e:
            logger.error("加载定时任务失败: %s", e)

    def _load_execution_history(self):
        """加载运行历史"""
        self.history_table.setRowCount(0)

        try:
            history_dir = Path("history")
            if not history_dir.exists():
                return

            history_files = sorted(
                history_dir.glob("*.json"),
                key=lambda x: x.stat().st_mtime,
                reverse=True,
            )[:50]

            for history_file in history_files:
                try:
                    with open(history_file, "r", encoding="utf-8") as f:
                        data = json.load(f)

                    row = self.history_table.rowCount()
                    self.history_table.insertRow(row)

                    # 时间
                    timestamp = data.get("timestamp", "")
                    time_item = QTableWidgetItem(timestamp)
                    self.history_table.setItem(row, 0, time_item)

                    # 工作流名称
                    workflow_name = data.get("workflow_name", "未知")
                    name_item = QTableWidgetItem(workflow_name)
                    self.history_table.setItem(row, 1, name_item)

                    # 状态
                    status = data.get("status", "unknown")
                    status_map = {
                        "success": ("✅ 成功", ThemeManager.COLORS["success"]),
                        "failed": ("❌ 失败", ThemeManager.COLORS["error"]),
                        "running": ("⏳ 运行中", ThemeManager.COLORS["accent"]),
                    }
                    status_text, status_color = status_map.get(
                        status, ("❓ 未知", ThemeManager.COLORS["text_secondary"])
                    )
                    status_item = QTableWidgetItem(status_text)
                    status_item.setForeground(QColor(status_color))
                    self.history_table.setItem(row, 2, status_item)

                    # 耗时
                    duration = data.get("duration", 0)
                    duration_text = f"{duration:.2f}s" if duration else "--"
                    duration_item = QTableWidgetItem(duration_text)
                    self.history_table.setItem(row, 3, duration_item)

                    # 操作
                    action_widget = QWidget()
                    action_layout = QHBoxLayout(action_widget)
                    action_layout.setContentsMargins(4, 4, 4, 4)

                    view_btn = QPushButton("查看")
                    view_btn.setStyleSheet(ThemeManager.get_button_style("secondary"))
                    view_btn.setFixedHeight(28)
                    action_layout.addWidget(view_btn)

                    self.history_table.setCellWidget(row, 4, action_widget)

                except Exception as e:
                    logger.error("加载历史记录文件失败: %s - %s", history_file, e)

        except Exception as e:
            logger.error("加载运行历史失败: %s", e)

    def _on_add_scheduled_task_clicked(self):
        """打开新增定时任务对话框"""
        dialog = AddScheduledTaskDialog(self)
        if dialog.exec() == QDialog.Accepted:
            task_data = dialog.get_task_data()
            try:
                self.scheduler.add_task(
                    workflow_name=task_data["workflow_name"],
                    workflow_path=task_data["workflow_path"],
                    cron_expr=task_data["cron_expression"],
                )
                self._load_scheduled_tasks()
                ToastWidget.show(self, "定时任务已添加", "success")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"添加定时任务失败:\n{str(e)}")

    def _on_edit_scheduled_task(self, task: dict):
        """编辑定时任务"""
        dialog = AddScheduledTaskDialog(self, task=task)
        if dialog.exec() == QDialog.Accepted:
            task_data = dialog.get_task_data()
            try:
                self.scheduler.update_task(
                    task["id"],
                    workflow_name=task_data["workflow_name"],
                    workflow_path=task_data["workflow_path"],
                    cron_expression=task_data["cron_expression"],
                )
                self._load_scheduled_tasks()
                ToastWidget.show(self, "定时任务已更新", "success")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"更新定时任务失败:\n{str(e)}")

    def _on_delete_scheduled_task(self, task: dict):
        """删除定时任务"""
        reply = QMessageBox.question(
            self,
            "确认删除",
            f"确定要删除定时任务 '{task.get('workflow_name', '未知')}' 吗？\n此操作无法撤销。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if reply == QMessageBox.Yes:
            try:
                self.scheduler.delete_task(task["id"])
                self._load_scheduled_tasks()
                ToastWidget.show(self, "定时任务已删除", "success")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"删除定时任务失败:\n{str(e)}")


class AddScheduledTaskDialog(QDialog):
    """新增/编辑定时任务对话框"""

    def __init__(self, parent=None, task: dict = None):
        super().__init__(parent)
        self.task = task
        self.setWindowTitle("编辑定时任务" if task else "新增定时任务")
        self.setMinimumWidth(450)
        self._setup_ui()
        self._load_workflows()
        if task:
            self._load_task_data()

    def _setup_ui(self):
        """设置UI"""
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(20, 20, 20, 20)

        # 表单
        form_layout = QFormLayout()
        form_layout.setSpacing(12)

        # 工作流选择
        self.workflow_combo = QComboBox()
        self.workflow_combo.setStyleSheet(ThemeManager.get_input_style())
        form_layout.addRow("工作流:", self.workflow_combo)

        # 定时类型
        self.schedule_type = QComboBox()
        self.schedule_type.addItems(["预设间隔", "自定义 Cron"])
        self.schedule_type.setStyleSheet(ThemeManager.get_input_style())
        self.schedule_type.currentIndexChanged.connect(self._on_schedule_type_changed)
        form_layout.addRow("定时类型:", self.schedule_type)

        # 预设间隔
        self.preset_combo = QComboBox()
        presets = self._get_preset_intervals()
        for preset in presets:
            self.preset_combo.addItem(preset["name"], preset["cron"])
        self.preset_combo.setStyleSheet(ThemeManager.get_input_style())
        form_layout.addRow("执行间隔:", self.preset_combo)

        # 自定义 Cron
        self.cron_input = QLineEdit()
        self.cron_input.setPlaceholderText("例如: 0 9 * * 1-5 (工作日早上9点)")
        self.cron_input.setStyleSheet(ThemeManager.get_input_style())
        form_layout.addRow("Cron 表达式:", self.cron_input)

        # Cron 帮助文本
        cron_help = QLabel(
            "格式: 分 时 日 月 周\n"
            "示例: 0 9 * * 1-5 = 工作日早上9点\n"
            "      0 */6 * * * = 每6小时\n"
            "      30 14 * * 1 = 每周一14:30"
        )
        cron_help.setStyleSheet(
            f"color: {ThemeManager.COLORS['text_secondary']}; font-size: 11px;"
        )
        form_layout.addRow("", cron_help)

        layout.addLayout(form_layout)

        # 按钮
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        # 初始状态
        self._on_schedule_type_changed(0)

    def _get_preset_intervals(self) -> list:
        """获取预设时间间隔"""
        return [
            {"name": "每分钟", "cron": "*/1 * * * *"},
            {"name": "每小时", "cron": "0 * * * *"},
            {"name": "每天", "cron": "0 0 * * *"},
            {"name": "每周", "cron": "0 0 * * 0"},
            {"name": "每月", "cron": "0 0 1 * *"},
            {"name": "工作日每天 (周一至周五)", "cron": "0 9 * * 1-5"},
            {"name": "周末 (周六周日)", "cron": "0 10 * * 0,6"},
        ]

    def _load_workflows(self):
        """加载工作流列表到下拉框"""
        from src.core.workflow_scanner import scan_workflows
        self.workflow_combo.clear()
        for wf in scan_workflows():
            self.workflow_combo.addItem(wf["name"], wf["path"])

    def _load_task_data(self):
        """加载现有任务数据（编辑模式）"""
        # 设置工作流
        workflow_path = self.task.get("workflow_path", "")
        for i in range(self.workflow_combo.count()):
            if self.workflow_combo.itemData(i) == workflow_path:
                self.workflow_combo.setCurrentIndex(i)
                break

        # 设置 Cron 表达式
        cron_expr = self.task.get("cron_expression", "0 * * * *")

        # 检查是否是预设
        is_preset = False
        for i in range(self.preset_combo.count()):
            if self.preset_combo.itemData(i) == cron_expr:
                self.preset_combo.setCurrentIndex(i)
                is_preset = True
                break

        if is_preset:
            self.schedule_type.setCurrentIndex(0)
        else:
            self.schedule_type.setCurrentIndex(1)
            self.cron_input.setText(cron_expr)

    def _on_schedule_type_changed(self, index: int):
        """定时类型改变"""
        if index == 0:  # 预设间隔
            self.preset_combo.setVisible(True)
            self.cron_input.setVisible(False)
        else:  # 自定义 Cron
            self.preset_combo.setVisible(False)
            self.cron_input.setVisible(True)

    def get_task_data(self) -> dict:
        """获取任务数据"""
        if self.schedule_type.currentIndex() == 0:
            cron_expression = self.preset_combo.currentData()
        else:
            cron_expression = self.cron_input.text().strip()

        return {
            "workflow_name": self.workflow_combo.currentText(),
            "workflow_path": self.workflow_combo.currentData(),
            "cron_expression": cron_expression,
        }
