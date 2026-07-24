"""
简单工作流示例
演示如何创建和执行一个包含多个节点的工作流
"""
import sys
import os

# 添加父目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.workflow_executor import WorkflowExecutor
from src.core.node_base import NodeBase
from src.core.uv_manager import UVManager


def example_1_basic_calculation():
    """示例1: 基础计算工作流"""
    print("=" * 60)
    print("示例1: 基础计算工作流")
    print("=" * 60)
    
    # 创建UV管理器
    uv_manager = UVManager()
    
    # 检查uv是否安装
    if not uv_manager.check_uv_installed():
        print("警告: uv未安装，将使用本地Python环境")
    
    # 创建工作流执行器
    executor = WorkflowExecutor("example_basic_calc", uv_manager)
    
    # 准备环境
    print("\n准备工作流环境...")
    executor.prepare_environment()
    
    # 创建节点
    # 节点1: 赋值 x = 10
    node1 = NodeBase.from_dict({"node_id": "node1", "node_type": "variable_assign", "config": {
        "variable_name": "x",
        "value": "10",
        "value_type": "int"
    }})
    
    # 节点2: 赋值 y = 20
    node2 = NodeBase.from_dict({"node_id": "node2", "node_type": "variable_assign", "config": {
        "variable_name": "y",
        "value": "20",
        "value_type": "int"
    }})
    
    # 节点3: 计算 result = x + y * 2
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
    
    # 执行工作流
    print("\n开始执行工作流...")
    try:
        result = executor.execute()
        print("\n执行结果:")
        print(f"  x = {result.get('x')}")
        print(f"  y = {result.get('y')}")
        print(f"  result = {result.get('result')}")
        print(f"\n预期: result = 10 + 20 * 2 = 50")
        
        # 保存工作流
        executor.save_workflow("workflows/example_basic_calc/workflow.json")
        print("\n工作流已保存到: workflows/example_basic_calc/workflow.json")
        
    except Exception as e:
        print(f"\n执行失败: {e}")
        import traceback
        traceback.print_exc()


def example_2_sqlite_workflow():
    """示例2: SQLite数据库工作流"""
    print("\n" + "=" * 60)
    print("示例2: SQLite数据库工作流")
    print("=" * 60)
    
    uv_manager = UVManager()
    executor = WorkflowExecutor("example_sqlite", uv_manager)
    
    # 准备环境
    print("\n准备工作流环境...")
    executor.prepare_environment()
    
    # 节点1: 连接数据库
    node1 = NodeBase.from_dict({"node_id": "db_connect", "node_type": "sqlite_connect", "config": {
        "db_path": "./workflows/example_sqlite/test.db",
        "connection_name": "db_conn"
    }})

    # 节点2: SQL创建表语句
    node2 = NodeBase.from_dict({"node_id": "sql_create", "node_type": "sql_statement", "config": {
        "sql": "CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, name TEXT, age INTEGER)",
        "output_var": "sql"
    }})

    # 节点3: 执行创建表
    node3 = NodeBase.from_dict({"node_id": "execute_create", "node_type": "sqlite_execute", "config": {
        "connection_name": "db_conn",
        "sql_var": "sql",
        "output_var": "create_result"
    }})

    # 节点4: SQL插入语句
    node4 = NodeBase.from_dict({"node_id": "sql_insert", "node_type": "sql_statement", "config": {
        "sql": "INSERT INTO users (name, age) VALUES ('Alice', 25), ('Bob', 30), ('Charlie', 35)",
        "output_var": "sql"
    }})

    # 节点5: 执行插入
    node5 = NodeBase.from_dict({"node_id": "execute_insert", "node_type": "sqlite_execute", "config": {
        "connection_name": "db_conn",
        "sql_var": "sql",
        "output_var": "insert_result"
    }})

    # 节点6: SQL查询语句
    node6 = NodeBase.from_dict({"node_id": "sql_select", "node_type": "sql_statement", "config": {
        "sql": "SELECT * FROM users WHERE age >= 30",
        "output_var": "sql"
    }})

    # 节点7: 执行查询
    node7 = NodeBase.from_dict({"node_id": "execute_select", "node_type": "sqlite_execute", "config": {
        "connection_name": "db_conn",
        "sql_var": "sql",
        "output_var": "query_result"
    }})
    
    # 添加节点
    for node in [node1, node2, node3, node4, node5, node6, node7]:
        executor.add_node(node)
    
    # 添加连接（线性流程）
    executor.add_edge("db_connect", "sql_create")
    executor.add_edge("sql_create", "execute_create")
    executor.add_edge("execute_create", "sql_insert")
    executor.add_edge("sql_insert", "execute_insert")
    executor.add_edge("execute_insert", "sql_select")
    executor.add_edge("sql_select", "execute_select")
    
    # 执行工作流
    print("\n开始执行工作流...")
    try:
        result = executor.execute()
        print("\n执行结果:")
        print(f"  创建表结果: {result.get('create_result')}")
        print(f"  插入结果: {result.get('insert_result')}")
        print(f"  查询结果: {result.get('query_result')}")
        
        # 保存工作流
        executor.save_workflow("workflows/example_sqlite/workflow.json")
        print("\n工作流已保存到: workflows/example_sqlite/workflow.json")
        
    except Exception as e:
        print(f"\n执行失败: {e}")
        import traceback
        traceback.print_exc()


