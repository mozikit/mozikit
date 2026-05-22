"""
工作流同步对话框
提供图形化的 Push / Pull / Status 操作界面
"""
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.core.config_manager import ConfigManager
from src.core.log_manager import get_logger
from src.core.theme_manager import ThemeManager
from src.core.workflow_sync import WorkflowSync

logger = get_logger("workflow_sync_dialog")


class SyncWorker(QThread):
    """后台同步操作线程"""

    finished = Signal(bool, str)

    def __init__(self, sync_service: WorkflowSync, action: str, workflow_path: str, workflow_name: str):
        super().__init__()
        self.sync_service = sync_service
        self.action = action
        self.workflow_path = workflow_path
        self.workflow_name = workflow_name

    def run(self):
        try:
            if self.action == "push":
                success, msg = self.sync_service.push_workflow(self.workflow_path)
            elif self.action == "pull":
                from pathlib import Path
                dest = Path(self.workflow_path).parent.parent  # workflows/
                success, msg = self.sync_service.pull_workflow(self.workflow_name, str(dest))
            elif self.action == "status":
                result = self.sync_service.check_status(self.workflow_path)
                status_text = {
                    "identical": "✅ 本地与远程一致",
                    "ahead": "⬆ 本地领先于远程",
                    "behind": "⬇ 本地落后于远程",
                    "diverged": "⚠ 本地与远程内容不同",
                    "remote_only": "☁️ 仅远程存在",
                    "local_only": "📁 仅本地存在",
                    "error": "❌ " + result.get("message", ""),
                }
                msg = status_text.get(result["status"], f"未知状态: {result['message']}")
                if result.get("local_updated_at"):
                    msg += f"\n本地更新: {result['local_updated_at'][:19]}"
                if result.get("remote_updated_at"):
                    msg += f"\n远程更新: {result['remote_updated_at'][:19]}"
                success = result["status"] != "error"
            else:
                success, msg = False, f"未知操作: {self.action}"
            self.finished.emit(success, msg)
        except Exception as e:
            self.finished.emit(False, f"操作失败: {e}")


