#!/usr/bin/env python3
"""
测试 UV 检测功能
"""
import sys
import os

# 添加项目根目录到路径
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from core.uv_manager import UVManager

def test_uv_detection():
    """测试 uv 检测功能"""
    print("=== UV 检测功能测试 ===\n")
    
    # 创建 UVManager 实例
    uv_manager = UVManager()
    
    # 测试基本检测
    print("1. 基本检测:")
    is_installed = uv_manager.check_uv_installed()
    print(f"   UV 是否已安装: {is_installed}")
    
    # 查找所有 uv 安装
    print("\n2. 查找所有 UV 安装:")
    uv_paths = uv_manager.find_uv_installations()
    print(f"   找到 {len(uv_paths)} 个 UV 安装:")
    for i, path in enumerate(uv_paths, 1):
        print(f"   {i}. {path}")
    
    # 获取首选路径
    print("\n3. 首选路径:")
    preferred_path = uv_manager.get_preferred_uv_path()
    if preferred_path:
        print(f"   首选路径: {preferred_path}")
        
        # 验证该路径
        is_valid = uv_manager._verify_uv_executable(preferred_path)
        print(f"   路径有效性: {is_valid}")
        
        # 获取版本信息
        try:
            import subprocess
            result = subprocess.run(
                [preferred_path, "--version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                print(f"   版本信息: {result.stdout.strip()}")
        except:
            pass
    else:
        print("   未找到可用的 UV 路径")
    
    # 测试常见路径查找
    print("\n4. 常见路径查找:")
    common_paths = uv_manager._get_common_uv_paths()
    print(f"   找到 {len(common_paths)} 个常见路径:")
    for i, path in enumerate(common_paths, 1):
        print(f"   {i}. {path}")
        print(f"      存在: {os.path.exists(path)}")
        print(f"      可执行: {os.access(path, os.X_OK) if os.path.exists(path) else False}")
    
    print("\n=== 测试完成 ===")

if __name__ == "__main__":
    test_uv_detection()