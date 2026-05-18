"""
Playwright 脚本编辑弹窗
"""
import ast
import os
import shutil
import tempfile

from PySide6.QtCore import Qt, QEventLoop, QProcess
from PySide6.QtGui import QFont, QAction
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.core.playwright_node_utils import (
    build_playwright_config_schema,
    extract_playwright_params,
)
from src.core.python_syntax_highlighter import PythonSyntaxHighlighter
from src.core.theme_manager import ThemeManager


# 预设模板
_TEMPLATES = {
    "浏览器截图": (
        "from playwright.sync_api import sync_playwright\n"
        "\n"
        "with sync_playwright() as p:\n"
        "    browser = p.chromium.launch(headless=LF_HEADLESS, channel=LF_BROWSER_CHANNEL or None)\n"
        "    page = browser.new_page()\n"
        "    page.goto('{{url}}')\n"
        "    page.screenshot(path='screenshot.png')\n"
        "    lf_add_artifact('screenshot', 'screenshot.png')\n"
        "    lf_set_output({'screenshot_path': 'screenshot.png'})\n"
    ),
    "下载文件": (
        "from playwright.sync_api import sync_playwright\n"
        "\n"
        "with sync_playwright() as p:\n"
        "    browser = p.chromium.launch(headless=LF_HEADLESS, channel=LF_BROWSER_CHANNEL or None)\n"
        "    page = browser.new_page()\n"
        "    page.goto('{{url}}')\n"
        "    # 点击触发下载的链接/按钮\n"
        "    page.get_by_role('link').click()\n"
        "    # 下载由系统自动保存到下载目录\n"
        "    lf_set_output({'url': '{{url}}'})\n"
    ),
    "下载并读取": (
        "from playwright.sync_api import sync_playwright\n"
        "\n"
        "with sync_playwright() as p:\n"
        "    browser = p.chromium.launch(headless=LF_HEADLESS, channel=LF_BROWSER_CHANNEL or None)\n"
        "    page = browser.new_page()\n"
        "    page.goto('{{url}}')\n"
        "    # 点击触发下载\n"
        "    page.get_by_role('link').click()\n"
        "    # 等待下载完成（若已启用自动下载则无需手动调用）\n"
        "    lf_download_wait()\n"
        "    # 读取下载的文件\n"
        "    import os\n"
        "    files = os.listdir(LF_DOWNLOAD_DIR)\n"
        "    lf_set_output({'files': files, 'url': '{{url}}'})\n"
    ),
    "多页面抓取": (
        "from playwright.sync_api import sync_playwright\n"
        "\n"
        "with sync_playwright() as p:\n"
        "    browser = p.chromium.launch(headless=LF_HEADLESS, channel=LF_BROWSER_CHANNEL or None)\n"
        "    page = browser.new_page()\n"
        "    results = []\n"
        "    for url in {{urls}}:\n"
        "        page.goto(url)\n"
        "        title = page.title()\n"
        "        results.append({'url': url, 'title': title})\n"
        "    lf_set_output({'results': results})\n"
    ),
    "表单填写": (
        "from playwright.sync_api import sync_playwright\n"
        "\n"
        "with sync_playwright() as p:\n"
        "    browser = p.chromium.launch(headless=LF_HEADLESS, channel=LF_BROWSER_CHANNEL or None)\n"
        "    page = browser.new_page()\n"
        "    page.goto('{{url}}')\n"
        "    page.fill('#username', '{{username}}')\n"
        "    page.fill('#password', '{{password}}')\n"
        "    page.click('button[type=submit]')\n"
        "    page.wait_for_load_state('networkidle')\n"
        "    lf_set_output({'result_url': page.url})\n"
    ),
}

# 帮助函数列表
_HELP_FUNCTIONS = [
    ("lf_set_output(data=None, **kwargs)", "设置结构化输出数据，供下游节点使用"),
    ("lf_download_wait(timeout=None, min_stable_seconds=2)", "等待下载目录中的文件稳定（不再增长），返回文件列表"),
    ("lf_read_file(file_path, encoding='utf-8', max_size_mb=10)", "读取文件内容：JSON 自动解析，文本返回字符串"),
    ("lf_add_artifact(name, path)", "注册产物路径，结果中会包含 artifacts 字典"),
    ("lf_create_context(browser, **kwargs)", "创建浏览器上下文，自动开启 accept_downloads"),
    ("lf_configure_browser_download(browser_context)", "配置浏览器下载路径（尝试设置 download_path）"),
    ("lf_handle_download(page, download_event)", "手动处理下载事件保存文件"),
    ("lf_log(message)", "输出日志（子进程模式下实时刷新到父进程）"),
    ("LF_HEADLESS (bool)", "无头模式配置值"),
    ("LF_DOWNLOAD_DIR (str)", "下载目录路径"),
    ("LF_ARTIFACTS_DIR (str)", "产物目录路径"),
    ("LF_TIMEOUT_SECONDS (int)", "超时时间配置值"),
    ("LF_INPUT_DATA (dict)", "上游节点传递的输入数据"),
    ("LF_PARAMS (dict)", "参数占位符 {{xxx}} 的运行时值"),
]


