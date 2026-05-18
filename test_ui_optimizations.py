#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
UI优化功能测试脚本
验证前端优化的核心功能
"""

import sys
from pathlib import Path

# 添加源代码路径
src_path = Path(__file__).parent / "src"
sys.path.insert(0, str(src_path))

from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QPushButton, QLabel
from PySide6.QtCore import Qt

from src.core.theme_manager import ThemeManager


def test_theme_system():
    """测试主题系统"""
    print("\n🎨 测试主题系统...")
    
    # 验证颜色配置
    colors = [
        'background', 'surface', 'accent', 'success', 
        'warning', 'error', 'text', 'text_secondary'
    ]
    
    for color in colors:
        if color in ThemeManager.COLORS:
            print(f"  ✓ {color}: {ThemeManager.COLORS[color]}")
        else:
            print(f"  ✗ {color}: 缺失")
    
    # 验证节点颜色
    node_colors = ['variable_assign', 'variable_calc', 'sqlite_connect', 'custom']
    print(f"\n  节点类型颜色测试:")
    for node_type in node_colors:
        if node_type in ThemeManager.NODE_COLORS:
            colors = ThemeManager.NODE_COLORS[node_type]
            print(f"  ✓ {node_type}: normal={colors['normal']}, glow={colors['glow']}")
    
    # 验证样式获取
    try:
        button_style = ThemeManager.get_button_style("primary")
        print("  ✓ 按钮样式获取成功")
        
        dock_style = ThemeManager.get_dock_widget_style()
        print("  ✓ Dock样式获取成功")
        
        tab_style = ThemeManager.get_tab_widget_style()
        print("  ✓ 标签页样式获取成功")
        
    except Exception as e:
        print(f"  ✗ 样式获取失败: {e}")


def test_optimization_features():
    """测试优化特性"""
    print("\n🚀 测试优化特性...")
    
    # 检查新增配置
    features = {
        "阴影配置": "SHADOWS" in dir(ThemeManager),
        "节点发光颜色": all("glow" in colors for colors in ThemeManager.NODE_COLORS.values()),
        "节点阴影颜色": all("shadow" in colors for colors in ThemeManager.NODE_COLORS.values()),
    }
    
    for feature, available in features.items():
        status = "✓" if available else "✗"
        print(f"  {status} {feature}")


class TestWindow(QWidget):
    """测试窗口"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("UI优化效果测试")
        self.setGeometry(100, 100, 600, 400)
        self._setup_ui()
    
    def _setup_ui(self):
        """设置测试UI"""
        layout = QVBoxLayout(self)
        
        # 标题
        title = QLabel("LocalFlow UI优化测试")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(f"""
            font-size: 18px; 
            font-weight: bold; 
            color: {ThemeManager.COLORS['accent']};
            margin: 20px;
        """)
        layout.addWidget(title)
        
        # 测试按钮
        btn_primary = QPushButton("主要按钮")
        btn_primary.setStyleSheet(ThemeManager.get_button_style("primary"))
        btn_primary.setFixedWidth(150)
        
        btn_secondary = QPushButton("次要按钮") 
        btn_secondary.setStyleSheet(ThemeManager.get_button_style("secondary"))
        btn_secondary.setFixedWidth(150)
        
        btn_danger = QPushButton("危险操作")
        btn_danger.setStyleSheet(ThemeManager.get_button_style("danger"))
        btn_danger.setFixedWidth(150)
        
        for btn in [btn_primary, btn_secondary, btn_danger]:
            layout.addWidget(btn, alignment=Qt.AlignCenter)
            btn.setFixedHeight(40)
        
        # 状态显示
        status_label = QLabel("✅ 主题系统加载成功")
        status_label.setAlignment(Qt.AlignCenter)
        status_label.setStyleSheet(f"""
            color: {ThemeManager.COLORS['success']};
            font-size: 14px;
            margin: 20px;
        """)
        layout.addWidget(status_label)
        
        # 底部说明
        desc = QLabel("这是一个优化后的UI测试窗口，展示了按钮样式和主题效果")
        desc.setAlignment(Qt.AlignCenter)
        desc.setStyleSheet(f"""
            color: {ThemeManager.COLORS['text_secondary']};
            font-style: italic;
        """)
        layout.addWidget(desc)
        
        # 应用窗口样式
        self.setStyleSheet(f"""
            background-color: {ThemeManager.COLORS['background']};
        """)


def main():
    """主测试函数"""
    print("🧪 LocalFlow UI优化功能测试")
    print("=" * 40)
    
    # 测试主题系统
    test_theme_system()
    
    # 测试优化特性  
    test_optimization_features()
    
    print("\n🎯 启动UI演示...")
    
    # 创建应用和窗口
    app = QApplication(sys.argv)
    ThemeManager.apply_theme(app)
    
    window = TestWindow()
    window.show()
    
    print("\n✅ UI测试窗口已启动")
    print("关闭窗口结束测试")
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()