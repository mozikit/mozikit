"""
节点基类和节点类型定义
每个节点都是一个独立的Python脚本
"""

import json
import sys
from abc import ABC, abstractmethod
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional

from src.core.log_manager import get_logger

logger = get_logger("node_base")


class NodeType(Enum):
    """节点类型枚举 — 保留用于兼容已保存工作流的 node_type 字符串值"""

    VARIABLE_ASSIGN = "variable_assign"  # 变量赋值
    VARIABLE_CALC = "variable_calc"  # 变量计算
    SQLITE_CONNECT = "sqlite_connect"  # SQLite连接
    SQLITE_EXECUTE = "sqlite_execute"  # SQLite执行
    SQL_STATEMENT = "sql_statement"  # SQL语句
    PLAYWRIGHT_SCRIPT = "playwright_script"  # Playwright脚本
    TABLE_READER = "table_reader"  # 表格读取
    TABLE_AGGREGATE = "table_aggregate"  # 表格聚合
    TEXT_TEMPLATE_RENDER = "text_template_render"  # 文本模板渲染
    CLIPBOARD_SEND = "clipboard_send"  # 剪贴板发送
    IM_CONTROL = "im_control"  # IM软件控制


class NodeBase(ABC):
    """节点基类"""

    def __init__(
        self, node_id: str, node_type, config: dict = None, version: str = None
    ):
        """
        初始化节点

        Args:
            node_id: 节点唯一ID
            node_type: 节点类型（NodeType 枚举或字符串）
            config: 节点配置
            version: 节点版本号（可选，用于绑定特定版本）
        """
        self.node_id = node_id
        self.node_type = node_type
        self.config = config or {}
        self.version = version  # 节点版本绑定
        self.inputs = []  # 输入节点ID列表
        self.outputs = []  # 输出节点ID列表

    @abstractmethod
    def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行节点逻辑

        Args:
            input_data: 输入数据字典

        Returns:
            输出数据字典
        """
        pass

    def generate_script(self, output_path: str) -> str:
        """
        生成节点的Python脚本文件

        Args:
            output_path: 输出路径

        Returns:
            脚本文件路径
        """
        script_content = self._get_script_template()

        script_path = Path(output_path) / f"node_{self.node_id}.py"
        script_path.parent.mkdir(parents=True, exist_ok=True)

        with open(script_path, "w", encoding="utf-8") as f:
            f.write(script_content)

        return str(script_path)

    @abstractmethod
    def _get_script_template(self) -> str:
        """获取脚本模板"""
        pass

    def to_dict(self) -> dict:
        """转换为字典"""
        result = {
            "node_id": self.node_id,
            "node_type": self.node_type.value
            if hasattr(self.node_type, "value")
            else str(self.node_type),
            "config": self.config,
            "inputs": self.inputs,
            "outputs": self.outputs,
        }
        if self.version:
            result["version"] = self.version
        return result

    @classmethod
    def from_dict(cls, data: dict) -> "NodeBase":
        """从字典创建节点 — 统一通过注册表 + CustomNode"""
        node_type_str = data["node_type"]
        config = data.get("config", {})
        version = data.get("version")

        node = CustomNode(data["node_id"], node_type_str, config, version)

        # 从注册表注入 source_code（优先使用工作流绑定的版本）
        from src.core.node_registry import get_registry

        registry = get_registry()
        node_def = registry.get_node(node_type_str)
        if node_def:
            node.source_code = node_def.source_code
        else:
            logger.warning("未找到节点类型 %s 的定义", node_type_str)

        node.inputs = data.get("inputs", [])
        node.outputs = data.get("outputs", [])
        return node


class CustomNode(NodeBase):
    """外部导入或自定义节点"""

    def __init__(
        self, node_id: str, node_type_str: str, config: dict = None, version: str = None
    ):
        super().__init__(node_id, node_type_str, config, version)
        self.source_code = ""

    def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        在当前进程执行自定义节点
        注意：复杂节点建议在虚拟环境中通过 generate_script 执行
        """
        return {**input_data}

    def _get_script_template(self) -> str:
        """获取脚本模板（使用 BootstrapHook 或直接使用源代码）"""
        if not self.source_code:
            from src.core.node_registry import get_registry

            registry = get_registry()
            self.source_code = registry.get_source_code(self.node_type)

        node_type_str = (
            self.node_type.value
            if hasattr(self.node_type, "value")
            else str(self.node_type)
        )

        # 检查是否有注册的 BootstrapHook（如 Playwright 节点）
        from src.core.node_extension_registries import bootstrap_hooks

        hook = bootstrap_hooks.get(node_type_str)
        if hook:
            execute_func = hook(self.config)
        else:
            execute_func = self.source_code

        return f"""#!/usr/bin/env python
# -*- coding: utf-8 -*-
import json
import sys

# 节点配置
NODE_CONFIG = {repr(self.config)}

def report_progress(percent, message=""):
    percent = max(0, min(100, int(percent)))
    payload = json.dumps({{"percent": percent, "message": message}}, ensure_ascii=False)
    print(f"###PROGRESS##{{payload}}", flush=True)

{execute_func}

def main():
    try:
        input_str = sys.stdin.read()
        input_data = json.loads(input_str) if input_str else {{}}

        class NodeShim:
            def __init__(self, config):
                self.config = config

        shim = NodeShim(NODE_CONFIG)
        output_data = execute(shim, input_data)

        print("###JSON_OUTPUT###")
        print(json.dumps(output_data, ensure_ascii=False))
        print("###JSON_OUTPUT_END###")
    except Exception as e:
        print(f"Error: {{e}}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
"""
