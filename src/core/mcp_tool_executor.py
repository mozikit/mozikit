"""Native executor for the official MCP Tool node."""
from __future__ import annotations

from typing import Any

from .exceptions import ErrorCode, MozikitError
from .expression_engine import render_expressions
from .mcp_client_service import get_mcp_client_service


def _normalize(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _normalize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_normalize(v) for v in value]
    for method in ("model_dump", "to_dict"):
        converter = getattr(value, method, None)
        if callable(converter):
            try:
                return _normalize(converter())
            except Exception:
                pass
    if hasattr(value, "__dict__"):
        return _normalize(vars(value))
    return repr(value)


class MCPToolNativeExecutor:
    def execute(self, *, node, input_data: dict, context: dict,
                timeout: float | None = None, progress_callback=None,
                log_callback=None) -> dict:
        config = node.config or {}
        server_id = config.get("server_id")
        tool_name = config.get("tool_name")
        if not server_id or not tool_name:
            raise MozikitError(ErrorCode.NODE_VALIDATION_FAILED,
                               "MCP Tool requires server_id and tool_name")
        arguments = render_expressions(config.get("arguments", {}), context)
        if not isinstance(arguments, dict):
            raise MozikitError(ErrorCode.NODE_VALIDATION_FAILED,
                               "MCP Tool arguments must be an object")
        result = get_mcp_client_service().call_tool(
            server_id, tool_name, arguments,
            timeout=config.get("timeout"),
        )
        content = _normalize(result.content)
        if result.is_error:
            raise MozikitError(ErrorCode.MCP_TOOL_CALL_FAILED,
                               f"MCP tool returned an error: {content}")
        return {
            "result": _normalize(result.structured_content)
                         if result.structured_content is not None else content,
            "content": content,
            "is_error": False,
            "meta": _normalize(result.meta),
        }


def register_mcp_tool_executor() -> None:
    from .node_extension_registries import native_executors
    native_executors.register("mcp_tool", MCPToolNativeExecutor())
