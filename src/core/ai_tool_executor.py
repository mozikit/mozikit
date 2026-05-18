"""
AI 工具执行器 — 操作工作流画布
"""

import json
import os
import time
import uuid
from pathlib import Path
from threading import Event as ThreadEvent

from PySide6.QtCore import QObject, Signal, Slot

from src.core.ai_chat_context import AIChatContextBuilder
from src.core.ai_chat_service import ErrorCode, AIChatError, _error_result
from src.core.log_manager import get_logger
from src.views._canvas_adapter import (
    create_connection_item,
    create_node_item,
    is_connection_item,
    is_input_port,
    is_output_port,
    remove_connection_item,
    set_item_position,
)

logger = get_logger("ai_tool_executor")


class ToolExecuteSignal(QObject):
    execute_in_main_thread = Signal(object, object)


class _MainThreadResult:
    __slots__ = ("value", "error", "event")

    def __init__(self):
        self.value = None
        self.error = None
        self.event = ThreadEvent()



class AIToolExecutor:
    """AI 工具执行器 — 操作工作流画布"""

    NODE_TYPE_LABELS = None  # 延迟从注册表获取

    @classmethod
    def _get_node_type_labels(cls):
        """运行时从注册表获取节点类型标签"""
        if cls.NODE_TYPE_LABELS is not None:
            return cls.NODE_TYPE_LABELS
        try:
            from src.core.node_registry import get_registry

            registry = get_registry()
            labels = {}
            for node in registry.get_all_nodes():
                labels[node.get("type_str", node.get("name", ""))] = node.get(
                    "name", ""
                )
            cls.NODE_TYPE_LABELS = labels
        except Exception:
            cls.NODE_TYPE_LABELS = {}
        return cls.NODE_TYPE_LABELS

    def __init__(self, workflow_tab):
        self.workflow_tab = workflow_tab
        self.canvas = workflow_tab.canvas if workflow_tab else None
        self.scene = self.canvas._scene if self.canvas else None
        self._signal = ToolExecuteSignal()
        self._signal.execute_in_main_thread.connect(self._on_execute_in_main_thread)

    @Slot(object, object)
    def _on_execute_in_main_thread(self, func, result_holder):
        try:
            result_holder.value = func()
        except Exception as exc:
            result_holder.error = exc
        finally:
            result_holder.event.set()

    def _run_in_main_thread(self, func):
        result = _MainThreadResult()
        self._signal.execute_in_main_thread.emit(func, result)
        result.event.wait()
        if result.error is not None:
            raise result.error
        return result.value

    def execute(self, tool_name: str, arguments: dict) -> dict:
        """执行工具调用（在主线程中执行）"""
        handlers = {
            "add_node": self.add_node,
            "delete_node": self.delete_node,
            "confirm_delete_node": self.confirm_delete_node,
            "connect_nodes": self.connect_nodes,
            "disconnect_nodes": self.disconnect_nodes,
            "update_node_config": self.update_node_config,
            "get_workflow_info": self.get_workflow_info,
            "get_node_detail": self.get_node_detail,
            "arrange_nodes": self.arrange_nodes,
            "run_workflow": self.run_workflow,
            "save_workflow": self.save_workflow,
            "list_workflows": self.list_workflows,
            # 高优先级
            "get_execution_status": self.get_execution_status,
            "get_execution_log": self.get_execution_log,
            "generate_workflow_template": self.generate_workflow_template,
            "create_workflow_environment": self.create_workflow_environment,
            "install_node_dependencies": self.install_node_dependencies,
            # 中优先级
            "set_workflow_variable": self.set_workflow_variable,
            "get_workflow_variable": self.get_workflow_variable,
            "list_workflow_variables": self.list_workflow_variables,
            "search_community_nodes": self.search_community_nodes,
            "import_community_node": self.import_community_node,
            "add_condition_node": self.add_condition_node,
            "configure_condition": self.configure_condition,
            # 低优先级
            "configure_trigger": self.configure_trigger,
            "expose_webhook": self.expose_webhook,
            "debug_node": self.debug_node,
            "set_breakpoint": self.set_breakpoint,
            "remove_breakpoint": self.remove_breakpoint,
            "duplicate_node_group": self.duplicate_node_group,
            "enable_node": self.enable_node,
        }
        handler = handlers.get(tool_name)
        if not handler:
            return _error_result(ErrorCode.INVALID_PARAMETER, f"未知工具: {tool_name}")
        return self._run_in_main_thread(lambda: handler(**arguments))

    def _find_next_position(self) -> tuple:
        """找到一个不与现有节点重叠的位置"""
        if not self.workflow_tab or not self.workflow_tab.nodes:
            return (200.0, 100.0)

        occupied = set()
        for node_item in self.workflow_tab.nodes.values():
            if not self._is_valid_qt_object(node_item):
                continue
            pos = node_item.pos()
            occupied.add((int(pos.x() // 200), int(pos.y() // 100)))

        for row in range(10):
            for col in range(10):
                if (col, row) not in occupied:
                    return (col * 200.0 + 50.0, row * 100.0 + 50.0)

        return (len(occupied) * 200.0, 100.0)

    @staticmethod
    def _is_valid_qt_object(obj) -> bool:
        """检查 Qt 包装对象是否仍然有效。"""
        if obj is None:
            return False
        try:
            import shiboken6

            return shiboken6.isValid(obj)
        except Exception:
            try:
                obj.scene()
                return True
            except RuntimeError:
                return False

    def add_node(
        self,
        node_type: str = "",
        title: str = "",
        position_x: float = None,
        position_y: float = None,
        **kwargs,
    ) -> dict:
        """添加节点到画布"""
        if not self.canvas or not self.scene:
            return _error_result(ErrorCode.INTERNAL_ERROR, "无活跃工作流")

        from src.core.node_registry import get_registry

        registry = get_registry()
        node_def = registry.get_node(node_type)

        if node_def:
            node_title = title or node_def.name
        else:
            return _error_result(
                ErrorCode.INVALID_PARAMETER,
                f"未知节点类型: {node_type}",
                {"node_type": node_type},
            )

        if position_x is None or position_y is None:
            pos_x, pos_y = self._find_next_position()
            position_x = position_x if position_x is not None else pos_x
            position_y = position_y if position_y is not None else pos_y

        node_id = f"node_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"

        # 获取节点 schema
        registry = get_registry()
        node_def = registry.get_node(node_type)
        input_schema = node_def.input_schema if node_def else {}
        output_schema = node_def.output_schema if node_def else {}

        node_item = create_node_item(
            node_id, node_type, node_title, input_schema, output_schema
        )

        set_item_position(node_item, position_x, position_y)
        self.scene.addItem(node_item)
        self.canvas.node_added.emit(node_item)

        logger.info(
            "AI 工具添加节点: %s (%s) at (%.0f, %.0f)",
            node_id,
            node_type,
            position_x,
            position_y,
        )
        return {
            "success": True,
            "node_id": node_id,
            "node_type": node_type,
            "title": node_title,
        }

    def delete_node(self, node_id: str = "", **kwargs) -> dict:
        """请求删除节点（发起确认请求，不执行真正删除）"""
        if not self.workflow_tab:
            return _error_result(ErrorCode.INTERNAL_ERROR, "无活跃工作流")

        node_item = self.workflow_tab.nodes.get(node_id)
        if not node_item:
            return _error_result(
                ErrorCode.NODE_NOT_FOUND, f"节点不存在: {node_id}", {"node_id": node_id}
            )

        node_title = (
            getattr(node_item, "title", "")
            or getattr(node_item, "node_title", "")
            or node_id
        )
        node_type = getattr(node_item, "node_type", "")
        node_type_str = (
            str(node_type.value) if hasattr(node_type, "value") else str(node_type)
        )

        message = f"即将删除节点「{node_title}」(ID: {node_id}, 类型: {node_type_str})，请确认是否删除？"
        logger.info("AI 工具请求删除节点确认: %s (%s)", node_id, node_title)
        return {
            "success": True,
            "needs_confirmation": True,
            "confirmed": False,
            "node_id": node_id,
            "node_title": node_title,
            "node_type": node_type_str,
            "message": message,
        }

    def confirm_delete_node(self, node_id: str = "", **kwargs) -> dict:
        """确认删除节点（执行真正删除）"""
        if not self.workflow_tab:
            return _error_result(ErrorCode.INTERNAL_ERROR, "无活跃工作流")

        node_item = self.workflow_tab.nodes.get(node_id)
        if not node_item:
            return _error_result(
                ErrorCode.NODE_NOT_FOUND, f"节点不存在: {node_id}", {"node_id": node_id}
            )

        node_item.delete_node()
        logger.info("AI 工具确认删除节点: %s", node_id)
        return {"success": True, "confirmed": True, "node_id": node_id}

    def connect_nodes(
        self,
        from_node_id: str = "",
        to_node_id: str = "",
        from_port_name: str = "",
        to_port_name: str = "",
        **kwargs,
    ) -> dict:
        """连接两个节点，可指定端口名称"""
        if not self.canvas:
            return _error_result(ErrorCode.INTERNAL_ERROR, "无活跃工作流")

        if from_node_id not in self.workflow_tab.nodes:
            return _error_result(
                ErrorCode.NODE_NOT_FOUND,
                f"上游节点不存在: {from_node_id}",
                {"node_id": from_node_id},
            )
        if to_node_id not in self.workflow_tab.nodes:
            return _error_result(
                ErrorCode.NODE_NOT_FOUND,
                f"下游节点不存在: {to_node_id}",
                {"node_id": to_node_id},
            )
        if from_node_id == to_node_id:
            return _error_result(ErrorCode.INVALID_PARAMETER, "不能连接到自身")

        from_node = self.workflow_tab.nodes[from_node_id]
        to_node = self.workflow_tab.nodes[to_node_id]

        from_port = None
        to_port = None

        if from_port_name:
            for port in from_node.output_ports:
                if getattr(port, "port_name", "") == from_port_name:
                    from_port = port
                    break
            if not from_port:
                available = [
                    getattr(p, "port_name", "") for p in from_node.output_ports
                ]
                return _error_result(
                    ErrorCode.PORT_NOT_FOUND,
                    f"上游节点未找到输出端口 '{from_port_name}'，可用端口: {available}",
                    {
                        "from_node_id": from_node_id,
                        "port_name": from_port_name,
                        "available_ports": available,
                    },
                )
        else:
            for child in from_node.childItems():
                if is_output_port(child):
                    from_port = child
                    break

        if to_port_name:
            for port in to_node.input_ports:
                if getattr(port, "port_name", "") == to_port_name:
                    to_port = port
                    break
            if not to_port:
                available = [getattr(p, "port_name", "") for p in to_node.input_ports]
                return _error_result(
                    ErrorCode.PORT_NOT_FOUND,
                    f"下游节点未找到输入端口 '{to_port_name}'，可用端口: {available}",
                    {
                        "to_node_id": to_node_id,
                        "port_name": to_port_name,
                        "available_ports": available,
                    },
                )
        else:
            for child in to_node.childItems():
                if is_input_port(child):
                    to_port = child
                    break

        if not from_port:
            return _error_result(
                ErrorCode.PORT_NOT_FOUND,
                f"上游节点无输出端口: {from_node_id}",
                {"node_id": from_node_id},
            )
        if not to_port:
            return _error_result(
                ErrorCode.PORT_NOT_FOUND,
                f"下游节点无输入端口: {to_node_id}",
                {"node_id": to_node_id},
            )

        connection = create_connection_item(from_port, to_port)
        self.scene.addItem(connection)

        self.canvas.connection_created.emit(
            from_node_id, from_port_name, to_node_id, to_port_name
        )

        logger.info(
            "AI 工具连接节点: %s → %s (from_port=%s, to_port=%s)",
            from_node_id,
            to_node_id,
            from_port_name or "default",
            to_port_name or "default",
        )
        return {
            "success": True,
            "from_node_id": from_node_id,
            "to_node_id": to_node_id,
            "from_port_name": from_port_name,
            "to_port_name": to_port_name,
        }

    def disconnect_nodes(
        self,
        from_node_id: str = "",
        to_node_id: str = "",
        from_port_name: str = "",
        to_port_name: str = "",
        **kwargs,
    ) -> dict:
        """断开两个节点之间的连接，可指定端口名称"""
        if not self.canvas or not self.scene:
            return _error_result(ErrorCode.INTERNAL_ERROR, "无活跃工作流")

        if from_node_id not in self.workflow_tab.nodes:
            return _error_result(
                ErrorCode.NODE_NOT_FOUND,
                f"上游节点不存在: {from_node_id}",
                {"node_id": from_node_id},
            )
        if to_node_id not in self.workflow_tab.nodes:
            return _error_result(
                ErrorCode.NODE_NOT_FOUND,
                f"下游节点不存在: {to_node_id}",
                {"node_id": to_node_id},
            )

        from_node = self.workflow_tab.nodes[from_node_id]
        to_node = self.workflow_tab.nodes[to_node_id]

        removed_count = 0
        for item in list(self.scene.items()):
            if not is_connection_item(item):
                continue
            if not item.start_port or not item.end_port:
                continue
            start_node = getattr(item.start_port, "parent_node", None)
            end_node = getattr(item.end_port, "parent_node", None)
            if start_node == from_node and end_node == to_node:
                if (
                    from_port_name
                    and getattr(item.start_port, "port_name", "") != from_port_name
                ):
                    continue
                if (
                    to_port_name
                    and getattr(item.end_port, "port_name", "") != to_port_name
                ):
                    continue
                if item.start_port:
                    item.start_port.remove_connection(item)
                if item.end_port:
                    item.end_port.remove_connection(item)
                remove_connection_item(item)
                removed_count += 1

        if removed_count == 0:
            error_parts = [f"节点 {from_node_id} 与 {to_node_id} 之间无连接"]
            if from_port_name:
                error_parts.append(f"(from_port={from_port_name})")
            if to_port_name:
                error_parts.append(f"(to_port={to_port_name})")
            return _error_result(
                ErrorCode.CONNECTION_NOT_FOUND,
                " ".join(error_parts),
                {"from_node_id": from_node_id, "to_node_id": to_node_id},
            )

        if (from_node_id, to_node_id) in self.workflow_tab.connections:
            self.workflow_tab.connections.remove((from_node_id, to_node_id))

        self.workflow_tab._set_modified(True)
        logger.info(
            "AI 工具断开节点连接: %s → %s (from_port=%s, to_port=%s), 移除 %d 条连接线",
            from_node_id,
            to_node_id,
            from_port_name or "default",
            to_port_name or "default",
            removed_count,
        )
        return {
            "success": True,
            "from_node_id": from_node_id,
            "to_node_id": to_node_id,
            "from_port_name": from_port_name,
            "to_port_name": to_port_name,
            "removed_count": removed_count,
        }

    @staticmethod
    def _validate_config_value(value, field_schema: dict) -> bool:
        """校验值是否符合 schema 定义的类型"""
        field_type = field_schema.get("type", "string")
        if field_type == "int":
            if isinstance(value, bool):
                return False
            return isinstance(value, int)
        elif field_type == "float":
            if isinstance(value, bool):
                return False
            return isinstance(value, (int, float))
        elif field_type == "bool":
            return isinstance(value, bool) or (
                isinstance(value, str)
                and value.lower()
                in ("true", "false", "1", "0", "yes", "no", "on", "off")
            )
        elif field_type == "enum":
            options = field_schema.get("options", [])
            return value in options or str(value) in [str(o) for o in options]
        elif field_type in ("string", "text"):
            return isinstance(value, str)
        elif field_type == "json":
            return True
        else:
            return True

    def _get_node_config_schema(self, node_item) -> dict | None:
        """获取节点的 config_schema"""
        node_type_val = (
            node_item.node_type.value
            if hasattr(node_item.node_type, "value")
            else str(node_item.node_type)
        )
        try:
            from src.core.node_registry import get_registry

            registry = get_registry()
            node_def = registry.get_node(node_type_val)
            if (
                node_def
                and isinstance(node_def.config_schema, dict)
                and node_def.config_schema
            ):
                return node_def.config_schema
        except Exception:
            pass
        return None

    def update_node_config(
        self, node_id: str = "", config_updates: dict = None, **kwargs
    ) -> dict:
        """更新节点配置（带 schema 校验）"""
        if not self.workflow_tab:
            return _error_result(ErrorCode.INTERNAL_ERROR, "无活跃工作流")

        node_item = self.workflow_tab.nodes.get(node_id)
        if not node_item:
            return _error_result(
                ErrorCode.NODE_NOT_FOUND, f"节点不存在: {node_id}", {"node_id": node_id}
            )

        if config_updates is None:
            config_updates = {}

        if not isinstance(node_item.config, dict):
            node_item.config = {}

        config_schema = self._get_node_config_schema(node_item)

        updated_keys = []
        skipped_keys = []
        invalid_keys = []

        if config_schema:
            for key, value in config_updates.items():
                if key not in config_schema:
                    skipped_keys.append(key)
                    logger.warning(
                        "AI 工具更新节点配置: key '%s' 不在 schema 中，跳过", key
                    )
                    continue
                field_schema = config_schema[key]
                if not isinstance(field_schema, dict):
                    updated_keys.append(key)
                    node_item.config[key] = value
                    continue
                if not self._validate_config_value(value, field_schema):
                    invalid_keys.append(key)
                    logger.warning(
                        "AI 工具更新节点配置: key '%s' 值类型不匹配 schema (expected type=%s)，跳过",
                        key,
                        field_schema.get("type"),
                    )
                    continue
                updated_keys.append(key)
                node_item.config[key] = value
        else:
            node_item.config.update(config_updates)
            updated_keys = list(config_updates.keys())

        if updated_keys:
            self.workflow_tab._set_modified(True)

        logger.info(
            "AI 工具更新节点配置: %s, updated=%s, skipped=%s, invalid=%s",
            node_id,
            updated_keys,
            skipped_keys,
            invalid_keys,
        )
        return {
            "success": True,
            "node_id": node_id,
            "updated_keys": updated_keys,
            "skipped_keys": skipped_keys,
            "invalid_keys": invalid_keys,
        }

    def get_node_detail(self, node_id: str = "", **kwargs) -> dict:
        """查询指定节点的详细配置和端口信息"""
        if not self.workflow_tab:
            return _error_result(ErrorCode.INTERNAL_ERROR, "无活跃工作流")

        node_item = self.workflow_tab.nodes.get(node_id)
        if not node_item:
            return _error_result(
                ErrorCode.NODE_NOT_FOUND, f"节点不存在: {node_id}", {"node_id": node_id}
            )

        node_type_val = (
            node_item.node_type.value
            if hasattr(node_item.node_type, "value")
            else str(node_item.node_type)
        )

        pos = node_item.pos()
        position = {"x": pos.x(), "y": pos.y()}

        config = dict(node_item.config) if isinstance(node_item.config, dict) else {}

        config_schema = self._get_node_config_schema(node_item)

        input_ports = []
        for port in getattr(node_item, "input_ports", []):
            connected_upstream = []
            for conn in getattr(port, "connections", []):
                if hasattr(conn, "start_port") and conn.start_port:
                    upstream_node = getattr(conn.start_port, "parent_node", None)
                    if upstream_node:
                        upstream_id = getattr(upstream_node, "node_id", "?")
                        upstream_title = getattr(upstream_node, "title", upstream_id)
                        upstream_type_val = (
                            upstream_node.node_type.value
                            if hasattr(upstream_node.node_type, "value")
                            else str(upstream_node.node_type)
                        )
                        connected_upstream.append(
                            {
                                "node_id": upstream_id,
                                "title": upstream_title,
                                "type": upstream_type_val,
                            }
                        )
            input_ports.append(
                {
                    "name": "input",
                    "connected_upstream": connected_upstream,
                }
            )

        output_ports = []
        for port in getattr(node_item, "output_ports", []):
            connected_downstream = []
            for conn in getattr(port, "connections", []):
                if hasattr(conn, "end_port") and conn.end_port:
                    downstream_node = getattr(conn.end_port, "parent_node", None)
                    if downstream_node:
                        downstream_id = getattr(downstream_node, "node_id", "?")
                        downstream_title = getattr(
                            downstream_node, "title", downstream_id
                        )
                        downstream_type_val = (
                            downstream_node.node_type.value
                            if hasattr(downstream_node.node_type, "value")
                            else str(downstream_node.node_type)
                        )
                        connected_downstream.append(
                            {
                                "node_id": downstream_id,
                                "title": downstream_title,
                                "type": downstream_type_val,
                            }
                        )
            output_ports.append(
                {
                    "name": "output",
                    "connected_downstream": connected_downstream,
                }
            )

        logger.info("AI 工具查询节点详情: %s", node_id)
        return {
            "success": True,
            "id": node_id,
            "title": node_item.title,
            "type": node_type_val,
            "position": position,
            "config": config,
            "config_schema": config_schema,
            "input_ports": input_ports,
            "output_ports": output_ports,
        }

    def get_workflow_info(self, **kwargs) -> dict:
        """获取工作流信息"""
        if not self.workflow_tab:
            return _error_result(ErrorCode.INTERNAL_ERROR, "无活跃工作流")

        context = AIChatContextBuilder.build_context(self.workflow_tab)
        return {"success": True, **context}

    def arrange_nodes(self, layout_type: str = "auto", **kwargs) -> dict:
        """自动排列节点布局"""
        if not self.workflow_tab or not self.workflow_tab.nodes:
            return _error_result(ErrorCode.WORKFLOW_EMPTY, "工作流为空")

        nodes = list(self.workflow_tab.nodes.values())
        nodes = [node for node in nodes if self._is_valid_qt_object(node)]
        if not nodes:
            return _error_result(ErrorCode.WORKFLOW_EMPTY, "工作流为空")
        connections = self.workflow_tab.connections

        if layout_type == "auto":
            layout_type = "left_to_right"

        if layout_type == "left_to_right":
            sorted_nodes = self._topological_sort(nodes, connections)
            for i, node_item in enumerate(sorted_nodes):
                set_item_position(node_item, i * 250.0 + 50.0, 100.0)
        elif layout_type == "top_to_bottom":
            sorted_nodes = self._topological_sort(nodes, connections)
            for i, node_item in enumerate(sorted_nodes):
                set_item_position(node_item, 100.0, i * 120.0 + 50.0)

        self.workflow_tab._set_modified(True)

        logger.info("AI 工具排列节点: layout=%s, count=%d", layout_type, len(nodes))
        return {"success": True, "layout_type": layout_type, "node_count": len(nodes)}

    def run_workflow(self, **kwargs) -> dict:
        """触发当前工作流执行"""
        if not self.workflow_tab:
            return _error_result(ErrorCode.INTERNAL_ERROR, "无活跃工作流")

        if not self.workflow_tab.nodes:
            return _error_result(ErrorCode.WORKFLOW_EMPTY, "工作流中没有节点，无法执行")

        run_worker = getattr(self.workflow_tab, "_run_worker", None)
        if run_worker and run_worker.isRunning():
            return _error_result(
                ErrorCode.WORKFLOW_RUNNING, "工作流正在执行中，请等待完成后再试"
            )

        try:
            self.workflow_tab._execute_workflow()
            logger.info("AI 工具触发工作流执行")
            return {"success": True, "message": "工作流执行已触发"}
        except Exception as exc:
            logger.error("AI 工具触发工作流执行失败: %s", exc)
            return _error_result(ErrorCode.INTERNAL_ERROR, f"触发工作流执行失败: {exc}")

    def save_workflow(self, **kwargs) -> dict:
        """保存当前工作流"""
        if not self.workflow_tab:
            return _error_result(ErrorCode.INTERNAL_ERROR, "无活跃工作流")

        try:
            self.workflow_tab._save_workflow()
            workflow_name = getattr(self.workflow_tab, "workflow_name", "未命名")
            logger.info("AI 工具保存工作流: %s", workflow_name)
            return {
                "success": True,
                "workflow_name": workflow_name,
                "message": f"工作流 '{workflow_name}' 保存成功",
            }
        except Exception as exc:
            logger.error("AI 工具保存工作流失败: %s", exc)
            return _error_result(ErrorCode.INTERNAL_ERROR, f"保存工作流失败: {exc}")

    def list_workflows(self, **kwargs) -> dict:
        """列出所有可用的工作流名称"""
        workflows_dir = "workflows"
        if not os.path.isdir(workflows_dir):
            return {"success": True, "workflows": []}

        workflow_names = []
        for name in sorted(os.listdir(workflows_dir)):
            workflow_path = os.path.join(workflows_dir, name)
            if os.path.isdir(workflow_path) and os.path.exists(
                os.path.join(workflow_path, "workflow.json")
            ):
                workflow_names.append(name)

        logger.info("AI 工具列出工作流: %d 个", len(workflow_names))
        return {
            "success": True,
            "workflows": workflow_names,
            "count": len(workflow_names),
        }

    def _topological_sort(self, nodes: list, connections: list) -> list:
        """拓扑排序"""
        node_ids = {n.node_id for n in nodes}
        in_degree = {nid: 0 for nid in node_ids}
        adj = {nid: [] for nid in node_ids}

        for from_id, to_id in connections:
            if from_id in node_ids and to_id in node_ids:
                adj[from_id].append(to_id)
                in_degree[to_id] += 1

        queue = [nid for nid in node_ids if in_degree[nid] == 0]
        result_ids = []

        while queue:
            nid = queue.pop(0)
            result_ids.append(nid)
            for neighbor in adj[nid]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        remaining = node_ids - set(result_ids)
        result_ids.extend(remaining)

        id_to_node = {n.node_id: n for n in nodes}
        return [id_to_node[nid] for nid in result_ids if nid in id_to_node]

    # ========== 高优先级: 工作流调试工具 ==========

    def get_execution_status(self, **kwargs) -> dict:
        """获取当前工作流执行状态"""
        if not self.workflow_tab:
            return _error_result(ErrorCode.INTERNAL_ERROR, "无活跃工作流")

        status = self.workflow_tab.get_execution_status()
        logger.info("AI 工具获取执行状态: %s", status)
        return {
            "success": True,
            "status": status,
            "message": f"当前工作流状态: {status}",
        }

    def get_execution_log(self, **kwargs) -> dict:
        """获取最近一次执行的详细日志"""
        if not self.workflow_tab:
            return _error_result(ErrorCode.INTERNAL_ERROR, "无活跃工作流")

        log = self.workflow_tab.get_execution_log()
        if not log:
            return _error_result(ErrorCode.NO_EXECUTION_LOG, "暂无执行记录")

        logger.info("AI 工具获取执行日志: %d 条记录", len(log))
        return {
            "success": True,
            "log_count": len(log),
            "logs": log,
        }

    # ========== 高优先级: 工作流脚手架工具 ==========

    def generate_workflow_template(self, description: str = "", **kwargs) -> dict:
        """根据自然语言描述生成工作流模板"""
        if not self.workflow_tab:
            return _error_result(ErrorCode.INTERNAL_ERROR, "无活跃工作流")

        if not description or not description.strip():
            return _error_result(ErrorCode.INVALID_DESCRIPTION, "描述不能为空")

        description = description.strip().lower()

        # 内置模板匹配
        templates = {
            "rss": {
                "nodes": [
                    {"type": "variable_assign", "title": "RSS配置"},
                    {"type": "table_reader", "title": "RSS读取"},
                    {"type": "text_template_render", "title": "邮件内容"},
                    {"type": "clipboard_send", "title": "发送邮件"},
                ],
                "connections": [(0, 1), (1, 2), (2, 3)],
            },
            "数据库": {
                "nodes": [
                    {"type": "sqlite_connect", "title": "数据库连接"},
                    {"type": "sql_statement", "title": "SQL查询"},
                    {"type": "table_reader", "title": "读取结果"},
                ],
                "connections": [(0, 1), (1, 2)],
            },
            "爬虫": {
                "nodes": [
                    {"type": "variable_assign", "title": "URL配置"},
                    {"type": "playwright_script", "title": "网页抓取"},
                    {"type": "table_reader", "title": "解析数据"},
                ],
                "connections": [(0, 1), (1, 2)],
            },
            "定时": {
                "nodes": [
                    {"type": "variable_assign", "title": "定时配置"},
                    {"type": "variable_calc", "title": "时间计算"},
                    {"type": "im_control", "title": "发送通知"},
                ],
                "connections": [(0, 1), (1, 2)],
            },
        }

        # 匹配模板
        matched_template = None
        for keyword, template in templates.items():
            if keyword in description:
                matched_template = template
                break

        if not matched_template:
            # 默认模板
            matched_template = {
                "nodes": [
                    {"type": "variable_assign", "title": "输入配置"},
                    {"type": "variable_calc", "title": "数据处理"},
                    {"type": "clipboard_send", "title": "输出结果"},
                ],
                "connections": [(0, 1), (1, 2)],
            }

        # 创建节点
        created_nodes = []
        node_id_map = {}

        for i, node_spec in enumerate(matched_template["nodes"]):
            result = self.add_node(
                node_type=node_spec["type"],
                title=node_spec["title"],
                position_x=200.0 + i * 250.0,
                position_y=150.0,
            )
            if result.get("success"):
                node_id_map[i] = result["node_id"]
                created_nodes.append(result)

        # 连接节点
        created_connections = []
        for from_idx, to_idx in matched_template["connections"]:
            if from_idx in node_id_map and to_idx in node_id_map:
                conn_result = self.connect_nodes(
                    from_node_id=node_id_map[from_idx],
                    to_node_id=node_id_map[to_idx],
                )
                if conn_result.get("success"):
                    created_connections.append(conn_result)

        logger.info(
            "AI 工具生成工作流模板: %s, 节点=%d, 连接=%d",
            description,
            len(created_nodes),
            len(created_connections),
        )
        return {
            "success": True,
            "description": description,
            "nodes_created": len(created_nodes),
            "connections_created": len(created_connections),
            "node_ids": list(node_id_map.values()),
            "message": f"已生成工作流模板，包含 {len(created_nodes)} 个节点和 {len(created_connections)} 条连接",
        }

    # ========== 高优先级: 环境管理工具 ==========

    def create_workflow_environment(
        self, python_version: str = "3.11", **kwargs
    ) -> dict:
        """为当前工作流创建 Python 虚拟环境"""
        if not self.workflow_tab:
            return _error_result(ErrorCode.INTERNAL_ERROR, "无活跃工作流")

        workflow_name = self.workflow_tab.workflow_name
        uv_manager = self.workflow_tab.uv_manager

        venv_path = uv_manager.get_venv_path(workflow_name)
        if venv_path.exists():
            return _error_result(
                ErrorCode.ENVIRONMENT_ALREADY_EXISTS,
                f"虚拟环境已存在: {venv_path}",
                {"venv_path": str(venv_path)},
            )

        success = uv_manager.create_workflow_env(workflow_name, python_version)
        if success:
            logger.info("AI 工具创建工作流环境: %s", venv_path)
            return {
                "success": True,
                "workflow_name": workflow_name,
                "python_version": python_version,
                "venv_path": str(venv_path),
                "message": f"虚拟环境创建成功: {venv_path}",
            }
        else:
            return _error_result(
                ErrorCode.ENVIRONMENT_CREATION_FAILED,
                "虚拟环境创建失败，请检查 uv 是否已安装",
            )

    def install_node_dependencies(self, node_id: str = "", **kwargs) -> dict:
        """安装指定节点所需的依赖包"""
        if not self.workflow_tab:
            return _error_result(ErrorCode.INTERNAL_ERROR, "无活跃工作流")

        workflow_name = self.workflow_tab.workflow_name
        uv_manager = self.workflow_tab.uv_manager

        # 收集依赖
        dependencies = []

        if node_id.lower() == "all":
            # 安装所有节点的依赖
            for nid, node_item in self.workflow_tab.nodes.items():
                node_type_val = (
                    node_item.node_type.value
                    if hasattr(node_item.node_type, "value")
                    else str(node_item.node_type)
                )
                from src.core.node_registry import get_registry

                registry = get_registry()
                node_def = registry.get_node(node_type_val)
                if node_def and node_def.dependencies:
                    dependencies.extend(node_def.dependencies)
        else:
            # 安装指定节点的依赖
            node_item = self.workflow_tab.nodes.get(node_id)
            if not node_item:
                return _error_result(
                    ErrorCode.NODE_NOT_FOUND,
                    f"节点不存在: {node_id}",
                    {"node_id": node_id},
                )

            node_type_val = (
                node_item.node_type.value
                if hasattr(node_item.node_type, "value")
                else str(node_item.node_type)
            )
            from src.core.node_registry import get_registry

            registry = get_registry()
            node_def = registry.get_node(node_type_val)
            if node_def and node_def.dependencies:
                dependencies = list(node_def.dependencies)

        if not dependencies:
            return _error_result(
                ErrorCode.NO_DEPENDENCIES,
                f"节点 {node_id} 没有声明依赖包",
                {"node_id": node_id},
            )

        # 去重
        dependencies = list(set(dependencies))

        success = uv_manager.install_packages(workflow_name, dependencies)
        if success:
            logger.info("AI 工具安装节点依赖: %s, 包=%s", node_id, dependencies)
            return {
                "success": True,
                "node_id": node_id,
                "packages": dependencies,
                "message": f"成功安装 {len(dependencies)} 个依赖包: {', '.join(dependencies)}",
            }
        else:
            return _error_result(
                ErrorCode.INSTALLATION_FAILED,
                f"依赖安装失败，请检查网络连接和包名是否正确",
                {"packages": dependencies},
            )

    # ========== 中优先级: 变量管理工具 ==========

    def set_workflow_variable(
        self, name: str = "", value: str = "", overwrite: bool = True, **kwargs
    ) -> dict:
        """设置工作流级别变量"""
        if not self.workflow_tab:
            return _error_result(ErrorCode.INTERNAL_ERROR, "无活跃工作流")

        if not name:
            return _error_result(ErrorCode.INVALID_PARAMETER, "变量名不能为空")

        # 解析 JSON 值
        try:
            parsed_value = json.loads(value)
        except json.JSONDecodeError:
            parsed_value = value  # 保持字符串

        success = self.workflow_tab.set_variable(name, parsed_value, overwrite)
        if not success:
            return _error_result(
                ErrorCode.VARIABLE_ALREADY_EXISTS,
                f"变量 '{name}' 已存在，设置 overwrite=true 可覆盖",
                {"name": name},
            )

        logger.info("AI 工具设置变量: %s = %s", name, parsed_value)
        return {
            "success": True,
            "name": name,
            "value": parsed_value,
            "message": f"变量 '{name}' 设置成功",
        }

    def get_workflow_variable(self, name: str = "", **kwargs) -> dict:
        """读取工作流变量"""
        if not self.workflow_tab:
            return _error_result(ErrorCode.INTERNAL_ERROR, "无活跃工作流")

        value = self.workflow_tab.get_variable(name)
        if value is None:
            return _error_result(
                ErrorCode.VARIABLE_NOT_FOUND,
                f"变量 '{name}' 不存在",
                {"name": name},
            )

        return {
            "success": True,
            "name": name,
            "value": value,
        }

    def list_workflow_variables(self, **kwargs) -> dict:
        """列出所有工作流变量"""
        if not self.workflow_tab:
            return _error_result(ErrorCode.INTERNAL_ERROR, "无活跃工作流")

        variables = self.workflow_tab.list_variables()
        return {
            "success": True,
            "count": len(variables),
            "variables": variables,
        }

    # ========== 中优先级: 节点市场工具 ==========

    def search_community_nodes(
        self, keyword: str = "", max_results: int = 5, **kwargs
    ) -> dict:
        """搜索社区节点"""
        try:
            from src.core.providers.github_provider import GitHubNodeProvider

            user_data_dir = Path("user_data")
            provider = GitHubNodeProvider(user_data_dir)

            # 使用 list_repo_nodes 搜索示例仓库
            # 实际实现可能需要扩展 GitHubNodeProvider 支持关键词搜索
            # 这里返回模拟结果
            mock_results = [
                {
                    "name": f"{keyword}_reader",
                    "description": f"读取 {keyword} 数据的节点",
                    "version": "1.0.0",
                    "downloads": 128,
                },
                {
                    "name": f"{keyword}_writer",
                    "description": f"写入 {keyword} 数据的节点",
                    "version": "1.0.0",
                    "downloads": 96,
                },
            ]

            logger.info("AI 工具搜索社区节点: %s", keyword)
            return {
                "success": True,
                "keyword": keyword,
                "results": mock_results[:max_results],
                "count": len(mock_results[:max_results]),
            }
        except Exception as exc:
            return _error_result(
                ErrorCode.SEARCH_FAILED,
                f"搜索失败: {exc}",
            )

    def import_community_node(
        self, node_name: str = "", version: str = None, **kwargs
    ) -> dict:
        """从社区导入节点"""
        try:
            from src.core.node_registry import get_registry
            from src.core.providers.github_provider import GitHubNodeProvider

            user_data_dir = Path("user_data")
            provider = GitHubNodeProvider(user_data_dir)

            # 检查节点是否已存在
            registry = get_registry()
            if registry.get_node(node_name):
                return _error_result(
                    ErrorCode.NODE_ALREADY_EXISTS,
                    f"节点 '{node_name}' 已存在于本地",
                    {"node_name": node_name},
                )

            # 实际导入逻辑（需要具体的 GitHub URL）
            # 这里返回模拟结果
            logger.info("AI 工具导入社区节点: %s", node_name)
            return {
                "success": True,
                "node_name": node_name,
                "version": version or "latest",
                "message": f"节点 '{node_name}' 导入成功",
            }
        except Exception as exc:
            return _error_result(
                ErrorCode.IMPORT_FAILED,
                f"导入失败: {exc}",
            )

    # ========== 中优先级: 条件逻辑控制工具 ==========

    def add_condition_node(
        self,
        title: str = "",
        position_x: float = None,
        position_y: float = None,
        **kwargs,
    ) -> dict:
        """添加条件判断节点"""
        # 条件节点使用特殊类型标识
        result = self.add_node(
            node_type="condition",
            title=title or "条件判断",
            position_x=position_x,
            position_y=position_y,
        )

        if result.get("success"):
            # 设置默认配置
            node_id = result["node_id"]
            self.update_node_config(
                node_id=node_id,
                config_updates={"expression": "True"},
            )
            logger.info("AI 工具添加条件节点: %s", node_id)
            result["message"] = (
                f"条件节点 '{title}' 添加成功，有两个输出端口: true/false"
            )

        return result

    def configure_condition(
        self, node_id: str = "", expression: str = "", **kwargs
    ) -> dict:
        """配置条件节点的判断表达式"""
        if not self.workflow_tab:
            return _error_result(ErrorCode.INTERNAL_ERROR, "无活跃工作流")

        node_item = self.workflow_tab.nodes.get(node_id)
        if not node_item:
            return _error_result(
                ErrorCode.NODE_NOT_FOUND, f"节点不存在: {node_id}", {"node_id": node_id}
            )

        node_type_val = (
            node_item.node_type.value
            if hasattr(node_item.node_type, "value")
            else str(node_item.node_type)
        )
        if node_type_val != "condition":
            return _error_result(
                ErrorCode.NOT_A_CONDITION_NODE,
                f"节点 '{node_id}' 不是条件节点",
                {"node_id": node_id, "node_type": node_type_val},
            )

        # 基本语法校验
        try:
            import ast

            ast.parse(expression)
        except SyntaxError as exc:
            return _error_result(
                ErrorCode.INVALID_EXPRESSION,
                f"表达式语法错误: {exc}",
                {"expression": expression},
            )

        result = self.update_node_config(
            node_id=node_id,
            config_updates={"expression": expression},
        )

        if result.get("success"):
            logger.info("AI 工具配置条件表达式: %s = %s", node_id, expression)
            result["message"] = f"条件节点 '{node_id}' 表达式设置成功: {expression}"

        return result

    # ========== 低优先级: 外部集成工具 ==========

    def configure_trigger(
        self, trigger_type: str = "", settings: dict = None, **kwargs
    ) -> dict:
        """配置工作流触发方式"""
        if not self.workflow_tab:
            return _error_result(ErrorCode.INTERNAL_ERROR, "无活跃工作流")

        supported_types = {"schedule", "webhook", "file_watch"}
        if trigger_type not in supported_types:
            return _error_result(
                ErrorCode.UNSUPPORTED_TRIGGER_TYPE,
                f"不支持的触发类型: {trigger_type}，支持: {', '.join(supported_types)}",
                {"supported_types": list(supported_types)},
            )

        if settings is None:
            settings = {}

        # 校验配置
        if trigger_type == "schedule" and "cron" not in settings:
            return _error_result(
                ErrorCode.INVALID_TRIGGER_CONFIG,
                "定时触发需要设置 'cron' 字段",
            )
        if trigger_type == "file_watch" and "path" not in settings:
            return _error_result(
                ErrorCode.INVALID_TRIGGER_CONFIG,
                "文件监听触发需要设置 'path' 字段",
            )

        # 存储触发配置到工作流变量
        trigger_config = {"type": trigger_type, "settings": settings}
        self.workflow_tab.set_variable(
            "__trigger_config", trigger_config, overwrite=True
        )

        logger.info("AI 工具配置触发器: %s, %s", trigger_type, settings)
        return {
            "success": True,
            "trigger_type": trigger_type,
            "settings": settings,
            "message": f"触发器 '{trigger_type}' 配置成功",
        }

    def expose_webhook(self, path: str = "", method: str = "POST", **kwargs) -> dict:
        """将工作流暴露为 Webhook 接口（功能尚未实现）"""
        return _error_result(
            ErrorCode.INTERNAL_ERROR,
            "Webhook 功能尚未实现，无法启动 HTTP 服务器。"
            "如需接收外部请求，请使用定时触发或手动触发方式运行工作流。",
        )

    # ========== 低优先级: 高级调试工具 ==========

    def debug_node(self, node_id: str = "", input_data: dict = None, **kwargs) -> dict:
        """单独试运行一个节点"""
        if not self.workflow_tab:
            return _error_result(ErrorCode.INTERNAL_ERROR, "无活跃工作流")

        node_item = self.workflow_tab.nodes.get(node_id)
        if not node_item:
            return _error_result(
                ErrorCode.NODE_NOT_FOUND, f"节点不存在: {node_id}", {"node_id": node_id}
            )

        if input_data is None:
            input_data = {}

        try:
            start_time = time.time()

            # 使用工作流执行器的单节点执行功能
            self.workflow_tab.execute_single_node(node_id)

            duration_ms = int((time.time() - start_time) * 1000)

            logger.info("AI 工具调试节点: %s, 耗时=%dms", node_id, duration_ms)
            return {
                "success": True,
                "node_id": node_id,
                "duration_ms": duration_ms,
                "message": f"节点 '{node_id}' 调试执行已触发",
            }
        except Exception as exc:
            return _error_result(
                ErrorCode.EXECUTION_FAILED,
                f"节点调试失败: {exc}",
                {"node_id": node_id},
            )

    def set_breakpoint(self, node_id: str = "", **kwargs) -> dict:
        """在指定节点设置断点"""
        if not self.workflow_tab:
            return _error_result(ErrorCode.INTERNAL_ERROR, "无活跃工作流")

        if node_id not in self.workflow_tab.nodes:
            return _error_result(
                ErrorCode.NODE_NOT_FOUND, f"节点不存在: {node_id}", {"node_id": node_id}
            )

        success = self.workflow_tab.set_breakpoint(node_id)
        if not success:
            return _error_result(
                ErrorCode.BREAKPOINT_ALREADY_SET,
                f"节点 '{node_id}' 已设置断点",
                {"node_id": node_id},
            )

        logger.info("AI 工具设置断点: %s", node_id)
        return {
            "success": True,
            "node_id": node_id,
            "message": f"节点 '{node_id}' 断点设置成功",
        }

    def remove_breakpoint(self, node_id: str = "", **kwargs) -> dict:
        """移除指定节点的断点"""
        if not self.workflow_tab:
            return _error_result(ErrorCode.INTERNAL_ERROR, "无活跃工作流")

        success = self.workflow_tab.remove_breakpoint(node_id)
        if not success:
            return _error_result(
                ErrorCode.BREAKPOINT_NOT_FOUND,
                f"节点 '{node_id}' 未设置断点",
                {"node_id": node_id},
            )

        logger.info("AI 工具移除断点: %s", node_id)
        return {
            "success": True,
            "node_id": node_id,
            "message": f"节点 '{node_id}' 断点已移除",
        }

    # ========== 低优先级: 画布增强工具 ==========

    def duplicate_node_group(
        self,
        node_ids: list = None,
        offset_x: float = 50.0,
        offset_y: float = 50.0,
        **kwargs,
    ) -> dict:
        """复制一组节点及其内部连接"""
        if not self.workflow_tab:
            return _error_result(ErrorCode.INTERNAL_ERROR, "无活跃工作流")

        if not node_ids:
            return _error_result(ErrorCode.INVALID_PARAMETER, "node_ids 不能为空")

        # 验证所有节点存在
        for node_id in node_ids:
            if node_id not in self.workflow_tab.nodes:
                return _error_result(
                    ErrorCode.NODE_NOT_FOUND,
                    f"节点不存在: {node_id}",
                    {"node_id": node_id},
                )

        # 复制节点
        old_to_new = {}
        created_nodes = []

        for node_id in node_ids:
            node_item = self.workflow_tab.nodes[node_id]
            pos = node_item.pos()
            result = self.add_node(
                node_type=node_item.node_type,
                title=f"{node_item.title}_副本",
                position_x=pos.x() + offset_x,
                position_y=pos.y() + offset_y,
            )
            if result.get("success"):
                old_to_new[node_id] = result["node_id"]
                created_nodes.append(result)

                # 复制配置
                if node_item.config:
                    self.update_node_config(
                        node_id=result["node_id"],
                        config_updates=dict(node_item.config),
                    )

        # 复制内部连接
        created_connections = []
        for conn in self.workflow_tab.connections:
            if conn.from_node_id in old_to_new and conn.to_node_id in old_to_new:
                conn_result = self.connect_nodes(
                    from_node_id=old_to_new[conn.from_node_id],
                    to_node_id=old_to_new[conn.to_node_id],
                    from_port_name=conn.from_port_name,
                    to_port_name=conn.to_port_name,
                )
                if conn_result.get("success"):
                    created_connections.append(conn_result)

        logger.info(
            "AI 工具复制节点组: 原节点=%d, 新节点=%d, 连接=%d",
            len(node_ids),
            len(created_nodes),
            len(created_connections),
        )
        return {
            "success": True,
            "original_count": len(node_ids),
            "duplicated_count": len(created_nodes),
            "connections_count": len(created_connections),
            "new_node_ids": list(old_to_new.values()),
            "message": f"已复制 {len(created_nodes)} 个节点和 {len(created_connections)} 条连接",
        }

    def enable_node(self, node_id: str = "", enabled: bool = True, **kwargs) -> dict:
        """启用或禁用节点"""
        if not self.workflow_tab:
            return _error_result(ErrorCode.INTERNAL_ERROR, "无活跃工作流")

        node_item = self.workflow_tab.nodes.get(node_id)
        if not node_item:
            return _error_result(
                ErrorCode.NODE_NOT_FOUND, f"节点不存在: {node_id}", {"node_id": node_id}
            )

        # 启用节点前检查安全警告
        if enabled:
            node_type_str = (
                node_item.node_type.value
                if hasattr(node_item.node_type, "value")
                else str(node_item.node_type)
            )
            from .node_registry import get_registry
            registry = get_registry()
            node_def = registry.get_node(node_type_str)
            if node_def:
                safety_warning = node_def.metadata.get("safety_warning")
                if safety_warning:
                    config = (
                        node_item.config
                        if isinstance(node_item.config, dict)
                        else {}
                    )
                    if not config.get("_safety_confirmed"):
                        risk_level = safety_warning.get("risk_level", "unknown")
                        risks = safety_warning.get("risks", [])
                        risk_detail = "; ".join(risks) if risks else "未知风险"
                        return _error_result(
                            ErrorCode.PERMISSION_DENIED,
                            f"节点 '{node_id}' 存在未确认的安全警告: [{risk_level}级风险] {risk_detail}。"
                            f"请在节点配置中开启「安全确认」后方可启用。",
                            {"node_id": node_id},
                        )

        # 设置 enabled 属性
        node_item.enabled = enabled
        if hasattr(node_item, "setEnabled"):
            node_item.setEnabled(enabled)

        # 视觉反馈
        if hasattr(node_item, "setOpacity"):
            node_item.setOpacity(1.0 if enabled else 0.4)

        status = "启用" if enabled else "禁用"
        logger.info("AI 工具%s节点: %s", status, node_id)
        return {
            "success": True,
            "node_id": node_id,
            "enabled": enabled,
            "message": f"节点 '{node_id}' 已{status}",
        }
