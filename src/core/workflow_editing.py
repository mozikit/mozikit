"""Headless editing rules shared by the CLI and Qt adapters."""
import json


def parse_config_value(value: str):
    """Accept JSON values; unquoted text remains a string."""
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def ports_compatible(output_type: str, input_type: str) -> bool:
    return (
        "any" in (output_type, input_type)
        or output_type == input_type
        or input_type in {
            "int": {"float", "string"},
            "float": {"string"},
            "bool": {"string"},
        }.get(output_type, set())
    )


def connect_nodes(executor, registry, from_id, from_port, to_id, to_port):
    """Validate ports and replace the existing input connection, as Qt does."""
    if from_id == to_id:
        raise ValueError("不能连接到同一个节点")
    types = []
    for node_id, port, direction in (
        (from_id, from_port, "output"), (to_id, to_port, "input")
    ):
        if node_id not in executor.nodes:
            raise ValueError(f"节点不存在: {node_id}")
        definition = registry.get_node(executor.nodes[node_id].node_type)
        if definition is None:
            raise ValueError(f"节点类型未注册: {node_id}")
        schema = getattr(definition, f"{direction}_schema") or {direction: {"type": "any"}}
        if port not in schema:
            raise ValueError(f"端口不存在: {node_id}:{port}")
        field = schema[port]
        types.append(field.get("type", "any") if isinstance(field, dict) else "any")
    if not ports_compatible(*types):
        raise ValueError(f"端口类型不兼容: {types[0]} → {types[1]}")
    executor.edges = [e for e in executor.edges if not (e.to_node == to_id and e.to_port == to_port)]
    # Rebuild references because several ports may connect the same node pair.
    edges = [(e.from_node, e.from_port, e.to_node, e.to_port) for e in executor.edges]
    executor.edges = []
    for node in executor.nodes.values():
        node.inputs = []
        node.outputs = []
    for edge in edges + [(from_id, from_port, to_id, to_port)]:
        executor.add_edge(*edge)


def upstream_node_ids(target, node_ids, edges):
    if target not in node_ids:
        raise ValueError(f"节点不存在: {target}")
    required, pending = set(), [target]
    while pending:
        current = pending.pop()
        if current in required:
            continue
        required.add(current)
        pending.extend(source for source, dest in edges if dest == current)
    return required
