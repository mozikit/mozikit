"""
工作流扫描器
扫描所有工作流文件，建立节点类型到工作流的索引
"""
import json
import os
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass

from src.core.log_manager import get_logger

logger = get_logger("workflow_scanner")


@dataclass
class WorkflowNodeInfo:
    """工作流节点信息"""
    workflow_name: str
    workflow_path: str
    node_ids: List[str]  # 该类型节点在此工作流中的所有ID
    count: int  # 使用次数


@dataclass
class NodeUsageInfo:
    """节点使用信息"""
    node_type: str
    node_name: str  # 中文名称
    node_icon: str
    count: int
    node_ids: List[str]  # 节点ID列表，按顺序


class WorkflowScanner:
    """工作流扫描器"""
    
    # 节点类型到中文名称和图标的映射 — 延迟从注册表获取
    NODE_INFO = {
        "variable_assign": {"name": "变量赋值", "icon": "📝"},
        "variable_calc": {"name": "变量计算", "icon": "🔢"},
        "sqlite_connect": {"name": "SQLite连接", "icon": "🔌"},
        "sql_statement": {"name": "SQL语句", "icon": "📄"},
        "sqlite_execute": {"name": "SQLite执行", "icon": "▶️"},
    }

    @classmethod
    def _get_node_info(cls, node_type_str):
        """获取节点信息，优先从注册表获取"""
        # 先检查本地缓存
        if node_type_str in cls.NODE_INFO:
            return cls.NODE_INFO[node_type_str]
        # 从注册表获取
        try:
            from src.core.node_registry import get_registry
            registry = get_registry()
            node_def = registry.get_node(node_type_str)
            if node_def:
                info = {
                    "name": node_def.name,
                    "icon": node_def.metadata.get("icon", "📦"),
                }
                cls.NODE_INFO[node_type_str] = info
                return info
        except Exception:
            pass
        return {"name": node_type_str, "icon": "📦"}
    
    def __init__(self, workflows_dir: str = "workflows"):
        """
        初始化扫描器
        
        Args:
            workflows_dir: 工作流目录路径
        """
        self.workflows_dir = Path(workflows_dir)
        # 节点类型 -> 使用该节点的工作流列表
        self._node_to_workflows: Dict[str, List[WorkflowNodeInfo]] = {}
        # 工作流名称 -> 节点使用情况
        self._workflow_to_nodes: Dict[str, List[NodeUsageInfo]] = {}
    
    def scan_all_workflows(self) -> None:
        """扫描所有工作流并建立索引"""
        self._node_to_workflows.clear()
        self._workflow_to_nodes.clear()
        
        if not self.workflows_dir.exists():
            return
        
        # 遍历工作流目录
        for item in self.workflows_dir.iterdir():
            if item.is_dir():
                workflow_json = item / "workflow.json"
                if workflow_json.exists() and workflow_json.is_file():
                    self._scan_workflow(workflow_json)
    
    def _scan_workflow(self, workflow_path: Path) -> None:
        """
        扫描单个工作流文件
        
        Args:
            workflow_path: workflow.json 文件路径
        """
        try:
            with open(workflow_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            if not isinstance(data, dict) or 'workflow_name' not in data:
                return
            
            workflow_name = data.get('workflow_name', workflow_path.parent.name)
            nodes = data.get('nodes', [])
            
            # 统计每种节点类型的使用情况
            node_type_count: Dict[str, List[str]] = {}  # type -> [node_ids]
            
            for node in nodes:
                node_type = node.get('node_type', '')
                node_id = node.get('node_id', '')
                
                if node_type and node_id:
                    if node_type not in node_type_count:
                        node_type_count[node_type] = []
                    node_type_count[node_type].append(node_id)
            
            # 更新索引
            for node_type, node_ids in node_type_count.items():
                if node_type not in self._node_to_workflows:
                    self._node_to_workflows[node_type] = []
                
                self._node_to_workflows[node_type].append(WorkflowNodeInfo(
                    workflow_name=workflow_name,
                    workflow_path=str(workflow_path),
                    node_ids=node_ids,
                    count=len(node_ids)
                ))
            
            # 建立工作流到节点的索引（按顺序）
            usage_list: List[NodeUsageInfo] = []
            seen_types: Dict[str, NodeUsageInfo] = {}
            
            for node in nodes:
                node_type = node.get('node_type', '')
                node_id = node.get('node_id', '')
                
                if node_type and node_id:
                    if node_type in seen_types:
                        # 已存在，更新计数和ID列表
                        seen_types[node_type].count += 1
                        seen_types[node_type].node_ids.append(node_id)
                    else:
                        # 首次出现
                        info = self.NODE_INFO.get(node_type, {"name": node_type, "icon": "📦"})
                        usage_info = NodeUsageInfo(
                            node_type=node_type,
                            node_name=info["name"],
                            node_icon=info["icon"],
                            count=1,
                            node_ids=[node_id]
                        )
                        seen_types[node_type] = usage_info
                        usage_list.append(usage_info)
            
            self._workflow_to_nodes[workflow_name] = usage_list
            
        except (json.JSONDecodeError, IOError) as e:
            logger.error("扫描工作流失败: %s - %s", workflow_path, e)
    
    def get_workflows_using_node(self, node_type: str) -> List[WorkflowNodeInfo]:
        """
        获取使用指定节点类型的所有工作流
        
        Args:
            node_type: 节点类型值 (如 "variable_assign")
        
        Returns:
            使用该节点的工作流信息列表
        """
        # 确保索引是最新的
        self.scan_all_workflows()
        return self._node_to_workflows.get(node_type, [])
    
    def get_nodes_in_workflow(self, workflow_name: str) -> List[NodeUsageInfo]:
        """
        获取工作流中使用的节点及使用次数
        
        Args:
            workflow_name: 工作流名称
        
        Returns:
            节点使用信息列表（按首次出现顺序）
        """
        # 确保索引是最新的
        self.scan_all_workflows()
        return self._workflow_to_nodes.get(workflow_name, [])
    
    def get_node_info(self, node_type: str) -> dict:
        """
        获取节点类型的显示信息
        
        Args:
            node_type: 节点类型值
        
        Returns:
            包含 name 和 icon 的字典
        """
        return self.NODE_INFO.get(node_type, {"name": node_type, "icon": "📦"})


def scan_workflows(workflows_dir: str = "workflows") -> list[dict]:
    """扫描工作流目录，返回按更新时间排序的工作流元数据列表。

    Returns:
        按 updated_at 降序排列: [{"name", "path", "created_at", "updated_at"}, ...]
    """
    from datetime import datetime
    base = Path(workflows_dir)
    if not base.exists():
        return []
    result = []
    for item in sorted(base.iterdir()):
        if not item.is_dir():
            continue
        wf = item / "workflow.json"
        if not wf.is_file():
            continue
        try:
            data = json.loads(wf.read_text("utf-8"))
            if not isinstance(data, dict) or "workflow_name" not in data:
                continue
            result.append({
                "name": data.get("workflow_name", item.name),
                "path": str(wf),
                "created_at": data.get("created_at"),
                "updated_at": data.get("updated_at"),
                "node_count": len(data.get("nodes", [])),
            })
        except (json.JSONDecodeError, OSError):
            logger.warning("跳过损坏的工作流文件: %s", wf)

    def _sort_key(w):
        try:
            return datetime.fromisoformat((w["updated_at"] or "").replace("Z", "+00:00"))
        except Exception:
            try:
                return datetime.fromtimestamp(Path(w["path"]).stat().st_mtime)
            except Exception:
                return datetime.min
    result.sort(key=_sort_key, reverse=True)
    return result
