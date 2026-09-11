"""Smoke tests against the installed MCP SDK transports.

These tests intentionally use a real SDK server.  They are skipped in minimal
development environments that do not install the project's MCP dependency.
"""
from __future__ import annotations

import asyncio
import socket
import subprocess
import sys
import textwrap

import pytest

mcp = pytest.importorskip("mcp")
pytest.importorskip("httpx2")

from src.core.mcp_client_manager import MCPClientManager


SERVER_CODE = textwrap.dedent(
    """
    import anyio
    import os
    from mcp.server.mcpserver import MCPServer

    server = MCPServer("mozikit-test")

    def echo(value: int) -> dict:
        return {"value": value}

    def add(left: int, right: int) -> int:
        return left + right

    def fail() -> str:
        raise RuntimeError("intentional tool failure")

    def env_probe() -> str:
        return repr(os.environ.get("MOZIKIT_SECRET_SHOULD_NOT_LEAK"))

    server.add_tool(echo, name="echo", description="Echo a value")
    server.add_tool(add, name="add", description="Add two values")
    server.add_tool(fail, name="fail", description="Fail intentionally")
    server.add_tool(env_probe, name="env_probe", description="Inspect test environment")
    anyio.run(server.run_stdio_async)
    """
)


class RealRegistry:
    def __init__(self, transport: str, config: dict):
        self.transport = transport
        self.config = config

    def resolve_server(self, server_id: str) -> dict:
        return {"id": server_id, "name": "SDK test", "transport": self.transport,
                "stdio": self.config if self.transport == "stdio" else None,
                "http": self.config if self.transport != "stdio" else None}


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.mark.asyncio
@pytest.mark.slow
async def test_real_stdio_echo_add_and_tool_failure():
    import os

    os.environ["MOZIKIT_SECRET_SHOULD_NOT_LEAK"] = "must-not-be-inherited"
    registry = RealRegistry("stdio", {"command": sys.executable, "args": ["-c", SERVER_CODE]})
    manager = MCPClientManager(registry, connect_timeout=10)
    try:
        tools = await manager.list_tools("sdk-stdio")
        assert {tool.name for tool in tools} >= {"echo", "add", "fail", "env_probe"}

        echo = await manager.call_tool("sdk-stdio", "echo", {"value": 7})
        added = await manager.call_tool("sdk-stdio", "add", {"left": 2, "right": 5})
        failed = await manager.call_tool("sdk-stdio", "fail", {})
        env_probe = await manager.call_tool("sdk-stdio", "env_probe", {})

        assert not echo.is_error
        assert not added.is_error
        assert failed.is_error
        assert "None" in str(env_probe.content)
    finally:
        await manager.close_all()
        os.environ.pop("MOZIKIT_SECRET_SHOULD_NOT_LEAK", None)


@pytest.mark.asyncio
@pytest.mark.slow
async def test_real_streamable_http_list_tools_and_call():
    port = _free_port()
    server_code = SERVER_CODE.replace("anyio.run(server.run_stdio_async)",
                                     f"anyio.run(lambda: server.run_streamable_http_async(host='127.0.0.1', port={port}, stateless_http=True))")
    process = subprocess.Popen([sys.executable, "-c", server_code], stdout=subprocess.DEVNULL,
                               stderr=subprocess.PIPE)
    try:
        for _ in range(100):
            if process.poll() is not None:
                pytest.fail("MCP HTTP test server exited before becoming ready")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                    break
            except OSError:
                await asyncio.sleep(0.05)
        else:
            pytest.fail("MCP HTTP test server did not become ready")

        registry = RealRegistry("streamable_http", {"url": f"http://127.0.0.1:{port}/mcp"})
        manager = MCPClientManager(registry, connect_timeout=10)
        try:
            tools = await manager.list_tools("sdk-http")
            result = await manager.call_tool("sdk-http", "add", {"left": 3, "right": 4})
            assert {tool.name for tool in tools} >= {"echo", "add", "fail"}
            assert not result.is_error
        finally:
            await manager.close_all()
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
