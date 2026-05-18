"""
测试工作流执行系统
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.core.workflow_executor import WorkflowExecutor
from src.core.node_base import NodeBase
from src.core.uv_manager import UVManager


def test_basic():
    """测试基本功能"""
    print("=" * 60)
    print("测试: 基本工作流执行")
    print("=" * 60)
    
    # 创建管理器
    uv_manager = UVManager()
    print(f"\nUV 已安装: {uv_manager.check_uv_installed()}")
    
    # 创建执行器
    executor = WorkflowExecutor("test_workflow", uv_manager)
    
    # 创建节点
    node1 = NodeBase.from_dict({"node_id": "node1", "node_type": "variable_assign", "config": {
        "variable_name": "x",
        "value": "10",
        "value_type": "int"
    }})
    
    node2 = NodeBase.from_dict({"node_id": "node2", "node_type": "variable_assign", "config": {
        "variable_name": "y",
        "value": "20",
        "value_type": "int"
    }})
    
    node3 = NodeBase.from_dict({"node_id": "node3", "node_type": "variable_calc", "config": {
        "expression": "x + y * 2",
        "output_var": "result"
    }})
    
    # 添加节点
    executor.add_node(node1)
    executor.add_node(node2)
    executor.add_node(node3)
    
    # 添加连接
    executor.add_edge("node1", "node3")
    executor.add_edge("node2", "node3")
    
    print("\n节点创建完成:")
    print(f"  - node1: 变量赋值 (x = 10)")
    print(f"  - node2: 变量赋值 (y = 20)")
    print(f"  - node3: 变量计算 (result = x + y * 2)")
    
    # 准备环境
    print("\n准备工作流环境...")
    if executor.prepare_environment():
        print("环境准备成功")
    else:
        print("环境准备失败，将使用当前Python环境")
    
    # 执行工作流
    print("\n开始执行工作流...")
    try:
        result = executor.execute()
        
        print("\n执行结果:")
        print(f"  x = {result.get('x')}")
        print(f"  y = {result.get('y')}")
        print(f"  result = {result.get('result')}")
        print(f"\n验证: 10 + 20 * 2 = {10 + 20 * 2}")
        
        if result.get('result') == 50:
            print("\n[OK] 测试通过!")
        else:
            print("\n[FAIL] 测试失败!")
        
        # 保存工作流
        executor.save_workflow("workflows/test_workflow/workflow.json")
        print(f"\n工作流已保存")
        
    except Exception as e:
        print(f"\n执行失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    try:
        test_basic()
    except KeyboardInterrupt:
        print("\n\n用户中断")
    except Exception as e:
        print(f"\n错误: {e}")
        import traceback
        traceback.print_exc()
