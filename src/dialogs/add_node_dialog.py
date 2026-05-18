"""
添加节点对话框
支持 AI 生成、GitHub 导入、内网导入和手工创建自定义节点
"""

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.core.ai_node_generator import AINodeGenerationService
from src.core.config_manager import ConfigManager
from src.core.node_registry import NodeSource, get_registry
from src.core.theme_manager import ThemeManager
from src.views.toast_widget import ToastWidget


class AINodeGenerationWorker(QThread):
    """AI 节点生成线程"""

    finished = Signal(bool, object)

    def __init__(self, ai_settings: dict, spec: dict):
        super().__init__()
        self.ai_settings = ai_settings
        self.spec = spec

    def run(self):
        try:
            service = AINodeGenerationService(self.ai_settings)
            result = service.generate_node(self.spec)
            self.finished.emit(True, result)
        except Exception as exc:
            self.finished.emit(False, str(exc))


class GitHubImportWorker(QThread):
    """GitHub 节点导入线程"""

    finished = Signal(bool, object, object)  # success, node_defs, error_message

    def __init__(self, user_data_dir, github_url: str, github_token: str = None):
        super().__init__()
        self.user_data_dir = user_data_dir
        self.github_url = github_url
        self.github_token = github_token

    def run(self):
        try:
            from src.core.providers.github_provider import GitHubNodeProvider

            provider = GitHubNodeProvider(
                self.user_data_dir, github_token=self.github_token
            )
            node_defs = provider.download_nodes(self.github_url)
            self.finished.emit(True, node_defs, None)
        except Exception as exc:
            self.finished.emit(False, None, str(exc))


