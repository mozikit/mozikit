#!/usr/bin/env python3
"""
测试设置对话框修复后的功能
"""
import sys
import os

# 添加 src 目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from PySide6.QtWidgets import QApplication
from dialogs.settings_dialog import SettingsDialog

def test_settings_fix():
    """测试设置界面修复"""
    app = QApplication(sys.argv)
    
    print("=== 测试设置对话框修复 ===")
    print("修复内容:")
    print("1. 修复 QInputDialog.getText() 不支持 placeholderText 参数的问题")
    print("2. 改进镜像地址变更处理逻辑")
    print("3. 简化镜像配置保存逻辑")
    print()
    
    dialog = SettingsDialog()
    
    # 显示当前配置
    print(f"当前 UV 路径: {dialog.uv_path}")
    print(f"当前镜像: {dialog.uv_mirror}")
    print()
    
    # 模拟测试镜像选择
    print("测试镜像选择功能:")
    print("- 选择预设镜像: https://pypi.tuna.tsinghua.edu.cn/simple")
    dialog.mirror_combo.setCurrentText("https://pypi.tuna.tsinghua.edu.cn/simple")
    dialog._on_mirror_changed("https://pypi.tuna.tsinghua.edu.cn/simple")
    print(f"设置后的镜像: {dialog.uv_mirror}")
    
    print("- 选择默认镜像")
    dialog.mirror_combo.setCurrentText("默认镜像")
    dialog._on_mirror_changed("默认镜像")
    print(f"设置后的镜像: {dialog.uv_mirror}")
    
    print()
    print("显示设置界面进行手动测试...")
    print("请尝试:")
    print("1. 选择不同的预设镜像")
    print("2. 选择'自定义镜像...'测试自定义输入")
    print("3. 选择'默认镜像'清除配置")
    
    # 显示对话框
    dialog.show()
    
    print("\n关闭对话框以结束测试")
    
    # 运行应用程序
    sys.exit(app.exec())

if __name__ == "__main__":
    test_settings_fix()