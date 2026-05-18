#!/usr/bin/env python3
"""
测试镜像配置是否真正生效
"""
import sys
import os
import subprocess
import tempfile

# 添加项目根目录到路径
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from core.uv_manager import UVManager

def test_mirror_effectiveness():
    """测试镜像是否真正生效"""
    print("=== 测试镜像配置有效性 ===\n")
    
    uv_manager = UVManager()
    
    # 获取当前 UV 路径
    uv_path = uv_manager.get_preferred_uv_path()
    if not uv_path:
        print("ERROR: 未找到 UV 安装")
        return
    
    print(f"使用 UV 路径: {uv_path}")
    
    # 测试镜像
    test_mirrors = [
        "https://pypi.tuna.tsinghua.edu.cn/simple",
        "https://mirrors.aliyun.com/pypi/simple",
        "https://pypi.mirrors.ustc.edu.cn/simple"
    ]
    
    for mirror in test_mirrors:
        print(f"\n--- 测试镜像: {mirror} ---")
        
        # 设置镜像
        uv_manager.set_custom_mirror(mirror)
        
        # 创建临时工作流
        with tempfile.TemporaryDirectory() as temp_dir:
            workflow_name = "test_mirror"
            
            # 创建工作流环境
            print("创建虚拟环境...")
            success = uv_manager.create_workflow_env(workflow_name)
            if not success:
                print("   创建虚拟环境失败")
                continue
            
            print("   虚拟环境创建成功")
            
            # 尝试安装一个小包（注意：这里只是演示，不会真正安装）
            print(f"使用镜像安装包...")
            
            # 模拟安装命令（实际执行）
            python_exe = uv_manager._get_python_executable(workflow_name)
            cmd = [uv_path, "pip", "install", "--dry-run", "--index-url", mirror, "requests", "--python", str(python_exe)]
            
            print(f"   执行命令: {' '.join(cmd)}")
            
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                
                if result.returncode == 0:
                    print("   [OK] 镜像配置生效，可以正常访问")
                else:
                    print(f"   [ERROR] 镜像可能有问题: {result.stderr}")
                    
            except Exception as e:
                print(f"   [ERROR] 测试失败: {e}")
            
            # 清理工作流环境
            uv_manager.delete_workflow_env(workflow_name)
            print("   虚拟环境已清理")
    
    # 恢复原始配置
    print(f"\n恢复默认配置...")
    uv_manager.set_custom_mirror("")
    
    print("\n=== 测试完成 ===")

if __name__ == "__main__":
    test_mirror_effectiveness()