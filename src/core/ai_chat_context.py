"""
AI 聊天工作流上下文构建器
提取当前工作流的结构信息，序列化为 LLM 可理解的格式
"""

from src.core.log_manager import get_logger

logger = get_logger("ai_chat_context")


def _get_node_name_map():
    """从注册表获取 node_type -> name 映射"""
    try:
        from src.core.node_registry import get_registry
        registry = get_registry()
        name_map = {}
        for node in registry.get_all_nodes():
            nt = node.get("type_str") or (node.get("type").value if node.get("type") and hasattr(node.get("type"), "value") else None)
            if nt:
                name_map[nt] = node.get("name", nt)
        return name_map
    except Exception:
        return {}


class AIChatContextBuilder:
    """工作流上下文构建器"""

    @staticmethod
    def build_context(workflow_tab) -> dict:
        """
        从 WorkflowTabWidget 提取上下文

        Args:
            workflow_tab: WorkflowTabWidget 实例

        Returns:
            dict: 工作流上下文
        """
        if workflow_tab is None:
            return {"workflow_name": "", "nodes": [], "connections": [],
                    "available_node_types": [], "canvas_size": {"width": 800, "height": 600}}

        node_name_map = _get_node_name_map()

        nodes = []
        for node_id, node_item in workflow_tab.nodes.items():
            node_type_val = (node_item.node_type.value
                             if hasattr(node_item.node_type, "value")
                             else str(node_item.node_type))
            pos = node_item.pos()
            nodes.append({
                "node_id": node_id,
                "node_type": node_type_val,
                "title": node_name_map.get(node_type_val, node_type_val),
                "config": node_item.config if hasattr(node_item, "config") else {},
                "position": {"x": pos.x(), "y": pos.y()},
            })

        connections = []
        for from_id, to_id in workflow_tab.connections:
            from_node = workflow_tab.nodes.get(from_id)
            to_node = workflow_tab.nodes.get(to_id)
            connections.append({
                "from_node_id": from_id,
                "from_node_title": (node_name_map.get(
                    from_node.node_type.value if hasattr(from_node.node_type, "value") else str(from_node.node_type),
                    from_id
                ) if from_node else from_id),
                "to_node_id": to_id,
                "to_node_title": (node_name_map.get(
                    to_node.node_type.value if hasattr(to_node.node_type, "value") else str(to_node.node_type),
                    to_id
                ) if to_node else to_id),
            })

        available_node_types = list(node_name_map.keys())

        canvas_size = {"width": 800, "height": 600}
        if hasattr(workflow_tab, "canvas"):
            canvas = workflow_tab.canvas
            canvas_size = {"width": canvas.width(), "height": canvas.height()}

        return {
            "workflow_name": workflow_tab.workflow_name,
            "nodes": nodes,
            "connections": connections,
            "available_node_types": available_node_types,
            "node_name_map": node_name_map,
            "canvas_size": canvas_size,
        }

    @staticmethod
    def build_system_prompt_text(context: dict) -> str:
        """
        将上下文转为自然语言系统提示词片段

        Args:
            context: build_context() 的返回值

        Returns:
            str: 系统提示词文本
        """
        workflow_name = context.get("workflow_name", "未命名")
        nodes = context.get("nodes", [])
        connections = context.get("connections", [])
        available_types = context.get("available_node_types", [])

        lines = [f"当前工作流: '{workflow_name}'"]

        if not nodes:
            lines.append("工作流为空，尚无任何节点。")
        else:
            lines.append(f"包含 {len(nodes)} 个节点:")
            for node in nodes:
                config_summary = ""
                cfg = node.get("config", {})
                if cfg:
                    keys = list(cfg.keys())[:3]
                    config_summary = f", 配置: {keys}"
                pos = node.get("position", {})
                lines.append(
                    f"  - {node['node_id']} ({node['title']}): "
                    f"位置({pos.get('x', 0):.0f}, {pos.get('y', 0):.0f}){config_summary}"
                )

        if connections:
            lines.append(f"连接关系 ({len(connections)} 条):")
            for conn in connections:
                lines.append(f"  - {conn['from_node_title']}({conn['from_node_id']}) → "
                             f"{conn['to_node_title']}({conn['to_node_id']})")
        else:
            lines.append("暂无连接关系。")

        if available_types:
            name_map = context.get("node_name_map", {})
            type_labels = [f"{t}({name_map.get(t, t)})" if name_map.get(t, t) != t else t for t in available_types]
            lines.append(f"可用节点类型: {', '.join(type_labels)}")

        return "\n".join(lines)
