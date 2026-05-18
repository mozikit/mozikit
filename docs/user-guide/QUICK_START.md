# LocalFlow 快速开始指南

## 🚀 5分钟上手

### 1. 测试系统是否正常

```bash
python test_workflow.py
```

预期输出：
```
============================================================
测试: 基本工作流执行
============================================================

UV 已安装: True

节点创建完成:
  - node1: 变量赋值 (x = 10)
  - node2: 变量赋值 (y = 20)
  - node3: 变量计算 (result = x + y * 2)

准备工作流环境...
环境准备成功

开始执行工作流...
执行顺序: ['node1', 'node2', 'node3']
已生成 3 个节点脚本
执行节点: node1 (variable_assign)
节点 node1 执行成功
执行节点: node2 (variable_assign)
节点 node2 执行成功
执行节点: node3 (variable_calc)
节点 node3 执行成功

执行结果:
  x = 10
  y = 20
  result = 50

验证: 10 + 20 * 2 = 50

[OK] 测试通过!
```

### 2. 创建你的第一个工作流

创建文件 `my_first_workflow.py`:

```python
from src.core.workflow_executor import WorkflowExecutor
from src.core.node_base import VariableAssignNode, VariableCalcNode

# 创建工作流
executor = WorkflowExecutor("hello_workflow")

# 准备环境
executor.prepare_environment()

# 创建节点
greeting = VariableAssignNode("greeting", {
    "variable_name": "message",
    "value": "Hello, LocalFlow!",
    "value_type": "str"
})

length = VariableCalcNode("length", {
    "expression": "len(message)",
    "output_var": "message_length"
})

# 添加到工作流
executor.add_node(greeting)
executor.add_node(length)
executor.add_edge("greeting", "length")

# 执行
result = executor.execute()
print(f"\n消息: {result['message']}")
print(f"长度: {result['message_length']}")
```

运行：
```bash
python my_first_workflow.py
```

### 3. 使用 GUI

```bash
python main.py
```

在GUI中：
1. 右键画布 → 选择节点类型
2. 节点会出现在画布上
3. 拖拽移动节点
4. 右键节点 → 配置/执行/删除

## 📚 示例集合

### 示例1: 温度转换

```python
from src.core.workflow_executor import WorkflowExecutor
from src.core.node_base import VariableAssignNode, VariableCalcNode

executor = WorkflowExecutor("temperature_converter")
executor.prepare_environment()

# 输入摄氏度
celsius = VariableAssignNode("celsius_input", {
    "variable_name": "celsius",
    "value": "25",
    "value_type": "float"
})

# 转换为华氏度
to_fahrenheit = VariableCalcNode("to_fahrenheit", {
    "expression": "celsius * 9/5 + 32",
    "output_var": "fahrenheit"
})

# 转换为开尔文
to_kelvin = VariableCalcNode("to_kelvin", {
    "expression": "celsius + 273.15",
    "output_var": "kelvin"
})

executor.add_node(celsius)
executor.add_node(to_fahrenheit)
executor.add_node(to_kelvin)
executor.add_edge("celsius_input", "to_fahrenheit")
executor.add_edge("celsius_input", "to_kelvin")

result = executor.execute()
print(f"{result['celsius']}°C = {result['fahrenheit']}°F = {result['kelvin']}K")
```

### 示例2: 数据库查询

```python
from src.core.workflow_executor import WorkflowExecutor
from src.core.node_base import *

executor = WorkflowExecutor("database_query")
executor.prepare_environment()

# 连接数据库
connect = SQLiteConnectNode("connect", {
    "db_path": "./users.db",
    "connection_name": "db"
})

# 设置查询参数
user_id = VariableAssignNode("user_id", {
    "variable_name": "id",
    "value": "1",
    "value_type": "int"
})

# 构建SQL
sql = SQLStatementNode("sql", {
    "sql": "SELECT * FROM users WHERE id = {id}",
    "output_var": "query"
})

# 执行查询
execute = SQLiteExecuteNode("execute", {
    "connection_name": "db",
    "sql_var": "query",
    "output_var": "result"
})

executor.add_node(connect)
executor.add_node(user_id)
executor.add_node(sql)
executor.add_node(execute)

executor.add_edge("connect", "execute")
executor.add_edge("user_id", "sql")
executor.add_edge("sql", "execute")

result = executor.execute()
print(f"查询结果: {result['result']}")
```

### 示例3: 批量计算

