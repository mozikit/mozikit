#!/usr/bin/env python3
"""
PyInstaller Build Script
Used to package LocalFlow into an executable
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path

def get_version_from_git():
    """从 git tag 获取版本号"""
    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--always"],
            capture_output=True,
            text=True,
            cwd=Path("."),
        )
        if result.returncode == 0:
            version = result.stdout.strip()
            if version.startswith("v"):
                version = version[1:]
            return version
    except Exception:
        pass
    return "0.0.0"


def generate_version_file():
    """生成版本号文件供打包后使用"""
    version = get_version_from_git()
    version_file = Path("src/core/_version.py")

    content = f'''# Auto-generated version file
# Do not edit manually
__version__ = "{version}"
'''

    with open(version_file, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"[OK] Version file generated: {version_file} (version: {version})")
    return version


def check_requirements():
    """Check necessary dependencies"""
    print("Checking build dependencies...")

    try:
        import PyInstaller
        print("[OK] PyInstaller is installed")
    except ImportError:
        print("[ERROR] PyInstaller not installed, installing...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
        print("[OK] PyInstaller installed successfully")

    try:
        import PIL
        print("[OK] Pillow is installed")
    except ImportError:
        print("[ERROR] Pillow not installed, installing...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "Pillow"])
        print("[OK] Pillow installed successfully")

def create_spec_file():
    """Create PyInstaller spec file"""
    print("Creating PyInstaller spec file...")
    
    # 验证必要的文件和目录
    ROOT_DIR = Path(".")
    ASSETS_DIR = ROOT_DIR / "assets"
    ICONS_DIR = ASSETS_DIR / "icons"
    EXAMPLES_DIR = ROOT_DIR / "examples"
    
    # 检查文件是否存在
    missing_files = []
    
    # Windows 可执行文件图标必须使用 ICO，任务管理器与开始菜单均依赖此图标资源
    ico_file = ASSETS_DIR / "localflow.ico"
    png_file = ASSETS_DIR / "localflow_64.png"
    
    icon_file = None
    if ico_file.exists():
        icon_file = ico_file
        print(f"[OK] Using ICO icon: {ico_file}")
    else:
        raise FileNotFoundError(f"Required Windows icon not found: {ico_file}")
    
    if not ICONS_DIR.exists():
        missing_files.append(str(ICONS_DIR))
    
    if missing_files:
        print("[WARNING] Warning: The following files or directories do not exist:")
        for file in missing_files:
            print(f"   - {file}")
        print("Skipping these files...")
    
    # 构建文件列表
    added_files = []
    
    # 资源文件
    if ico_file.exists():
        added_files.append((str(ico_file), "assets"))

    if png_file.exists():
        added_files.append((str(png_file), "assets"))
    
    if ICONS_DIR.exists():
        added_files.append((str(ICONS_DIR), "assets/icons"))
    
    # 示例文件
    if EXAMPLES_DIR.exists():
        added_files.append((str(EXAMPLES_DIR), "examples"))
    
    # 工作流运行脚本
    runner_script = ROOT_DIR / "src" / "core" / "workflow_runner.py"
    if runner_script.exists():
        added_files.append((str(runner_script), "src/core"))

    # 版本号文件
    version_file = ROOT_DIR / "src" / "core" / "_version.py"
    if version_file.exists():
        added_files.append((str(version_file), "src/core"))

    # 官方节点快照
    official_nodes_dir = ROOT_DIR / "official_nodes"
    if official_nodes_dir.exists():
        added_files.append((str(official_nodes_dir), "official_nodes"))
    
    # 手动构建spec内容，避免f-string问题
    spec_lines = [
        '# -*- mode: python ; coding: utf-8 -*-',
        '',
        'import sys',
        'from pathlib import Path',
        '',
        '# 项目根目录',
        'ROOT_DIR = Path(".")',
        'ASSETS_DIR = ROOT_DIR / "assets"',
        '',
        '# 收集所有需要的文件',
        'added_files = ' + repr(added_files),
        '',
        '# 隐藏导入',
        'hiddenimports = [',
        '    # PySide6 模块',
        '    "PySide6.QtCore",',
        '    "PySide6.QtWidgets",', 
        '    "PySide6.QtGui",',
        '    "PySide6.QtNetwork",',
        '    ',
        '    # 项目模块',
        '    "src.main_window",',
        '    "src.views.workflow_canvas",',
        '    "src.views.workflow_tab_widget",',
        '    "src.views.overview_widget",',
        '    "src.views.node_graphics",',
        '    "src.views.node_browser",',
        '    "src.views.node_properties",',
        '    "src.dialogs.settings_dialog",',
        '    "src.core.workflow_executor",',
        '    "src.core.uv_manager",',
        '    "src.core.node_base",',
        '    "src.core.node_repo_manager",',
        '    "src.core.workflow_runner",',
        '    "src.core.custom_node_manager",',
        '    "src.core.ai_node_generator",',
        '    "src.core.code_safety",',
        '    "src.core.github_oauth",',
        '    "src.core.credential_store",',
        '    "src.core.node_version_manager",',
        '    "src.core.providers.github_provider",',
        '    ',
        '    # JSON 和其他依赖',
        '    "json",',
        '    "pathlib",',
        '    "shutil",',
        '    "time",',
        '    "math",',
        '    ',
        '    # UV 相关',
        '    "uv",',
        ']',
        '',
        'a = Analysis(',
        '    ["main.py"],',
        '    pathex=[str(ROOT_DIR)],',
        '    binaries=[],',
        '    datas=added_files,',
        '    hiddenimports=hiddenimports,',
        '    hookspath=[],',
        '    hooksconfig={},',
        '    runtime_hooks=[],',
        '    excludes=[',
        '        # 排除不需要的模块以减小体积',
        '        "tkinter",',
        '        "matplotlib",',
        '        "numpy",',
        '        "scipy",',
        '        "pandas",',
        '        "IPython",',
        '    ],',
        '    noarchive=False,',
        ')',
        '',
        'pyz = PYZ(a.pure)',
        '',
        '# 图标路径',
        'icon_path = None',
        'if Path("assets/localflow.ico").exists():',
        '    icon_path = "assets/localflow.ico"',
        '    print(f"[INFO] 设置图标: {icon_path}")',
        'else:',
        '    raise FileNotFoundError("Missing required icon: assets/localflow.ico")',
        '',
        '# 注意：PySide6 使用 LGPL 许可证，为了合规性，',
        '# 不建议打包为单文件，而是使用目录版本',
        'exe = EXE(',
        '    pyz,',
        '    a.scripts,',
        '    [],  # 不包含 binaries 和 datas，由 COLLECT 处理',
        '    name="LocalFlow",',
        '    debug=False,',
        '    bootloader_ignore_signals=False,',
        '    strip=False,',
        '    upx=True,',
        '    upx_exclude=[],',
        '    runtime_tmpdir=None,',
        '    console=False,  # 不显示控制台窗口',
        '    disable_windowed_traceback=False,',
        '    argv_emulation=False,',
        '    target_arch=None,',
        '    codesign_identity=None,',
        '    entitlements_file=None,',
        '    icon=icon_path,',
        ')',
        '',
        '# 创建目录版本（PySide6 推荐方式）',
        'coll = COLLECT(',
        '    exe,',
        '    a.binaries,',
        '    a.datas,',
        '    strip=False,',
        '    upx=True,',
        '    upx_exclude=[],',
        '    name="LocalFlow"',
        ')',
    ]
    
    spec_content = '\n'.join(spec_lines)
    
    with open('LocalFlow.spec', 'w', encoding='utf-8') as f:
        f.write(spec_content)
    
    print("[OK] LocalFlow.spec created successfully")

def clean_build():
    """Clean previous build files"""
    print("Cleaning previous build files...")
    
    dirs_to_clean = ['build', 'dist', 'LocalFlow_dir']
    for dir_name in dirs_to_clean:
        if os.path.exists(dir_name):
            shutil.rmtree(dir_name)
            print(f"  - Deleted {dir_name}")
    
    files_to_clean = ['LocalFlow.spec']
    for file_name in files_to_clean:
        if os.path.exists(file_name):
            os.remove(file_name)
            print(f"  - Deleted {file_name}")

def build_executable():
    """Build executable"""
    print("Starting build...")
    
    # Build
    cmd = [
        'pyinstaller',
        '--clean',
        '--noconfirm',
        'LocalFlow.spec'
    ]
    
    try:
        subprocess.check_call(cmd)
        print("[OK] Build completed!")
        return True
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Build failed: {e}")
        return False

def verify_build():
    """Verify build results"""
    print("Verifying build results...")
    
    # Check directory version (PySide6 recommended)
    dir_path = Path('dist/LocalFlow')
    if dir_path.exists():
        print(f"[OK] Directory distribution found: {dir_path}")
        
        # Check main executable
        main_exe = dir_path / 'LocalFlow.exe'
        if main_exe.exists():
            size_mb = main_exe.stat().st_size / (1024 * 1024)
            print(f"   Main executable: {main_exe}")
            print(f"   Size: {size_mb:.1f} MB")
            print("   ✅ Compliant with PySide6 LGPL requirements")
        
        return True
    else:
        print("[ERROR] Directory distribution not found")
        return False

def create_release_package():
    """Create release package (zip) matching GitHub Actions"""
    print("Creating release package...")
    
    release_dir = Path("release")
    release_dir.mkdir(exist_ok=True)
    
    zip_path = release_dir / "LocalFlow-Windows-x64.zip"
    source_dir = Path("dist/LocalFlow")
    
    if not source_dir.exists():
        print(f"[ERROR] Source directory not found: {source_dir}")
        return False
        
    import zipfile
    
    try:
        print(f"Zipping to {zip_path}...")
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for file_path in source_dir.rglob('*'):
                arcname = file_path.relative_to(source_dir.parent)
                zf.write(file_path, arcname)
                
        print(f"[OK] Release package created: {zip_path}")
        return True
    except Exception as e:
        print(f"[ERROR] Failed to create zip: {e}")
        return False

def create_portable_package():
    """Create portable package"""
    print("Creating portable package...")
    
    portable_dir = Path('dist/LocalFlow_Portable')
    if portable_dir.exists():
        shutil.rmtree(portable_dir)
    
    portable_dir.mkdir(parents=True)
    
    # Copy directory version
    dir_path = Path('dist/LocalFlow')
    if dir_path.exists():
        shutil.copytree(dir_path, portable_dir / 'LocalFlow', dirs_exist_ok=True)
    
    # Create start script
    if os.name == 'nt':  # Windows
        start_script = portable_dir / 'Start_LocalFlow.bat'
        start_script.write_text('''@echo off
cd /d "%~dp0LocalFlow"
LocalFlow.exe
pause
''')
        print("[OK] Portable version created (Start script: Start_LocalFlow.bat)")
    else:  # Linux/Mac
        start_script = portable_dir / 'start_localflow.sh'
        start_script.write_text('''#!/bin/bash
cd "$(dirname "$0")/LocalFlow"
./LocalFlow
''')
        os.chmod(start_script, 0o755)
        print("[OK] Portable version created (Start script: start_localflow.sh)")

def main():
    """Main function"""
    print("=" * 50)
    print("LocalFlow PyInstaller Build Script")
    print("=" * 50)
    
    # Check current directory
    if not Path('main.py').exists():
        print("[ERROR] Error: Please run this script from project root")
        sys.exit(1)
    
    try:
        # 1. Check dependencies
        check_requirements()

        # 2. Generate version file
        generate_version_file()

        # 3. Ask to clean
        clean = input("\nClean previous build files? (y/N): ").lower().startswith('y')
        if clean:
            clean_build()

        # 4. Create spec file
        create_spec_file()
        
        # 4. Build executable
        if not build_executable():
            sys.exit(1)
        
        # 5. Verify build
        if not verify_build():
            sys.exit(1)
        
        # 6. Create release package (GitHub Actions style)
        create_release_package()

        # 7. Create portable version (Optional, kept for convenience)
        create_portable_package()
        
        print("\n" + "=" * 50)
        print("[SUCCESS] Build completed!")
        print("=" * 50)
        print("\nOutput files:")
        print("  - dist/LocalFlow/                (Directory version)")
        print("  - release/LocalFlow-Windows-x64.zip (Release Package - Matches GitHub Actions)")
        print("  - dist/LocalFlow_Portable/       (Portable version with start script)")
        print("\n✅ Compliant with PySide6 LGPL requirements")
        print("Recommended usage:")
        print("  - Use release/LocalFlow-Windows-x64.zip for distribution")
        
    except KeyboardInterrupt:
        print("\n\n[INFO] Build cancelled")
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] Error occurred: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()