"""
Canvas 适配器 — 将 AIToolExecutor 对 Qt 画布项的依赖封装在此。
其他核心模块不应直接导入 src.views.node_graphics。
"""
from typing import Any


def create_node_item(
    node_id: str, node_type: str, node_title: str, input_schema: dict, output_schema: dict
) -> Any:
    """创建 NodeGraphicsItem 实例（延迟导入避免核心层依赖 Qt 视图）"""
    from src.views.node_graphics import NodeGraphicsItem

    return NodeGraphicsItem(node_id, node_type, node_title, input_schema, output_schema)


def create_connection_item(start_port: Any, end_port: Any, animated: bool = False) -> Any:
    """创建 ConnectionGraphicsItem 实例"""
    from src.views.node_graphics import ConnectionGraphicsItem

    conn = ConnectionGraphicsItem(start_port)
    conn.set_end_port(end_port)
    if animated:
        conn.start_animation()
    return conn


def remove_connection_item(conn: Any) -> None:
    """从场景移除连接项"""
    scene = conn.scene()
    if scene:
        scene.removeItem(conn)


def is_output_port(child: Any) -> bool:
    """判断子项是否为输出端口"""
    from src.views.node_graphics import PortType

    return hasattr(child, "port_type") and child.port_type == PortType.OUTPUT


def is_input_port(child: Any) -> bool:
    """判断子项是否为输入端口"""
    from src.views.node_graphics import PortType

    return hasattr(child, "port_type") and child.port_type == PortType.INPUT


def is_connection_item(item: Any) -> bool:
    """判断是否为 ConnectionGraphicsItem 实例"""
    from src.views.node_graphics import ConnectionGraphicsItem

    return isinstance(item, ConnectionGraphicsItem)


def set_item_position(item: Any, x: float, y: float) -> None:
    """设置画布项的位置"""
    item.setPos(x, y)