```python
from src.core.workflow_executor import WorkflowExecutor
from src.core.node_base import VariableAssignNode, VariableCalcNode

executor = WorkflowExecutor("batch_calculation")
executor.prepare_environment()

# 定义数据
numbers = VariableAssignNode("numbers", {
    "variable_name": "data",
    "value": '[10, 20, 30, 40, 50]',
    "value_type": "json"
})

# 计算总和
total = VariableCalcNode("sum", {
    "expression": "sum(data)",
    "output_var": "total"
})

# 计算平均值
average = VariableCalcNode("average", {
    "expression": "total / len(data)",
    "output_var": "avg"
})

executor.add_node(numbers)
executor.add_node(total)
executor.add_node(average)

executor.add_edge("numbers", "sum")
executor.add_edge("sum", "average")

result = executor.execute()
print(f"数据: {result['data']}")
print(f"总和: {result['total']}")
print(f"平均值: {result['avg']}")
```

## 🎯 节点类型速查

### 1. 变量赋值 (VariableAssignNode)

**用途**: 创建变量并赋值

**配置**:
```python
{
    "variable_name": "变量名",
    "value": "值",
    "value_type": "类型"  # str, int, float, bool, json
}
```

**示例**:
```python
VariableAssignNode("node1", {
    "variable_name": "price",
    "value": "99.99",
    "value_type": "float"
})
```

### 2. 变量计算 (VariableCalcNode)

**用途**: 使用Python表达式计算

**配置**:
```python
{
    "expression": "Python表达式",
    "output_var": "输出变量名"
}
```

**示例**:
```python
VariableCalcNode("node2", {
    "expression": "price * 0.9",  # 打9折
    "output_var": "discount_price"
})
```

### 3. SQLite连接 (SQLiteConnectNode)

**用途**: 连接SQLite数据库

**配置**:
```python
{
    "db_path": "数据库路径",
    "connection_name": "连接名称"
}
```

**示例**:
```python
SQLiteConnectNode("node3", {
    "db_path": "./data.db",
    "connection_name": "my_db"
})
```

### 4. SQL语句 (SQLStatementNode)

**用途**: 生成SQL语句（支持变量插值）

**配置**:
```python
{
    "sql": "SQL语句模板",
    "output_var": "输出变量名"
}
```

**示例**:
```python
SQLStatementNode("node4", {
    "sql": "SELECT * FROM products WHERE price < {max_price}",
    "output_var": "query"
})
```

### 5. SQLite执行 (SQLiteExecuteNode)

**用途**: 执行SQL语句

**配置**:
```python
{
    "connection_name": "连接名称",
    "sql_var": "SQL变量名",
    "output_var": "输出变量名"
}
```

**示例**:
```python
SQLiteExecuteNode("node5", {
    "connection_name": "my_db",
    "sql_var": "query",
    "output_var": "products"
})
```

## 💡 常用技巧

### 技巧1: 调试节点

查看生成的脚本：
```bash
cat workflows/[workflow_name]/scripts/node_*.py
```

### 技巧2: 查看执行日志

脚本输出会显示在控制台：
```
执行节点: node1 (variable_assign)
虚拟环境不存在，使用当前Python: ...
节点 node1 执行成功
```

### 技巧3: 保存和加载工作流

```python
# 保存
executor.save_workflow("my_workflow.json")

# 加载
from src.core.workflow_executor import WorkflowExecutor
executor = WorkflowExecutor.load_workflow("my_workflow.json")
result = executor.execute()
```

### 技巧4: 添加依赖包

```python
executor.prepare_environment(
    packages=["pandas", "requests", "numpy"]
)
```

## ⚠️ 常见问题

### Q1: UV未安装怎么办？

**A**: 系统会自动降级使用当前Python环境，或：
1. 打开GUI
2. 点击左下角设置按钮
3. 使用一键安装UV

### Q2: 节点执行失败

**A**: 检查：
1. 脚本语法错误
2. 变量名拼写
3. 数据类型是否匹配
4. 查看生成的脚本文件

### Q3: 如何查看中间结果？

**A**: 执行后检查 `executor.context`:
```python
result = executor.execute()
print(executor.context)  # 所有中间变量
```

### Q4: 如何删除工作流环境？

```python
uv_manager.delete_workflow_env("workflow_name")
```

## 🔗 更多资源

- 📖 完整文档: `WORKFLOW_EXECUTION.md`
- 📝 实现总结: `IMPLEMENTATION_SUMMARY.md`
- 🎨 主题支持: `THEME_SUPPORT.md`
- 💻 示例代码: `examples/simple_workflow_example.py`

## 🎉 开始创造！

现在你已经掌握了基础，可以：
1. 创建更复杂的工作流
2. 组合多个节点类型
3. 处理真实数据
4. 构建自动化流程

**祝你使用愉快！** 🚀
