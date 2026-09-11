import asyncio
from contextlib import asynccontextmanager

import pytest

from src.core.exceptions import ErrorCode, MozikitError
from src.core.mcp_client_manager import MCPClientManager
from src.core.mcp_models import MCPToolResult


class FakeRegistry:
    def __init__(self):
        self.config = {"id": "demo", "name": "Demo", "enabled": True,
                       "transport": "stdio", "stdio": {"command": "demo", "args": []}}

    def resolve_server(self, server_id):
        if server_id != "demo":
            raise MozikitError(ErrorCode.MCP_SERVER_NOT_FOUND, server_id)
        if not self.config["enabled"]:
            raise MozikitError(ErrorCode.MCP_SERVER_DISABLED, server_id)
        return dict(self.config)


class FakeClient:
    instances = []

    def __init__(self, resolved):
        self.resolved = resolved
        self.closed = False
        self.calls = []
        type(self).instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        self.closed = True

    async def list_tools(self):
        return {"tools": [{"name": "echo", "description": "Echo", "inputSchema": {"type": "object"}}]}

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return {"content": [{"type": "text", "text": "ok"}],
                "structuredContent": {"value": arguments["value"]}, "isError": False}


@asynccontextmanager
async def fake_factory(resolved):
    client = FakeClient(resolved)
    try:
        yield client
    finally:
        await client.__aexit__()


@pytest.mark.asyncio
async def test_stdio_client_is_reused_and_call_result_is_normalized():
    FakeClient.instances.clear()
    registry = FakeRegistry()
    manager = MCPClientManager(registry, client_factory=fake_factory)

    tools = await manager.list_tools("demo")
    result = await manager.call_tool("demo", "echo", {"value": 3})
    await manager.call_tool("demo", "echo", {"value": 4})

    assert [tool.name for tool in tools] == ["echo"]
    assert isinstance(result, MCPToolResult)
    assert result.structured_content == {"value": 3}
    assert len(FakeClient.instances) == 1
    assert len(FakeClient.instances[0].calls) == 2
    await manager.close_all()
    assert FakeClient.instances[0].closed


@pytest.mark.asyncio
async def test_concurrent_access_creates_one_client_and_serializes_calls():
    FakeClient.instances.clear()
    manager = MCPClientManager(FakeRegistry(), client_factory=fake_factory)
    await asyncio.gather(
        manager.call_tool("demo", "echo", {"value": 1}),
        manager.call_tool("demo", "echo", {"value": 2}),
    )
    assert len(FakeClient.instances) == 1
    assert len(FakeClient.instances[0].calls) == 2
    await manager.close_all()


@pytest.mark.asyncio
async def test_config_change_recreates_client_and_invalidate_closes_it():
    FakeClient.instances.clear()
    registry = FakeRegistry()
    manager = MCPClientManager(registry, client_factory=fake_factory)
    await manager.list_tools("demo")
    first = FakeClient.instances[0]
    registry.config["stdio"]["args"] = ["changed"]
    await manager.list_tools("demo")
    assert first.closed
    assert len(FakeClient.instances) == 2
    await manager.invalidate("demo")
    assert FakeClient.instances[1].closed


@pytest.mark.asyncio
async def test_connection_timeout_is_structured_and_test_client_is_temporary():
    class SlowClient(FakeClient):
        async def list_tools(self):
            await asyncio.sleep(0.05)

    @asynccontextmanager
    async def slow_factory(resolved):
        client = SlowClient(resolved)
        yield client

    result = await MCPClientManager(FakeRegistry(), client_factory=slow_factory).test_connection("demo", 0.001)
    assert not result.success
    assert result.error_code == ErrorCode.MCP_CONNECTION_TIMEOUT.value


@pytest.mark.asyncio
@pytest.mark.parametrize("config_change", ["missing", "disabled"])
async def test_connection_registry_errors_are_structured(config_change):
    registry = FakeRegistry()
    server_id = "demo"
    if config_change == "missing":
        server_id = "unknown"
    else:
        registry.config["enabled"] = False

    result = await MCPClientManager(registry, client_factory=fake_factory).test_connection(server_id)

    assert not result.success
    assert result.error_code in {
        ErrorCode.MCP_SERVER_NOT_FOUND.value,
        ErrorCode.MCP_SERVER_DISABLED.value,
    }


@pytest.mark.asyncio
async def test_close_waits_for_an_inflight_call_before_closing_transport():
    entered = asyncio.Event()
    release = asyncio.Event()

    class BlockingClient(FakeClient):
        async def call_tool(self, name, arguments):
            entered.set()
            await release.wait()
            return await super().call_tool(name, arguments)

    @asynccontextmanager
    async def blocking_factory(resolved):
        client = BlockingClient(resolved)
        try:
            yield client
        finally:
            await client.__aexit__()

    manager = MCPClientManager(FakeRegistry(), client_factory=blocking_factory)
    call = asyncio.create_task(manager.call_tool("demo", "echo", {"value": 1}))
    await entered.wait()
    closing = asyncio.create_task(manager.close("demo"))
    await asyncio.sleep(0)
    assert not closing.done()
    assert not FakeClient.instances[-1].closed
    release.set()
    await call
    await closing
    assert FakeClient.instances[-1].closed
