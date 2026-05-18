#!/usr/bin/env python3
"""
非交互式打包脚本 - 自动运行打包过程
"""

import sys
import os
from build import create_spec_file, clean_build, build_executable, verify_build, create_portable_package

def auto_build():
    """自动构建（不询问）"""
    print("=" * 50)
    print("LocalFlow Auto-Build Script")
    print("=" * 50)
    
    # 检查当前目录
    if not os.path.exists('main.py'):
        print("[ERROR] Error: Please run this script from the project root directory")
        sys.exit(1)
    
    try:
        # 1. 清理之前的构建
        clean_build()
        
        # 2. 创建 spec 文件
        create_spec_file()
        
        # 3. 构建可执行文件
        if not build_executable():
            sys.exit(1)
        
        # 4. 验证构建
        if not verify_build():
            sys.exit(1)
        
        # 5. 创建便携版本
        create_portable_package()
        
        print("\n" + "=" * 50)
        print("[SUCCESS] Auto-build completed!")
        print("=" * 50)
        
    except Exception as e:
        print(f"\n[ERROR] Error during build process: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    auto_build()