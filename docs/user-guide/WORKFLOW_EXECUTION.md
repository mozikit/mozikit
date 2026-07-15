# Mozikit 工作流执行系统

## 概述

Mozikit 是一个基于 UV 包管理器的可视化工作流执行系统。每个工作流都有独立的 Python 虚拟环境（使用 UV 的共享缓存），节点之间通过 JSON 序列化传递数据。

## 核心架构

### 1. UV 环境管理 (`UVManager`)

- **共享缓存**: 所有工作流共享包缓存，节省磁盘空间
- **独立环境**: 每个工作流有独立的虚拟环境
- **快速创建**: 使用 `uv venv` 快速创建环境
- **包管理**: 使用 `uv pip` 安装和管理依赖

```python
from src.core.uv_manager import UVManager

# 创建管理器
uv_manager = UVManager()

# 创建工作流环境
uv_manager.create_workflow_env("my_workflow")

# 安装包
uv_manager.install_packages("my_workflow", ["pandas", "numpy"])

# 运行脚本
result = uv_manager.run_python_script("my_workflow", "script.py", {"input": "data"})
```

### 2. 节点系统 (`NodeBase`)

每个节点都是一个独立的 Python 脚本，支持以下节点类型：

#### 变量赋值节点 (`VariableAssignNode`)
```python
node = VariableAssignNode("node1", {
    "variable_name": "x",
    "value": "100",
    "value_type": "int"  # str, int, float, bool, json
})
```

#### 变量计算节点 (`VariableCalcNode`)
```python
node = VariableCalcNode("node2", {
    "expression": "x + y * 2",
    "output_var": "result"
})
```

#### SQLite 连接节点 (`SQLiteConnectNode`)
```python
node = SQLiteConnectNode("node3", {
    "db_path": "./data.db",
    "connection_name": "db_conn"
})
```

#### SQLite 执行节点 (`SQLiteExecuteNode`)
```python
node = SQLiteExecuteNode("node4", {
    "connection_name": "db_conn",
    "sql_var": "sql",
    "output_var": "query_result"
})
```

#### SQL 语句节点 (`SQLStatementNode`)
```python
node = SQLStatementNode("node5", {
    "sql": "SELECT * FROM users WHERE id = {user_id}",
    "output_var": "sql"
})
```

### 3. 工作流执行器 (`WorkflowExecutor`)

```python
from src.core.workflow_executor import WorkflowExecutor

# 创建执行器
executor = WorkflowExecutor("my_workflow")

# 准备环境
executor.prepare_environment()

# 添加节点
executor.add_node(node1)
executor.add_node(node2)

# 添加连接
executor.add_edge("node1", "node2")

# 执行工作流
result = executor.execute({"initial": "data"})

# 保存工作流
executor.save_workflow("workflow.json")
```

## 数据传递机制

### JSON 序列化

节点之间通过 JSON 序列化传递数据：

1. **输入**: 节点从 stdin 读取 JSON 数据
2. **输出**: 节点输出包裹在特殊标记中的 JSON 数据
3. **上下文**: 工作流维护一个全局上下文字典

### 输出格式

```python
print("###JSON_OUTPUT###")
print(json.dumps({"result": value}))
print("###JSON_OUTPUT_END###")
```

### 示例数据流

```
节点1: VariableAssign
输入: {}
输出: {"x": 10}

节点2: VariableAssign  
输入: {"x": 10}
输出: {"x": 10, "y": 20}

节点3: VariableCalc
输入: {"x": 10, "y": 20}
输出: {"x": 10, "y": 20, "result": 50}
```

## 快速开始

### 1. 安装 UV

```bash
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# 或使用 pip
pip install uv
```

### 2. 运行示例

```bash
python examples/simple_workflow_example.py
```

### 3. 创建自己的工作流

```python
from src.core.workflow_executor import WorkflowExecutor
from src.core.node_base import VariableAssignNode, VariableCalcNode

# 创建执行器
executor = WorkflowExecutor("my_first_workflow")

# 准备环境
executor.prepare_environment()

# 创建节点
node1 = VariableAssignNode("input", {
    "variable_name": "temperature",
    "value": "25",
    "value_type": "float"
})

node2 = VariableCalcNode("convert", {
    "expression": "temperature * 9/5 + 32",
    "output_var": "fahrenheit"
})

# 添加节点和连接
executor.add_node(node1)
executor.add_node(node2)
executor.add_edge("input", "convert")

# 执行
result = executor.execute()
print(f"温度转换: {result['temperature']}°C = {result['fahrenheit']}°F")
```

