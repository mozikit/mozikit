#!/usr/bin/env python3
"""
测试设置界面的自定义功能
"""
import sys
import os

# 添加项目根目录到路径
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from PySide6.QtWidgets import QApplication
from dialogs.settings_dialog import SettingsDialog

def test_settings_ui():
    """测试设置界面"""
    app = QApplication(sys.argv)
    
    print("=== 测试设置界面 ===")
    print("功能说明:")
    print("1. UV 路径下拉框：")
    print("   - 显示所有检测到的 UV 安装")
    print("   - '自定义路径...' 选项允许手动输入")
    print("2. 镜像地址下拉框：")
    print("   - 预设常用镜像（清华、阿里云、中科大等）")
    print("   - 支持编辑和自定义镜像")
    print("3. 配置会自动保存到 ~/.uv/uv.toml")
    print()
    
    dialog = SettingsDialog()
    
    # 显示当前检测到的信息
    print(f"检测到的 UV 路径数量: {len(dialog.uv_paths)}")
    print(f"当前 UV 路径: {dialog.uv_path}")
    print(f"当前镜像: {dialog.uv_mirror}")
    print()
    
    # 显示对话框
    dialog.show()
    
    print("对话框已显示，请测试以下功能:")
    print("- 点击 UV 路径下拉框，选择'自定义路径...'")
    print("- 点击镜像地址下拉框，选择预设镜像或'自定义镜像...'")
    print("- 点击'重新检测'按钮刷新检测")
    print()
    print("关闭对话框以结束测试")
    
    # 运行应用程序
    sys.exit(app.exec())

if __name__ == "__main__":
    test_settings_ui()