"""
AI 聊天对话框 UI 组件
"""

from PySide6.QtCore import QSize, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.core.ai_chat_context import AIChatContextBuilder
from src.core.ai_chat_service import AIChatService
from src.core.ai_tool_executor import AIChatError, AIToolExecutor
from src.core.config_manager import ConfigManager
from src.core.log_manager import get_logger
from src.core.theme_manager import ThemeManager

logger = get_logger("ai_chat_widget")


class ChatWorker(QThread):
    """后台聊天请求线程"""

    finished = Signal(dict)
    error = Signal(str)
    stream_chunk = Signal(str)

    def __init__(
        self,
        chat_service: AIChatService,
        user_message: str,
        workflow_context: dict,
        tool_executor=None,
    ):
        super().__init__()
        self.chat_service = chat_service
        self.user_message = user_message
        self.workflow_context = workflow_context
        self.tool_executor = tool_executor

    def run(self):
        try:
            result = self.chat_service.chat(
                self.user_message,
                self.workflow_context,
                self.tool_executor,
                stream_callback=self._on_stream_chunk,
            )
            self.finished.emit(result)
        except AIChatError as exc:
            self.error.emit(str(exc))
        except Exception as exc:
            self.error.emit(f"请求失败: {exc}")

    def _on_stream_chunk(self, chunk_text: str):
        self.stream_chunk.emit(chunk_text)


