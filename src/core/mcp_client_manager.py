"""Runtime MCP client lifecycle owned by Mozikit.

The official MCP Python SDK owns protocol framing and transport semantics. This
module only resolves registry definitions, owns client contexts, normalizes
results, and translates failures into Mozikit errors.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from .exceptions import ErrorCode, MozikitError
from .mcp_models import MCPConnectionTestResult, MCPToolDefinition, MCPToolResult
from .mcp_server_registry import MCPServerRegistry, get_registry


@dataclass
class MCPClientHandle:
    server_id: str
    transport: str
    client: Any
    stack: AsyncExitStack
    started_at: datetime
    last_used_at: datetime
    healthy: bool
    config_fingerprint: str
    lock: asyncio.Lock


class MCPClientManager:
    def __init__(self, registry: MCPServerRegistry | None = None, *,
                 connect_timeout: float = 15.0, default_call_timeout: float = 60.0,
                 client_factory: Callable[[dict[str, Any]], Any] | None = None):
        self.registry = registry or get_registry()
        self.connect_timeout = connect_timeout
        self.default_call_timeout = default_call_timeout
        self._clients: dict[str, MCPClientHandle] = {}
        self._clients_lock = asyncio.Lock()
        self._creation_lock = asyncio.Lock()
        # Tests can inject an async context-manager factory without importing mcp.
        self._client_factory = client_factory

    async def test_connection(self, server_id: str, timeout: float = 15.0) -> MCPConnectionTestResult:
        resolved = self._resolve(server_id)
        started = time.perf_counter()
        transport = resolved["transport"]
        name = resolved.get("name")
        try:
            async with AsyncExitStack() as stack:
                client = await asyncio.wait_for(self._enter_client(stack, resolved), timeout)
                tools = await asyncio.wait_for(client.list_tools(), timeout)
                normalized = self._normalize_tools(tools)
            return MCPConnectionTestResult(True, name, transport, len(normalized), normalized,
                                           latency_ms=round((time.perf_counter() - started) * 1000))
        except asyncio.TimeoutError as exc:
            error = MozikitError(ErrorCode.MCP_CONNECTION_TIMEOUT,
                                 f"MCP connection test timed out: {server_id}", cause=exc)
        except MozikitError as exc:
            error = exc
        except Exception as exc:
            error = self._translate_connection_error(exc, server_id)
        return MCPConnectionTestResult(False, name, transport, error_code=error.code.value,
                                       error_message=error.message,
                                       latency_ms=round((time.perf_counter() - started) * 1000))

    async def list_tools(self, server_id: str, *, refresh: bool = False,
                         timeout: float = 15.0) -> list[MCPToolDefinition]:
        handle = await self._get_handle(server_id)
        try:
            async with handle.lock:
                handle.last_used_at = _now()
                return self._normalize_tools(await asyncio.wait_for(handle.client.list_tools(), timeout))
        except asyncio.TimeoutError as exc:
            await self._discard_if_current(server_id, handle)
            raise MozikitError(ErrorCode.MCP_CONNECTION_TIMEOUT,
                               f"MCP tools/list timed out: {server_id}", cause=exc) from exc
        except Exception as exc:
            await self._discard_if_current(server_id, handle)
            raise self._translate_operation_error(exc, server_id, listing=True) from exc

    async def call_tool(self, server_id: str, tool_name: str, arguments: dict,
                        *, timeout: float | None = None) -> MCPToolResult:
        handle = await self._get_handle(server_id)
        try:
            async with handle.lock:
                handle.last_used_at = _now()
                result = await asyncio.wait_for(
                    handle.client.call_tool(tool_name, arguments),
                    self.default_call_timeout if timeout is None else timeout,
                )
                return self._normalize_result(result)
        except asyncio.TimeoutError as exc:
            raise MozikitError(ErrorCode.MCP_TOOL_TIMEOUT,
                               f"MCP tool timed out: {tool_name}", cause=exc) from exc
        except Exception as exc:
            if _is_transport_failure(exc):
                await self._discard_if_current(server_id, handle)
            raise self._translate_operation_error(exc, server_id, tool_name=tool_name) from exc

    async def invalidate(self, server_id: str) -> None:
        await self.close(server_id)

    async def close(self, server_id: str) -> None:
        async with self._clients_lock:
            handle = self._clients.pop(server_id, None)
        if handle:
            await handle.stack.aclose()

    async def close_all(self) -> None:
        async with self._clients_lock:
            handles = list(self._clients.values())
            self._clients.clear()
        first_error: BaseException | None = None
        for handle in handles:
            try:
                await handle.stack.aclose()
            except BaseException as exc:
                if first_error is None:
                    first_error = exc
        if first_error:
            raise first_error

    def _resolve(self, server_id: str) -> dict[str, Any]:
        return self.registry.resolve_server(server_id)

    async def _get_handle(self, server_id: str) -> MCPClientHandle:
        resolved = self._resolve(server_id)
        fingerprint = _fingerprint(resolved)
        async with self._creation_lock:
            async with self._clients_lock:
                current = self._clients.get(server_id)
                if current and current.healthy and current.config_fingerprint == fingerprint:
                    return current
                if current:
                    self._clients.pop(server_id, None)
            if current:
                await current.stack.aclose()
            try:
                stack = AsyncExitStack()
                client = await asyncio.wait_for(self._enter_client(stack, resolved), self.connect_timeout)
            except asyncio.TimeoutError as exc:
                await stack.aclose()
                raise MozikitError(ErrorCode.MCP_CONNECTION_TIMEOUT,
                                   f"MCP connection timed out: {server_id}", cause=exc) from exc
            except Exception as exc:
                await stack.aclose()
                raise self._translate_connection_error(exc, server_id) from exc
            handle = MCPClientHandle(server_id, resolved["transport"], client, stack,
                                     _now(), _now(), True, fingerprint, asyncio.Lock())
            async with self._clients_lock:
                self._clients[server_id] = handle
            return handle

    async def _enter_client(self, stack: AsyncExitStack, resolved: dict[str, Any]) -> Any:
        if self._client_factory:
            return await stack.enter_async_context(self._client_factory(resolved))
        try:
            from mcp import Client
            from mcp.client.stdio import StdioServerParameters
        except ImportError as exc:
            raise MozikitError(ErrorCode.MCP_CONNECTION_FAILED,
                               "The mcp package is required for MCP clients", cause=exc) from exc
        transport = resolved["transport"]
        if transport == "stdio":
            config = resolved["stdio"]
            env = dict(os.environ) if config.get("inherit_env", True) else {}
            env.update(config.get("env") or {})
            server = StdioServerParameters(command=config["command"], args=config.get("args") or [],
                                           env=env, cwd=config.get("cwd"))
            return await stack.enter_async_context(Client(server))
        config = resolved["http"]
        try:
            import httpx2
            from mcp.client.streamable_http import streamable_http_client
        except ImportError as exc:
            raise MozikitError(ErrorCode.MCP_CONNECTION_FAILED,
                               "The installed mcp package lacks HTTP client support", cause=exc) from exc
        http_client = httpx2.AsyncClient(headers=config.get("headers") or {},
                                         timeout=float(config.get("timeout", self.connect_timeout)))
        await stack.enter_async_context(http_client)
        transport_context = streamable_http_client(config["url"], http_client=http_client)
        return await stack.enter_async_context(Client(transport_context))

    @staticmethod
    def _normalize_tools(result: Any) -> list[MCPToolDefinition]:
        items = _field(result, "tools", result if isinstance(result, list) else [])
        return [MCPToolDefinition(str(_field(t, "name", "")), str(_field(t, "description", "") or ""),
                                   _field(t, "inputSchema", _field(t, "input_schema", None)),
                                   _field(t, "outputSchema", _field(t, "output_schema", None)),
                                   _field(t, "annotations", None)) for t in items]

    @staticmethod
    def _normalize_result(result: Any) -> MCPToolResult:
        return MCPToolResult(list(_field(result, "content", []) or []),
                             _field(result, "structuredContent", _field(result, "structured_content", None)),
                             bool(_field(result, "isError", _field(result, "is_error", False))),
                             _field(result, "_meta", _field(result, "meta", None)), result)

    async def _discard_if_current(self, server_id: str, handle: MCPClientHandle) -> None:
        async with self._clients_lock:
            if self._clients.get(server_id) is handle:
                self._clients.pop(server_id, None)
                handle.healthy = False
                await handle.stack.aclose()

    @staticmethod
    def _translate_connection_error(exc: Exception, server_id: str) -> MozikitError:
        text = str(exc).lower()
        if isinstance(exc, (FileNotFoundError, PermissionError)):
            code = ErrorCode.MCP_PROCESS_START_FAILED
        elif "401" in text or "403" in text or "authentication" in text or "unauthorized" in text:
            code = ErrorCode.MCP_AUTHENTICATION_FAILED
        elif isinstance(exc, (EOFError, BrokenPipeError, ConnectionError)):
            code = ErrorCode.MCP_PROCESS_EXITED
        else:
            code = ErrorCode.MCP_CONNECTION_FAILED
        return MozikitError(code,
                            f"Unable to connect to MCP Server: {server_id}", cause=exc)

    @staticmethod
    def _translate_operation_error(exc: Exception, server_id: str, *, listing: bool = False,
                                   tool_name: str | None = None) -> MozikitError:
        code = ErrorCode.MCP_TOOL_NOT_FOUND if tool_name and "not found" in str(exc).lower() else ErrorCode.MCP_TOOL_CALL_FAILED
        if listing:
            code = ErrorCode.MCP_PROTOCOL_ERROR
        return MozikitError(code, f"MCP operation failed for {server_id}", cause=exc)


def _field(value: Any, name: str, default: Any) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _fingerprint(value: dict[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(payload).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _is_transport_failure(exc: Exception) -> bool:
    return isinstance(exc, (EOFError, BrokenPipeError, ConnectionError))
