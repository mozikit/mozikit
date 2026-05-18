#!/usr/bin/env python3
"""
测试自定义 UV 路径和镜像功能
"""
import sys
import os

# 添加项目根目录到路径
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from core.uv_manager import UVManager

def test_custom_settings():
    """测试自定义设置功能"""
    print("=== 测试自定义 UV 设置 ===\n")
    
    # 创建 UVManager 实例
    uv_manager = UVManager()
    
    # 测试当前配置
    print("1. 当前配置:")
    print(f"   UV 路径: {uv_manager.get_preferred_uv_path()}")
    print(f"   镜像地址: {uv_manager.get_current_mirror()}")
    
    # 测试镜像设置
    print("\n2. 测试镜像设置:")
    test_mirror = "https://pypi.tuna.tsinghua.edu.cn/simple"
    
    if uv_manager.set_custom_mirror(test_mirror):
        print(f"   [OK] 镜像设置成功: {test_mirror}")
        print(f"   [OK] 当前镜像: {uv_manager.get_current_mirror()}")
    else:
        print(f"   [ERROR] 镜像设置失败")
    
    # 检查配置文件
    config_file = os.path.join(os.path.expanduser("~"), ".uv", "uv.toml")
    print(f"\n3. 配置文件检查:")
    print(f"   配置文件路径: {config_file}")
    print(f"   配置文件存在: {os.path.exists(config_file)}")
    
    if os.path.exists(config_file):
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                content = f.read()
            print(f"   配置文件内容:\n{content}")
        except Exception as e:
            print(f"   读取配置文件失败: {e}")
    
    # 检查环境变量
    print(f"\n4. 环境变量检查:")
    uv_index_url = os.environ.get("UV_INDEX_URL", "")
    print(f"   UV_INDEX_URL: {uv_index_url}")
    
    # 测试多个路径查找
    print(f"\n5. UV 路径查找测试:")
    uv_paths = uv_manager.find_uv_installations()
    print(f"   找到 {len(uv_paths)} 个 UV 安装:")
    for i, path in enumerate(uv_paths, 1):
        print(f"   {i}. {path}")
    
    print("\n=== 测试完成 ===")

if __name__ == "__main__":
    test_custom_settings()