class PlaywrightScriptDialog(QDialog):
    """Playwright Python 脚本编辑器"""

    def __init__(
        self,
        script_source: str = "",
        existing_param_schema: dict | None = None,
        node_name: str = "Playwright",
        parent=None,
    ):
        super().__init__(parent)
        self._existing_param_schema = existing_param_schema or {}
        self._result_script = script_source or ""
        self._result_param_schema = build_playwright_config_schema(
            extract_playwright_params(self._result_script),
            self._existing_param_schema,
        )
        self.setWindowTitle(f"编辑 Playwright 脚本 - {node_name}")
        self.setMinimumSize(900, 620)
        self._setup_ui()
        self._apply_style()
        self.editor.setPlainText(self._result_script)
        self._refresh_preview()

    def _insert_template(self, template_name: str):
        """向编辑器中插入模板代码"""
        code = _TEMPLATES.get(template_name)
        if not code:
            return
        cursor = self.editor.textCursor()
        cursor.insertText(code)
        self.editor.setTextCursor(cursor)
        self.editor.setFocus()
        self._refresh_preview()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # ── 顶部工具栏：模板 + 帮助函数 ──
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        template_btn = QPushButton("📖 插入模板")
        template_btn.setStyleSheet(ThemeManager.get_button_style("secondary"))
        template_menu = QMenu(self)
        for name in _TEMPLATES:
            action = QAction(name, self)
            action.triggered.connect(lambda checked, n=name: self._insert_template(n))
            template_menu.addAction(action)
        template_btn.setMenu(template_menu)
        toolbar.addWidget(template_btn)

        help_btn = QPushButton("❓ 帮助函数")
        help_btn.setStyleSheet(ThemeManager.get_button_style("secondary"))
        help_menu = QMenu(self)
        for sig, desc in _HELP_FUNCTIONS:
            action = QAction(sig, self)
            action.setToolTip(desc)
            help_menu.addAction(action)
        help_btn.setMenu(help_menu)
        toolbar.addWidget(help_btn)

        record_btn = QPushButton("🎬 录制")
        record_btn.setStyleSheet(ThemeManager.get_button_style("secondary"))
        record_btn.setToolTip("打开 Playwright Codegen 录制浏览器，关闭后自动插入录制的脚本")
        record_btn.clicked.connect(self._start_recording)
        toolbar.addWidget(record_btn)

        toolbar.addStretch()
        layout.addLayout(toolbar)

        help_label = QLabel(
            "粘贴 Python Playwright 脚本。可使用 {{report_date}} 这类占位符，保存后会自动生成参数。\n"
            "提示：下载文件时，系统会自动保存到下载目录并读取内容，无需手动处理下载事件。"
        )
        help_label.setWordWrap(True)
        help_label.setStyleSheet(
            f"color: {ThemeManager.COLORS['text_secondary']}; font-size: 9pt;"
        )
        layout.addWidget(help_label)

        content = QHBoxLayout()
        content.setSpacing(12)

        editor_container = QWidget()
        editor_layout = QVBoxLayout(editor_container)
        editor_layout.setContentsMargins(0, 0, 0, 0)

        editor_title = QLabel("脚本代码")
        editor_title.setStyleSheet(f"color: {ThemeManager.COLORS['text']}; font-weight: bold;")
        editor_layout.addWidget(editor_title)

        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText(
            "例如:\n"
            "from playwright.sync_api import sync_playwright\n\n"
            "with sync_playwright() as p:\n"
            "    browser = p.chromium.launch(headless=LF_HEADLESS, channel=LF_BROWSER_CHANNEL or None)\n"
            "    page = browser.new_page()\n"
            "    page.goto('https://example.com')\n\n"
            "    # 触发下载（系统自动保存到下载目录）\n"
            "    page.get_by_role('link').click()\n\n"
            "    lf_set_output({'date': '{{report_date}}'})\n"
        )
        font = QFont("Consolas", 10)
        self.editor.setFont(font)
        editor_layout.addWidget(self.editor)

        # 设置 Python 语法高亮
        self._highlighter = PythonSyntaxHighlighter(self.editor.document())

        self.validation_label = QLabel("")
        self.validation_label.setWordWrap(True)
        editor_layout.addWidget(self.validation_label)

        content.addWidget(editor_container, 3)

        preview_container = QWidget()
        preview_layout = QVBoxLayout(preview_container)
        preview_layout.setContentsMargins(0, 0, 0, 0)

        preview_title = QLabel("参数预览")
        preview_title.setStyleSheet(f"color: {ThemeManager.COLORS['text']}; font-weight: bold;")
        preview_layout.addWidget(preview_title)

        self.param_list = QListWidget()
        preview_layout.addWidget(self.param_list)

        preview_hint = QLabel("仅展示脚本中识别出的 {{param}} 业务参数。")
        preview_hint.setWordWrap(True)
        preview_hint.setStyleSheet(
            f"color: {ThemeManager.COLORS['text_secondary']}; font-size: 9pt;"
        )
        preview_layout.addWidget(preview_hint)

        content.addWidget(preview_container, 1)
        layout.addLayout(content)

        button_layout = QHBoxLayout()
        button_layout.addStretch()

        validate_btn = QPushButton("校验并预览")
        validate_btn.setStyleSheet(ThemeManager.get_button_style("secondary"))
        validate_btn.clicked.connect(self._on_validate)
        button_layout.addWidget(validate_btn)

        cancel_btn = QPushButton("取消")
        cancel_btn.setStyleSheet(ThemeManager.get_button_style("secondary"))
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        save_btn = QPushButton("保存")
        save_btn.setStyleSheet(ThemeManager.get_button_style("primary"))
        save_btn.clicked.connect(self._on_save)
        button_layout.addWidget(save_btn)

        layout.addLayout(button_layout)

    def _apply_style(self):
        self.setStyleSheet(
            f"""
            QDialog {{
                background-color: {ThemeManager.COLORS['surface']};
            }}
            QLabel {{
                color: {ThemeManager.COLORS['text']};
            }}
            QListWidget {{
                background-color: {ThemeManager.COLORS['background']};
                border: 1px solid {ThemeManager.COLORS['border']};
                color: {ThemeManager.COLORS['text']};
            }}
            QPlainTextEdit {{
                background-color: {ThemeManager.COLORS['background']};
                color: {ThemeManager.COLORS['text']};
                border: 1px solid {ThemeManager.COLORS['border']};
                padding: 8px;
            }}
            """
        )

    def _validate_source(self, source_code: str):
        if not source_code.strip():
            raise ValueError("请输入 Playwright Python 脚本")
        try:
            ast.parse(source_code)
        except SyntaxError as exc:
            raise ValueError(f"语法错误: {exc.msg} (第{exc.lineno}行)") from exc

    def _refresh_preview(self):
        source_code = self.editor.toPlainText()
        param_names = extract_playwright_params(source_code)
        self.param_list.clear()
        if param_names:
            self.param_list.addItems(param_names)
        else:
            self.param_list.addItem("未识别到业务参数")
        self._result_script = source_code
        self._result_param_schema = build_playwright_config_schema(
            param_names,
            self._existing_param_schema,
        )
        return param_names

    def _on_validate(self):
        try:
            self._validate_source(self.editor.toPlainText())
            param_names = self._refresh_preview()
            self.validation_label.setStyleSheet(f"color: {ThemeManager.COLORS['success']};")
            self.validation_label.setText(
                f"校验通过，识别到 {len(param_names)} 个业务参数。"
            )
        except Exception as exc:
            self.validation_label.setStyleSheet(f"color: {ThemeManager.COLORS['error']};")
            self.validation_label.setText(str(exc))

    def _on_save(self):
        try:
            self._validate_source(self.editor.toPlainText())
            self._refresh_preview()
            self.accept()
        except Exception as exc:
            QMessageBox.warning(self, "脚本校验失败", str(exc))

    def _check_and_install_playwright(self) -> bool:
        """检查 playwright CLI 是否可用，不可用时尝试自动安装"""
        import subprocess, sys, shutil

        # 检查 playwright 命令是否存在
        pw_path = shutil.which("playwright")
        if pw_path:
            # 再检查 playwright codegen 子命令是否可用
            try:
                r = subprocess.run(
                    [pw_path, "--version"],
                    capture_output=True, text=True, encoding="utf-8", errors="replace",
                    timeout=10,
                )
                if r.returncode == 0:
                    return True
            except Exception:
                pass

        # playwright 不可用，询问是否安装
        reply = QMessageBox.question(
            self, "安装 Playwright",
            "录制功能需要 Playwright，是否现在安装？\n\n"
            "将执行: uv pip install playwright",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return False

        # 执行安装（使用 uv，项目包管理统一用 uv）
        try:
            from PySide6.QtCore import QEventLoop

            uv_path = shutil.which("uv") or "uv"
            install_cmd = [uv_path, "pip", "install", "playwright"]

            # 进度对话框（不确定进度 = 旋转条）
            progress = QProgressDialog("正在使用 uv 安装 playwright...", "取消", 0, 0, self)
            progress.setWindowTitle("安装 Playwright")
            progress.setWindowModality(Qt.WindowModality.WindowModal)
            progress.setMinimumDuration(0)
            progress.show()

            # 启动安装进程
            install_proc = QProcess(self)
            install_proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)

            # 用事件循环等待，不阻塞 UI
            loop = QEventLoop(self)
            install_proc.finished.connect(loop.quit)
            progress.canceled.connect(loop.quit)

            install_proc.start(install_cmd[0], install_cmd[1:])
            if not install_proc.waitForStarted(5000):
                progress.close()
                QMessageBox.warning(self, "安装失败", "无法启动 uv 安装进程。")
                self.validation_label.setText("")
                return False

            # 事件循环等待（UI 保持响应）
            loop.exec()

            if progress.wasCanceled():
                install_proc.kill()
                progress.close()
                self.validation_label.setText("")
                return False

            progress.close()

            output = install_proc.readAll().data().decode("utf-8", errors="replace")
            if install_proc.exitCode() != 0:
                QMessageBox.warning(
                    self, "安装失败",
                    f"uv pip install playwright 失败:\n{output[:500]}"
                )
                self.validation_label.setText("")
                return False

            QMessageBox.information(self, "安装成功", "Playwright 已安装，可以开始录制。")
            self.validation_label.setText("")
            return True

        except Exception as e:
            QMessageBox.warning(self, "安装出错", str(e))
            self.validation_label.setText("")
            return False

    def _start_recording(self):
        """启动 Playwright Codegen 录制"""
        if not self._check_and_install_playwright():
            return

        url, ok = QInputDialog.getText(
            self,
            "录制 Playwright 脚本",
            "起始 URL（可选，留空则打开空白页）:",
            text="https://",
        )
        if not ok:
            return

        # 创建临时文件接收录制的脚本
        tmp = tempfile.NamedTemporaryFile(suffix=".py", delete=False, mode="w", encoding="utf-8")
        self._record_temp_path = tmp.name
        tmp.close()

        # 构建命令行参数
        args = [
            "codegen",
            "--target", "python",
            "-o", self._record_temp_path,
            "--browser", "chromium",
            "--channel", "chrome",
        ]
        url = url.strip()
        if url and url != "https://":
            args.append(url)

        # 启动子进程
        self._record_process = QProcess(self)
        self._record_process.finished.connect(
            lambda exitCode, exitStatus: self._on_recording_finished(exitCode)
        )
        self._record_process.start("playwright", args)

        # 检查启动是否成功
        if not self._record_process.waitForStarted(3000):
            os.unlink(self._record_temp_path)
            QMessageBox.warning(
                self, "录制启动失败",
                "无法启动 Playwright Codegen。请确认已安装 playwright 并已执行 playwright install。"
            )
            return

        self.validation_label.setText(
            "🎬 录制中... 在打开的浏览器中操作，关闭浏览器后脚本将自动导入。"
        )

    def _on_recording_finished(self, exit_code: int):
        """录制完成回调"""
        if exit_code != 0:
            error_output = self._record_process.readAllStandardError().data().decode("utf-8", errors="replace")
            QMessageBox.warning(
                self, "录制异常",
                f"Playwright Codegen 退出码: {exit_code}\n{error_output}"
            )
            return

        # 读取录制的脚本
        try:
            if not os.path.exists(self._record_temp_path):
                raise FileNotFoundError("未生成录制文件")
            with open(self._record_temp_path, "r", encoding="utf-8") as f:
                recorded_code = f.read()
            os.unlink(self._record_temp_path)

            if not recorded_code.strip():
                QMessageBox.information(self, "录制为空", "未录制到任何操作。")
                return

            # 插入到编辑器
            cursor = self.editor.textCursor()
            cursor.insertText(recorded_code)
            self.editor.setTextCursor(cursor)
            self.editor.setFocus()
            self._refresh_preview()
            self.validation_label.setText(
                f"✅ 录制完成，已导入 {len(recorded_code.splitlines())} 行脚本。"
            )
        except Exception as exc:
            QMessageBox.warning(self, "读取录制脚本失败", str(exc))

    def get_result(self):
        """获取保存结果"""
        return {
            "script_source": self._result_script,
            "param_schema": self._result_param_schema,
            "param_names": extract_playwright_params(self._result_script),
        }

# -- auto register extension --
from src.core.node_extension_registries import editors
editors.register('playwright_script', PlaywrightScriptDialog)
