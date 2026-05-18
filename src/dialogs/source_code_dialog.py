"""
源代码编辑弹窗
用于查看、复制、编辑、重置和保存节点源代码
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QVBoxLayout,
    QApplication,
)

from src.core.theme_manager import ThemeManager
from src.core.log_manager import get_logger

logger = get_logger("source_code_dialog")


class SourceCodeDialog(QDialog):
    """源代码编辑器弹窗"""

    def __init__(
        self,
        source_code: str = "",
        node_type: str = "",
        node_name: str = "",
        is_playwright: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self._original_source = source_code or ""
        self._current_source = source_code or ""
        self._node_type = node_type
        self._node_name = node_name
        self._is_playwright = is_playwright
        self._is_modified = False
        
        title = f"编辑 Playwright 脚本 - {node_name}" if is_playwright else f"源代码 - {node_name}"
        self.setWindowTitle(title)
        self.setMinimumSize(800, 600)
        self.resize(900, 650)
        
        self._setup_ui()
        self._apply_style()
        self.editor.setPlainText(self._current_source)
        self._update_status()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        # 顶部信息栏
        info_layout = QHBoxLayout()
        
        self.status_label = QLabel("")
        self.status_label.setStyleSheet(f"color: {ThemeManager.COLORS['text_secondary']};")
        info_layout.addWidget(self.status_label)
        
        info_layout.addStretch()
        
        # 节点类型标签
        type_label = QLabel(f"类型: {self._node_type}")
        type_label.setStyleSheet(f"color: {ThemeManager.COLORS['text_secondary']}; font-size: 9pt;")
        info_layout.addWidget(type_label)
        
        layout.addLayout(info_layout)

        # 代码编辑器
        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText("源代码将显示在这里...")
        font = QFont("Consolas", 10)
        self.editor.setFont(font)
        self.editor.textChanged.connect(self._on_text_changed)
        layout.addWidget(self.editor)

        # 底部按钮栏
        button_layout = QHBoxLayout()
        button_layout.setSpacing(8)
        
        # 左侧：复制和重置按钮
        self.copy_btn = QPushButton("📋 复制")
        self.copy_btn.setStyleSheet(ThemeManager.get_button_style("secondary"))
        self.copy_btn.clicked.connect(self._copy_source)
        button_layout.addWidget(self.copy_btn)
        
        self.reset_btn = QPushButton("↩️ 重置")
        self.reset_btn.setStyleSheet(ThemeManager.get_button_style("secondary"))
        self.reset_btn.clicked.connect(self._reset_source)
        button_layout.addWidget(self.reset_btn)
        
        button_layout.addStretch()
        
        # 右侧：取消和保存按钮
        cancel_btn = QPushButton("取消")
        cancel_btn.setStyleSheet(ThemeManager.get_button_style("secondary"))
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        
        self.save_btn = QPushButton("💾 保存")
        self.save_btn.setStyleSheet(ThemeManager.get_button_style("primary"))
        self.save_btn.clicked.connect(self._on_save)
        self.save_btn.setEnabled(False)  # 初始禁用，有修改时才启用
        button_layout.addWidget(self.save_btn)
        
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
            QPlainTextEdit {{
                background-color: {ThemeManager.COLORS['background']};
                color: {ThemeManager.COLORS['text']};
                border: 1px solid {ThemeManager.COLORS['border']};
                border-radius: 4px;
                padding: 12px;
            }}
            QPlainTextEdit:focus {{
                border: 2px solid {ThemeManager.COLORS['accent']};
            }}
            """
        )

    def _on_text_changed(self):
        """文本变化时更新状态"""
        current_text = self.editor.toPlainText()
        self._is_modified = current_text != self._original_source
        self._current_source = current_text
        self._update_status()
        self.save_btn.setEnabled(self._is_modified)

    def _update_status(self):
        """更新状态标签"""
        if self._is_modified:
            self.status_label.setText("● 已修改")
            self.status_label.setStyleSheet(f"color: {ThemeManager.COLORS['accent']};")
        else:
            self.status_label.setText("未修改")
            self.status_label.setStyleSheet(f"color: {ThemeManager.COLORS['text_secondary']};")

    def _copy_source(self):
        """复制源代码到剪贴板"""
        source_code = self.editor.toPlainText()
        QApplication.clipboard().setText(source_code)
        logger.info("源代码已复制到剪贴板")
        
        # 临时改变按钮文字提示用户
        original_text = self.copy_btn.text()
        self.copy_btn.setText("✓ 已复制")
        from PySide6.QtCore import QTimer
        QTimer.singleShot(1500, lambda: self.copy_btn.setText(original_text))

    def _reset_source(self):
        """重置源代码到原始版本"""
        if not self._is_modified:
            return
            
        reply = QMessageBox.question(
            self,
            "确认重置",
            "确定要重置源代码到原始版本吗？\n\n您的修改将会丢失。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.editor.setPlainText(self._original_source)
            self._is_modified = False
            self._current_source = self._original_source
            self._update_status()
            self.save_btn.setEnabled(False)
            logger.info("源代码已重置")

    def _on_save(self):
        """保存源代码"""
        self._current_source = self.editor.toPlainText()
        self.accept()

    def get_source_code(self) -> str:
        """获取编辑后的源代码"""
        return self._current_source

    def is_modified(self) -> bool:
        """返回源代码是否被修改过"""
        return self._is_modified
