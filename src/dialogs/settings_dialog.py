import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import requests as _requests
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.core.config_manager import ConfigManager
from src.core.log_manager import get_logger
from src.core.theme_manager import ThemeManager
from src.views.toast_widget import ToastWidget

logger = get_logger("settings_dialog")


class InstallWorker(QThread):
    """Worker thread for installing uv"""

    finished = Signal(bool, str)
    progress = Signal(str)

    def __init__(self, install_args):
        super().__init__()
        self.install_args = install_args

    def run(self):
        try:
            self.progress.emit("正在安装 uv，请稍候...")

            if os.name == "nt":
                creationflags = 0x08000000  # CREATE_NO_WINDOW
            else:
                creationflags = 0

            process = subprocess.Popen(
                self.install_args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=creationflags,
            )

            stdout, stderr = process.communicate()

            if process.returncode == 0:
                self.progress.emit("安装成功！")
                self.finished.emit(True, stdout)
            else:
                self.progress.emit("安装失败！")
                self.finished.emit(False, stderr)
        except Exception as e:
            self.finished.emit(False, str(e))


class _PSDownloadWorker(QThread):
    """Worker thread for downloading the uv install.ps1 script"""

    finished = Signal(bool, str)  # success, script_path_or_error
    progress = Signal(str)

    UV_INSTALL_URL = "https://astral.sh/uv/install.ps1"

    def run(self):
        try:
            self.progress.emit("正在下载安装脚本...")
            resp = _requests.get(self.UV_INSTALL_URL, timeout=30)
            resp.raise_for_status()
            content = resp.text

            if not content or len(content) < 100:
                self.finished.emit(False, "下载的脚本内容异常（过短或为空），已拒绝执行")
                return

            fd, tmp_path = tempfile.mkstemp(suffix=".ps1", prefix="uv_install_")
            try:
                os.write(fd, content.encode("utf-8"))
            finally:
                os.close(fd)

            self.progress.emit("安装脚本已下载，开始执行...")
            self.finished.emit(True, tmp_path)
        except _requests.RequestException as e:
            self.finished.emit(False, f"网络请求失败: {e}")
        except Exception as e:
            self.finished.emit(False, f"下载失败: {e}")


class UVDetectWorker(QThread):
    """Worker thread for detecting uv installations and mirror config"""

    finished = Signal(list, str, str)
    progress = Signal(str)

    def run(self):
        try:
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
            from core.uv_manager import UVManager

            uv_manager = UVManager()
            uv_paths = uv_manager.find_uv_installations()

            # 在后台线程中预先获取每个 uv 的版本信息，避免主线程阻塞
            uv_entries = []
            if os.name == "nt":
                creationflags = 0x08000000
            else:
                creationflags = 0
            for uv_path in uv_paths:
                try:
                    result = subprocess.run(
                        [uv_path, "--version"],
                        capture_output=True,
                        text=True,
                        timeout=5,
                        creationflags=creationflags,
                    )
                    if result.returncode == 0:
                        version = result.stdout.strip()
                        display_text = f"{uv_path} ({version})"
                    else:
                        display_text = uv_path
                except Exception:
                    display_text = uv_path
                uv_entries.append((display_text, uv_path))

            uv_mirror = ""
            config_mirror = None
            env_mirror = ""

            try:
                config_file = os.path.join(os.path.expanduser("~"), ".uv", "uv.toml")
                if os.path.exists(config_file):
                    with open(config_file, "r", encoding="utf-8") as f:
                        content = f.read()
                    import re

                    match = re.search(r'index-url\s*=\s*"([^"]+)"', content)
                    if match:
                        config_mirror = match.group(1)
            except Exception:
                pass

            env_mirror = os.environ.get("UV_INDEX_URL", "")

            if config_mirror:
                uv_mirror = config_mirror
            elif env_mirror:
                uv_mirror = env_mirror
            else:
                if os.name == "nt":
                    creationflags = 0x08000000
                else:
                    creationflags = 0
                try:
                    pip_result = subprocess.run(
                        ["pip", "config", "get", "global.index-url"],
                        capture_output=True,
                        text=True,
                        timeout=3,
                        creationflags=creationflags,
                    )
                    if pip_result.returncode == 0:
                        pip_mirror = pip_result.stdout.strip()
                        if pip_mirror:
                            uv_mirror = f"{pip_mirror} (从 pip 配置检测)"
                except Exception:
                    pass

            self.finished.emit(uv_entries, uv_mirror, "")
        except Exception as e:
            self.finished.emit([], "", str(e))


class _OAuthWorker(QThread):
    """Worker thread for GitHub OAuth Device Flow"""

    finished = Signal(bool, str, str)
    prompt = Signal(str, str)

    def run(self):
        try:
            from src.core.github_oauth import GitHubOAuth

            oauth = GitHubOAuth()
            success, token, username = oauth.authorize(
                timeout=900,
                on_user_code=lambda code, uri: self.prompt.emit(code, uri),
            )
            if success:
                self.finished.emit(True, token, username)
            else:
                self.finished.emit(False, "", username or "授权失败")
        except Exception as e:
            self.finished.emit(False, "", str(e))


