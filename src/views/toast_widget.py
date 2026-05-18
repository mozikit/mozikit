from PySide6.QtWidgets import QWidget, QLabel, QHBoxLayout, QGraphicsDropShadowEffect
from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QPoint
from PySide6.QtGui import QColor

from src.core.theme_manager import ThemeManager


class ToastWidget(QWidget):
    """气泡提示组件

    用于替代 QMessageBox.information 的成功提示，自动消失，无需用户点击。
    支持成功、警告、错误、信息四种类型，默认停留 4 秒后自动淡出。
    """

    _instance = None
    _active_toasts = []

    def __init__(self, parent, message: str, toast_type: str = "success", duration: int = 4000):
        super().__init__(parent)
        self._duration = duration
        self._setup_ui(message, toast_type)
        self._setup_animation()

    def _setup_ui(self, message: str, toast_type: str):
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose)

        colors = {
            "success": (ThemeManager.COLORS["success"], ThemeManager.COLORS["success_dark"]),
            "warning": (ThemeManager.COLORS["warning"], ThemeManager.COLORS["warning_dark"]),
            "error": (ThemeManager.COLORS["error"], ThemeManager.COLORS["error_dark"]),
            "info": (ThemeManager.COLORS["info"], ThemeManager.COLORS["accent_dark"]),
        }
        bg_color, border_color = colors.get(toast_type, colors["success"])

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(8)

        icon_map = {
            "success": "✓",
            "warning": "⚠",
            "error": "✗",
            "info": "ℹ",
        }
        icon_label = QLabel(icon_map.get(toast_type, "✓"))
        icon_label.setStyleSheet(f"color: {bg_color}; font-size: 14px; font-weight: bold;")
        layout.addWidget(icon_label)

        self.msg_label = QLabel(message)
        self.msg_label.setStyleSheet(f"""
            color: {ThemeManager.COLORS['text']};
            font-size: 13px;
            font-weight: 500;
        """)
        self.msg_label.setWordWrap(True)
        layout.addWidget(self.msg_label)

        self.setStyleSheet(f"""
            ToastWidget {{
                background-color: {ThemeManager.COLORS['surface']};
                border: 1px solid {border_color};
                border-radius: 10px;
                border-left: 4px solid {bg_color};
            }}
        """)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setColor(QColor(0, 0, 0, 120))
        shadow.setOffset(0, 4)
        self.setGraphicsEffect(shadow)

        self.adjustSize()

    def _setup_animation(self):
        self._opacity_anim = QPropertyAnimation(self, b"windowOpacity")
        self._opacity_anim.setDuration(300)
        self._opacity_anim.setEasingCurve(QEasingCurve.InOutQuad)

    def show_toast(self):
        self.setWindowOpacity(0.0)
        super().show()
        self.raise_()

        parent = self.parent()
        if parent:
            # 找到最顶层窗口（QMainWindow）作为参照
            top_window = parent
            while top_window.parent():
                top_window = top_window.parent()

            # 使用顶层窗口的 geometry（屏幕坐标）进行居中计算
            window_geo = top_window.geometry()
            x = window_geo.center().x() - self.width() // 2
            y = window_geo.top() + 40
            self.move(x, y)

        self._opacity_anim.setStartValue(0.0)
        self._opacity_anim.setEndValue(1.0)
        self._opacity_anim.start()

        QTimer.singleShot(self._duration, self._start_fade_out)

    def _start_fade_out(self):
        self._opacity_anim.setStartValue(1.0)
        self._opacity_anim.setEndValue(0.0)
        self._opacity_anim.finished.connect(self.close)
        self._opacity_anim.start()

    @classmethod
    def show(cls, parent, message: str, toast_type: str = "success", duration: int = 4000):
        """显示气泡提示

        Args:
            parent: 父窗口
            message: 提示消息
            toast_type: 类型 - success/warning/error/info
            duration: 显示时长（毫秒），默认 4000
        """
        toast = cls(parent, message, toast_type, duration)
        toast.show_toast()
        cls._active_toasts.append(toast)

        def on_destroyed():
            if toast in cls._active_toasts:
                cls._active_toasts.remove(toast)

        toast.destroyed.connect(on_destroyed)