class AddNodeDialog(QDialog):
    """添加节点对话框"""

    # 信号：当有新节点被成功导入时发出
    nodes_imported = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("添加节点")
        self.setMinimumWidth(520)
        self.setMinimumHeight(480)
        self.setMaximumHeight(700)
        self.config_manager = ConfigManager()
        self.generate_worker = None
        self.github_import_worker = None
        self._setup_ui()
        self._apply_style()

    def _setup_ui(self):
        """设置UI - 使用标签页布局优化空间"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # 创建标签页
        self.tab_widget = QTabWidget()
        self.tab_widget.setDocumentMode(True)

        # === AI 生成标签页 ===
        ai_tab = QWidget()
        ai_layout = QVBoxLayout(ai_tab)
        ai_layout.setContentsMargins(12, 12, 12, 12)
        ai_layout.setSpacing(12)

        # 使用滚动区域容纳AI表单的多个字段
        ai_scroll = QScrollArea()
        ai_scroll.setWidgetResizable(True)
        ai_scroll.setFrameShape(QScrollArea.NoFrame)

        ai_form_widget = QWidget()
        ai_form_layout = QFormLayout(ai_form_widget)
        ai_form_layout.setSpacing(10)
        ai_form_layout.setContentsMargins(0, 0, 0, 0)

        self.ai_name_input = QLineEdit()
        self.ai_name_input.setPlaceholderText("例如: HTTP 请求节点")
        ai_form_layout.addRow("节点名称:", self.ai_name_input)

        self.ai_desc_input = QTextEdit()
        self.ai_desc_input.setMaximumHeight(60)
        self.ai_desc_input.setPlaceholderText("描述节点要完成的核心功能")
        ai_form_layout.addRow("用途描述:", self.ai_desc_input)

        self.ai_input_spec = QTextEdit()
        self.ai_input_spec.setMaximumHeight(50)
        self.ai_input_spec.setPlaceholderText("input_data 中提供的字段")
        ai_form_layout.addRow("输入说明:", self.ai_input_spec)

        self.ai_output_spec = QTextEdit()
        self.ai_output_spec.setMaximumHeight(50)
        self.ai_output_spec.setPlaceholderText("execute 返回的字段")
        ai_form_layout.addRow("输出说明:", self.ai_output_spec)

        self.ai_constraints_input = QTextEdit()
        self.ai_constraints_input.setMaximumHeight(50)
        self.ai_constraints_input.setPlaceholderText("例如: 优先使用标准库，超时10秒")
        ai_form_layout.addRow("约束条件:", self.ai_constraints_input)

        # 示例输入输出并排
        example_widget = QWidget()
        example_layout = QHBoxLayout(example_widget)
        example_layout.setContentsMargins(0, 0, 0, 0)
        example_layout.setSpacing(8)

        self.ai_example_input = QTextEdit()
        self.ai_example_input.setMaximumHeight(50)
        self.ai_example_input.setPlaceholderText('{"url": "https://example.com"}')
        example_layout.addWidget(QLabel("示例输入:"))
        example_layout.addWidget(self.ai_example_input)

        self.ai_example_output = QTextEdit()
        self.ai_example_output.setMaximumHeight(50)
        self.ai_example_output.setPlaceholderText('{"status": 200}')
        example_layout.addWidget(QLabel("输出:"))
        example_layout.addWidget(self.ai_example_output)

        ai_form_layout.addRow("示例:", example_widget)

        ai_scroll.setWidget(ai_form_widget)
        ai_layout.addWidget(ai_scroll)

        ai_hint = QLabel("需在设置中配置 OpenAI 兼容接口")
        ai_hint.setStyleSheet(
            f"color: {ThemeManager.COLORS['text_secondary']}; font-size: 9pt;"
        )
        ai_layout.addWidget(ai_hint)

        self.ai_generate_btn = QPushButton("生成节点")
        self.ai_generate_btn.setStyleSheet(ThemeManager.get_button_style("primary"))
        self.ai_generate_btn.clicked.connect(self._start_ai_generation)
        ai_layout.addWidget(self.ai_generate_btn)

        self.tab_widget.addTab(ai_tab, "🤖 AI 生成")

        # === GitHub 导入标签页 ===
        github_tab = QWidget()
        github_layout = QVBoxLayout(github_tab)
        github_layout.setContentsMargins(12, 12, 12, 12)
        github_layout.setSpacing(12)

        # --- 导入区域 ---
        import_group = QGroupBox("导入新仓库")
        import_group.setStyleSheet(f"""
            QGroupBox {{
                color: {ThemeManager.COLORS["text_secondary"]};
                font-size: 9pt;
                border: 1px solid {ThemeManager.COLORS["border"]};
                border-radius: 6px;
                margin-top: 8px;
                padding-top: 8px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 4px;
            }}
        """)
        import_layout = QVBoxLayout(import_group)
        import_layout.setSpacing(8)
        import_layout.setContentsMargins(10, 4, 10, 10)

        github_form = QFormLayout()
        github_form.setSpacing(10)

        self.github_url_input = QLineEdit()
        self.github_url_input.setPlaceholderText(
            "https://github.com/username/node-repo"
        )
        github_form.addRow("仓库 URL:", self.github_url_input)
        import_layout.addLayout(github_form)

        github_hint = QLabel(
            "支持单节点仓库、manifest.json 多节点仓库，或直接填写某个节点目录 URL\nPrivate 仓库需先在设置中配置 GitHub 认证"
        )
        github_hint.setStyleSheet(
            f"color: {ThemeManager.COLORS['text_secondary']}; font-size: 9pt;"
        )
        github_hint.setWordWrap(True)
        import_layout.addWidget(github_hint)

        self.github_import_btn = QPushButton("导入节点")
        self.github_import_btn.setStyleSheet(ThemeManager.get_button_style("primary"))
        self.github_import_btn.clicked.connect(self._import_github_node)
        import_layout.addWidget(self.github_import_btn)

        github_layout.addWidget(import_group)

        # --- 已导入仓库区域 ---
        imported_group = QGroupBox("已导入的仓库")
        imported_group.setStyleSheet(f"""
            QGroupBox {{
                color: {ThemeManager.COLORS["text_secondary"]};
                font-size: 9pt;
                border: 1px solid {ThemeManager.COLORS["border"]};
                border-radius: 6px;
                margin-top: 8px;
                padding-top: 8px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 4px;
            }}
        """)
        imported_layout = QVBoxLayout(imported_group)
        imported_layout.setSpacing(8)
        imported_layout.setContentsMargins(10, 4, 10, 10)

        self.imported_repos_list = QListWidget()
        self.imported_repos_list.setStyleSheet(f"""
            QListWidget {{
                background-color: {ThemeManager.COLORS["background"]};
                border: 1px solid {ThemeManager.COLORS["border"]};
                border-radius: 6px;
                padding: 4px;
                outline: none;
            }}
            QListWidget::item {{
                padding: 6px 8px;
                border-radius: 4px;
                margin: 1px 0px;
            }}
            QListWidget::item:selected {{
                background-color: {ThemeManager.COLORS["accent"]};
                color: white;
            }}
            QListWidget::item:hover {{
                background-color: {ThemeManager.COLORS["surface_light"]};
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
        """)
        self.imported_repos_list.itemClicked.connect(self._on_imported_repo_clicked)
        imported_layout.addWidget(self.imported_repos_list)

        # 已选仓库的节点列表
        self.imported_nodes_label = QLabel("点击仓库查看已导入的节点")
        self.imported_nodes_label.setStyleSheet(
            f"color: {ThemeManager.COLORS['text_secondary']}; font-size: 9pt;"
        )
        self.imported_nodes_label.hide()
        imported_layout.addWidget(self.imported_nodes_label)

        self.imported_nodes_list = QListWidget()
        self.imported_nodes_list.setStyleSheet(f"""
            QListWidget {{
                background-color: {ThemeManager.COLORS["background"]};
                border: 1px solid {ThemeManager.COLORS["border"]};
                border-radius: 6px;
                padding: 4px;
                outline: none;
            }}
            QListWidget::item {{
                padding: 4px 8px;
                border-radius: 4px;
                margin: 1px 0px;
                font-size: 9pt;
            }}
            QListWidget::item:selected {{
                background-color: {ThemeManager.COLORS["accent"]};
                color: white;
            }}
            QListWidget::item:hover {{
                background-color: {ThemeManager.COLORS["surface_light"]};
            }}
        """)
        self.imported_nodes_list.hide()
        imported_layout.addWidget(self.imported_nodes_list)

        # 删除按钮
        btn_layout = QHBoxLayout()
        self.delete_repo_btn = QPushButton("删除选中仓库")
        self.delete_repo_btn.setStyleSheet(ThemeManager.get_button_style("danger"))
        self.delete_repo_btn.setEnabled(False)
        self.delete_repo_btn.clicked.connect(self._delete_imported_repo)
        btn_layout.addWidget(self.delete_repo_btn)
        btn_layout.addStretch()
        imported_layout.addLayout(btn_layout)

        github_layout.addWidget(imported_group)
        github_layout.setStretch(0, 0)
        github_layout.setStretch(1, 1)

        self.tab_widget.addTab(github_tab, "🌐 GitHub 导入")

        # 加载已导入的仓库列表
        self._load_imported_repos()

        # === 手工创建标签页 ===
        custom_tab = QWidget()
        custom_layout = QVBoxLayout(custom_tab)
        custom_layout.setContentsMargins(12, 12, 12, 12)
        custom_layout.setSpacing(12)

        custom_form = QFormLayout()
        custom_form.setSpacing(10)

        self.custom_name_input = QLineEdit()
        self.custom_name_input.setPlaceholderText("我的自定义节点")
        custom_form.addRow("节点名称:", self.custom_name_input)

        self.custom_desc_input = QLineEdit()
        self.custom_desc_input.setPlaceholderText("节点功能描述")
        custom_form.addRow("节点描述:", self.custom_desc_input)

        custom_layout.addLayout(custom_form)

        custom_hint = QLabel("创建后可在属性面板编辑源代码")
        custom_hint.setStyleSheet(
            f"color: {ThemeManager.COLORS['text_secondary']}; font-size: 9pt;"
        )
        custom_layout.addWidget(custom_hint)

        custom_layout.addStretch()

        self.custom_create_btn = QPushButton("创建节点")
        self.custom_create_btn.setStyleSheet(ThemeManager.get_button_style("primary"))
        self.custom_create_btn.clicked.connect(self._create_custom_node)
        custom_layout.addWidget(self.custom_create_btn)

        self.tab_widget.addTab(custom_tab, "📝 手工创建")

        layout.addWidget(self.tab_widget)

        # 进度条
        self.progress_label = QLabel("")
        self.progress_label.hide()
        self.progress_label.setStyleSheet(f"color: {ThemeManager.COLORS['accent']};")
        layout.addWidget(self.progress_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.hide()
        self.progress_bar.setRange(0, 0)
        layout.addWidget(self.progress_bar)

        # 底部按钮
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        cancel_btn = QPushButton("关闭")
        cancel_btn.setStyleSheet(ThemeManager.get_button_style("secondary"))
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        layout.addLayout(button_layout)

    def _apply_style(self):
        """应用样式"""
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {ThemeManager.COLORS["surface"]};
            }}
            QLabel {{
                color: {ThemeManager.COLORS["text"]};
            }}
            QProgressBar {{
                border: 1px solid {ThemeManager.COLORS["border"]};
                border-radius: 4px;
                background-color: {ThemeManager.COLORS["surface_light"]};
            }}
            QProgressBar::chunk {{
                background-color: {ThemeManager.COLORS["accent"]};
            }}
            QTabWidget::pane {{
                border: 1px solid {ThemeManager.COLORS["border"]};
                border-radius: 8px;
                background-color: {ThemeManager.COLORS["background"]};
                top: -1px;
            }}
            QTabBar::tab {{
                background-color: {ThemeManager.COLORS["surface_light"]};
                color: {ThemeManager.COLORS["text_secondary"]};
                border: 1px solid {ThemeManager.COLORS["border"]};
                border-bottom: none;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                padding: 8px 16px;
                margin-right: 2px;
            }}
            QTabBar::tab:selected {{
                background-color: {ThemeManager.COLORS["accent"]};
                color: {ThemeManager.COLORS["white"]};
            }}
            QTabBar::tab:hover:!selected {{
                background-color: {ThemeManager.COLORS["surface_lighter"]};
                color: {ThemeManager.COLORS["text"]};
            }}
            {ThemeManager.get_input_style()}
        """)

    def _start_ai_generation(self):
        """启动 AI 节点生成"""
        name = self.ai_name_input.text().strip()
        description = self.ai_desc_input.toPlainText().strip()
        if not name:
            QMessageBox.warning(self, "提示", "请输入节点名称")
            return
        if not description:
            QMessageBox.warning(self, "提示", "请输入用途描述")
            return

        ai_settings = self.config_manager.get_ai_settings()
        missing_fields = [
            field
            for field in ("base_url", "api_key", "model")
            if not str(ai_settings.get(field, "")).strip()
        ]
        if missing_fields:
            QMessageBox.warning(
                self,
                "AI 配置缺失",
                f"请先在设置中补全 AI 配置：{', '.join(missing_fields)}",
            )
            return

        spec = {
            "name": name,
            "description": description,
            "input_spec": self.ai_input_spec.toPlainText().strip(),
            "output_spec": self.ai_output_spec.toPlainText().strip(),
            "constraints": self.ai_constraints_input.toPlainText().strip(),
            "example_input": self.ai_example_input.toPlainText().strip(),
            "example_output": self.ai_example_output.toPlainText().strip(),
        }

        self._set_generating_state(True, "正在生成节点，请稍候...")
        self.generate_worker = AINodeGenerationWorker(ai_settings, spec)
        self.generate_worker.finished.connect(self._on_ai_generation_finished)
        self.generate_worker.start()

    def _on_ai_generation_finished(self, success: bool, payload):
        """AI 生成结束"""
        self._set_generating_state(False)
        worker = self.generate_worker
        self.generate_worker = None
        if worker:
            worker.deleteLater()

        if not success:
            QMessageBox.critical(self, "生成失败", f"AI 生成节点失败：\n\n{payload}")
            return

        try:
            from src.core.custom_node_manager import CustomNodeManager
            from src.core.node_registry import get_registry

            registry = get_registry()
            manager = CustomNodeManager(registry._user_data_dir)
            node_def = manager.create_generated_node(
                name=payload.name,
                description=payload.description,
                source_code=payload.source_code,
                config_schema=payload.config_schema,
                dependencies=payload.dependencies,
                category=payload.category,
                version=payload.version,
            )
            if not node_def:
                raise ValueError("创建节点目录失败")

            registry.register_external_node(node_def)
        except Exception as exc:
            QMessageBox.critical(
                self, "保存失败", f"AI 已生成节点代码，但写入本地节点失败：\n\n{exc}"
            )
            return

        dependency_text = (
            "无额外依赖"
            if not payload.dependencies
            else ", ".join(payload.dependencies)
        )
        ToastWidget.show(
            self,
            f"AI 节点 '{payload.name}' 创建成功！依赖: {dependency_text}",
            "success",
        )
        self.accept()

    def _set_generating_state(self, generating: bool, message: str = ""):
        """切换生成中状态"""
        self.ai_generate_btn.setEnabled(not generating)
        if generating:
            self.progress_label.setText(message)
            self.progress_label.show()
            self.progress_bar.show()
        else:
            self.progress_label.hide()
            self.progress_bar.hide()

    def _load_imported_repos(self):
        """加载已导入的 GitHub 仓库列表"""
        self.imported_repos_list.clear()
        self.imported_nodes_list.hide()
        self.imported_nodes_label.hide()
        self.delete_repo_btn.setEnabled(False)

        registry = get_registry()
        github_nodes = registry.get_nodes_by_source(NodeSource.GITHUB)

        # 按 repo_url 分组
        repos = {}
        for node in github_nodes:
            repo_url = node.repo_url or "未知仓库"
            if repo_url not in repos:
                repos[repo_url] = []
            repos[repo_url].append(node)

        if not repos:
            item = QListWidgetItem("暂无已导入的仓库")
            item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
            self.imported_repos_list.addItem(item)
            return

        for repo_url, nodes in sorted(repos.items()):
            # 提取仓库短名
            parts = repo_url.rstrip("/").split("/")
            if len(parts) >= 2:
                short_name = f"{parts[-2]}/{parts[-1]}"
            else:
                short_name = repo_url

            item = QListWidgetItem(f"📦 {short_name}  ({len(nodes)} 个节点)")
            item.setData(Qt.UserRole, {"repo_url": repo_url, "nodes": nodes})
            self.imported_repos_list.addItem(item)

    def _on_imported_repo_clicked(self, item):
        """点击已导入仓库，展示该仓库下的节点"""
        data = item.data(Qt.UserRole)
        if not data:
            return

        self.imported_nodes_label.setText(f"节点列表 ({len(data['nodes'])} 个):")
        self.imported_nodes_label.show()
        self.imported_nodes_list.show()
        self.imported_nodes_list.clear()
        self.delete_repo_btn.setEnabled(True)

        for node in data["nodes"]:
            node_item = QListWidgetItem(f"  • {node.name}")
            node_item.setData(Qt.UserRole, node.node_type)
            node_item.setToolTip(node.description or "")
            self.imported_nodes_list.addItem(node_item)

    def _delete_imported_repo(self):
        """删除选中的已导入仓库"""
        current_item = self.imported_repos_list.currentItem()
        if not current_item:
            return

        data = current_item.data(Qt.UserRole)
        if not data:
            return

        repo_url = data["repo_url"]
        nodes = data["nodes"]

        reply = QMessageBox.question(
            self,
            "确认删除",
            f"确定要删除仓库 '{repo_url}' 下的 {len(nodes)} 个节点吗？\n\n此操作不可恢复。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        try:
            from src.core.providers.github_provider import GitHubNodeProvider

            registry = get_registry()
            provider = GitHubNodeProvider(registry._user_data_dir)

            deleted_count = 0
            for node in nodes:
                if provider.delete_node(node.node_type):
                    deleted_count += 1

            ToastWidget.show(self, f"已删除 {deleted_count} 个节点", "success")
            self._load_imported_repos()
        except Exception as exc:
            QMessageBox.critical(self, "错误", f"删除节点失败: {exc}")

    def _import_github_node(self):
        """导入 GitHub 节点（后台线程执行，避免 UI 卡顿）"""
        url = self.github_url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "提示", "请输入 GitHub 仓库 URL")
            return

        # 防止重复点击
        if self.github_import_worker and self.github_import_worker.isRunning():
            return

        self.github_import_btn.setEnabled(False)
        self.github_import_btn.setText("导入中...")

        try:
            from src.core.node_registry import get_registry

            registry = get_registry()
            token = self.config_manager.get_github_token()
            self.github_import_worker = GitHubImportWorker(
                registry._user_data_dir, url, github_token=token
            )
            self.github_import_worker.finished.connect(self._on_github_import_finished)
            self.github_import_worker.start()
        except Exception as exc:
            self.github_import_btn.setEnabled(True)
            self.github_import_btn.setText("导入节点")
            QMessageBox.critical(self, "错误", f"启动导入失败: {exc}")

    def _on_github_import_finished(self, success: bool, node_defs, error_message):
        """GitHub 导入完成后的回调（主线程）"""
        self.github_import_btn.setEnabled(True)
        self.github_import_btn.setText("导入节点")
        self.github_import_worker = None

        if not success:
            QMessageBox.critical(
                self, "错误", f"导入 GitHub 节点过程中发生异常: {error_message}"
            )
            return

        if node_defs:
            if len(node_defs) == 1:
                node_name = node_defs[0].name
                message = (
                    f"GitHub 节点 '{node_name}' 导入成功！\n"
                    '请在节点浏览器的"GitHub"分类下查看。'
                )
            else:
                imported_names = "、".join(node.name for node in node_defs[:5])
                if len(node_defs) > 5:
                    imported_names += " 等"
                message = (
                    f"成功导入 {len(node_defs)} 个 GitHub 节点：{imported_names}\n"
                    '请在节点浏览器的"GitHub"分类下查看。'
                )
            ToastWidget.show(self, message, "success")
            self._load_imported_repos()
            self.github_url_input.clear()
            # 通知外部监听器节点已导入，触发节点列表刷新
            self.nodes_imported.emit()
        else:
            QMessageBox.critical(
                self, "错误", "无法从提供的 URL 导入节点，请检查 URL 是否正确。"
            )

    def _create_custom_node(self):
        """创建空白自定义节点"""
        name = self.custom_name_input.text().strip()
        desc = self.custom_desc_input.text().strip()

        if not name:
            QMessageBox.warning(self, "提示", "请输入节点名称")
            return

        try:
            from src.core.custom_node_manager import CustomNodeManager
            from src.core.node_registry import get_registry

            registry = get_registry()
            manager = CustomNodeManager(registry._user_data_dir)
            node_def = manager.create_node(name, desc)
            if node_def:
                registry.register_external_node(node_def)
                ToastWidget.show(
                    self,
                    f"自定义节点 '{name}' 创建成功！请在节点浏览器的“自定义”分类下查看并编辑。",
                    "success",
                )
                self.accept()
            else:
                QMessageBox.critical(self, "错误", "创建节点失败，请重试。")
        except Exception as exc:
            QMessageBox.critical(self, "错误", f"创建节点过程中发生异常: {exc}")
