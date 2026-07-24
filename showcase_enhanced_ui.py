#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Mozikit UI 优化展示脚本
此脚本展示了前端UI优化的各个方面
"""

import sys
from pathlib import Path

# 添加源代码路径
src_path = Path(__file__).parent / "src"
sys.path.insert(0, str(src_path))

from PySide6.QtWidgets import QApplication, QMainWindow, QLabel, QVBoxLayout, QWidget
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from src.core.theme_manager import ThemeManager


class OptimizationShowcase(QMainWindow):
    """UI优化展示窗口"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Mozikit UI 优化展示")
        self.setGeometry(100, 100, 800, 600)
        
        self._setup_ui()
    
    def _setup_ui(self):
        """设置展示UI"""
        # 中央widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        layout = QVBoxLayout(central_widget)
        
        # 标题
        title = QLabel("🎉 Mozikit 前端优化成果展示")
        title.setAlignment(Qt.AlignCenter)
        title_font = QFont("Segoe UI", 20, QFont.Bold)
        title.setFont(title_font)
        title.setStyleSheet(f"color: {ThemeManager.COLORS['accent']}; margin: 20px;")
        layout.addWidget(title)
        
        # 优化项目列表
        optimizations = [
            "✨ 主题系统增强",
            "  - 现代化深色主题配色",
            "  - 丰富的节点类型颜色映射",
            "  - 优化的渐变和阴影效果",
            "",
            "✨ 节点图形改进",
            "  - 改进的发光和阴影效果",
            "  - 更好的视觉层次和反馈",
            "  - 流畅的动画过渡",
            "",
            "✨ 画布视觉效果增强",
            "  - 现代化网格背景",
            "  - 渐变背景和主网格线",
            "  - 优化的渲染性能",
            "",
            "✨ 工具栏和布局优化", 
            "  - 改进的按钮样式和间距",
            "  - 文字标签显示在图标下方",
            "  - 统一的视觉风格",
            "",
            "✨ 交互动效增强",
            "  - 流畅的悬停和点击反馈",
            "  - 现代化的圆角和阴影",
            "  - 一致的动画时长",
        ]
        
        for item in optimizations:
            label = QLabel(item)
            if item.startswith("✨"):
                label.setStyleSheet(f"""
                    color: {ThemeManager.COLORS['text']}; 
                    font-size: 16px; 
                    font-weight: bold;
                    margin-top: 20px;
                    margin-bottom: 10px;
                """)
            else:
                label.setStyleSheet(f"""
                    color: {ThemeManager.COLORS['text_secondary']}; 
                    font-size: 14px;
                    margin-left: 20px;
                """)
            layout.addWidget(label)
        
        # 颜色展示
        colors_title = QLabel("\n🎨 主要配色展示")
        colors_title.setStyleSheet(f"""
            color: {ThemeManager.COLORS['text']}; 
            font-size: 16px; 
            font-weight: bold;
            margin-top: 30px;
        """)
        layout.addWidget(colors_title)
        
        colors_layout = QVBoxLayout()
        main_colors = [
            ("主题强调色", ThemeManager.COLORS['accent']),
            ("成功状态", ThemeManager.COLORS['success']),
            ("警告状态", ThemeManager.COLORS['warning']),
            ("错误状态", ThemeManager.COLORS['error']),
            ("背景色", ThemeManager.COLORS['background']),
            ("表面色", ThemeManager.COLORS['surface']),
        ]
        
        for name, color in main_colors:
            color_label = QLabel(f"■ {name}: {color}")
            color_label.setStyleSheet(f"""
                color: {color}; 
                font-family: monospace;
                font-size: 14px;
                padding: 8px;
                background: {ThemeManager.COLORS['surface']};
                border-radius: 6px;
                margin: 4px 0;
            """)
            colors_layout.addWidget(color_label)
        
        layout.addLayout(colors_layout)
        
        # 底部说明
        footer = QLabel("\n💡 这些优化提升了用户体验、视觉吸引力和操作流畅度")
        footer.setAlignment(Qt.AlignCenter)
        footer.setStyleSheet(f"""
            color: {ThemeManager.COLORS['text_muted']}; 
            font-style: italic;
            margin-top: 30px;
        """)
        layout.addWidget(footer)
        
        # 设置整体布局样式
        central_widget.setStyleSheet(f"""
            background: {ThemeManager.COLORS['background']};
        """)


def main():
    """主函数"""
    app = QApplication(sys.argv)
    
    # 应用主题
    ThemeManager.apply_theme(app)
    
    # 创建展示窗口
    showcase = OptimizationShowcase()
    showcase.show()
    
    print("🎉 Mozikit UI 优化展示启动成功！")
    print("\n优化内容包括：")
    print("  • 主题系统增强")
    print("  • 节点图形改进") 
    print("  • 画布视觉效果")
    print("  • 工具栏和布局优化")
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()