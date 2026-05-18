#!/usr/bin/env python3
"""
测试运行器
运行所有测试或指定类型的测试
"""
import sys
import os
import subprocess
from pathlib import Path

# 添加项目根目录到路径
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)

def run_test_file(test_file):
    """运行单个测试文件"""
    print(f"运行测试: {test_file}")
    try:
        result = subprocess.run(
            [sys.executable, str(test_file)],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode == 0:
            print(f"[OK] {test_file.name} - 通过")
            return True
        else:
            print(f"[ERROR] {test_file.name} - 失败")
            print(f"  错误输出: {result.stderr}")
            return False
    except Exception as e:
        print(f"[ERROR] {test_file.name} - 异常: {e}")
        return False

def run_test_category(category):
    """运行指定类别的测试"""
    print(f"\n=== 运行 {category} 测试 ===")
    test_dir = Path(__file__).parent / category
    
    if not test_dir.exists():
        print(f"测试目录不存在: {test_dir}")
        return False
    
    test_files = list(test_dir.glob("test_*.py"))
    if not test_files:
        print(f"在 {category} 目录中没有找到测试文件")
        return False
    
    success_count = 0
    total_count = len(test_files)
    
    for test_file in test_files:
        if run_test_file(test_file):
            success_count += 1
    
    print(f"\n{category} 测试结果: {success_count}/{total_count} 通过")
    return success_count == total_count

def run_all_tests():
    """运行所有测试"""
    print("=== 运行所有测试 ===")
    
    categories = ["unit", "integration", "ui"]
    total_success = True
    
    for category in categories:
        category_success = run_test_category(category)
        if not category_success:
            total_success = False
    
    return total_success

def main():
    if len(sys.argv) == 1:
        # 运行所有测试
        success = run_all_tests()
    elif len(sys.argv) == 2:
        category = sys.argv[1]
        if category in ["unit", "integration", "ui"]:
            success = run_test_category(category)
        else:
            print(f"未知的测试类别: {category}")
            print("支持的类别: unit, integration, ui")
            return 1
    else:
        print("用法:")
        print("  python run_tests.py              # 运行所有测试")
        print("  python run_tests.py <category>   # 运行指定类别的测试")
        print("  支持的类别: unit, integration, ui")
        return 1
    
    print("\n" + "="*50)
    if success:
        print("[SUCCESS] 所有测试通过!")
        return 0
    else:
        print("[FAILED] 部分测试失败")
        return 1

if __name__ == "__main__":
    sys.exit(main())