def example_3_combined_workflow():
    """示例3: 组合工作流（变量计算 + 数据库）"""
    print("\n" + "=" * 60)
    print("示例3: 组合工作流（变量 + 数据库）")
    print("=" * 60)
    
    uv_manager = UVManager()
    executor = WorkflowExecutor("example_combined", uv_manager)
    
    # 准备环境
    print("\n准备工作流环境...")
    executor.prepare_environment()
    
    # 节点1: 设置用户ID
    node1 = NodeBase.from_dict({"node_id": "set_user_id", "node_type": "variable_assign", "config": {
        "variable_name": "user_id",
        "value": "1",
        "value_type": "int"
    }})
    
    # 节点2: 连接数据库
    node2 = NodeBase.from_dict({"node_id": "db_connect", "node_type": "sqlite_connect", "config": {
        "db_path": "./workflows/example_combined/users.db",
        "connection_name": "db_conn"
    }})
    
    # 节点3: 生成SQL查询（使用变量）
    node3 = NodeBase.from_dict({"node_id": "sql_query", "node_type": "sql_statement", "config": {
        "sql": "SELECT * FROM users WHERE id = {user_id}",
        "output_var": "sql"
    }})
    
    # 节点4: 执行查询
    node4 = NodeBase.from_dict({"node_id": "execute_query", "node_type": "sqlite_execute", "config": {
        "connection_name": "db_conn",
        "sql_var": "sql",
        "output_var": "user_data"
    }})
    
    # 添加节点
    for node in [node1, node2, node3, node4]:
        executor.add_node(node)
    
    # 添加连接
    executor.add_edge("set_user_id", "sql_query")
    executor.add_edge("db_connect", "execute_query")
    executor.add_edge("sql_query", "execute_query")
    
    # 先创建数据库和表（预处理）
    import sqlite3
    import os
    
    db_path = "./workflows/example_combined/users.db"
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, name TEXT, email TEXT)")
    cursor.execute("INSERT OR REPLACE INTO users VALUES (1, 'Alice', 'alice@example.com')")
    cursor.execute("INSERT OR REPLACE INTO users VALUES (2, 'Bob', 'bob@example.com')")
    conn.commit()
    conn.close()
    print("数据库已预先创建并填充数据")
    
    # 执行工作流
    print("\n开始执行工作流...")
    try:
        result = executor.execute()
        print("\n执行结果:")
        print(f"  user_id = {result.get('user_id')}")
        print(f"  生成的SQL = {result.get('sql')}")
        print(f"  查询结果 = {result.get('user_data')}")
        
        # 保存工作流
        executor.save_workflow("workflows/example_combined/workflow.json")
        print("\n工作流已保存到: workflows/example_combined/workflow.json")
        
    except Exception as e:
        print(f"\n执行失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    print("Mozikit 工作流示例")
    print("=" * 60)
    
    try:
        # 运行示例1
        example_1_basic_calculation()
        
        # 运行示例2
        example_2_sqlite_workflow()
        
        # 运行示例3
        example_3_combined_workflow()
        
        print("\n" + "=" * 60)
        print("所有示例执行完成！")
        print("=" * 60)
        
    except KeyboardInterrupt:
        print("\n\n用户中断执行")
    except Exception as e:
        print(f"\n执行出错: {e}")
        import traceback
        traceback.print_exc()