class LoadingIndicator(QFrame):
    """加载动画指示器"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        self._start_animation()

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(6)

        # 三个点的加载动画
        self.dots = []
        for i in range(3):
            dot = QLabel("●")
            dot.setStyleSheet(
                f"color: {ThemeManager.COLORS['accent']}; font-size: 8px;"
            )
            dot.setFixedSize(12, 12)
            dot.setAlignment(Qt.AlignCenter)
            layout.addWidget(dot)
            self.dots.append(dot)

        layout.addStretch()

        self.setStyleSheet(f"""
            LoadingIndicator {{
                background-color: {ThemeManager.COLORS["surface_light"]};
                border-radius: 12px;
                border: 1px solid {ThemeManager.COLORS["border"]};
            }}
        """)

    def _start_animation(self):
        """启动呼吸动画"""
        self._animation_index = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._animate)
        self._timer.start(400)

    def _animate(self):
        """动画帧"""
        colors = [
            ThemeManager.COLORS["accent"],
            ThemeManager.COLORS["accent_hover"],
            ThemeManager.COLORS["text_muted"],
        ]
        for i, dot in enumerate(self.dots):
            color_index = (i + self._animation_index) % 3
            dot.setStyleSheet(f"color: {colors[color_index]}; font-size: 8px;")
        self._animation_index += 1

    def stop_animation(self):
        """停止动画"""
        if hasattr(self, "_timer"):
            self._timer.stop()


class MessageBubble(QFrame):
    """消息气泡"""

    def __init__(self, text: str, is_user: bool = True, parent=None):
        super().__init__(parent)
        self.is_user = is_user
        self._raw_text = text
        self._setup_ui(text)

    def _setup_ui(self, text: str):
        # 设置消息气泡随父容器宽度自适应
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(8)

        # 头像/标识
        avatar = QLabel("你" if self.is_user else "AI")
        avatar.setFixedSize(28, 28)
        avatar.setAlignment(Qt.AlignCenter)
        avatar_font = QFont()
        avatar_font.setPointSize(9)
        avatar_font.setBold(True)
        avatar.setFont(avatar_font)

        if self.is_user:
            avatar.setStyleSheet(f"""
                QLabel {{
                    background-color: {ThemeManager.COLORS["accent"]};
                    color: {ThemeManager.COLORS["white"]};
                    border-radius: 14px;
                }}
            """)
        else:
            avatar.setStyleSheet(f"""
                QLabel {{
                    background-color: {ThemeManager.COLORS["surface_lighter"]};
                    color: {ThemeManager.COLORS["accent"]};
                    border-radius: 14px;
                    border: 1px solid {ThemeManager.COLORS["border"]};
                }}
            """)

        # 消息内容 - 设置内容布局可扩展
        content_layout = QVBoxLayout()
        content_layout.setSpacing(4)
        content_layout.setContentsMargins(0, 0, 0, 0)
        # 使用 SetMaximumSize 允许布局根据可用空间扩展
        content_layout.setSizeConstraint(QLayout.SetMaximumSize)

        if self.is_user:
            label = QLabel(text)
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
            # 设置最大宽度允许内容扩展
            label.setMaximumWidth(10000)
            # 初始化时根据父容器宽度设置最小宽度
            parent = self.parentWidget()
            parent_width = parent.width() if parent else 400
            available_width = max(200, parent_width - 80)
            label.setMinimumWidth(available_width)
            self._content_label = label

            font = QFont()
            font.setPointSize(9)
            label.setFont(font)

            label.setStyleSheet(f"""
                QLabel {{
                    color: {ThemeManager.COLORS["white"]};
                    background-color: {ThemeManager.COLORS["accent"]};
                    border-radius: 12px;
                    padding: 10px 14px;
                }}
            """)
        else:
            browser = QTextBrowser()
            browser.setOpenExternalLinks(True)
            browser.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            browser.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            browser.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
            browser.setMinimumHeight(40)
            browser.setMaximumHeight(16777215)
            browser.setMaximumWidth(10000)  # 允许宽度扩展
            browser.setFrameShape(QFrame.NoFrame)
            # 初始化时根据父容器宽度设置最小宽度
            parent = self.parentWidget()
            parent_width = parent.width() if parent else 400
            available_width = max(200, parent_width - 80)
            browser.setMinimumWidth(available_width)
            self._content_browser = browser

            font = QFont()
            font.setPointSize(9)
            browser.setFont(font)

            self._update_ai_content(text)

        # 时间戳
        from datetime import datetime

        time_label = QLabel(datetime.now().strftime("%H:%M"))
        time_font = QFont()
        time_font.setPointSize(7)
        time_label.setFont(time_font)
        time_label.setStyleSheet(f"color: {ThemeManager.COLORS['text_muted']};")

        if self.is_user:
            content_layout.addWidget(label, alignment=Qt.AlignRight)
            content_layout.addWidget(time_label, alignment=Qt.AlignRight)
            layout.addStretch(1)
            layout.addLayout(content_layout, stretch=10)  # 内容区域可扩展
            layout.addWidget(avatar, alignment=Qt.AlignTop)
        else:
            layout.addWidget(avatar, alignment=Qt.AlignTop)
            layout.addLayout(content_layout, stretch=10)  # 内容区域可扩展
            content_layout.addWidget(browser, alignment=Qt.AlignLeft)
            content_layout.addWidget(time_label, alignment=Qt.AlignLeft)
            layout.addStretch(1)

        self.setStyleSheet("QFrame { background: transparent; border: none; }")

    def _update_ai_content(self, text: str):
        """更新 AI 消息内容（支持 Markdown 渲染）"""
        browser = self._content_browser
        if not text:
            browser.setPlainText("")
        else:
            # 确保文本是 UTF-8 编码的字符串
            if isinstance(text, bytes):
                text = text.decode("utf-8")
            logger.debug(
                "_update_ai_content: text type=%s, len=%d, repr=%r",
                type(text).__name__,
                len(text),
                text[:100],
            )
            browser.setMarkdown(text)
        browser.setStyleSheet(f"""
            QTextBrowser {{
                color: {ThemeManager.COLORS["text"]};
                background-color: {ThemeManager.COLORS["surface_light"]};
                border-radius: 12px;
                padding: 10px 14px;
                border: 1px solid {ThemeManager.COLORS["border"]};
            }}
            QTextBrowser h1, QTextBrowser h2, QTextBrowser h3,
            QTextBrowser h4, QTextBrowser h5, QTextBrowser h6 {{
                color: {ThemeManager.COLORS["text"]};
                margin-top: 8px;
                margin-bottom: 4px;
            }}
            QTextBrowser p {{
                margin-top: 4px;
                margin-bottom: 4px;
            }}
            QTextBrowser pre {{
                background-color: {ThemeManager.COLORS["background"]};
                border: 1px solid {ThemeManager.COLORS["border"]};
                border-radius: 6px;
                padding: 8px;
                margin: 6px 0;
            }}
            QTextBrowser code {{
                background-color: {ThemeManager.COLORS["background"]};
                color: {ThemeManager.COLORS["accent_light"]};
                border-radius: 4px;
                padding: 1px 4px;
                font-family: {ThemeManager.FONTS["family_mono"]};
                font-size: {ThemeManager.FONTS["size_small"]};
            }}
            QTextBrowser pre code {{
                background-color: transparent;
                color: {ThemeManager.COLORS["text"]};
                border-radius: 0;
                padding: 0;
            }}
            QTextBrowser blockquote {{
                border-left: 3px solid {ThemeManager.COLORS["accent"]};
                margin: 6px 0;
                padding-left: 10px;
                color: {ThemeManager.COLORS["text_secondary"]};
            }}
            QTextBrowser a {{
                color: {ThemeManager.COLORS["accent"]};
                text-decoration: none;
            }}
            QTextBrowser a:hover {{
                text-decoration: underline;
            }}
            QTextBrowser ul, QTextBrowser ol {{
                margin-top: 4px;
                margin-bottom: 4px;
                padding-left: 20px;
            }}
            QTextBrowser li {{
                margin: 2px 0;
            }}
            QTextBrowser hr {{
                border: none;
                border-top: 1px solid {ThemeManager.COLORS["border"]};
                margin: 8px 0;
            }}
            QTextBrowser table {{
                border-collapse: collapse;
                margin: 6px 0;
            }}
            QTextBrowser th, QTextBrowser td {{
                border: 1px solid {ThemeManager.COLORS["border"]};
                padding: 4px 8px;
            }}
            QTextBrowser th {{
                background-color: {ThemeManager.COLORS["surface"]};
            }}
        """)
        QTimer.singleShot(0, self._update_browser_height)

    def _update_browser_height(self):
        """根据内容自动调整 QTextBrowser 高度"""
        browser = getattr(self, "_content_browser", None)
        if not browser:
            return
        doc = browser.document()
        if not doc:
            return
        # 使用QTextBrowser自身的宽度来计算文档高度
        browser_width = browser.width()
        if browser_width <= 0:
            browser_width = self.width() - 60
        if browser_width < 200:
            browser_width = 200
        # 考虑QTextBrowser的内边距
        available_width = browser_width - 28  # 减去左右padding (14+14)
        # 重新设置文档宽度以适应容器
        doc.setTextWidth(available_width)
        doc_height = int(doc.size().height())
        height = doc_height + 28  # 加上上下padding (14+14)
        browser.setMinimumHeight(max(40, height))
        browser.setMaximumHeight(max(40, height))

    def resizeEvent(self, event):
        """当气泡大小改变时，调整内部组件宽度"""
        super().resizeEvent(event)
        # 计算可用宽度（减去头像、边距和间距）
        available_width = self.width() - 60  # 头像28 + 边距和间距约32
        if available_width < 200:
            available_width = 200

        if self.is_user:
            # 用户消息：设置 QLabel 的最小宽度以填充可用空间
            if hasattr(self, "_content_label"):
                self._content_label.setMinimumWidth(available_width)
        else:
            # AI 消息：设置 QTextBrowser 的最小宽度并调整高度
            if hasattr(self, "_content_browser"):
                self._content_browser.setMinimumWidth(available_width)
                self._update_browser_height()

    def setText(self, text: str):
        """设置消息文本"""
        self._raw_text = text
        if self.is_user:
            self._content_label.setText(text)
        else:
            self._update_ai_content(text)
            self._update_browser_height()


class ToolResultCard(QFrame):
    """工具执行结果卡片"""

    def __init__(self, tool_name: str, arguments: dict, result: dict, parent=None):
        super().__init__(parent)
        self._setup_ui(tool_name, arguments, result)

    def _setup_ui(self, tool_name: str, arguments: dict, result: dict):
        # 设置工具结果卡片可水平扩展
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(4)

        success = result.get("success", False) if isinstance(result, dict) else False
        status_text = "成功" if success else "失败"
        status_color = (
            ThemeManager.COLORS["success"] if success else ThemeManager.COLORS["error"]
        )

        header = QLabel(f"[工具] {tool_name} - {status_text}")
        header.setFont(QFont("", 9, QFont.Bold))
        header.setStyleSheet(f"color: {status_color}; border: none;")
        layout.addWidget(header)

        args_text = ", ".join(f"{k}={v}" for k, v in arguments.items() if v)
        if args_text:
            args_label = QLabel(f"参数: {args_text}")
            args_label.setFont(QFont("", 8))
            args_label.setStyleSheet(
                f"color: {ThemeManager.COLORS['text_secondary']}; border: none;"
            )
            args_label.setWordWrap(True)
            layout.addWidget(args_label)

        if isinstance(result, dict):
            if not success and result.get("error"):
                err_label = QLabel(f"错误: {result['error']}")
                err_label.setStyleSheet(
                    f"color: {ThemeManager.COLORS['error']}; border: none;"
                )
                err_label.setWordWrap(True)
                layout.addWidget(err_label)
            elif success and result.get("node_id"):
                ok_label = QLabel(f"节点ID: {result['node_id']}")
                ok_label.setStyleSheet(
                    f"color: {ThemeManager.COLORS['success']}; border: none;"
                )
                layout.addWidget(ok_label)

        self.setStyleSheet(f"""
            ToolResultCard {{
                background-color: {ThemeManager.COLORS["surface"]};
                border-left: 3px solid {status_color};
                border-radius: 6px;
                margin: 4px 8px;
            }}
        """)


class AIChatWidget(QWidget):
    """AI 聊天对话框"""

    open_settings_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.chat_service = None
        self.tool_executor = None
        self.workflow_tab = None
        self.config_manager = (
            parent.config_manager
            if parent and hasattr(parent, "config_manager")
            else ConfigManager()
        )
        self._chat_worker = None
        self._loading_indicator = None
        self._setup_ui()
        self._init_chat_service()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 顶部工具栏
        toolbar = QWidget()
        toolbar.setMinimumHeight(40)
        toolbar.setStyleSheet(f"""
            QWidget {{
                background-color: {ThemeManager.COLORS["surface"]};
                border-bottom: 1px solid {ThemeManager.COLORS["border"]};
            }}
        """)
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(12, 8, 12, 8)
        toolbar_layout.setSpacing(8)

        # 标题
        title_label = QLabel("AI 助手")
        title_font = QFont()
        title_font.setPointSize(11)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setStyleSheet(f"color: {ThemeManager.COLORS['text']};")
        toolbar_layout.addWidget(title_label)

        toolbar_layout.addStretch()

        # 模型状态标签
        self.model_label = QLabel("")
        model_font = QFont()
        model_font.setPointSize(8)
        self.model_label.setFont(model_font)
        self.model_label.setStyleSheet(f"color: {ThemeManager.COLORS['text_muted']};")
        toolbar_layout.addWidget(self.model_label)

        # 清空按钮 - 使用 secondary 样式
        clear_btn = QPushButton("清空")
        clear_btn.setFixedSize(50, 28)
        clear_btn.setStyleSheet(ThemeManager.get_button_style("secondary"))
        clear_btn.setCursor(Qt.PointingHandCursor)
        clear_btn.clicked.connect(self._clear_chat)
        toolbar_layout.addWidget(clear_btn)

        # 导出按钮
        export_btn = QPushButton("导出")
        export_btn.setFixedSize(50, 28)
        export_btn.setStyleSheet(ThemeManager.get_button_style("secondary"))
        export_btn.setCursor(Qt.PointingHandCursor)
        export_btn.clicked.connect(self._export_chat)
        toolbar_layout.addWidget(export_btn)

        layout.addWidget(toolbar)

        # 消息滚动区域
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setStyleSheet(f"""
            QScrollArea {{
                background-color: {ThemeManager.COLORS["background"]};
                border: none;
            }}
            QScrollBar:vertical {{
                background: transparent;
                width: 6px;
                border-radius: 3px;
            }}
            QScrollBar::handle:vertical {{
                background: {ThemeManager.COLORS["border_light"]};
                border-radius: 3px;
                min-height: 20px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {ThemeManager.COLORS["accent"]};
            }}
        """)

        self.message_container = QWidget()
        # 设置消息容器可水平扩展，垂直方向使用Preferred以便内容决定高度
        self.message_container.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Preferred
        )
        self.message_layout = QVBoxLayout(self.message_container)
        self.message_layout.setContentsMargins(8, 8, 8, 8)
        self.message_layout.setSpacing(6)
        # 设置布局对齐方式为顶部，并且让widget水平拉伸填充
        self.message_layout.setAlignment(Qt.AlignTop)
        self.message_layout.addStretch()

        self.scroll_area.setWidget(self.message_container)
        layout.addWidget(self.scroll_area, 1)

        # 输入区域 - 现代化圆角卡片设计
        input_area = QWidget()
        input_area.setMinimumHeight(80)
        input_area.setMaximumHeight(140)
        input_area.setStyleSheet(f"""
            QWidget {{
                background-color: {ThemeManager.COLORS["surface"]};
                border-top: 1px solid {ThemeManager.COLORS["border"]};
            }}
        """)
        input_layout = QHBoxLayout(input_area)
        input_layout.setContentsMargins(16, 12, 16, 12)
        input_layout.setSpacing(0)
        input_layout.setAlignment(Qt.AlignVCenter)

        # 输入框容器 - 圆角卡片包裹
        input_container = QFrame()
        input_container.setStyleSheet(f"""
            QFrame {{
                background-color: {ThemeManager.COLORS["background"]};
                border: 1px solid {ThemeManager.COLORS["border"]};
                border-radius: 12px;
            }}
            QFrame:focus-within {{
                border: 1px solid {ThemeManager.COLORS["accent"]};
            }}
        """)
        container_layout = QHBoxLayout(input_container)
        container_layout.setContentsMargins(4, 4, 4, 4)
        container_layout.setSpacing(4)
        container_layout.setAlignment(Qt.AlignVCenter)

        self.input_edit = QTextEdit()
        self.input_edit.setPlaceholderText("输入消息，Enter 发送，Shift+Enter 换行...")
        self.input_edit.setMinimumHeight(40)
        self.input_edit.setMaximumHeight(90)
        self.input_edit.setStyleSheet(f"""
            QTextEdit {{
                background-color: transparent;
                color: {ThemeManager.COLORS["text"]};
                border: none;
                padding: 8px 12px;
                selection-background-color: {ThemeManager.COLORS["selection"]};
                selection-color: {ThemeManager.COLORS["white"]};
                font-size: {ThemeManager.FONTS["size_small"]};
            }}
            QTextEdit:focus {{
                border: none;
                outline: none;
            }}
        """)
        self.input_edit.setFont(QFont("", 9))
        self.input_edit.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.input_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.input_edit.installEventFilter(self)
        container_layout.addWidget(self.input_edit, 1)

        # 发送按钮 - 圆形图标按钮
        self.send_btn = QPushButton()
        self.send_btn.setFixedSize(36, 36)
        self.send_btn.setCursor(Qt.PointingHandCursor)
        self.send_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {ThemeManager.COLORS["accent"]};
                color: {ThemeManager.COLORS["white"]};
                border: none;
                border-radius: 18px;
                padding: 0px;
            }}
            QPushButton:hover {{
                background-color: {ThemeManager.COLORS["accent_hover"]};
            }}
            QPushButton:pressed {{
                background-color: {ThemeManager.COLORS["accent_pressed"]};
            }}
            QPushButton:disabled {{
                background-color: {ThemeManager.COLORS["surface_lighter"]};
                color: {ThemeManager.COLORS["text_disabled"]};
            }}
        """)
        # 绘制发送图标 (SVG arrow)
        self.send_btn.setIcon(self._create_send_icon())
        self.send_btn.setIconSize(QSize(16, 16))
        self.send_btn.clicked.connect(self._send_message)
        container_layout.addWidget(self.send_btn, alignment=Qt.AlignBottom)

        input_layout.addWidget(input_container, 1)
        layout.addWidget(input_area)

        self._add_welcome_message()

    def _add_welcome_message(self):
        """添加欢迎消息"""
        welcome = (
            "你好！我是 Mozikit AI 助手，可以帮你组织工作流节点。\n\n"
            "例如：\n"
            "- 添加一个 SQLite 连接节点\n"
            "- 添加数据库查询流程（自动添加多个节点并连接）\n"
            "- 查看当前工作流信息\n"
            "- 自动排列节点"
        )
        self._append_ai_message(welcome)

    def _init_chat_service(self):
        """初始化聊天服务"""
        ai_settings = self.config_manager.get_ai_settings()
        model = ai_settings.get("model", "")

        if model:
            max_rounds = int(ai_settings.get("max_history_rounds", 0) or 0) or None
            self.chat_service = AIChatService(
                ai_settings, max_history_rounds=max_rounds
            )
            self.model_label.setText(model)
        else:
            self.chat_service = None
            self.model_label.setText("未配置")

    def set_workflow_context(self, workflow_tab):
        """设置当前工作流上下文"""
        self.workflow_tab = workflow_tab
        if workflow_tab:
            self.tool_executor = AIToolExecutor(workflow_tab)
        else:
            self.tool_executor = None

    def refresh_settings(self):
        """刷新 AI 配置"""
        self._init_chat_service()

    def _send_message(self):
        """发送消息"""
        text = self.input_edit.toPlainText().strip()
        if not text:
            return

        if not self.chat_service:
            self._append_ai_message(
                "AI 未配置，请先在设置中配置 AI 接口（base_url、api_key、model）。"
            )
            return

        if not self.workflow_tab:
            self._append_ai_message("请先打开或创建一个工作流。")
            return

        self.input_edit.clear()
        self._append_user_message(text)

        # 显示加载指示器
        self._show_loading()

        self.send_btn.setEnabled(False)
        self.send_btn.setText("...")
        self.input_edit.setEnabled(False)

        workflow_context = AIChatContextBuilder.build_context(self.workflow_tab)

        # 如果之前有正在运行的线程，先等待它完成
        if self._chat_worker is not None and self._chat_worker.isRunning():
            self._chat_worker.wait(2000)  # 最多等待2秒
            self._chat_worker = None

        self._chat_worker = ChatWorker(
            self.chat_service, text, workflow_context, self.tool_executor
        )
        self._chat_worker.finished.connect(self._on_chat_finished)
        self._chat_worker.error.connect(self._on_chat_error)
        self._chat_worker.stream_chunk.connect(self._on_stream_chunk)
        self._streaming_bubble = None
        self._chat_worker.start()

    def _show_loading(self):
        """显示加载指示器"""
        self._loading_indicator = LoadingIndicator()
        self.message_layout.insertWidget(
            self.message_layout.count() - 1, self._loading_indicator
        )
        self._scroll_to_bottom()

    def _hide_loading(self):
        """隐藏加载指示器"""
        if self._loading_indicator:
            self._loading_indicator.stop_animation()
            self._loading_indicator.hide()
            self._loading_indicator.deleteLater()
            self._loading_indicator = None

    @Slot(dict)
    def _on_chat_finished(self, result: dict):
        """聊天完成"""
        self._hide_loading()
        self.send_btn.setEnabled(True)
        self.send_btn.setText("发送")
        self.input_edit.setEnabled(True)
        if self._chat_worker is not None:
            self._chat_worker.deleteLater()
        self._chat_worker = None

        reply = result.get("reply", "")
        tool_results = result.get("tool_results", [])

        for tr in tool_results:
            card = ToolResultCard(tr["tool_name"], tr["arguments"], tr["result"])
            self.message_layout.insertWidget(
                self.message_layout.count() - 1, card, alignment=Qt.AlignTop
            )

        if self._streaming_bubble:
            bubble = self._streaming_bubble
            self._streaming_bubble = None
            if reply and bubble._content_browser.toPlainText() != reply:
                bubble.setText(reply)
            elif not reply:
                idx = self.message_layout.indexOf(bubble)
                if idx >= 0:
                    self.message_layout.removeWidget(bubble)
                    bubble.deleteLater()
        elif reply:
            self._append_ai_message(reply)

    @Slot(str)
    def _on_chat_error(self, error_msg: str):
        """聊天错误"""
        self._hide_loading()
        self.send_btn.setEnabled(True)
        self.send_btn.setText("发送")
        self.input_edit.setEnabled(True)
        if self._chat_worker is not None:
            self._chat_worker.deleteLater()
        self._chat_worker = None
        self._streaming_bubble = None
        self._append_ai_message(f"错误: {error_msg}")

    @Slot(str)
    def _on_stream_chunk(self, chunk_text: str):
        """流式文本块到达"""
        logger.debug("_on_stream_chunk called with chunk: %r", chunk_text)
        if self._streaming_bubble is None:
            self._hide_loading()
            bubble = MessageBubble(chunk_text, is_user=False)
            # 设置气泡宽度对齐为顶部，使其水平扩展填充可用空间
            self.message_layout.insertWidget(
                self.message_layout.count() - 1, bubble, alignment=Qt.AlignTop
            )
            # 强制更新气泡宽度以匹配容器
            QTimer.singleShot(0, lambda: self._update_bubble_width(bubble))
            self._streaming_bubble = bubble
        else:
            self._streaming_bubble.setText(
                self._streaming_bubble._raw_text + chunk_text
            )
        self._scroll_to_bottom()

    def _append_user_message(self, text: str):
        """追加用户消息"""
        bubble = MessageBubble(text, is_user=True)
        # 设置气泡宽度对齐为顶部，使其水平扩展填充可用空间
        self.message_layout.insertWidget(
            self.message_layout.count() - 1, bubble, alignment=Qt.AlignTop
        )
        self._scroll_to_bottom()

    def _append_ai_message(self, text: str):
        """追加 AI 消息"""
        bubble = MessageBubble(text, is_user=False)
        # 设置气泡宽度对齐为顶部，使其水平扩展填充可用空间
        self.message_layout.insertWidget(
            self.message_layout.count() - 1, bubble, alignment=Qt.AlignTop
        )
        # 强制更新气泡宽度以匹配容器
        QTimer.singleShot(0, lambda: self._update_bubble_width(bubble))
        self._scroll_to_bottom()

    def _update_bubble_width(self, bubble):
        """更新消息气泡宽度以匹配容器"""
        if not bubble or not self.message_container:
            return
        # 获取可用宽度
        container_width = self.message_container.width()
        if container_width > 0:
            available_width = max(200, container_width - 16)  # 减去边距
            if hasattr(bubble, "_content_browser"):
                bubble._content_browser.setMinimumWidth(available_width - 60)

    def _scroll_to_bottom(self):
        """滚动到底部"""
        QApplication.processEvents()
        scrollbar = self.scroll_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _clear_chat(self):
        """清空对话"""
        while self.message_layout.count() > 1:
            item = self.message_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if self.chat_service:
            self.chat_service.clear_history()

        self._add_welcome_message()

    def _export_chat(self):
        """导出对话历史到文件"""
        if not self.chat_service:
            return

        history_text = self.chat_service.export_history()
        file_path, _ = QFileDialog.getSaveFileName(
            self, "导出对话历史", "chat_history.txt", "文本文件 (*.txt);;所有文件 (*)"
        )
        if file_path:
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(history_text)
            except Exception as exc:
                logger.warning("导出对话历史失败: %s", exc)

    def _create_send_icon(self):
        """创建发送图标"""
        from PySide6.QtCore import QPoint

        pixmap = QPixmap(18, 18)
        pixmap.fill(QColor("transparent"))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(ThemeManager.COLORS["white"]))
        # 绘制纸飞机图标
        points = [
            QPoint(3, 9),
            QPoint(14, 4),
            QPoint(9, 9),
            QPoint(14, 14),
        ]
        painter.drawPolygon(points)
        painter.end()
        return QIcon(pixmap)

    def eventFilter(self, watched, event):
        """事件过滤器：处理输入框键盘事件"""
        if watched == self.input_edit and event.type() == event.Type.KeyPress:
            key_event = event
            if key_event.key() == Qt.Key_Return:
                if not key_event.modifiers() & Qt.ShiftModifier:
                    self._send_message()
                    return True
                else:
                    self.input_edit.insertPlainText("\n")
                    return True
        return super().eventFilter(watched, event)
