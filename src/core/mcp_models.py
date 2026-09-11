"""Application-owned models for MCP client operations."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, TypeAlias


JsonValue: TypeAlias = (str | int | float | bool | None |
                        list["JsonValue"] | dict[str, "JsonValue"])


@dataclass
class MCPToolDefinition:
    name: str
    description: str = ""
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None
    annotations: dict[str, Any] | None = None


@dataclass
class MCPToolResult:
    content: list[Any]
    structured_content: JsonValue
    is_error: bool
    meta: dict[str, Any] | None
    raw: Any | None = None


@dataclass
class MCPConnectionTestResult:
    success: bool
    server_name: Optional[str]
    transport: str
    tool_count: int = 0
    tools: list[MCPToolDefinition] | None = None
    error_code: str | None = None
    error_message: str | None = None
    latency_ms: int | None = None

    def __post_init__(self) -> None:
        if self.tools is None:
            self.tools = []
