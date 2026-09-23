#!/usr/bin/env python3
"""
非交互式打包脚本 - 自动运行打包过程
"""

import sys
import os
from build import (
    build_executable,
    check_requirements,
    clean_build,
    create_portable_package,
    create_release_package,
    create_spec_file,
    generate_version_file,
    sync_official_nodes_snapshot,
    verify_build,
)

def auto_build():
    """自动构建（不询问）"""
    print("=" * 50)
    print("Mozikit Auto-Build Script")
    print("=" * 50)
    
    # 检查当前目录
    if not os.path.exists('main.py'):
        print("[ERROR] Error: Please run this script from the project root directory")
        sys.exit(1)
    
    try:
        # 1. 检查构建环境并解析统一版本
        check_requirements()
        generate_version_file()

        # 2. 同步官方节点快照；正式产物不得无节点继续发布
        if not os.environ.get("MOZIKIT_SKIP_OFFICIAL_NODES_SYNC"):
            if not sync_official_nodes_snapshot() and not os.path.exists(
                os.path.join("official_nodes", "manifest.json")
            ):
                raise RuntimeError("Official nodes snapshot is required for a Desktop build")
        elif not os.path.exists(os.path.join("official_nodes", "manifest.json")):
            raise RuntimeError("Official nodes snapshot is required for a Desktop build")

        # 3. 清理之前的构建（保留 build/bundled_uv/uv.exe）
        clean_build()
        
        # 4. 验证共享 spec
        create_spec_file()
        
        # 5. 构建可执行文件
        if not build_executable():
            sys.exit(1)
        
        # 6. 验证目录、CLI、bundled UV 和官方节点
        if not verify_build():
            sys.exit(1)
        
        # 7. 创建 Portable ZIP 和本地便利目录
        create_release_package()
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
