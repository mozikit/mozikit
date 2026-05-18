"""
测试暗色和亮色主题
运行此脚本查看设置对话框在不同主题下的效果
"""
import sys
from PySide6.QtWidgets import QApplication, QPushButton, QVBoxLayout, QWidget
from PySide6.QtGui import QPalette, QColor
from src.dialogs.settings_dialog import SettingsDialog


class ThemeTestWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("主题测试")
        self.setGeometry(100, 100, 300, 150)
        
        layout = QVBoxLayout()
        
        # Light theme button
        light_btn = QPushButton("测试亮色主题")
        light_btn.clicked.connect(self.test_light_theme)
        layout.addWidget(light_btn)
        
        # Dark theme button
        dark_btn = QPushButton("测试暗色主题")
        dark_btn.clicked.connect(self.test_dark_theme)
        layout.addWidget(dark_btn)
        
        self.setLayout(layout)
    
    def test_light_theme(self):
        """Test light theme"""
        app = QApplication.instance()
        app.setStyle("Fusion")
        
        # Set light palette
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor(240, 240, 240))
        palette.setColor(QPalette.WindowText, QColor(0, 0, 0))
        palette.setColor(QPalette.Base, QColor(255, 255, 255))
        palette.setColor(QPalette.AlternateBase, QColor(245, 245, 245))
        palette.setColor(QPalette.Text, QColor(0, 0, 0))
        palette.setColor(QPalette.Button, QColor(240, 240, 240))
        palette.setColor(QPalette.ButtonText, QColor(0, 0, 0))
        app.setPalette(palette)
        
        # Open settings dialog
        dialog = SettingsDialog(self)
        dialog.exec()
    
    def test_dark_theme(self):
        """Test dark theme"""
        app = QApplication.instance()
        app.setStyle("Fusion")
        
        # Set dark palette
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor(53, 53, 53))
        palette.setColor(QPalette.WindowText, QColor(255, 255, 255))
        palette.setColor(QPalette.Base, QColor(35, 35, 35))
        palette.setColor(QPalette.AlternateBase, QColor(53, 53, 53))
        palette.setColor(QPalette.Text, QColor(255, 255, 255))
        palette.setColor(QPalette.Button, QColor(53, 53, 53))
        palette.setColor(QPalette.ButtonText, QColor(255, 255, 255))
        palette.setColor(QPalette.BrightText, QColor(255, 0, 0))
        palette.setColor(QPalette.Link, QColor(42, 130, 218))
        palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
        palette.setColor(QPalette.HighlightedText, QColor(35, 35, 35))
        app.setPalette(palette)
        
        # Open settings dialog
        dialog = SettingsDialog(self)
        dialog.exec()


if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = ThemeTestWindow()
    window.show()
    sys.exit(app.exec())
