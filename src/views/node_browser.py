"""
节点浏览器 - 优化版
显示官方支持的节点类型列表，并支持查看节点使用情况和工作流节点统计
优化特性：
- 更现代的UI设计
- 增强的视觉反馈
- 改进的交互体验
"""

from PySide6.QtCore import QMimeData, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QDrag, QFont, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.core.log_manager import get_logger
from src.core.node_registry import (
    NODE_SOURCE_INFO,
    NodeRegistry,
    NodeSource,
    get_registry,
)
from src.core.theme_manager import ThemeManager
from src.core.workflow_scanner import WorkflowScanner
from src.views.toast_widget import ToastWidget

logger = get_logger("node_browser")


class DraggableListWidget(QListWidget):
    """支持拖拽的列表控件 - 优化版"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragOnly)
        self.setSpacing(4)

    def startDrag(self, supportedActions):
        """开始拖拽"""
        item = self.currentItem()
        if not item:
            return

        node_data = item.data(Qt.UserRole)
        if not node_data:
            return

        # 创建拖拽对象
        drag = QDrag(self)
        mime_data = QMimeData()

        # 设置节点类型数据
        node_type_str = node_data.get("type_str") or node_data.get("type", "")

        if not node_type_str:
            return

        mime_data.setText(node_type_str)
        drag.setMimeData(mime_data)

        # 执行拖拽
        drag.exec_(Qt.CopyAction)


class NodeUpdateWorker(QThread):
    """异步节点更新工作线程 - 逐步检查官方节点和GitHub外部节点更新"""

    progress = Signal(str)
    step_result = Signal(str, bool)
    nodes_updated = Signal()
    finished_all = Signal()

    _SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, user_data_dir, github_token, parent=None):
        super().__init__(parent)
        self._user_data_dir = user_data_dir
        self._github_token = github_token
        self._step_wait = _StepWait()

    def _emit_step(self, msg: str, is_error: bool):
        """发出步骤结果并等待UI展示完毕"""
        self.step_result.emit(msg, is_error)
        self._step_wait.wait()

    def resume(self):
        """UI展示完毕，通知Worker继续"""
        self._step_wait.wake()

    def run(self):
        import json
        from pathlib import Path

        from src.core.node_repo_manager import NodeRepoManager
        from src.core.providers.github_provider import GitHubNodeProvider

        user_data = Path(self._user_data_dir)
        any_updated = False

        try:
            self.progress.emit("检查官方节点更新...")
            mgr = NodeRepoManager(user_data)
            mgr.set_github_token(self._github_token)
            check = mgr.check_for_updates()
            if check.error:
                self._emit_step(f"官方节点: {check.error}", True)
            elif check.has_updates:
                # 新 API：只报告可更新的版本，不自动安装
                total_new = sum(len(u.new_versions) for u in check.updates)
                total_nodes = len(check.updates)
                new_nodes_count = len(check.new_nodes)
                self._emit_step(
                    f"官方 ✓ 发现更新: {check.remote_repo_version} "
                    f"({total_nodes}个节点有{total_new}个新版本, "
                    f"{new_nodes_count}个新节点)",
                    False,
                )
                # 注意：不再自动拉取，用户需要在节点库面板选择性安装
            else:
                ver = check.repo_version
                self._emit_step(f"官方已是最新 ({ver})", False)
        except Exception as e:
            self._emit_step(f"官方节点: {e}", True)

        try:
            external_github_dir = user_data / "external_nodes" / "github"
            if external_github_dir.exists():
                repos_checked = set()
                for config_file in external_github_dir.rglob("node.json"):
                    repo_url = ""
                    try:
                        with open(config_file, "r", encoding="utf-8") as f:
                            config = json.load(f)
                        repo_url = config.get("repo_url", "")
                        if not repo_url or repo_url in repos_checked:
                            continue
                        repos_checked.add(repo_url)
                        short_name = repo_url.rstrip("/").split("/")[-1]
                        self.progress.emit(f"更新 GitHub: {short_name}...")
                        provider = GitHubNodeProvider(user_data, self._github_token)
                        downloaded = provider.download_nodes(repo_url)
                        if downloaded:
                            any_updated = True
                            self._emit_step(
                                f"GitHub ✓ {short_name} ({len(downloaded)}节点)", False
                            )
                        else:
                            self._emit_step(f"GitHub - {short_name} 无更新", False)
                    except Exception as ex:
                        self._emit_step(f"GitHub ✗ {short_name or '?'}: {ex}", True)
        except Exception as e:
            logger.error("GitHub节点更新失败: %s", e)

        if any_updated:
            self.nodes_updated.emit()
        self.finished_all.emit()


class _StepWait:
    """线程同步：Worker发出结果后等待UI展示完毕再继续"""

    def __init__(self):
        from threading import Condition

        self._cond = Condition()
        self._ready = False

    def wait(self, timeout=5.0):
        with self._cond:
            self._ready = False
            self._cond.wait_for(lambda: self._ready, timeout=timeout)

    def wake(self):
        with self._cond:
            self._ready = True
            self._cond.notify_all()


class NodeBrowserWidget(QWidget):
    """节点面板 - 优化版"""

    node_selected = Signal(str, dict)
    open_workflow_requested = Signal(str, str, str)
    highlight_nodes_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scanner = WorkflowScanner()
        self._current_workflow_name = None
        self._update_worker = None
        self._spinner_timer = QTimer(self)
        self._spinner_timer.timeout.connect(self._advance_spinner)
        self._spinner_index = 0
        self._setup_ui()
        self._load_nodes()

    def _setup_ui(self):
        """设置UI - 优化版"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Tab切换
        self.tab_widget = QTabWidget()
        self.tab_widget.setStyleSheet(ThemeManager.get_tab_widget_style())
        layout.addWidget(self.tab_widget)

        # Tab 1: 节点列表
        self._setup_node_list_tab()

        # Tab 2: 使用统计
        self._setup_usage_stats_tab()

    def _setup_node_list_tab(self):
        """设置节点列表Tab - 优化版"""
        tab_widget = QWidget()
        tab_layout = QVBoxLayout(tab_widget)
        tab_layout.setContentsMargins(12, 12, 12, 12)
        tab_layout.setSpacing(12)

        # 工具栏 - 紧凑版
        toolbar_layout = QHBoxLayout()
        toolbar_layout.setSpacing(8)

        # 添加节点按钮
        self.add_node_btn = QPushButton("➕ 添加")
        self.add_node_btn.setFixedHeight(30)
        self.add_node_btn.setStyleSheet(ThemeManager.get_button_style("primary"))
        self.add_node_btn.setCursor(Qt.PointingHandCursor)
        self.add_node_btn.clicked.connect(self._on_add_node_clicked)
        toolbar_layout.addWidget(self.add_node_btn)

        # 检查更新按钮
        self.update_btn = QPushButton("🔄 更新")
        self.update_btn.setFixedHeight(30)
        self.update_btn.setStyleSheet(ThemeManager.get_button_style("secondary"))
        self.update_btn.setCursor(Qt.PointingHandCursor)
        self.update_btn.clicked.connect(self._on_check_updates_clicked)
        toolbar_layout.addWidget(self.update_btn)

        toolbar_layout.addStretch()

        # 来源筛选下拉框
        self.source_filter = QComboBox()
        self.source_filter.addItems(
            ["全部", "🏛️ 官方", "🐙 GitHub", "🏢 内网", "👤 自定义"]
        )
        self.source_filter.setStyleSheet(ThemeManager.get_input_style())
        self.source_filter.setMinimumWidth(100)
        self.source_filter.setFixedHeight(30)
        self.source_filter.currentIndexChanged.connect(self._on_source_filter_changed)
        toolbar_layout.addWidget(self.source_filter)

        tab_layout.addLayout(toolbar_layout)

        # 搜索框 - 紧凑版
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 搜索...")
        self.search_input.setFixedHeight(30)
        self.search_input.textChanged.connect(self._filter_nodes)
        self.search_input.setStyleSheet(ThemeManager.get_input_style())
        tab_layout.addWidget(self.search_input)

        # 使用Splitter分割节点列表和使用详情
        splitter = QSplitter(Qt.Vertical)
        splitter.setStyleSheet(f"""
            QSplitter::handle {{
                background-color: {ThemeManager.COLORS["border"]};
                height: 2px;
            }}
        """)

        # 节点列表
        self.node_list = DraggableListWidget()
        self.node_list.setStyleSheet(self._get_list_style())
        self.node_list.itemClicked.connect(self._on_node_clicked)
        self.node_list.itemDoubleClicked.connect(self._on_node_double_clicked)
        splitter.addWidget(self.node_list)

        # 节点使用详情区域 - 紧凑版
        usage_container = QWidget()
        usage_container.setStyleSheet(f"""
            background-color: {ThemeManager.COLORS["surface"]};
            border-radius: 8px;
        """)
        usage_layout = QVBoxLayout(usage_container)
        usage_layout.setContentsMargins(10, 10, 10, 10)
        usage_layout.setSpacing(8)

        usage_title = QLabel("📋 使用情况")
        usage_title_font = QFont()
        usage_title_font.setPointSize(10)
        usage_title_font.setWeight(QFont.Weight.Bold)
        usage_title.setFont(usage_title_font)
        usage_title.setStyleSheet(f"color: {ThemeManager.COLORS['text']};")
        usage_layout.addWidget(usage_title)

        self.usage_list = QListWidget()
        self.usage_list.setStyleSheet(self._get_list_style())
        self.usage_list.itemDoubleClicked.connect(self._on_workflow_double_clicked)
        self.usage_list.setMinimumHeight(60)
        usage_layout.addWidget(self.usage_list)

        self.usage_hint = QLabel("点击节点查看使用情况\n双击工作流可打开")
        self.usage_hint.setStyleSheet(f"""
            color: {ThemeManager.COLORS["text_secondary"]};
            font-size: 9px;
            padding: 6px;
        """)
        self.usage_hint.setAlignment(Qt.AlignCenter)
        usage_layout.addWidget(self.usage_hint)

        splitter.addWidget(usage_container)

        # 设置Splitter初始比例
        splitter.setSizes([350, 200])

        tab_layout.addWidget(splitter)

        # 说明标签 - 紧凑版
        help_label = QLabel("💡 双击或拖拽添加节点")
        help_label.setStyleSheet(f"""
            color: {ThemeManager.COLORS["text_secondary"]};
            font-size: 10px;
            padding: 6px;
        """)
        help_label.setAlignment(Qt.AlignCenter)
        tab_layout.addWidget(help_label)

        self.tab_widget.addTab(tab_widget, "📦 节点列表")

    def _setup_usage_stats_tab(self):
        """设置使用统计Tab - 优化版"""
        tab_widget = QWidget()
        tab_layout = QVBoxLayout(tab_widget)
        tab_layout.setContentsMargins(12, 12, 12, 12)
        tab_layout.setSpacing(12)

        # 当前工作流标题
        title_container = QWidget()
        title_container.setStyleSheet(f"""
            background-color: {ThemeManager.COLORS["surface"]};
            border-radius: 10px;
        """)
        title_layout = QHBoxLayout(title_container)
        title_layout.setContentsMargins(14, 12, 14, 12)

        workflow_icon = QLabel("📁")
        title_layout.addWidget(workflow_icon)

        self.workflow_title = QLabel("当前工作流: 无")
        title_font = QFont()
        title_font.setPointSize(12)
        title_font.setWeight(QFont.Weight.Bold)
        self.workflow_title.setFont(title_font)
        self.workflow_title.setStyleSheet(f"color: {ThemeManager.COLORS['text']};")
        title_layout.addWidget(self.workflow_title)
        title_layout.addStretch()

        tab_layout.addWidget(title_container)

        # 节点使用统计列表
        self.stats_list = QListWidget()
        self.stats_list.setStyleSheet(self._get_list_style())
        self.stats_list.itemClicked.connect(self._on_stats_item_clicked)
        self.stats_list.itemDoubleClicked.connect(self._on_stats_item_double_clicked)
        tab_layout.addWidget(self.stats_list)

        # 空状态提示
        self.stats_empty_label = QLabel("打开一个工作流后，\n这里会显示节点使用统计")
        self.stats_empty_label.setStyleSheet(f"""
            color: {ThemeManager.COLORS["text_secondary"]};
            font-size: 12px;
            padding: 40px;
        """)
        self.stats_empty_label.setAlignment(Qt.AlignCenter)
        tab_layout.addWidget(self.stats_empty_label)

        # 提示
        stats_hint = QLabel("💡 点击查看详情，双击高亮节点")
        stats_hint.setStyleSheet(f"""
            color: {ThemeManager.COLORS["text_secondary"]};
            font-size: 11px;
            padding: 8px;
        """)
        stats_hint.setAlignment(Qt.AlignCenter)
        tab_layout.addWidget(stats_hint)

        self.tab_widget.addTab(tab_widget, "📊 使用统计")

    def _get_list_style(self) -> str:
        """获取列表控件样式 - 紧凑版"""
        return f"""
            QListWidget {{
                background-color: {ThemeManager.COLORS["background"]};
                border: 1px solid {ThemeManager.COLORS["border"]};
                border-radius: 8px;
                padding: 4px;
                outline: none;
            }}
            QListWidget::item {{
                padding: 8px 10px;
                border-radius: 6px;
                margin: 1px 0px;
                font-size: 10pt;
            }}
            QListWidget::item:selected {{
                background-color: {ThemeManager.COLORS["accent"]};
                color: white;
            }}
            QListWidget::item:hover {{
                background-color: {ThemeManager.COLORS["surface_light"]};
            }}
            QListWidget::item:selected:hover {{
                background-color: {ThemeManager.COLORS["accent_hover"]};
            }}
            QScrollBar:vertical {{
                background: transparent;
                width: 6px;
                border-radius: 3px;
            }}
            QScrollBar::handle:vertical {{
                background: {ThemeManager.COLORS["border"]};
                border-radius: 3px;
                min-height: 24px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {ThemeManager.COLORS["border_light"]};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
        """

    def _load_nodes(self):
        """加载节点列表"""
        # 从节点注册表加载节点
        self._registry = get_registry()
        self.nodes_data = self._registry.get_all_nodes()
        self._current_source_filter = None
        self._populate_list(self.nodes_data)

    def _populate_list(self, nodes):
        """填充节点列表"""
        self.node_list.clear()

        for node_data in nodes:
            item = QListWidgetItem()

            # 获取来源信息
            source = node_data.get("source", NodeSource.OFFICIAL)
            source_info = NODE_SOURCE_INFO.get(
                source, NODE_SOURCE_INFO[NodeSource.OFFICIAL]
            )

            # 是否已修改
            is_modified = node_data.get("modified", False)
            modified_marker = " ⚡已修改" if is_modified else ""

            # 设置文本：来源标签 + 名称 + 仓库名 + 修改标记
            source_tag = f"[{source_info['name']}]"
            name_part = node_data["name"]

            # GitHub节点追加仓库名（只展示仓库名）
            repo_suffix = ""
            if source == NodeSource.GITHUB:
                repo_url = node_data.get("repo_url", "")
                if repo_url:
                    # 从 https://github.com/owner/repo 提取 repo
                    parts = repo_url.rstrip("/").split("/")
                    if len(parts) >= 1:
                        repo_suffix = f"@{parts[-1]}"

            text = f"{source_tag}{name_part}{repo_suffix}{modified_marker}\n{node_data.get('description', '')}"
            item.setText(text)

            # 设置数据
            item.setData(Qt.UserRole, node_data)

            # 根据来源设置颜色
            if is_modified:
                item.setForeground(QColor(ThemeManager.COLORS["warning"]))
            else:
                item.setForeground(QColor(source_info["color"]))

            self.node_list.addItem(item)

    def _on_source_filter_changed(self, index):
        """来源筛选变化"""
        source_map = {
            0: None,  # 全部
            1: NodeSource.OFFICIAL,
            2: NodeSource.GITHUB,
            3: NodeSource.ENTERPRISE,
            4: NodeSource.CUSTOM,
        }
        self._current_source_filter = source_map.get(index)
        self._apply_filters()

    def _on_add_node_clicked(self):
        """添加节点按钮点击"""
        from src.dialogs.add_node_dialog import AddNodeDialog

        dialog = AddNodeDialog(self)
        # 连接信号：当 GitHub 节点导入成功时实时刷新列表
        dialog.nodes_imported.connect(self._load_nodes)
        if dialog.exec():
            self._load_nodes()

    def _on_check_updates_clicked(self):
        """检查所有节点更新（官方+GitHub），异步执行不阻塞UI"""
        if self._update_worker and self._update_worker.isRunning():
            return

        from pathlib import Path

        from src.core.config_manager import ConfigManager

        config = ConfigManager()
        token = config.get_github_token()

        self.update_btn.setEnabled(False)
        self._spinner_index = 0
        self.update_btn.setText("⠋ 检查中...")
        self._spinner_timer.start(80)

        self._update_worker = NodeUpdateWorker(
            str(Path("user_data")), token, parent=self
        )
        self._update_worker.progress.connect(self._on_update_progress)
        self._update_worker.step_result.connect(self._on_step_result)
        self._update_worker.nodes_updated.connect(self._on_nodes_updated)
        self._update_worker.finished_all.connect(self._on_update_finished)
        self._update_worker.start()

    def _advance_spinner(self):
        """推进按钮上的spinner动画"""
        frames = NodeUpdateWorker._SPINNER_FRAMES
        self._spinner_index = (self._spinner_index + 1) % len(frames)
        current_text = self.update_btn.text()
        prefix = current_text.split(" ", 1)[1] if " " in current_text else "检查中..."
        self.update_btn.setText(f"{frames[self._spinner_index]} {prefix}")

    def _on_update_progress(self, msg: str):
        """更新进度提示"""
        frames = NodeUpdateWorker._SPINNER_FRAMES
        frame = frames[self._spinner_index]
        self.update_btn.setText(f"{frame} {msg}")

    def _on_step_result(self, msg: str, is_error: bool):
        """单个步骤完成，在按钮上短暂展示结果（绿色/红色），1.5秒后恢复spinner"""
        self._spinner_timer.stop()
        color = (
            ThemeManager.COLORS["error"] if is_error else ThemeManager.COLORS["success"]
        )
        self.update_btn.setStyleSheet(
            ThemeManager.get_button_style("secondary")
            + f"QPushButton {{ color: {color}; }}"
        )
        self.update_btn.setText(f"{'✗' if is_error else '✓'} {msg}")
        QTimer.singleShot(1500, self._resume_spinner_after_step)

    def _resume_spinner_after_step(self):
        """步骤结果展示完毕，唤醒Worker继续，恢复spinner"""
        if self._update_worker:
            self._update_worker.resume()
        if self._update_worker and self._update_worker.isRunning():
            self.update_btn.setStyleSheet(ThemeManager.get_button_style("secondary"))
            self._spinner_index = 0
            self._spinner_timer.start(80)
            self.update_btn.setText("⠋ 继续...")
        else:
            self._finish_update_button()

    def _on_nodes_updated(self):
        """有节点被更新，重新加载注册表和列表"""
        self._registry._load_official_nodes()
        self._registry._load_external_nodes()
        self._load_nodes()

    def _on_update_finished(self):
        """所有更新完成"""
        if not self._spinner_timer.isActive():
            QTimer.singleShot(100, self._finish_update_button)
        else:
            self._finish_update_button()

    def _finish_update_button(self):
        """恢复按钮到初始状态"""
        self._spinner_timer.stop()
        self.update_btn.setEnabled(True)
        self.update_btn.setStyleSheet(ThemeManager.get_button_style("secondary"))
        self.update_btn.setText("🔄 更新")

    def _apply_filters(self):
        """应用筛选条件"""
        search_text = self.search_input.text().lower()

        filtered = []
        for node in self.nodes_data:
            # 来源筛选
            if self._current_source_filter is not None:
                if node.get("source") != self._current_source_filter:
                    continue

            # 搜索筛选
            if search_text:
                # 构建与显示一致的仓库后缀，用于支持 @仓库名 搜索
                repo_suffix = ""
                if node.get("source") == NodeSource.GITHUB:
                    repo_url = node.get("repo_url", "")
                    if repo_url:
                        parts = repo_url.rstrip("/").split("/")
                        if len(parts) >= 1:
                            repo_suffix = f"@{parts[-1]}"

                searchable = (
                    node["name"].lower()
                    + node.get("description", "").lower()
                    + node["category"].lower()
                    + repo_suffix.lower()
                )
                if search_text not in searchable:
                    continue

            filtered.append(node)

        self._populate_list(filtered)

    def _filter_nodes(self, text):
        """过滤节点"""
        self._apply_filters()

    def _on_node_clicked(self, item):
        """节点被点击"""
        node_data = item.data(Qt.UserRole)
        # 获取节点类型字符串
        node_type_str = node_data.get("type_str", "") or node_data.get("type", "")

        self.node_selected.emit(node_type_str, node_data)

        # 更新使用情况列表
        self._update_usage_list(node_type_str)

    def _update_usage_list(self, node_type: str):
        """更新节点使用情况列表"""
        self.usage_list.clear()

        workflows = self._scanner.get_workflows_using_node(node_type)

        if not workflows:
            self.usage_hint.setText("该节点暂未被任何工作流使用")
            self.usage_hint.show()
            return

        self.usage_hint.setText(f"被 {len(workflows)} 个工作流使用\n双击打开工作流")

        for wf_info in workflows:
            item = QListWidgetItem()
            item.setText(f"📁 {wf_info.workflow_name}  ({wf_info.count}次)")
            item.setData(
                Qt.UserRole,
                {
                    "workflow_name": wf_info.workflow_name,
                    "workflow_path": wf_info.workflow_path,
                    "node_type": node_type,
                    "node_ids": wf_info.node_ids,
                },
            )
            item.setForeground(QColor(ThemeManager.COLORS["text_secondary"]))
            self.usage_list.addItem(item)

    def _on_workflow_double_clicked(self, item):
        """使用情况中的工作流被双击"""
        data = item.data(Qt.UserRole)
        if data:
            self.open_workflow_requested.emit(
                data["workflow_name"], data["workflow_path"], data["node_type"]
            )

    def _on_node_double_clicked(self, item):
        """节点被双击"""
        node_data = item.data(Qt.UserRole)
        logger.info("双击节点: %s", node_data["name"])

        # 通知主窗口添加节点到画布中心
        # 向上查找主窗口
        widget = self.parent()
        while widget:
            if hasattr(widget, "add_node_to_canvas"):
                node_type_str = node_data.get("type_str")
                node_type_str = node_data.get("type_str", "") or node_data.get(
                    "type", ""
                )

                if node_type_str:
                    widget.add_node_to_canvas(node_type_str)
                break
            widget = widget.parent() if hasattr(widget, "parent") else None

    def _on_stats_item_clicked(self, item):
        """统计列表项被点击"""
        data = item.data(Qt.UserRole)
        if data:
            # 发送高亮请求
            self.highlight_nodes_requested.emit(data["node_type"])

    def _on_stats_item_double_clicked(self, item):
        """统计列表项被双击 - 高亮节点"""
        data = item.data(Qt.UserRole)
        if data:
            self.highlight_nodes_requested.emit(data["node_type"])

    def update_workflow_stats(self, workflow_name: str, nodes_data: list = None):
        """
        更新当前工作流的节点统计

        Args:
            workflow_name: 工作流名称，None表示无活跃工作流
            nodes_data: 可选的节点数据列表（如果提供则直接使用，否则从扫描器获取）
        """
        self._current_workflow_name = workflow_name
        self.stats_list.clear()

        if not workflow_name:
            self.workflow_title.setText("当前工作流: 无")
            self.stats_empty_label.show()
            self.stats_list.hide()
            return

        self.workflow_title.setText(f"当前工作流: {workflow_name}")

        # 获取节点统计
        if nodes_data is not None:
            # 从提供的数据构建统计
            usage_stats = self._build_stats_from_nodes(nodes_data)
        else:
            # 从扫描器获取
            usage_stats = self._scanner.get_nodes_in_workflow(workflow_name)

        if not usage_stats:
            self.stats_empty_label.setText("该工作流中暂无节点")
            self.stats_empty_label.show()
            self.stats_list.hide()
            return

        self.stats_empty_label.hide()
        self.stats_list.show()

        for usage_info in usage_stats:
            item = QListWidgetItem()
            count_text = f"×{usage_info.count}" if usage_info.count > 1 else ""
            item.setText(
                f"{usage_info.node_icon}  {usage_info.node_name}  {count_text}"
            )
            item.setData(
                Qt.UserRole,
                {"node_type": usage_info.node_type, "node_ids": usage_info.node_ids},
            )
            item.setForeground(QColor(ThemeManager.COLORS["text_secondary"]))
            self.stats_list.addItem(item)

    def _build_stats_from_nodes(self, nodes_data: list) -> list:
        """从节点数据构建统计信息"""
        from src.core.workflow_scanner import NodeUsageInfo

        seen_types = {}
        usage_list = []

        for node in nodes_data:
            node_type = node.get("node_type", "")
            node_id = node.get("node_id", "")

            if node_type and node_id:
                if node_type in seen_types:
                    seen_types[node_type].count += 1
                    seen_types[node_type].node_ids.append(node_id)
                else:
                    info = self._scanner.get_node_info(node_type)
                    usage_info = NodeUsageInfo(
                        node_type=node_type,
                        node_name=info["name"],
                        node_icon=info["icon"],
                        count=1,
                        node_ids=[node_id],
                    )
                    seen_types[node_type] = usage_info
                    usage_list.append(usage_info)

        return usage_list

    def refresh_node_usage(self):
        """刷新节点使用情况（重新扫描工作流目录）"""
        self._scanner.scan_all_workflows()

        # 如果当前有选中的节点，刷新使用列表
        current_item = self.node_list.currentItem()
        if current_item:
            node_data = current_item.data(Qt.UserRole)
            if node_data:
                node_type_str = node_data.get("type_str")
                node_type_str = node_data.get("type_str", "") or node_data.get(
                    "type", ""
                )
                if node_type_str:
                    self._update_usage_list(node_type_str)

        # 刷新当前工作流统计
        if self._current_workflow_name:
            self.update_workflow_stats(self._current_workflow_name)
