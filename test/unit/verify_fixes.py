"""
简单验证修复是否生效
"""

import sys
import time
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import QTimer
from src.main_window import MainWindow
from src.core.node_base import NodeType


def verify_fixes(window):
    """验证修复"""
    window.add_workflow_tab()
    workflow_tab = window.tabs.currentWidget()
    
    # 添加两个节点
    window.add_node_to_canvas(NodeType.VARIABLE_ASSIGN)
    time.sleep(0.1)
    window.add_node_to_canvas(NodeType.VARIABLE_CALC)
    
    print(f"Initial nodes count: {len(workflow_tab.nodes)}")
    
    # 删除第一个节点
    node_ids = list(workflow_tab.nodes.keys())
    first_node = workflow_tab.nodes[node_ids[0]]
    first_node.delete_node()
    
    # 延迟验证
    QTimer.singleShot(200, lambda: check_result(workflow_tab, node_ids[0]))


def check_result(workflow_tab, deleted_id):
    """检查结果"""
    print(f"After delete nodes count: {len(workflow_tab.nodes)}")
    print(f"Deleted node in dict: {deleted_id in workflow_tab.nodes}")
    
    # 保存并验证
    workflow_tab._save_workflow()
    
    import json
    save_path = f"workflows/{workflow_tab.workflow_name}/workflow.json"
    with open(save_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        saved_ids = [n['node_id'] for n in data['nodes']]
        
    print(f"Saved nodes count: {len(saved_ids)}")
    print(f"Deleted node in save file: {deleted_id in saved_ids}")
    
    # 显示结果
    result = f"""
Test Results:
-------------
Nodes in memory: {len(workflow_tab.nodes)} (should be 1)
Nodes in file: {len(saved_ids)} (should be 1)
Deleted node removed from memory: {deleted_id not in workflow_tab.nodes}
Deleted node removed from file: {deleted_id not in saved_ids}

Status: {'PASS' if len(workflow_tab.nodes) == 1 and len(saved_ids) == 1 else 'FAIL'}
"""
    
    print(result)
    QMessageBox.information(None, "Test Results", result)
    
    QTimer.singleShot(1000, QApplication.quit)


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    window._toggle_node_browser()
    
    QTimer.singleShot(500, lambda: verify_fixes(window))
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
