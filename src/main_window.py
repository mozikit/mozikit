import sys
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QDockWidget,
    QMainWindow,
    QMessageBox,
    QSizePolicy,
    QStatusBar,
    QSystemTrayIcon,
    QTabBar,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtWidgets import QMenu as TrayMenu

from src.core import __version__
from src.core.config_manager import ConfigManager
from src.core.log_manager import get_logger
from src.core.theme_manager import ThemeManager
from src.dialogs.settings_dialog import SettingsDialog
from src.views.ai_chat_widget import AIChatWidget
from src.views.execution_results_widget import ExecutionResultsWidget
from src.views.node_browser import NodeBrowserWidget
from src.views.node_properties import NodePropertiesWidget
from src.views.overview_widget import OverviewWidget
from src.views.workflow_tab_widget import WorkflowTabWidget

logger = get_logger("main_window")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"LocalFlow v{__version__}")
        self.setGeometry(300, 150, 785, 603)
        self._set_app_icon()
        self.workflow_count = 0

        self.config_manager = ConfigManager()

        self._setup_layout()
        self._restore_window_state()
        self._setup_system_tray()

    def _set_app_icon(self):
        """Prefer ICO for Windows shell integration, fallback to PNG for compatibility."""
        ico_path = self._get_resource_path("assets/localflow.ico")
        png_path = self._get_resource_path("assets/localflow_64.png")
        icon_path = ico_path if Path(ico_path).exists() else png_path
        self.setWindowIcon(QIcon(icon_path))

    def _setup_layout(self):
        """设置主窗口布局
        初始化主窗口的布局和UI组件

        创建并配置以下UI元素：
        - 左侧工具栏：包含节点浏览器和设置按钮
        - 中央标签页区域：包含Overview标签和工作流编辑标签
        - 右侧工具栏：包含节点属性按钮
        - 底部状态栏
        - 可停靠窗口：节点浏览器和节点属性面板

        配置所有UI组件的样式、大小策略和交互行为，包括：
        - 工具栏图标大小和方向
        - 标签页的可关闭和可移动属性
        - 停靠窗口的允许区域和默认状态
        - 各组件之间的信号连接

        内部方法，不直接对外暴露
        """
        toolbar = QToolBar("LeftToolbar", self)
        toolbar.setOrientation(Qt.Vertical)
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        toolbar.setIconSize(QSize(22, 22))
        toolbar.setStyleSheet(ThemeManager.get_toolbar_style("left"))
        toolbar.setFixedWidth(64)

        # 节点浏览器
        action_node_browser = toolbar.addAction(
            self._load_svg_icon("assets/icons/node_browser.svg"), "节点"
        )
        action_node_browser.triggered.connect(self._toggle_node_browser)

        # 添加弹性空间
        spacer = QWidget()
        # 扩展空白
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        toolbar.addWidget(spacer)

        # 运行结果按钮 - 切换底部运行结果面板
        action_execution_results = toolbar.addAction(
            self._load_svg_icon("assets/icons/execution.svg"), "运行结果"
        )
        action_execution_results.triggered.connect(self._toggle_execution_results)

        # 设置
        action_settings = toolbar.addAction(
            self._load_svg_icon("assets/icons/settings.svg"), "设置"
        )
        action_settings.triggered.connect(self._open_settings)

        # 中心区域
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.tabCloseRequested.connect(self._close_tab)
        self.tabs.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tabs.customContextMenuRequested.connect(self._show_tab_context_menu)
        self.tabs.setStyleSheet(ThemeManager.get_tab_widget_style())
        self.setCentralWidget(self.tabs)

        # 创建Overview标签页
        overview_widget = OverviewWidget(self)
        self.tabs.addTab(overview_widget, "首页")

        # 右侧工具栏
        toolbar_right = QToolBar("RightToolbar", self)
        toolbar_right.setOrientation(Qt.Vertical)
        toolbar_right.setMovable(False)
        toolbar_right.setFloatable(False)
        toolbar_right.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        toolbar_right.setIconSize(QSize(22, 22))
        toolbar_right.setStyleSheet(ThemeManager.get_toolbar_style("right"))
        toolbar_right.setFixedWidth(80)

        # 节点详情按钮 - 切换右侧节点属性面板
        action_node_props = toolbar_right.addAction(
            self._load_svg_icon("assets/icons/properties.svg"), "节点属性"
        )
        action_node_props.triggered.connect(self._toggle_node_properties)

        # AI 助手按钮 - 切换右侧 AI 聊天面板
        action_ai_chat = toolbar_right.addAction(
            self._load_svg_icon("assets/icons/ai_chat.svg"), "AI助手"
        )
        action_ai_chat.triggered.connect(self._toggle_ai_chat)

        # 节点浏览器 Dock（左侧）
        self.node_browser_dock = QDockWidget(self)
        self.node_browser_dock.setAllowedAreas(Qt.LeftDockWidgetArea)
        self.node_browser_dock.setTitleBarWidget(QWidget())  # 隐藏标题栏
        self.node_browser = NodeBrowserWidget(self)
        self.node_browser_dock.setWidget(self.node_browser)
        self.node_browser_dock.hide()

        # 节点属性 Dock（右侧）
        self.node_properties_dock = QDockWidget(self)
        self.node_properties_dock.setAllowedAreas(Qt.RightDockWidgetArea)
        self.node_properties_dock.setTitleBarWidget(QWidget())  # 隐藏标题栏
        self.node_properties = NodePropertiesWidget(self)
        self.node_properties_dock.setWidget(self.node_properties)
        self.node_properties_dock.hide()

        # 执行结果 Dock（底部）
        self.execution_results_dock = QDockWidget(self)
        self.execution_results_dock.setAllowedAreas(Qt.BottomDockWidgetArea)
        self.execution_results_dock.setTitleBarWidget(QWidget())  # 隐藏标题栏
        self.execution_results = ExecutionResultsWidget(self)
        self.execution_results_dock.setWidget(self.execution_results)
        # 设置最小高度，允许拖动调整
        self.execution_results_dock.setMinimumHeight(200)
        self.execution_results_dock.hide()

        # AI 聊天 Dock（右侧，与节点属性面板标签页堆叠）
        self.ai_chat_dock = QDockWidget(self)
        self.ai_chat_dock.setAllowedAreas(Qt.RightDockWidgetArea)
        self.ai_chat_dock.setTitleBarWidget(QWidget())
        self.ai_chat = AIChatWidget(self)
        self.ai_chat_dock.setWidget(self.ai_chat)
        self.ai_chat_dock.setMinimumWidth(320)
        self.ai_chat_dock.hide()

        # 信号连接：节点属性更新时通知当前工作流
        self.node_properties.properties_updated.connect(
            self._on_node_properties_updated
        )
        # 信号连接：从节点浏览器打开工作流
        self.node_browser.open_workflow_requested.connect(
            self._on_open_workflow_from_browser
        )
        # 信号连接：节点浏览器请求高亮节点
        self.node_browser.highlight_nodes_requested.connect(
            self._on_highlight_nodes_requested
        )
        # 信号连接：切换标签页时更新节点浏览器状态
        self.tabs.currentChanged.connect(self._on_tab_changed)

        # 布局：工具栏和停靠窗口
        self.addToolBar(Qt.LeftToolBarArea, toolbar)
        self.addToolBar(Qt.RightToolBarArea, toolbar_right)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.node_browser_dock)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.execution_results_dock)

        # 设置角落，使底部dock不占用左右两侧dock的空间
        self.setCorner(Qt.BottomLeftCorner, Qt.LeftDockWidgetArea)
        self.setCorner(Qt.BottomRightCorner, Qt.RightDockWidgetArea)

        # 右侧区域：使用自定义 QTabWidget 管理节点属性和 AI 助手
        self._right_tab_widget = QTabWidget()
        self._right_tab_widget.setDocumentMode(True)
        self._right_tab_widget.setTabsClosable(False)
        self._right_tab_widget.setMovable(False)
        self._right_tab_widget.setStyleSheet(ThemeManager.get_tab_widget_style())
        self._right_tab_widget.addTab(self.node_properties, "节点属性")
        self._right_tab_widget.addTab(self.ai_chat, "AI 助手")

        self._right_dock = QDockWidget(self)
        self._right_dock.setAllowedAreas(Qt.RightDockWidgetArea)
        self._right_dock.setTitleBarWidget(QWidget())
        self._right_dock.setWidget(self._right_tab_widget)
        self._right_dock.setMinimumWidth(320)
        self._right_dock.hide()
        self.addDockWidget(Qt.RightDockWidgetArea, self._right_dock)

        # 应用停靠窗口样式（包含 dock 标签栏样式）
        dock_style = ThemeManager.get_dock_widget_style()
        self.node_browser_dock.setStyleSheet(dock_style)
        self.execution_results_dock.setStyleSheet(dock_style)
        self._right_dock.setStyleSheet(dock_style)

        # 恢复dock窗口状态
        self._restore_dock_states()

        # 安装事件过滤器来监听dock窗口大小变化
        self.node_browser_dock.installEventFilter(self)
        self.execution_results_dock.installEventFilter(self)
        self._right_dock.installEventFilter(self)

    def _toggle_node_browser(self):
        """切换节点面板显示/隐藏"""
        if self.node_browser_dock.isVisible():
            self.node_browser_dock.hide()
        else:
            self.node_browser_dock.show()

    def _toggle_node_properties(self):
        """切换节点属性面板显示/隐藏"""
        if self._right_dock.isVisible() and self._right_tab_widget.currentIndex() == 0:
            self._right_dock.hide()
        else:
            self._right_tab_widget.setCurrentIndex(0)
            self._right_dock.show()

    def _toggle_execution_results(self):
        """切换运行结果面板显示/隐藏"""
        if self.execution_results_dock.isVisible():
            self.execution_results_dock.hide()
            # 隐藏时清除边框样式，避免残留视觉痕迹
            self.execution_results_dock.setStyleSheet("""
                QDockWidget {
                    border: none;
                    background: transparent;
                }
            """)
        else:
            # 显示时恢复原始样式
            dock_style = ThemeManager.get_dock_widget_style()
            self.execution_results_dock.setStyleSheet(dock_style)
            self.execution_results_dock.show()

    def _toggle_ai_chat(self):
        """切换 AI 聊天面板显示/隐藏"""
        if self._right_dock.isVisible() and self._right_tab_widget.currentIndex() == 1:
            self._right_dock.hide()
        else:
            self._right_tab_widget.setCurrentIndex(1)
            self._right_dock.show()
            self._update_ai_chat_context()

    def _update_ai_chat_context(self):
        """更新 AI 聊天的工作流上下文"""
        current_widget = self.tabs.currentWidget()
        if isinstance(current_widget, WorkflowTabWidget):
            self.ai_chat.set_workflow_context(current_widget)
        else:
            self.ai_chat.set_workflow_context(None)

    def _on_node_properties_updated(self, node_id: str, config: dict):
        """节点属性已更新"""
        # 获取当前工作流标签页
        current_widget = self.tabs.currentWidget()
        if isinstance(current_widget, WorkflowTabWidget):
            current_widget.update_node_config(node_id, config)

    def _on_open_workflow_from_browser(
        self, workflow_name: str, workflow_path: str, node_type: str
    ):
        """从节点面板请求打开工作流"""
        # 检查工作流是否已经打开
        for i in range(self.tabs.count()):
            widget = self.tabs.widget(i)
            if (
                isinstance(widget, WorkflowTabWidget)
                and widget.workflow_name == workflow_name
            ):
                # 已经打开，切换到该标签并高亮节点
                self.tabs.setCurrentIndex(i)
                widget.canvas.highlight_nodes_by_type(node_type)
                return

        # 需要打开工作流，复用OverviewWidget的逻辑
        overview_widget = self.tabs.widget(0)
        if hasattr(overview_widget, "_on_open_workflow"):
            overview_widget._on_open_workflow(workflow_name, workflow_path)

            # 等待工作流打开后高亮节点
            from PySide6.QtCore import QTimer

            QTimer.singleShot(100, lambda: self._highlight_after_open(node_type))

    def _highlight_after_open(self, node_type: str):
        """工作流打开后高亮节点"""
        current_widget = self.tabs.currentWidget()
        if isinstance(current_widget, WorkflowTabWidget):
            current_widget.canvas.highlight_nodes_by_type(node_type)

    def _on_highlight_nodes_requested(self, node_type: str):
        """处理高亮节点请求"""
        current_widget = self.tabs.currentWidget()
        if isinstance(current_widget, WorkflowTabWidget):
            current_widget.canvas.highlight_nodes_by_type(node_type)

    def _on_tab_changed(self, index: int):
        """Tab切换时更新节点面板统计"""
        widget = self.tabs.widget(index)
        if isinstance(widget, WorkflowTabWidget):
            # 获取工作流中的节点数据
            nodes_data = widget.canvas.get_all_nodes()
            self.node_browser.update_workflow_stats(widget.workflow_name, nodes_data)
        else:
            # 非工作流标签（如Overview）
            self.node_browser.update_workflow_stats(None)
            # 在首页时彻底隐藏运行结果dock，移除边框避免残留视觉痕迹
            self.execution_results_dock.hide()
            self.execution_results_dock.setStyleSheet("""
                QDockWidget {
                    border: none;
                    background: transparent;
                }
            """)
        # 更新 AI 聊天上下文
        self._update_ai_chat_context()

    def add_workflow_tab(self):
        """Add a new workflow tab"""
        self.workflow_count += 1
        workflow_name = f"工作流 {self.workflow_count}"
        workflow_widget = WorkflowTabWidget(workflow_name, self)

        # 连接工作流的修改信号
        workflow_widget.modified_changed.connect(self._on_workflow_modified)

        # Add the new workflow tab
        index = self.tabs.addTab(workflow_widget, workflow_name)

        # Change the current tab to the new one
        self.tabs.setCurrentIndex(index)

    def _close_tab(self, index):
        """关闭指定标签页"""
        # 不允许关闭Overview标签（第0个）
        if index == 0:
            return

        widget = self.tabs.widget(index)
        if isinstance(widget, WorkflowTabWidget):
            if widget.is_running():
                from PySide6.QtWidgets import QMessageBox

                reply = QMessageBox.question(
                    self,
                    "工作流正在运行",
                    f"工作流 '{widget.workflow_name}' 正在运行中。\n\n关闭将中断执行，是否继续？",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if reply == QMessageBox.No:
                    return
            if not self._check_save_before_close(widget):
                return  # 用户取消关闭

        self.tabs.removeTab(index)
        widget.deleteLater()

    def _show_tab_context_menu(self, pos):
        """显示标签页右键菜单"""
        # 获取点击的标签索引
        tab_bar = self.tabs.tabBar()
        index = tab_bar.tabAt(pos)

        if index < 0 or index == 0:  # 无效索引或Overview标签
            return

        from PySide6.QtWidgets import QMenu

        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background-color: {ThemeManager.COLORS["surface"]};
                color: {ThemeManager.COLORS["text"]};
                border: 1px solid {ThemeManager.COLORS["border"]};
                border-radius: 8px;
                padding: 6px;
            }}
            QMenu::item {{
                padding: 8px 24px;
                border-radius: 6px;
                margin: 2px 4px;
            }}
            QMenu::item:selected {{
                background-color: {ThemeManager.COLORS["accent"]};
                color: {ThemeManager.COLORS["white"]};
            }}
            QMenu::separator {{
                height: 1px;
                background-color: {ThemeManager.COLORS["border"]};
                margin: 4px 12px;
            }}
        """)

        close_action = menu.addAction("关闭当前")
        rename_action = menu.addAction("重命名")
        menu.addSeparator()
        close_others_action = menu.addAction("关闭其他")
        close_all_action = menu.addAction("关闭所有")

        action = menu.exec_(tab_bar.mapToGlobal(pos))

        if action == close_action:
            self._close_tab(index)
        elif action == rename_action:
            self._rename_tab(index)
        elif action == close_others_action:
            self._close_other_tabs(index)
        elif action == close_all_action:
            self._close_all_tabs()

    def _close_other_tabs(self, keep_index):
        """关闭除指定标签外的其他标签"""
        # 从后向前关闭，避免索引变化
        for i in range(self.tabs.count() - 1, 0, -1):
            if i != keep_index:
                self._close_tab(i)

    def _close_all_tabs(self):
        """关闭所有工作流标签（除了Overview）"""
        # 从后向前关闭
        for i in range(self.tabs.count() - 1, 0, -1):
            self._close_tab(i)

    def _check_save_before_close(self, workflow_widget):
        """关闭前检查是否需要保存

        Returns:
            bool: True表示可以继续关闭，False表示用户取消关闭
        """
        if not workflow_widget.is_modified():
            return True

        from PySide6.QtWidgets import QMessageBox

        reply = QMessageBox.question(
            self,
            "保存工作流",
            f"工作流 '{workflow_widget.workflow_name}' 有未保存的更改。\n是否保存？",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Save,
        )

        if reply == QMessageBox.Save:
            workflow_widget._save_workflow_sync()
            return True
        elif reply == QMessageBox.Discard:
            return True
        else:  # Cancel
            return False

    def _on_workflow_modified(self, is_modified):
        """工作流修改状态改变"""
        sender_widget = self.sender()
        if not sender_widget:
            return

        # 找到对应的标签索引
        for i in range(self.tabs.count()):
            if self.tabs.widget(i) == sender_widget:
                workflow_name = sender_widget.workflow_name
                if is_modified:
                    self.tabs.setTabText(i, f"{workflow_name} *")
                else:
                    self.tabs.setTabText(i, workflow_name)
                break

    def closeEvent(self, event):
        """窗口关闭事件"""
        from PySide6.QtWidgets import QApplication

        if getattr(self, "_quitting", False):
            for i in range(1, self.tabs.count()):
                widget = self.tabs.widget(i)
                if isinstance(widget, WorkflowTabWidget):
                    if not self._check_save_before_close(widget):
                        self._quitting = False
                        event.ignore()
                        return
            self._save_before_quit()
            event.accept()
            return

        if self._has_running_workflows():
            running_names = self._get_running_workflow_names()
            names_text = "、".join(running_names)
            reply = QMessageBox.question(
                self,
                "工作流正在运行",
                f"以下工作流正在运行中：{names_text}\n\n"
                f"关闭窗口将中断正在运行的工作流。\n\n"
                f"是否最小化到系统托盘继续运行？",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
                QMessageBox.Yes,
            )
            if reply == QMessageBox.Yes:
                self.hide()
                self._tray_icon.show()
                if not getattr(self, "_tray_notified", False):
                    self._tray_icon.showMessage(
                        "LocalFlow",
                        "工作流正在后台运行中，双击托盘图标恢复窗口",
                        QSystemTrayIcon.Information,
                        3000,
                    )
                    self._tray_notified = True
                event.ignore()
                return
            elif reply == QMessageBox.Cancel:
                event.ignore()
                return
            else:
                self._quitting = True
                for i in range(1, self.tabs.count()):
                    widget = self.tabs.widget(i)
                    if isinstance(widget, WorkflowTabWidget):
                        if not self._check_save_before_close(widget):
                            self._quitting = False
                            event.ignore()
                            return
                self._save_before_quit()
                event.accept()
                return

        for i in range(1, self.tabs.count()):
            widget = self.tabs.widget(i)
            if isinstance(widget, WorkflowTabWidget):
                if not self._check_save_before_close(widget):
                    event.ignore()
                    return

        self._save_before_quit()
        event.accept()

    def _save_before_quit(self):
        """退出前保存窗口和dock状态"""
        from PySide6.QtWidgets import QApplication

        if not self.isMaximized() and not self.isFullScreen():
            geometry = self.geometry()

            screen = QApplication.primaryScreen()
            available_geometry = screen.availableGeometry()

            x = max(
                available_geometry.left(),
                min(geometry.x(), available_geometry.right() - 100),
            )
            y = max(
                available_geometry.top(),
                min(geometry.y(), available_geometry.bottom() - 100),
            )
            width = min(geometry.width(), available_geometry.width())
            height = min(geometry.height(), available_geometry.height())

            self.config_manager.set_window_geometry(x, y, width, height)

        self._save_dock_states()
        self.config_manager.save_config_sync()

    def eventFilter(self, obj, event):
        """事件过滤器，监听dock窗口的大小变化"""
        from PySide6.QtCore import QEvent

        # 监听dock窗口的Resize事件
        if event.type() == QEvent.Resize:
            if obj in [
                self.node_browser_dock,
                self._right_dock,
                self.execution_results_dock,
            ]:
                # 使用定时器延迟保存，避免频繁保存
                if not hasattr(self, "_dock_save_timer"):
                    from PySide6.QtCore import QTimer

                    self._dock_save_timer = QTimer(self)
                    self._dock_save_timer.setSingleShot(True)
                    self._dock_save_timer.timeout.connect(self._save_dock_states)

                self._dock_save_timer.start(500)  # 500ms后保存

        return super().eventFilter(obj, event)

    def add_node_to_canvas(self, node_type):
        """添加节点到当前画布的中心位置"""
        current_widget = self.tabs.currentWidget()
        if isinstance(current_widget, WorkflowTabWidget):
            import time

            from src.views.node_graphics import NodeGraphicsItem

            # 统一从注册表获取节点显示名
            node_type_str = (
                node_type.value if hasattr(node_type, "value") else str(node_type)
            )

            from src.core.node_registry import get_registry

            registry = get_registry()
            node_def = registry.get_node(node_type_str)
            node_title = node_def.name if node_def else node_type_str

            # 生成唯一ID
            node_id = f"node_{int(time.time() * 1000)}"

            # 创建节点 — 统一使用字符串作为 node_type
            input_schema = node_def.input_schema if node_def else {}
            output_schema = node_def.output_schema if node_def else {}
            node_item = NodeGraphicsItem(
                node_id, node_type_str, node_title, input_schema, output_schema
            )

            # 获取画布中心位置（场景坐标）
            canvas = current_widget.canvas
            view_center = canvas.viewport().rect().center()
            scene_center = canvas.mapToScene(view_center)

            # 设置节点位置（考虑节点大小，使其居中）
            node_item.setPos(
                scene_center.x() - node_item.width / 2,
                scene_center.y() - node_item.height / 2,
            )

            # 添加到场景
            canvas._scene.addItem(node_item)

            # 触发节点添加信号（这会触发修改标识）
            canvas.node_added.emit(node_item)

            logger.info("添加节点到画布中心: %s (%s)", node_title, node_id)

    def _rename_tab(self, index):
        """重命名指定标签页"""
        if index <= 0:  # 不允许重命名Overview标签
            return

        widget = self.tabs.widget(index)
        if isinstance(widget, WorkflowTabWidget):
            widget.rename_workflow()

    def update_tab_name(self, workflow_widget, new_name):
        """更新标签页名称

        Args:
            workflow_widget: WorkflowTabWidget实例
            new_name: 新的工作流名称
        """
        # 找到对应的标签索引
        for i in range(self.tabs.count()):
            if self.tabs.widget(i) == workflow_widget:
                # 更新标签文本，考虑修改状态
                current_text = self.tabs.tabText(i)
                if current_text.endswith(" *"):
                    self.tabs.setTabText(i, f"{new_name} *")
                else:
                    self.tabs.setTabText(i, new_name)
                break

    def _restore_window_state(self):
        """恢复窗口状态"""
        from PySide6.QtWidgets import QApplication

        geometry = self.config_manager.get_window_geometry()

        # 获取屏幕可用区域（排除任务栏）
        screen = QApplication.primaryScreen()
        available_geometry = screen.availableGeometry()

        if geometry:
            x = geometry.get("x", 300)
            y = geometry.get("y", 150)
            width = geometry.get("width", 785)
            height = geometry.get("height", 603)

            # 确保窗口在可用区域内
            # 如果窗口超出屏幕边界，则调整到可用区域内
            if x < available_geometry.left():
                x = available_geometry.left()
            if y < available_geometry.top():
                y = available_geometry.top()
            if x + width > available_geometry.right():
                width = min(width, available_geometry.width())
                x = available_geometry.right() - width
            if y + height > available_geometry.bottom():
                height = min(height, available_geometry.height())
                y = available_geometry.bottom() - height

            # 如果窗口当前是最大化状态，先恢复正常
            if self.isMaximized():
                self.showNormal()
            if self.isFullScreen():
                self.showNormal()

            self.setGeometry(x, y, width, height)
        else:
            # 首次启动，使用默认大小并居中显示
            self.resize(785, 603)
            self.move(
                available_geometry.center().x() - self.width() // 2,
                available_geometry.center().y() - self.height() // 2,
            )

    def _restore_dock_states(self):
        """恢复dock窗口状态"""
        self.node_browser_dock.hide()
        self.execution_results_dock.hide()
        self._right_dock.hide()

    def _save_dock_states(self):
        """保存dock窗口状态（当前不记忆dock显示状态）"""
        pass

    def show_execution_report(self, report: dict):
        """显示运行结果面板"""
        self.execution_results.show_report(report)
        # 恢复dock的原始样式后再显示
        dock_style = ThemeManager.get_dock_widget_style()
        self.execution_results_dock.setStyleSheet(dock_style)
        self.execution_results_dock.show()
        self._save_dock_states()

    def _toggle_node_browser(self):
        """切换节点面板显示"""
        if self.node_browser_dock.isVisible():
            self.node_browser_dock.hide()
        else:
            self.node_browser_dock.show()

        # 实时保存状态
        self._save_dock_states()

    def _toggle_node_properties(self):
        """切换节点属性显示"""
        if self._right_dock.isVisible():
            self._right_dock.hide()
        else:
            self._right_tab_widget.setCurrentIndex(0)
            self._right_dock.show()

        # 实时保存状态
        self._save_dock_states()

    def _get_resource_path(self, relative_path):
        """获取资源文件的绝对路径，支持开发和打包环境"""
        # 开发环境
        dev_path = Path(relative_path)
        if dev_path.exists():
            return str(dev_path)

        # 打包环境（PyInstaller）
        if hasattr(sys, "_MEIPASS"):
            base_path = Path(sys._MEIPASS)
            resource_path = base_path / relative_path
        else:
            # 如果是其他情况，尝试相对于可执行文件
            base_path = Path(sys.executable).parent
            resource_path = base_path / relative_path

            # 如果在_internal目录中，需要调整路径
            if not resource_path.exists():
                internal_path = base_path.parent / "_internal" / relative_path
                if internal_path.exists():
                    resource_path = internal_path

        # 如果资源文件存在，返回路径
        if resource_path.exists():
            return str(resource_path)

        # 最后的备选方案
        return relative_path

    def _load_svg_icon(self, relative_path: str, size: QSize = None) -> QIcon:
        """加载 SVG 图标并渲染为 QIcon

        PySide6 的 QIcon 直接加载 SVG 时可能无法正确渲染。
        此方法读取 SVG 内容，将颜色替换为主题文字色，再渲染为 QPixmap，
        确保图标在深色主题下正确显示。

        Args:
            relative_path: SVG 文件的相对路径
            size: 目标图标大小，默认使用工具栏的 iconSize (22x22)

        Returns:
            QIcon: 渲染后的图标
        """
        if size is None:
            size = QSize(22, 22)

        svg_path = self._get_resource_path(relative_path)

        # 读取 SVG 内容并替换颜色为主题文字色
        try:
            with open(svg_path, "r", encoding="utf-8") as f:
                svg_content = f.read()
        except Exception:
            return QIcon()

        # 将所有硬编码颜色替换为主题文字色，使图标统一且可见
        import re

        # 替换 stroke="#xxxxxx" 和 fill="#xxxxxx"
        svg_content = re.sub(
            r'stroke="#[0-9A-Fa-f]{6}"',
            f'stroke="{ThemeManager.COLORS["text"]}"',
            svg_content,
        )
        svg_content = re.sub(
            r'fill="#[0-9A-Fa-f]{6}"',
            f'fill="{ThemeManager.COLORS["text"]}"',
            svg_content,
        )
        # 也替换 3 位颜色码
        svg_content = re.sub(
            r'stroke="#[0-9A-Fa-f]{3}"',
            f'stroke="{ThemeManager.COLORS["text"]}"',
            svg_content,
        )
        svg_content = re.sub(
            r'fill="#[0-9A-Fa-f]{3}"',
            f'fill="{ThemeManager.COLORS["text"]}"',
            svg_content,
        )

        # 从修改后的 SVG 内容创建渲染器
        from PySide6.QtCore import QByteArray

        renderer = QSvgRenderer(QByteArray(svg_content.encode("utf-8")))
        pixmap = QPixmap(size)
        pixmap.fill(Qt.transparent)

        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()

        return QIcon(pixmap)

    def _open_settings(self):
        """Open settings dialog"""
        dialog = SettingsDialog(self)
        dialog.exec()
        # 设置关闭后刷新 AI 聊天服务配置
        self.ai_chat.refresh_settings()

    def _setup_system_tray(self):
        """初始化系统托盘图标和菜单"""
        self._tray_icon = QSystemTrayIcon(self)
        self._tray_icon.setIcon(self.windowIcon())
        self._tray_icon.setToolTip("LocalFlow")

        tray_menu = TrayMenu(self)
        tray_menu.setStyleSheet(f"""
            QMenu {{
                background-color: {ThemeManager.COLORS["surface"]};
                color: {ThemeManager.COLORS["text"]};
                border: 1px solid {ThemeManager.COLORS["border"]};
                border-radius: 8px;
                padding: 6px;
            }}
            QMenu::item {{
                padding: 8px 24px;
                border-radius: 6px;
                margin: 2px 4px;
            }}
            QMenu::item:selected {{
                background-color: {ThemeManager.COLORS["accent"]};
                color: {ThemeManager.COLORS["white"]};
            }}
        """)

        show_action = tray_menu.addAction("显示主窗口")
        show_action.triggered.connect(self._show_from_tray)
        tray_menu.addSeparator()
        quit_action = tray_menu.addAction("退出")
        quit_action.triggered.connect(self._force_quit)

        self._tray_icon.setContextMenu(tray_menu)
        self._tray_icon.activated.connect(self._on_tray_activated)

    def _on_tray_activated(self, reason):
        """托盘图标激活事件"""
        if reason == QSystemTrayIcon.DoubleClick:
            self._show_from_tray()

    def _show_from_tray(self):
        """从系统托盘恢复显示主窗口"""
        self.showNormal()
        self.activateWindow()
        self.raise_()
        self._tray_icon.hide()
        self._tray_notified = False

    def _force_quit(self):
        """强制退出应用"""
        self._quitting = True
        self.close()

    def _has_running_workflows(self) -> bool:
        """检查是否有工作流正在运行"""
        for i in range(1, self.tabs.count()):
            widget = self.tabs.widget(i)
            if isinstance(widget, WorkflowTabWidget) and widget.is_running():
                return True
        return False

    def _get_running_workflow_names(self) -> list:
        """获取正在运行的工作流名称列表"""
        names = []
        for i in range(1, self.tabs.count()):
            widget = self.tabs.widget(i)
            if isinstance(widget, WorkflowTabWidget) and widget.is_running():
                names.append(widget.workflow_name)
        return names
