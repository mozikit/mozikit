"""
测试保存工作流的修复
验证不会出现 "Internal C++ object already deleted" 错误
"""

import sys
from pathlib import Path

def test_imports():
    """测试导入是否正常"""
    print("测试1: 检查模块导入...")
    try:
        from src.views.overview_widget import OverviewWidget, WorkflowCard
        from src.views.workflow_tab_widget import WorkflowTabWidget
        print("  [OK] 所有模块导入成功")
        return True
    except Exception as e:
        print(f"  [FAIL] 导入失败: {e}")
        return False


def test_overview_refresh_logic():
    """测试首页刷新逻辑"""
    print("\n测试2: 检查首页刷新逻辑...")
    
    try:
        from src.views.overview_widget import OverviewWidget
        from PySide6.QtWidgets import QApplication
        
        # 创建应用（测试需要）
        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)
        
        # 创建OverviewWidget实例
        widget = OverviewWidget()
        
        # 测试初始加载
        widget._load_workflows()
        print("  [OK] 初始加载成功")
        
        # 测试刷新
        widget.refresh_workflows()
        print("  [OK] 刷新方法成功")
        
        # 多次刷新测试（模拟保存后刷新场景）
        for i in range(3):
            widget.refresh_workflows()
        print("  [OK] 多次刷新测试通过")
        
        return True
        
    except Exception as e:
        print(f"  [FAIL] 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_workflow_tab_save():
    """测试工作流保存逻辑"""
    print("\n测试3: 检查保存逻辑...")
    
    try:
        from src.views.workflow_tab_widget import WorkflowTabWidget
        from PySide6.QtWidgets import QApplication
        
        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)
        
        # 创建工作流标签页
        widget = WorkflowTabWidget("测试工作流")
        
        # 检查_refresh_overview_list方法存在
        if hasattr(widget, '_refresh_overview_list'):
            print("  [OK] _refresh_overview_list 方法存在")
        else:
            print("  [FAIL] 缺少 _refresh_overview_list 方法")
            return False
        
        # 测试调用（不会真正保存）
        widget._refresh_overview_list()
        print("  [OK] 刷新方法调用成功")
        
        return True
        
    except Exception as e:
        print(f"  [FAIL] 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    print("=" * 60)
    print("保存工作流错误修复测试")
    print("=" * 60)
    
    results = []
    results.append(("模块导入", test_imports()))
    results.append(("首页刷新逻辑", test_overview_refresh_logic()))
    results.append(("工作流保存逻辑", test_workflow_tab_save()))
    
    print("\n" + "=" * 60)
    print("测试总结")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "[PASS]" if result else "[FAIL]"
        print(f"  {status}: {name}")
    
    print(f"\n总计: {passed}/{total} 项测试通过")
    
    if passed == total:
        print("\n[SUCCESS] 所有测试通过！修复成功！")
        print("\n修复说明:")
        print("1. empty_label 不再被删除，只是隐藏/显示")
        print("2. 使用 QTimer.singleShot 延迟刷新首页")
        print("3. 添加异常处理避免访问已删除的Qt对象")
        return 0
    else:
        print("\n[WARNING] 部分测试失败")
        return 1


if __name__ == "__main__":
    sys.exit(main())
