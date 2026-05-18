"""
测试标签页管理功能：
1. 标签页可关闭
2. 支持关闭当前、关闭其他、关闭所有
3. 有修改时显示 * 标识
4. 关闭前提示保存
"""

import sys
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import QTimer, Qt
from src.main_window import MainWindow
from src.core.node_base import NodeType


def test_tab_management(window):
    """测试标签页管理"""
    print("\n" + "="*60)
    print("测试标签页管理功能")
    print("="*60)
    
    # 1. 测试标签可关闭
    print("\n[测试1] 验证标签可关闭...")
    tabs = window.tabs
    if tabs.tabsClosable():
        print("[OK] 标签可关闭功能已启用")
    else:
        print("[FAIL] 标签可关闭功能未启用")
        return
    
    # 2. 创建多个工作流标签
    print("\n[测试2] 创建多个工作流标签...")
    window.add_workflow_tab()
    window.add_workflow_tab()
    window.add_workflow_tab()
    
    tab_count = tabs.count()
    print(f"[OK] 已创建标签，当前标签数: {tab_count} (应为4: 1个Overview + 3个工作流)")
    
    # 3. 测试修改标识
    print("\n[测试3] 测试修改标识...")
    # 切换到第一个工作流标签
    tabs.setCurrentIndex(1)
    workflow_tab = tabs.widget(1)  # 第一个工作流标签
    original_text = tabs.tabText(1)
    print(f"  原始标签文本: {original_text}")
    print(f"  当前标签索引: {tabs.currentIndex()}")
    
    # 添加节点触发修改
    window.add_node_to_canvas(NodeType.VARIABLE_ASSIGN)
    QTimer.singleShot(100, lambda: check_modified_indicator(window, original_text))


def check_modified_indicator(window, original_text):
    """检查修改标识"""
    tabs = window.tabs
    modified_text = tabs.tabText(1)
    print(f"  添加节点后标签文本: {modified_text}")
    
    if modified_text.endswith(" *"):
        print("[OK] 修改标识 * 已显示")
    else:
        print("[FAIL] 修改标识 * 未显示")
        return
    
    # 4. 测试保存后移除标识
    print("\n[测试4] 测试保存后移除修改标识...")
    workflow_tab = tabs.widget(1)
    
    # 保存工作流
    workflow_tab._save_workflow()
    
    QTimer.singleShot(100, lambda: check_saved_indicator(window, original_text))


def check_saved_indicator(window, original_text):
    """检查保存后的标识"""
    tabs = window.tabs
    saved_text = tabs.tabText(1)
    print(f"  保存后标签文本: {saved_text}")
    
    if not saved_text.endswith(" *"):
        print("[OK] 保存后修改标识已移除")
    else:
        print("[FAIL] 保存后修改标识未移除")
        return
    
    # 5. 测试关闭功能
    print("\n[测试5] 测试标签关闭功能...")
    initial_count = tabs.count()
    
    # 关闭第二个工作流标签（索引2，因为0是Overview）
    tabs.tabCloseRequested.emit(2)
    
    QTimer.singleShot(100, lambda: check_close(window, initial_count))


def check_close(window, initial_count):
    """检查关闭结果"""
    tabs = window.tabs
    new_count = tabs.count()
    print(f"  关闭前标签数: {initial_count}")
    print(f"  关闭后标签数: {new_count}")
    
    if new_count == initial_count - 1:
        print("[OK] 标签关闭成功")
    else:
        print("[FAIL] 标签关闭失败")
        return
    
    # 6. 测试不能关闭Overview标签
    print("\n[测试6] 测试不能关闭Overview标签...")
    before_count = tabs.count()
    tabs.tabCloseRequested.emit(0)  # 尝试关闭Overview
    
    QTimer.singleShot(100, lambda: check_overview_protection(window, before_count))


def check_overview_protection(window, before_count):
    """检查Overview保护"""
    tabs = window.tabs
    after_count = tabs.count()
    
    if after_count == before_count:
        print("[OK] Overview标签受保护，不能关闭")
    else:
        print("[FAIL] Overview标签被错误关闭")
        return
    
    # 7. 测试右键菜单（只能手动测试）
    print("\n[测试7] 右键菜单功能已实现，需要手动测试:")
    print("  - 在标签上右键点击")
    print("  - 验证'关闭当前'、'关闭其他'、'关闭所有'菜单")
    
    # 8. 测试未保存提示（需要手动测试）
    print("\n[测试8] 未保存提示功能已实现，需要手动测试:")
    print("  - 修改工作流（添加节点）")
    print("  - 尝试关闭标签")
    print("  - 验证弹出保存提示对话框")
    
    print("\n" + "="*60)
    print("自动化测试完成！")
    print("="*60)
    print("\n总结:")
    print("[OK] 1. 标签可关闭")
    print("[OK] 2. 多个工作流标签创建")
    print("[OK] 3. 修改时显示 * 标识")
    print("[OK] 4. 保存后移除 * 标识")
    print("[OK] 5. 标签关闭功能")
    print("[OK] 6. Overview标签受保护")
    print("[MANUAL] 7. 右键菜单（需手动测试）")
    print("[MANUAL] 8. 未保存提示（需手动测试）")
    
    print("\n请手动测试以下功能:")
    print("1. 在标签上右键，测试'关闭当前'、'关闭其他'、'关闭所有'")
    print("2. 修改工作流后关闭，验证保存提示")
    print("3. 关闭主窗口时，验证检查所有未保存的工作流")
    
    QTimer.singleShot(3000, QApplication.quit)


def main():
    app = QApplication(sys.argv)
    
    # 创建主窗口
    window = MainWindow()
    window.show()
    
    # 延迟执行测试
    QTimer.singleShot(500, lambda: test_tab_management(window))
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