## 在 GUI 中使用

### 添加节点

1. 在工作流画布上右键
2. 选择节点类型
3. 配置节点参数（双击节点）

### 连接节点

1. 从输出端口拖动
2. 连接到目标节点的输入端口

### 执行工作流

1. 点击"执行"按钮
2. 查看执行状态
3. 查看执行结果

## 目录结构

```
Mozikit/
├── src/
│   ├── core/                    # 核心执行引擎
│   │   ├── uv_manager.py       # UV 环境管理
│   │   ├── node_base.py        # 节点基类和类型
│   │   └── workflow_executor.py # 工作流执行器
│   ├── views/                   # UI 组件
│   │   ├── node_graphics.py    # 节点图形组件
│   │   └── workflow_canvas.py  # 工作流画布
│   └── dialogs/                 # 对话框
│       └── settings_dialog.py  # 设置对话框
├── workflows/                   # 工作流数据
│   └── [workflow_name]/
│       ├── .venv/              # 虚拟环境
│       ├── scripts/            # 生成的节点脚本
│       └── workflow.json       # 工作流定义
└── examples/                    # 示例代码
    └── simple_workflow_example.py
```

## 工作流文件格式

```json
{
  "workflow_name": "example_workflow",
  "nodes": [
    {
      "node_id": "node1",
      "node_type": "variable_assign",
      "config": {
        "variable_name": "x",
        "value": "10",
        "value_type": "int"
      },
      "inputs": [],
      "outputs": ["node3"]
    }
  ],
  "edges": [
    ["node1", "node3"],
    ["node2", "node3"]
  ]
}
```

## 性能优化

### UV 共享缓存

所有工作流共享包缓存，首次安装后，后续工作流可以快速复用：

```
workflows/
├── workflow1/.venv/  -> 使用共享缓存
├── workflow2/.venv/  -> 使用共享缓存
└── workflow3/.venv/  -> 使用共享缓存
```

### 节点脚本生成

节点脚本只在需要时生成，后续执行直接使用：

```python
# 首次执行：生成脚本
executor.execute()  # 生成 scripts/node_*.py

# 后续执行：直接使用
executor.execute()  # 直接运行已生成的脚本
```

## 扩展节点类型

创建自定义节点：

```python
from src.core.node_base import NodeBase, NodeType

class MyCustomNode(NodeBase):
    def __init__(self, node_id: str, config: dict = None):
        super().__init__(node_id, NodeType.CUSTOM, config)
    
    def execute(self, input_data: dict) -> dict:
        # 自定义逻辑
        return {"output": "result"}
    
    def _get_script_template(self) -> str:
        execute_code = '''        # 自定义节点逻辑
        output_data = {"output": "result"}'''
        return self._get_base_script_template(execute_code)
```

## 故障排除

### UV 未安装

```bash
# 检查 UV 是否安装
uv --version

# 如果未安装，使用设置对话框中的一键安装
```

### 环境创建失败

```python
# 检查 UV 是否可用
uv_manager = UVManager()
if uv_manager.check_uv_installed():
    print("UV 已安装")
else:
    print("请先安装 UV")
```

### 节点执行超时

```python
# 增加超时时间
result = uv_manager.run_python_script(
    workflow_name,
    script_path,
    input_data,
    timeout=600  # 10分钟
)
```

## 最佳实践

1. **环境隔离**: 每个项目使用独立的工作流
2. **依赖管理**: 在工作流创建时声明所有依赖
3. **错误处理**: 在节点脚本中添加 try-except
4. **日志记录**: 使用 print 输出调试信息（写入 stderr）
5. **数据验证**: 在节点间传递数据前验证格式

## 未来计划

- [ ] 支持条件分支节点
- [ ] 支持循环节点
- [ ] 支持 HTTP 请求节点
- [ ] 支持文件读写节点
- [ ] 支持 Pandas 数据处理节点
- [ ] 支持并行执行
- [ ] 支持节点缓存
- [ ] 支持工作流版本控制

---

**开始构建你的第一个工作流吧！** 🚀