class _AITestWorker(QThread):
    """Worker thread for testing AI API connection"""

    finished = Signal(bool, str)

    def __init__(self, base_url, api_key, model, timeout):
        super().__init__()
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def run(self):
        try:
            missing = []
            if not self.base_url:
                missing.append("接口地址")
            if not self.api_key:
                missing.append("API 密钥")
            if not self.model:
                missing.append("模型")
            if missing:
                msg = f"配置不完整，缺少: {'、'.join(missing)}"
                logger.warning("AI 连接测试失败: %s", msg)
                self.finished.emit(False, msg)
                return

            from urllib.parse import urlparse

            parsed = urlparse(self.base_url)
            if not parsed.scheme or parsed.scheme not in ("http", "https"):
                msg = "接口地址格式无效，需以 http:// 或 https:// 开头"
                logger.warning("AI 连接测试失败: %s (base_url=%s)", msg, self.base_url)
                self.finished.emit(False, msg)
                return

            normalized = self.base_url.rstrip("/")
            if normalized.endswith("/chat/completions"):
                endpoint = normalized
            elif normalized.endswith("/v1"):
                endpoint = f"{normalized}/chat/completions"
            else:
                endpoint = f"{normalized}/v1/chat/completions"

            logger.info(
                "AI 连接测试: endpoint=%s, model=%s, timeout=%ds",
                endpoint,
                self.model,
                self.timeout,
            )

            payload = {
                "model": self.model,
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 5,
                "stream": False,
            }
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            }

            resp = _requests.post(
                endpoint, json=payload, headers=headers, timeout=self.timeout
            )

            logger.debug(
                "AI 连接测试响应: status=%d, len=%d",
                resp.status_code,
                len(resp.content),
            )

            if resp.status_code == 200:
                try:
                    body = resp.json()
                except (ValueError, json.JSONDecodeError):
                    text = resp.text.strip()
                    if text.startswith("data:"):
                        for line in text.splitlines():
                            line = line.strip()
                            if not line.startswith("data:"):
                                continue
                            data_str = line[5:].strip()
                            if data_str == "[DONE]":
                                break
                            try:
                                body = json.loads(data_str)
                                break
                            except (ValueError, json.JSONDecodeError):
                                continue
                        else:
                            msg = "响应为 SSE 流式格式，但未能解析出有效数据"
                            logger.error(
                                "AI 连接测试: %s, body=%.200s", msg, text[:200]
                            )
                            self.finished.emit(False, msg)
                            return
                    else:
                        msg = "响应解析失败: 非 JSON 格式"
                        logger.error("AI 连接测试: %s, body=%.200s", msg, text[:200])
                        self.finished.emit(False, msg)
                        return
                model_used = body.get("model", self.model)
                usage = body.get("usage", {})
                logger.info("AI 连接测试成功: model=%s, usage=%s", model_used, usage)
                self.finished.emit(True, f"连接成功 (模型: {model_used})")
            elif resp.status_code == 401:
                logger.warning("AI 连接测试: 认证失败 (401)")
                self.finished.emit(False, "认证失败，请检查 API 密钥是否正确")
            elif resp.status_code == 403:
                logger.warning("AI 连接测试: 权限不足 (403)")
                self.finished.emit(False, "权限不足，API 密钥可能无权访问该模型")
            elif resp.status_code == 404:
                logger.warning("AI 连接测试: 端点未找到 (404), endpoint=%s", endpoint)
                self.finished.emit(
                    False, "接口地址未找到 (404)，请检查接口地址和模型名称是否正确"
                )
            elif resp.status_code == 429:
                logger.warning("AI 连接测试: 请求过于频繁 (429)")
                self.finished.emit(False, "请求过于频繁 (429)，请稍后重试")
            elif resp.status_code >= 500:
                logger.error("AI 连接测试: 服务端错误 (%d)", resp.status_code)
                self.finished.emit(
                    False, f"服务端错误 ({resp.status_code})，请稍后重试"
                )
            else:
                try:
                    err_body = resp.json()
                    err_msg = err_body.get("error", {}).get("message", resp.text[:200])
                except Exception:
                    err_msg = resp.text[:200]
                logger.warning(
                    "AI 连接测试: HTTP %d, error=%s", resp.status_code, err_msg
                )
                self.finished.emit(False, f"HTTP {resp.status_code}: {err_msg}")

        except _requests.exceptions.SSError as e:
            logger.error("AI 连接测试: SSL 错误: %s", e)
            self.finished.emit(False, f"SSL 证书错误，请检查接口地址是否正确")
        except _requests.exceptions.ConnectionError as e:
            logger.error("AI 连接测试: 连接失败: %s", e)
            self.finished.emit(False, "连接失败，请检查接口地址是否可达")
        except _requests.exceptions.Timeout:
            logger.warning("AI 连接测试: 请求超时 (%ds)", self.timeout)
            self.finished.emit(
                False, f"请求超时 ({self.timeout}s)，请检查网络或增大超时时间"
            )
        except _requests.exceptions.TooManyRedirects:
            logger.error("AI 连接测试: 重定向过多")
            self.finished.emit(False, "重定向过多，请检查接口地址")
        except Exception as e:
            logger.exception("AI 连接测试: 未知异常")
            self.finished.emit(False, f"未知错误: {e}")


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setMinimumSize(600, 500)
        self.setModal(True)

        self.uv_path = ""
        self.uv_mirror = ""
        self.uv_paths = []  # 存储找到的所有uv路径
        self.install_worker = None
        self.uv_detect_worker = None
        self.config_manager = (
            parent.config_manager
            if parent and hasattr(parent, "config_manager")
            else ConfigManager()
        )
        # self.is_dark_theme = self._detect_dark_theme() # Removed in favor of ThemeManager

        self._setup_ui()
        self._start_uv_detect()
        self._load_settings()

    def _setup_ui(self):
        """设置UI - 使用标签页布局优化空间"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # 创建标签页
        self.tab_widget = QTabWidget()
        self.tab_widget.setDocumentMode(True)

        # === UV 设置标签页 ===
        uv_tab = QWidget()
        uv_layout = QVBoxLayout(uv_tab)
        uv_layout.setContentsMargins(12, 12, 12, 12)
        uv_layout.setSpacing(16)

        # UV 配置组
        uv_config_group = QGroupBox("UV 配置")
        uv_config_layout = QFormLayout()
        uv_config_layout.setSpacing(10)

        # UV 路径
        self.path_combo = QComboBox()
        self.path_combo.setMinimumWidth(280)
        self.path_combo.currentTextChanged.connect(self._on_uv_path_changed)

        self.detect_btn = QPushButton("检测")
        self.detect_btn.setFixedWidth(60)
        self.detect_btn.clicked.connect(self._detect_uv)

        path_widget = QWidget()
        path_layout = QHBoxLayout(path_widget)
        path_layout.setContentsMargins(0, 0, 0, 0)
        path_layout.setSpacing(8)
        path_layout.addWidget(self.path_combo)
        path_layout.addWidget(self.detect_btn)

        uv_config_layout.addRow("UV 路径:", path_widget)

        # 路径详情
        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText("未检测到 uv")
        self.path_input.setReadOnly(True)
        uv_config_layout.addRow("当前路径:", self.path_input)

        # 镜像地址
        self.mirror_combo = QComboBox()
        self.mirror_combo.setEditable(True)
        self.mirror_combo.setMinimumWidth(280)
        self.mirror_combo.currentTextChanged.connect(self._on_mirror_changed)
        self.mirror_combo.addItems(
            [
                "默认镜像",
                "https://pypi.tuna.tsinghua.edu.cn/simple",
                "https://mirrors.aliyun.com/pypi/simple",
                "https://pypi.mirrors.ustc.edu.cn/simple",
                "https://mirrors.cloud.tencent.com/pypi/simple",
                "自定义镜像...",
            ]
        )
        uv_config_layout.addRow("镜像地址:", self.mirror_combo)

        # 状态
        self.status_label = QLabel("状态: 检测中...")
        self.status_label.setStyleSheet(
            f"color: {ThemeManager.COLORS['text_secondary']};"
        )
        uv_config_layout.addRow("状态:", self.status_label)

        uv_config_group.setLayout(uv_config_layout)
        uv_layout.addWidget(uv_config_group)

        # UV 安装组
        uv_install_group = QGroupBox("安装 UV")
        uv_install_layout = QVBoxLayout()
        uv_install_layout.setSpacing(10)

        info_label = QLabel("UV 是一个快速的 Python 包管理工具")
        info_label.setStyleSheet(
            f"color: {ThemeManager.COLORS['text_secondary']}; font-size: 12px;"
        )
        uv_install_layout.addWidget(info_label)

        # 安装按钮行
        install_btn_layout = QHBoxLayout()
        self.install_ps_btn = QPushButton("PowerShell 安装")
        self.install_ps_btn.clicked.connect(self._install_uv_powershell)
        self.install_pip_btn = QPushButton("pip 安装")
        self.install_pip_btn.clicked.connect(self._install_uv_pip)
        install_btn_layout.addWidget(self.install_ps_btn)
        install_btn_layout.addWidget(self.install_pip_btn)
        install_btn_layout.addStretch()
        uv_install_layout.addLayout(install_btn_layout)

        # 手动安装命令
        self.manual_text = QTextEdit()
        self.manual_text.setReadOnly(True)
        self.manual_text.setMaximumHeight(80)
        self.manual_text.setPlaceholderText("手动安装命令...")
        uv_install_layout.addWidget(self.manual_text)

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setRange(0, 0)
        uv_install_layout.addWidget(self.progress_bar)

        self.progress_label = QLabel("")
        self.progress_label.setVisible(False)
        uv_install_layout.addWidget(self.progress_label)

        uv_install_group.setLayout(uv_install_layout)
        uv_layout.addWidget(uv_install_group)
        uv_layout.addStretch()

        self.tab_widget.addTab(uv_tab, "UV 设置")

        # === 执行设置标签页 ===
        exec_tab = QWidget()
        exec_layout = QVBoxLayout(exec_tab)
        exec_layout.setContentsMargins(12, 12, 12, 12)
        exec_layout.setSpacing(16)

        exec_group = QGroupBox("节点执行配置")
        exec_form_layout = QFormLayout()
        exec_form_layout.setSpacing(12)

        exec_info = QLabel("配置工作流节点的执行超时时间")
        exec_info.setStyleSheet(
            f"color: {ThemeManager.COLORS['text_secondary']}; font-size: 12px;"
        )
        exec_info.setWordWrap(True)
        exec_form_layout.addRow(exec_info)

        timeout_widget = QWidget()
        timeout_layout = QHBoxLayout(timeout_widget)
        timeout_layout.setContentsMargins(0, 0, 0, 0)
        timeout_layout.setSpacing(8)
        timeout_label = QLabel("超时(秒):")
        self.node_timeout_input = QSpinBox()
        self.node_timeout_input.setRange(10, 3600)
        self.node_timeout_input.setValue(600)
        self.node_timeout_input.setFixedWidth(100)
        timeout_hint = QLabel("默认 600 秒（10 分钟）")
        timeout_hint.setStyleSheet(
            f"color: {ThemeManager.COLORS['text_secondary']}; font-size: 12px;"
        )
        timeout_layout.addWidget(timeout_label)
        timeout_layout.addWidget(self.node_timeout_input)
        timeout_layout.addWidget(timeout_hint)
        timeout_layout.addStretch()

        exec_form_layout.addRow("节点执行超时:", timeout_widget)

        exec_group.setLayout(exec_form_layout)
        exec_layout.addWidget(exec_group)
        exec_layout.addStretch()

        self.tab_widget.addTab(exec_tab, "执行设置")

        # === AI 设置标签页 ===
        ai_tab = QWidget()
        ai_layout = QVBoxLayout(ai_tab)
        ai_layout.setContentsMargins(12, 12, 12, 12)
        ai_layout.setSpacing(16)

        ai_group = QGroupBox("AI 节点生成配置")
        ai_form_layout = QFormLayout()
        ai_form_layout.setSpacing(12)

        ai_info = QLabel("配置后可在节点面板中使用 AI 生成本地自定义节点")
        ai_info.setStyleSheet(
            f"color: {ThemeManager.COLORS['text_secondary']}; font-size: 12px;"
        )
        ai_info.setWordWrap(True)
        ai_form_layout.addRow(ai_info)

        # Base URL
        self.ai_base_url_input = QLineEdit()
        self.ai_base_url_input.setPlaceholderText("https://api.openai.com/v1")
        ai_form_layout.addRow("接口地址:", self.ai_base_url_input)

        # API Key
        self.ai_api_key_input = QLineEdit()
        self.ai_api_key_input.setEchoMode(QLineEdit.Password)
        self.ai_api_key_input.setPlaceholderText("输入 API 密钥")
        ai_form_layout.addRow("API 密钥:", self.ai_api_key_input)

        # Model
        self.ai_model_input = QLineEdit()
        self.ai_model_input.setPlaceholderText("gpt-4o-mini")
        ai_form_layout.addRow("模型:", self.ai_model_input)

        # 参数行
        params_widget = QWidget()
        params_layout = QHBoxLayout(params_widget)
        params_layout.setContentsMargins(0, 0, 0, 0)
        params_layout.setSpacing(16)

        timeout_widget = QWidget()
        timeout_layout = QHBoxLayout(timeout_widget)
        timeout_layout.setContentsMargins(0, 0, 0, 0)
        timeout_layout.setSpacing(8)
        timeout_label = QLabel("超时(秒):")
        self.ai_timeout_input = QSpinBox()
        self.ai_timeout_input.setRange(5, 600)
        self.ai_timeout_input.setValue(60)
        self.ai_timeout_input.setFixedWidth(80)
        timeout_layout.addWidget(timeout_label)
        timeout_layout.addWidget(self.ai_timeout_input)

        temp_widget = QWidget()
        temp_layout = QHBoxLayout(temp_widget)
        temp_layout.setContentsMargins(0, 0, 0, 0)
        temp_layout.setSpacing(8)
        temp_label = QLabel("温度:")
        self.ai_temperature_input = QDoubleSpinBox()
        self.ai_temperature_input.setRange(0.0, 2.0)
        self.ai_temperature_input.setSingleStep(0.1)
        self.ai_temperature_input.setDecimals(2)
        self.ai_temperature_input.setValue(0.2)
        self.ai_temperature_input.setFixedWidth(80)
        temp_layout.addWidget(temp_label)
        temp_layout.addWidget(self.ai_temperature_input)

        history_widget = QWidget()
        history_layout = QHBoxLayout(history_widget)
        history_layout.setContentsMargins(0, 0, 0, 0)
        history_layout.setSpacing(8)
        history_label = QLabel("历史轮数:")
        self.ai_max_history_input = QDoubleSpinBox()
        self.ai_max_history_input.setRange(1, 200)
        self.ai_max_history_input.setSingleStep(1)
        self.ai_max_history_input.setDecimals(0)
        self.ai_max_history_input.setValue(20)
        self.ai_max_history_input.setFixedWidth(80)
        history_layout.addWidget(history_label)
        history_layout.addWidget(self.ai_max_history_input)

        params_layout.addWidget(timeout_widget)
        params_layout.addWidget(temp_widget)
        params_layout.addWidget(history_widget)
        params_layout.addStretch()

        ai_form_layout.addRow("参数:", params_widget)

        # 启用工具复选框
        self.ai_tools_enabled_checkbox = QCheckBox(
            "启用 AI 工具调用 (Function Calling)"
        )
        self.ai_tools_enabled_checkbox.setChecked(True)
        self.ai_tools_enabled_checkbox.setToolTip(
            "部分 API 端点不支持工具调用，如遇 400 错误可尝试取消勾选"
        )
        ai_form_layout.addRow(self.ai_tools_enabled_checkbox)

        # 测试连接按钮和状态
        test_row = QWidget()
        test_layout = QHBoxLayout(test_row)
        test_layout.setContentsMargins(0, 0, 0, 0)
        test_layout.setSpacing(12)

        self.ai_test_btn = QPushButton("测试连接")
        self.ai_test_btn.setFixedHeight(32)
        self.ai_test_btn.clicked.connect(self._on_test_ai_connection)

        self.ai_test_status = QLabel("")
        self.ai_test_status.setWordWrap(True)

        test_layout.addWidget(self.ai_test_btn)
        test_layout.addWidget(self.ai_test_status, 1)
        ai_form_layout.addRow(test_row)

        ai_group.setLayout(ai_form_layout)
        ai_layout.addWidget(ai_group)
        ai_layout.addStretch()

        self.tab_widget.addTab(ai_tab, "AI 设置")

        # === GitHub 标签页 ===
        github_tab = QWidget()
        github_layout = QVBoxLayout(github_tab)
        github_layout.setContentsMargins(12, 12, 12, 12)
        github_layout.setSpacing(16)

        github_group = QGroupBox("GitHub 连接")
        github_form_layout = QFormLayout()
        github_form_layout.setSpacing(12)

        gh_info = QLabel(
            "通过 GitHub Device Flow 登录，可访问 Private 仓库，无需填写 Client Secret"
        )
        gh_info.setStyleSheet(
            f"color: {ThemeManager.COLORS['text_secondary']}; font-size: 12px;"
        )
        gh_info.setWordWrap(True)
        github_form_layout.addRow(gh_info)

        # 登录按钮
        self.gh_login_btn = QPushButton("  登录 GitHub")
        self.gh_login_btn.setMinimumHeight(36)
        self.gh_login_btn.clicked.connect(self._start_oauth_login)
        github_form_layout.addRow(self.gh_login_btn)

        # 状态行
        status_widget = QWidget()
        status_layout = QHBoxLayout(status_widget)
        status_layout.setContentsMargins(0, 0, 0, 0)
        self.gh_status_label = QLabel("未连接")
        self.gh_status_label.setStyleSheet(
            f"color: {ThemeManager.COLORS['text_secondary']};"
        )
        status_layout.addWidget(self.gh_status_label)
        status_layout.addStretch()

        self.gh_disconnect_btn = QPushButton("断开连接")
        self.gh_disconnect_btn.setFixedWidth(80)
        self.gh_disconnect_btn.clicked.connect(self._disconnect_github)
        self.gh_disconnect_btn.setVisible(False)
        status_layout.addWidget(self.gh_disconnect_btn)

        github_form_layout.addRow("状态:", status_widget)

        self.gh_device_hint_label = QLabel("点击登录后，验证码会直接显示在这里。")
        self.gh_device_hint_label.setWordWrap(True)
        self.gh_device_hint_label.setStyleSheet(
            f"color: {ThemeManager.COLORS['text_secondary']}; font-size: 12px;"
        )
        github_form_layout.addRow("提示:", self.gh_device_hint_label)

        self.gh_code_input = QLineEdit()
        self.gh_code_input.setReadOnly(True)
        self.gh_code_input.setPlaceholderText("GitHub 验证码")
        self.gh_code_input.setVisible(False)
        github_form_layout.addRow("验证码:", self.gh_code_input)

        self.gh_verify_url_label = QLabel("")
        self.gh_verify_url_label.setWordWrap(True)
        self.gh_verify_url_label.setOpenExternalLinks(True)
        self.gh_verify_url_label.setVisible(False)
        github_form_layout.addRow("验证地址:", self.gh_verify_url_label)

        github_group.setLayout(github_form_layout)
        github_layout.addWidget(github_group)
        github_layout.addStretch()

        self.tab_widget.addTab(github_tab, "GitHub")

        layout.addWidget(self.tab_widget)

        # 底部按钮
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.close_btn = QPushButton("保存并关闭")
        self.close_btn.clicked.connect(self._save_and_close)
        self.close_btn.setFixedWidth(100)
        button_layout.addWidget(self.close_btn)

        layout.addLayout(button_layout)

        self._apply_styles()

    # Removed _detect_dark_theme

    def _apply_styles(self):
        """Apply modern styles to the dialog using ThemeManager"""
        # Global stylesheet for specific overrides/tweaks
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {ThemeManager.COLORS["background"]};
                color: {ThemeManager.COLORS["text"]};
            }}
            QLabel {{
                color: {ThemeManager.COLORS["text"]};
            }}
            QProgressBar {{
                border: 1px solid {ThemeManager.COLORS["border"]};
                border-radius: 4px;
                background-color: {ThemeManager.COLORS["surface"]};
                text-align: center;
                color: {ThemeManager.COLORS["text"]};
            }}
            QProgressBar::chunk {{
                background-color: {ThemeManager.COLORS["accent"]};
            }}
            QTabWidget::pane {{
                border: 1px solid {ThemeManager.COLORS["border"]};
                border-radius: 8px;
                background-color: {ThemeManager.COLORS["surface"]};
                top: -1px;
            }}
            QTabBar::tab {{
                background-color: {ThemeManager.COLORS["surface_light"]};
                color: {ThemeManager.COLORS["text_secondary"]};
                border: 1px solid {ThemeManager.COLORS["border"]};
                border-bottom: none;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                padding: 8px 20px;
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
        """)

        # Apply component styles
        self.path_combo.setStyleSheet(ThemeManager.get_input_style())
        self.mirror_combo.setStyleSheet(ThemeManager.get_input_style())
        self.path_input.setStyleSheet(ThemeManager.get_input_style())
        self.manual_text.setStyleSheet(ThemeManager.get_input_style())
        self.ai_base_url_input.setStyleSheet(ThemeManager.get_input_style())
        self.ai_api_key_input.setStyleSheet(ThemeManager.get_input_style())
        self.ai_model_input.setStyleSheet(ThemeManager.get_input_style())
        self.ai_timeout_input.setStyleSheet(ThemeManager.get_input_style())
        self.ai_temperature_input.setStyleSheet(ThemeManager.get_input_style())
        self.ai_max_history_input.setStyleSheet(ThemeManager.get_input_style())
        self.ai_tools_enabled_checkbox.setStyleSheet(ThemeManager.get_input_style())
        self.node_timeout_input.setStyleSheet(ThemeManager.get_input_style())
        self.gh_code_input.setStyleSheet(ThemeManager.get_input_style())

        # Buttons
        self.detect_btn.setStyleSheet(ThemeManager.get_button_style("secondary"))
        self.install_ps_btn.setStyleSheet(ThemeManager.get_button_style("primary"))
        self.install_pip_btn.setStyleSheet(ThemeManager.get_button_style("primary"))
        self.gh_login_btn.setStyleSheet(ThemeManager.get_button_style("primary"))
        self.gh_disconnect_btn.setStyleSheet(ThemeManager.get_button_style("secondary"))
        self.close_btn.setStyleSheet(ThemeManager.get_button_style("secondary"))

        # Group Boxes
        group_style = ThemeManager.get_group_box_style()
        for group_box in self.findChildren(QGroupBox):
            group_box.setStyleSheet(group_style)

    def _load_settings(self):
        """加载所有设置"""
        # 执行设置
        self.node_timeout_input.setValue(self.config_manager.get_node_timeout_seconds())

        # AI 设置
        self._load_ai_settings()

    def _load_ai_settings(self):
        """加载 AI 设置"""
        settings = self.config_manager.get_ai_settings()
        self.ai_base_url_input.setText(settings.get("base_url", ""))
        self.ai_api_key_input.setText(settings.get("api_key", ""))
        self.ai_model_input.setText(settings.get("model", ""))
        self.ai_timeout_input.setValue(int(settings.get("timeout_seconds", 60)))
        self.ai_temperature_input.setValue(float(settings.get("temperature", 0.2)))
        self.ai_max_history_input.setValue(int(settings.get("max_history_rounds", 20)))
        self.ai_tools_enabled_checkbox.setChecked(settings.get("tools_enabled", True))

        gh_settings = self.config_manager.get_github_settings()
        if gh_settings.get("connected") and gh_settings.get("username"):
            self.gh_status_label.setText(f"✓ 已连接: {gh_settings['username']}")
            self.gh_status_label.setStyleSheet(
                f"color: {ThemeManager.COLORS.get('success', '#4CAF50')};"
            )
            self.gh_disconnect_btn.setVisible(True)
            self.gh_login_btn.setText("  重新登录 GitHub")
            self.gh_device_hint_label.setText("已完成 GitHub 登录。")
            self.gh_code_input.clear()
            self.gh_code_input.setVisible(False)
            self.gh_verify_url_label.clear()
            self.gh_verify_url_label.setVisible(False)
        else:
            self.gh_disconnect_btn.setVisible(False)
            self.gh_device_hint_label.setText("点击登录后，验证码会直接显示在这里。")
            self.gh_code_input.clear()
            self.gh_code_input.setVisible(False)
            self.gh_verify_url_label.clear()
            self.gh_verify_url_label.setVisible(False)

    def _save_settings(self):
        """保存所有设置"""
        # 执行设置
        self.config_manager.set_node_timeout_seconds(self.node_timeout_input.value())

        # AI 设置
        self._save_ai_settings()

    def _save_ai_settings(self):
        """保存 AI 设置"""
        settings = {
            "provider_type": "openai_compatible",
            "base_url": self.ai_base_url_input.text().strip(),
            "api_key": self.ai_api_key_input.text().strip(),
            "model": self.ai_model_input.text().strip(),
            "timeout_seconds": self.ai_timeout_input.value(),
            "temperature": self.ai_temperature_input.value(),
            "max_history_rounds": int(self.ai_max_history_input.value()),
            "tools_enabled": self.ai_tools_enabled_checkbox.isChecked(),
        }
        self.config_manager.set_ai_settings(settings)

    def _on_test_ai_connection(self):
        """测试 AI API 连接"""
        base_url = self.ai_base_url_input.text().strip()
        api_key = self.ai_api_key_input.text().strip()
        model = self.ai_model_input.text().strip()
        timeout = self.ai_timeout_input.value()

        logger.info("开始 AI 连接测试: base_url=%s, model=%s", base_url, model)

        self.ai_test_btn.setEnabled(False)
        self.ai_test_btn.setText("测试中...")
        self.ai_test_status.setText("正在连接...")
        self.ai_test_status.setStyleSheet(
            f"color: {ThemeManager.COLORS['text_secondary']};"
        )

        self._ai_test_worker = _AITestWorker(base_url, api_key, model, timeout)
        self._ai_test_worker.finished.connect(self._on_ai_test_finished)
        self._ai_test_worker.start()

    def _on_ai_test_finished(self, success: bool, message: str):
        """AI 连接测试完成"""
        self.ai_test_btn.setEnabled(True)
        self.ai_test_btn.setText("测试连接")
        if success:
            self.ai_test_status.setText(f"✓ {message}")
            self.ai_test_status.setStyleSheet(
                f"color: {ThemeManager.COLORS.get('success', '#4CAF50')};"
            )
            logger.info("AI 连接测试完成: %s", message)
        else:
            self.ai_test_status.setText(f"✗ {message}")
            self.ai_test_status.setStyleSheet(
                f"color: {ThemeManager.COLORS.get('error', '#F44336')};"
            )
            logger.warning("AI 连接测试失败: %s", message)

    def _save_and_close(self):
        """保存设置并关闭"""
        self._save_settings()
        self.accept()

    def _start_oauth_login(self):
        """通过浏览器 Device Flow 登录 GitHub"""
        self.gh_login_btn.setEnabled(False)
        self.gh_status_label.setText("正在获取 GitHub 验证码...")
        self.gh_status_label.setStyleSheet(
            f"color: {ThemeManager.COLORS['text_secondary']};"
        )
        self.gh_device_hint_label.setText("正在打开 GitHub 验证页面...")
        self.gh_code_input.clear()
        self.gh_code_input.setVisible(False)
        self.gh_verify_url_label.clear()
        self.gh_verify_url_label.setVisible(False)

        self._oauth_worker = _OAuthWorker()
        self._oauth_worker.prompt.connect(self._on_oauth_prompt)
        self._oauth_worker.finished.connect(self._on_oauth_finished)
        self._oauth_worker.start()

    def _on_oauth_prompt(self, user_code: str, verification_uri: str):
        """显示 GitHub Device Flow 验证提示"""
        self.gh_status_label.setText(f"请在 GitHub 页面输入验证码: {user_code}")
        self.gh_status_label.setStyleSheet(f"color: {ThemeManager.COLORS['text']};")
        self.gh_device_hint_label.setText(
            "浏览器已打开 GitHub 验证页，请在页面输入下面的验证码。"
        )
        self.gh_code_input.setText(user_code)
        self.gh_code_input.setVisible(True)
        self.gh_verify_url_label.setText(
            f'<a href="{verification_uri}">{verification_uri}</a>'
        )
        self.gh_verify_url_label.setVisible(True)

        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(user_code)

    def _on_oauth_finished(self, success: bool, token: str, message: str):
        """OAuth 授权完成回调"""
        self.gh_login_btn.setEnabled(True)
        if success:
            self.gh_status_label.setText(f"✓ 已连接: {message}")
            self.gh_status_label.setStyleSheet(
                f"color: {ThemeManager.COLORS.get('success', '#4CAF50')};"
            )
            self.gh_disconnect_btn.setVisible(True)
            self.gh_login_btn.setText("  重新登录 GitHub")
            self.gh_device_hint_label.setText("GitHub 登录成功。")
            self.config_manager.set_github_settings(
                {
                    "token": token,
                    "username": message,
                    "connected": True,
                }
            )
        else:
            self.gh_status_label.setText(f"✗ {message}")
            self.gh_status_label.setStyleSheet(
                f"color: {ThemeManager.COLORS.get('error', '#F44336')};"
            )
            self.gh_device_hint_label.setText("GitHub 登录失败，请重试。")

    def _disconnect_github(self):
        """断开 GitHub 连接"""
        self.config_manager.set_github_settings(
            {
                "token": "",
                "username": "",
                "connected": False,
            }
        )
        self.gh_status_label.setText("未连接")
        self.gh_status_label.setStyleSheet(
            f"color: {ThemeManager.COLORS['text_secondary']};"
        )
        self.gh_disconnect_btn.setVisible(False)
        self.gh_login_btn.setText("  登录 GitHub")
        self.gh_device_hint_label.setText("点击登录后，验证码会直接显示在这里。")
        self.gh_code_input.clear()
        self.gh_code_input.setVisible(False)
        self.gh_verify_url_label.clear()
        self.gh_verify_url_label.setVisible(False)

    def closeEvent(self, event):
        """关闭窗口时保存设置"""
        self._save_settings()
        super().closeEvent(event)

    def _start_uv_detect(self):
        """启动异步 UV 检测工作线程"""
        self.status_label.setText("状态: 检测中...")
        self.status_label.setStyleSheet(
            f"color: {ThemeManager.COLORS['text_secondary']}; font-style: italic;"
        )
        self.detect_btn.setEnabled(False)

        self.uv_detect_worker = UVDetectWorker()
        self.uv_detect_worker.finished.connect(self._on_uv_detect_finished)
        self.uv_detect_worker.start()

    def _on_uv_detect_finished(self, uv_entries, uv_mirror, error):
        """UV 检测完成回调"""
        self.detect_btn.setEnabled(True)

        if error:
            logger.error("检测uv时出错: %s", error)
            self._uv_not_found()
            return

        self.uv_entries = uv_entries
        self.uv_paths = [entry[1] for entry in uv_entries]
        self.uv_mirror = uv_mirror

        if self.uv_paths:
            self.path_combo.clear()

            for display_text, uv_path in uv_entries:
                self.path_combo.addItem(display_text, uv_path)

            self.path_combo.addItem("自定义路径...", "custom")
            self.path_combo.setEnabled(True)
            if self.uv_paths:
                self.path_combo.setCurrentIndex(0)
                self.uv_path = self.uv_paths[0]
                self.path_input.setText(self.uv_path)

            if self.uv_mirror:
                self._set_mirror_selection(self.uv_mirror)
            else:
                self.mirror_combo.setCurrentIndex(0)

            count = len(self.uv_paths)
            if count == 1:
                self.status_label.setText("状态: ✓ 已安装 1 个uv")
            else:
                self.status_label.setText(f"状态: ✓ 已安装 {count} 个uv")
            self.status_label.setStyleSheet(
                f"color: {ThemeManager.COLORS['success']}; font-weight: bold;"
            )
        else:
            self._uv_not_found()

    def _detect_uv(self):
        """Detect uv installation and mirror configuration (同步版本，供手动触发使用)"""
        self._start_uv_detect()

    def _set_mirror_selection(self, mirror_url):
        """根据镜像URL设置下拉框选择"""
        # 检查是否为预设镜像
        preset_mirrors = [
            "https://pypi.tuna.tsinghua.edu.cn/simple",
            "https://mirrors.aliyun.com/pypi/simple",
            "https://pypi.mirrors.ustc.edu.cn/simple",
            "https://mirrors.cloud.tencent.com/pypi/simple",
        ]

        if mirror_url in preset_mirrors:
            index = self.mirror_combo.findText(mirror_url)
            if index >= 0:
                self.mirror_combo.setCurrentIndex(index)
        else:
            # 添加为自定义镜像
            self.mirror_combo.setItemText(
                self.mirror_combo.count() - 1, f"自定义: {mirror_url}"
            )
            self.mirror_combo.setCurrentIndex(self.mirror_combo.count() - 1)

    def _on_uv_path_changed(self, display_text):
        """处理uv路径选择变更"""
        if not display_text:
            return

        # 获取选择的uv路径
        current_data = self.path_combo.currentData()
        if current_data == "custom":
            # 用户选择自定义路径
            self._show_custom_path_dialog()
        elif current_data:
            self.uv_path = current_data
            self.path_input.setText(self.uv_path)

            # 更新UVManager的自定义路径
            try:
                sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
                from core.uv_manager import UVManager

                uv_manager = UVManager()
                uv_manager.set_custom_uv_path(self.uv_path)
            except:
                pass

    def _on_mirror_changed(self, text):
        """处理镜像地址变更"""
        # 检查是否是特殊选项
        if text == "自定义镜像...":
            self._show_custom_mirror_dialog()
            return
        elif text == "默认镜像":
            # 清除镜像配置
            self.uv_mirror = ""
            self._save_mirror_config()
            return

        # 检查是否是自定义镜像（以"自定义:"开头）
        if text.startswith("自定义:"):
            # 提取实际的镜像地址
            actual_mirror = text[4:]  # 去掉"自定义:"前缀
            self.uv_mirror = actual_mirror
            return

        # 预设镜像或直接输入的镜像地址
        self.uv_mirror = text
        self._save_mirror_config()

    def _show_custom_path_dialog(self):
        """显示自定义路径对话框"""
        from PySide6.QtWidgets import QInputDialog

        current_path = (
            self.path_input.text() if self.path_input.text() != "未检测到 uv" else ""
        )

        # 设置默认提示文本
        if not current_path:
            current_path = "C:\\path\\to\\uv.exe" if os.name == "nt" else "/path/to/uv"

        path, ok = QInputDialog.getText(
            self,
            "自定义 UV 路径",
            "请输入 UV 可执行文件的完整路径:\n(例如: C:\\Users\\username\\.local\\bin\\uv.exe)",
            text=current_path,
        )

        if ok and path:
            # 验证路径
            try:
                sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
                from core.uv_manager import UVManager

                uv_manager = UVManager()
                if uv_manager._verify_uv_executable(path):
                    self.uv_path = path
                    self.path_input.setText(path)
                    self.path_combo.setItemText(
                        self.path_combo.currentIndex(), f"自定义: {path}"
                    )
                    self.path_combo.setItemData(self.path_combo.currentIndex(), path)

                    # 更新UVManager
                    uv_manager.set_custom_uv_path(path)

                    ToastWidget.show(self, "自定义 UV 路径设置成功！", "success")
                else:
                    QMessageBox.warning(
                        self, "错误", "指定的路径不是有效的 UV 可执行文件"
                    )
            except Exception as e:
                QMessageBox.critical(self, "错误", f"验证路径时出错: {str(e)}")
        elif ok:
            # 用户取消了输入，恢复到第一个可用选项
            if self.uv_paths:
                self.path_combo.setCurrentIndex(0)

    def _show_custom_mirror_dialog(self):
        """显示自定义镜像对话框"""
        from PySide6.QtWidgets import QInputDialog

        current_mirror = self.uv_mirror if self.uv_mirror else ""

        # 设置默认文本作为提示
        if not current_mirror:
            current_mirror = "https://example.com/simple"

        mirror, ok = QInputDialog.getText(
            self,
            "自定义镜像地址",
            "请输入 PyPI 镜像地址:\n(例如: https://pypi.tuna.tsinghua.edu.cn/simple)",
            text=current_mirror,
        )

        if ok and mirror and mirror != "https://example.com/simple":
            self.uv_mirror = mirror
            self.mirror_combo.setItemText(
                self.mirror_combo.currentIndex(), f"自定义: {mirror}"
            )
            self._save_mirror_config()
        elif ok:
            # 用户取消了输入或使用了默认提示，恢复到默认镜像
            self.mirror_combo.setCurrentIndex(0)

    def _save_mirror_config(self):
        """保存镜像配置到环境变量和文件"""
        try:
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
            from core.uv_manager import UVManager

            uv_manager = UVManager()
            uv_manager.set_custom_mirror(self.uv_mirror)
        except Exception as e:
            logger.error("保存镜像配置时出错: %s", e)

    def _uv_not_found(self):
        """Handle case when uv is not found"""
        self.uv_path = ""
        self.uv_paths = []
        self.path_combo.clear()
        self.path_combo.addItem("未检测到 uv", "")
        self.path_combo.addItem("自定义路径...", "custom")
        self.path_combo.setEnabled(True)  # 允许用户选择自定义路径
        self.path_combo.setCurrentIndex(1)  # 默认选中"自定义路径..."
        self.path_input.setText("未检测到 uv")
        self.path_input.setPlaceholderText("请选择自定义路径或安装 uv")
        self.mirror_combo.setCurrentIndex(0)
        self.status_label.setText("状态: ✗ 未安装")
        self.status_label.setStyleSheet(
            f"color: {ThemeManager.COLORS['error']}; font-weight: bold;"
        )

    def _install_uv_powershell(self):
        """Install uv using PowerShell"""
        if sys.platform != "win32":
            QMessageBox.warning(self, "不支持", "此安装方法仅支持 Windows 系统。")
            return

        reply = QMessageBox.question(
            self,
            "确认安装",
            "将使用 PowerShell 安装 uv，这需要管理员权限。\n\n是否继续？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if reply == QMessageBox.Yes:
            self._start_installation_powershell()

    def _start_installation_powershell(self):
        """下载安装脚本并执行（下载与执行分离，避免 shell=True 风险）"""
        self.progress_bar.setVisible(True)
        self.progress_label.setVisible(True)
        self.progress_label.setText("正在下载安装脚本...")

        self.install_ps_btn.setEnabled(False)
        self.install_pip_btn.setEnabled(False)

        self._ps_worker = _PSDownloadWorker()
        self._ps_worker.progress.connect(self._on_install_progress)
        self._ps_worker.finished.connect(self._on_ps_download_finished)
        self._ps_worker.start()

    def _on_ps_download_finished(self, success, script_path_or_error):
        """PowerShell 脚本下载完成后的回调"""
        if not success:
            self.progress_bar.setVisible(False)
            self.progress_label.setVisible(False)
            self.install_ps_btn.setEnabled(True)
            self.install_pip_btn.setEnabled(True)
            QMessageBox.critical(
                self,
                "安装失败",
                f"下载安装脚本时出错：\n\n{script_path_or_error}",
            )
            return

        script_path = script_path_or_error
        install_args = [
            "powershell",
            "-ExecutionPolicy", "ByPass",
            "-File", script_path,
        ]
        self.install_worker = InstallWorker(install_args)
        self.install_worker.progress.connect(self._on_install_progress)
        self.install_worker.finished.connect(
            lambda success, msg: self._on_install_finished(success, msg, script_path)
        )
        self.install_worker.start()

    def _install_uv_pip(self):
        """Install uv using pip"""
        reply = QMessageBox.question(
            self,
            "确认安装",
            "将使用 pip 安装 uv。\n\n是否继续？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if reply == QMessageBox.Yes:
            install_args = [sys.executable, "-m", "pip", "install", "uv"]
            self._start_installation(install_args)

    def _start_installation(self, install_args):
        """Start the installation process"""
        self.progress_bar.setVisible(True)
        self.progress_label.setVisible(True)
        self.progress_label.setText("正在安装...")

        # Disable install buttons
        self.install_ps_btn.setEnabled(False)
        self.install_pip_btn.setEnabled(False)

        # Create and start worker thread
        self.install_worker = InstallWorker(install_args)
        self.install_worker.progress.connect(self._on_install_progress)
        self.install_worker.finished.connect(
            lambda success, msg: self._on_install_finished(success, msg)
        )
        self.install_worker.start()

    def _on_install_progress(self, message):
        """Handle installation progress updates"""
        self.progress_label.setText(message)

    def _on_install_finished(self, success, message, cleanup_path=None):
        """Handle installation completion"""
        self.progress_bar.setVisible(False)
        self.progress_label.setVisible(False)

        # Re-enable install buttons
        self.install_ps_btn.setEnabled(True)
        self.install_pip_btn.setEnabled(True)

        # Clean up temporary script file
        if cleanup_path:
            try:
                os.unlink(cleanup_path)
            except OSError:
                pass

        if success:
            ToastWidget.show(self, "UV 已成功安装！请重新检测以确认。", "success")
            self._detect_uv()
        else:
            QMessageBox.critical(
                self,
                "安装失败",
                f"安装 UV 时出现错误：\n\n{message}\n\n请尝试手动安装。",
            )