class WorkflowSyncDialog(QDialog):
    """工作流同步对话框"""

    def __init__(self, workflow_name: str, workflow_path: str, parent=None):
        super().__init__(parent)
        self.workflow_name = workflow_name
        self.workflow_path = workflow_path
        self._sync_service = None
        self._worker = None

        self._setup_ui()
        self._load_config()
        self._update_status_label()

    def _setup_ui(self):
        """初始化 UI"""
        self.setWindowTitle(f"同步工作流 - {self.workflow_name}")
        self.setMinimumWidth(520)
        self.setMinimumHeight(400)
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {ThemeManager.COLORS["background"]};
                color: {ThemeManager.COLORS["text"]};
            }}
            QLabel {{
                color: {ThemeManager.COLORS["text"]};
            }}
            QGroupBox {{
                font-weight: bold;
                border: 1px solid {ThemeManager.COLORS["border"]};
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 16px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # 工作流信息
        info_label = QLabel(f"工作流: <b>{self.workflow_name}</b>")
        info_label.setStyleSheet("font-size: 14px;")
        layout.addWidget(info_label)

        # 仓库配置
        repo_group = QGroupBox("GitHub 仓库")
        repo_form = QFormLayout()
        repo_form.setSpacing(8)

        self.repo_input = QLineEdit()
        self.repo_input.setPlaceholderText("owner/repo")
        self.repo_input.setStyleSheet(ThemeManager.get_input_style())
        repo_form.addRow("仓库:", self.repo_input)

        self.branch_input = QLineEdit("main")
        self.branch_input.setPlaceholderText("main")
        self.branch_input.setStyleSheet(ThemeManager.get_input_style())
        repo_form.addRow("分支:", self.branch_input)

        self.path_input = QLineEdit("workflows")
        self.path_input.setPlaceholderText("workflows")
        self.path_input.setStyleSheet(ThemeManager.get_input_style())
        repo_form.addRow("路径:", self.path_input)

        repo_group.setLayout(repo_form)
        layout.addWidget(repo_group)

        # 状态标签
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet(
            f"color: {ThemeManager.COLORS['text_secondary']}; font-size: 12px;"
        )
        layout.addWidget(self.status_label)

        # 操作按钮
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        self.status_btn = QPushButton("🔄 检查状态")
        self.status_btn.setStyleSheet(ThemeManager.get_button_style("secondary"))
        self.status_btn.clicked.connect(lambda: self._start_sync("status"))
        btn_layout.addWidget(self.status_btn)

        self.push_btn = QPushButton("⬆ 推送到 GitHub")
        self.push_btn.setStyleSheet(ThemeManager.get_button_style("primary"))
        self.push_btn.clicked.connect(lambda: self._start_sync("push"))
        btn_layout.addWidget(self.push_btn)

        self.pull_btn = QPushButton("⬇ 从 GitHub 拉取")
        self.pull_btn.setStyleSheet(ThemeManager.get_button_style("secondary"))
        self.pull_btn.clicked.connect(lambda: self._start_sync("pull"))
        btn_layout.addWidget(self.pull_btn)

        layout.addLayout(btn_layout)

        # 日志区域
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(150)
        self.log_text.setStyleSheet(f"""
            QTextEdit {{
                background-color: {ThemeManager.COLORS["surface"]};
                border: 1px solid {ThemeManager.COLORS["border"]};
                border-radius: 4px;
                color: {ThemeManager.COLORS["text"]};
                font-size: 12px;
                font-family: 'Consolas', 'Courier New', monospace;
            }}
        """)
        layout.addWidget(self.log_text)

        # 关闭按钮
        close_layout = QHBoxLayout()
        close_layout.addStretch()
        self.close_btn = QPushButton("关闭")
        self.close_btn.setStyleSheet(ThemeManager.get_button_style("secondary"))
        self.close_btn.clicked.connect(self.accept)
        close_layout.addWidget(self.close_btn)
        layout.addLayout(close_layout)

    def _load_config(self):
        """从配置加载默认仓库设置"""
        config_mgr = ConfigManager()
        settings = config_mgr.get_sync_settings()
        self.repo_input.setText(settings.get("default_repo", ""))
        self.branch_input.setText(settings.get("default_branch", "main"))
        self.path_input.setText(settings.get("sync_path", "workflows"))

    def _get_sync_service(self) -> WorkflowSync:
        """获取或创建同步服务实例"""
        if self._sync_service is None:
            config_mgr = ConfigManager()
            self._sync_service = WorkflowSync(config_mgr)
            self._sync_service.refresh_token()
            repo = self.repo_input.text().strip()
            branch = self.branch_input.text().strip() or "main"
            path = self.path_input.text().strip() or "workflows"
            if repo:
                self._sync_service.set_repo(repo, branch, path)
        return self._sync_service

    def _update_status_label(self):
        """更新连接状态指示"""
        svc = self._get_sync_service()
        if svc.is_configured():
            cfg = svc.get_repo_config()
            self.status_label.setText(
                f"✓ 已配置: {cfg['owner']}/{cfg['repo']} ({cfg['branch']})"
            )
            self.status_label.setStyleSheet(
                f"color: {ThemeManager.COLORS.get('success', '#4CAF50')}; font-size: 12px;"
            )
        else:
            self.status_label.setText(
                "⚠ 未配置。请填写仓库信息并确保已通过 GitHub 登录。"
            )
            self.status_label.setStyleSheet(
                f"color: {ThemeManager.COLORS.get('warning', '#FF9800')}; font-size: 12px;"
            )

    def _start_sync(self, action: str):
        """启动同步操作"""
        svc = self._get_sync_service()
        if not svc.is_configured():
            QMessageBox.warning(
                self,
                "配置不完整",
                "请先填写仓库信息（owner/repo），并确保已在设置中完成 GitHub 登录。",
            )
            return

        # 禁用按钮
        self.push_btn.setEnabled(False)
        self.pull_btn.setEnabled(False)
        self.status_btn.setEnabled(False)

        action_names = {
            "push": "推送到 GitHub",
            "pull": "从 GitHub 拉取",
            "status": "检查状态",
        }
        self.log_text.append(f"⏳ 正在{action_names.get(action, action)}...")
        self.log_text.repaint()

        # 在后台线程执行
        self._worker = SyncWorker(svc, action, self.workflow_path, self.workflow_name)
        self._worker.finished.connect(self._on_sync_finished)
        self._worker.start()

    def _on_sync_finished(self, success: bool, message: str):
        """同步操作完成"""
        # 恢复按钮
        self.push_btn.setEnabled(True)
        self.pull_btn.setEnabled(True)
        self.status_btn.setEnabled(True)

        icon = "✅" if success else "❌"
        self.log_text.append(f"{icon} {message}")
        self.log_text.append("")

        if not success:
            QMessageBox.warning(self, "同步失败", message)
