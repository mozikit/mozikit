"""
快速验证删除功能修复
显示一个测试窗口，可以手动测试删除功能
"""

import sys
from PySide6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QLabel
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from src.views.workflow_canvas import WorkflowCanvas, WorkflowGraphicsScene
from src.views.node_graphics import NodeGraphicsItem
from src.core.node_base import NodeType


class TestWindow(QMainWindow):
    """测试窗口"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("节点删除功能测试")
        self.setGeometry(100, 100, 800, 600)
        
        # 主布局
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        
        # 说明标签
        info_label = QLabel(
            "测试说明：\n"
            "1. 点击选中节点（会出现蓝色边框）\n"
            "2. 按 Delete 键或 Backspace 键删除\n"
            "3. 或者右键点击节点选择'删除节点'\n"
            "4. 验证节点和连接线都被删除"
        )
        info_font = QFont()
        info_font.setPointSize(10)
        info_label.setFont(info_font)
        info_label.setStyleSheet("""
            QLabel {
                background-color: #2d2d2d;
                color: #e0e0e0;
                padding: 10px;
                border-radius: 5px;
            }
        """)
        layout.addWidget(info_label)
        
        # 创建场景和画布
        scene = WorkflowGraphicsScene()
        self.canvas = WorkflowCanvas(scene, self)
        layout.addWidget(self.canvas)
        
        # 添加测试节点
        self._create_test_nodes(scene)
        
        # 状态标签
        self.status_label = QLabel("状态: 准备就绪")
        self.status_label.setStyleSheet("""
            QLabel {
                background-color: #1e1e1e;
                color: #4CAF50;
                padding: 5px;
            }
        """)
        layout.addWidget(self.status_label)
        
        # 连接信号
        self.canvas.node_deleted.connect(self._on_node_deleted)
    
    def _create_test_nodes(self, scene):
        """创建测试节点"""
        import time
        
        # 节点1
        node1 = NodeGraphicsItem(
            f"test_node_{int(time.time() * 1000)}",
            NodeType.VARIABLE_ASSIGN,
            "变量赋值"
        )
        node1.setPos(-200, 0)
        scene.addItem(node1)
        
        # 节点2
        node2 = NodeGraphicsItem(
            f"test_node_{int(time.time() * 1000) + 1}",
            NodeType.VARIABLE_CALC,
            "变量计算"
        )
        node2.setPos(100, 0)
        scene.addItem(node2)
        
        # 节点3
        node3 = NodeGraphicsItem(
            f"test_node_{int(time.time() * 1000) + 2}",
            NodeType.SQLITE_CONNECT,
            "SQLite连接"
        )
        node3.setPos(-200, 150)
        scene.addItem(node3)
        
        # 创建连接
        from src.views.node_graphics import ConnectionGraphicsItem
        
        if node1.output_ports and node2.input_ports:
            conn1 = ConnectionGraphicsItem(
                node1.output_ports[0],
                node2.input_ports[0]
            )
            scene.addItem(conn1)
        
        if node3.output_ports and node2.input_ports:
            conn2 = ConnectionGraphicsItem(
                node3.output_ports[0],
                node2.input_ports[0]
            )
            scene.addItem(conn2)
        
        self.status_label.setText("状态: 已创建3个测试节点和2条连接")
    
    def _on_node_deleted(self, node_id: str):
        """节点被删除"""
        self.status_label.setText(f"状态: ✅ 节点 {node_id} 已删除")
        print(f"节点已删除: {node_id}")


def main():
    app = QApplication(sys.argv)
    
    # 设置应用样式
    app.setStyle('Fusion')
    
    # 创建测试窗口
    window = TestWindow()
    window.show()
    
    print("=" * 60)
    print("节点删除功能测试窗口")
    print("=" * 60)
    print("\n测试步骤：")
    print("1. 点击选中一个节点（会出现蓝色边框）")
    print("2. 按 Delete 键或 Backspace 键")
    print("3. 观察节点是否被删除")
    print("4. 验证相关的连接线也被删除")
    print("\n如果删除成功：")
    print("- 节点消失")
    print("- 连接线消失")
    print("- 窗口底部显示'节点已删除'")
    print("- 控制台输出删除信息")
    print("\n" + "=" * 60)
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
