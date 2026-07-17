#!/usr/bin/env python3
"""
测试 UV 设置对话框功能
"""
import sys
import os

import pytest

pytest.importorskip("PySide6")

# 添加项目根目录到路径
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from PySide6.QtWidgets import QApplication
from dialogs.settings_dialog import SettingsDialog

@pytest.mark.qt
@pytest.mark.skip(reason="手动测试——打开对话框等待用户交互，不适合 CI")
def test_uv_settings():
    """测试 UV 设置对话框"""
    app = QApplication(sys.argv)
    
    dialog = SettingsDialog()
    
    # 显示检测到的 uv 信息
    print("=== UV 设置对话框测试 ===")
    print(f"检测到的 UV 路径数量: {len(dialog.uv_paths)}")
    if dialog.uv_paths:
        print("找到的 UV 路径:")
        for i, path in enumerate(dialog.uv_paths, 1):
            print(f"  {i}. {path}")
    
    print(f"当前选择的 UV 路径: {dialog.uv_path}")
    try:
        print(f"状态文本: {dialog.status_label.text()}")
    except UnicodeEncodeError:
        print("状态文本: [包含特殊字符，无法显示]")
    
    # 显示对话框（用于手动测试）
    dialog.show()
    
    print("\n对话框已显示，请手动测试 uv 路径选择功能")
    print("关闭对话框以结束测试")
    
    # 运行应用程序
    sys.exit(app.exec())

if __name__ == "__main__":
    test_uv_settings()