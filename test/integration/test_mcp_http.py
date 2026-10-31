"""Real loopback HTTP sessions with the official MCP client and uvicorn."""

from contextlib import asynccontextmanager
import socket

import pytest

pytest.importorskip("mcp")
import anyio
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
import uvicorn

from src.mcp_server import create_http_app


@asynccontextmanager
async def http_server(workspace, token=None):
    # Hold the socket from allocation through serving to avoid port races.
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        listener.setblocking(False)
        port = listener.getsockname()[1]
        app = create_http_app(workspace, port=port, token=token)
        server = uvicorn.Server(uvicorn.Config(
            app, host="127.0.0.1", port=port, log_level="error", access_log=False,
            timeout_graceful_shutdown=2,
        ))
        async with anyio.create_task_group() as tasks:
            async def serve():
                await server.serve(sockets=[listener])

            tasks.start_soon(serve)
            with anyio.fail_after(10):
                while not server.started:
                    await anyio.sleep(0.01)
            try:
                yield "http://127.0.0.1:{}/mcp".format(port)
            finally:
                server.should_exit = True


def test_http_sdk_roundtrip_and_real_run(mcp_project, monkeypatch):
    runtime, workspace, env = mcp_project
    from src.core import node_registry

    monkeypatch.chdir(runtime)
    monkeypatch.setenv("PYTHONPATH", env["PYTHONPATH"])
    monkeypatch.setattr(node_registry, "_registry_instance", None)

    async def scenario():
        with anyio.fail_after(30):
            async with http_server(workspace, token="test-secret") as url:
                async with httpx.AsyncClient(
                    headers={"Authorization": "Bearer test-secret"}, trust_env=False,
                ) as client:
                    async with streamable_http_client(url, http_client=client) as (reader, writer, get_id):
                        async with ClientSession(reader, writer) as session:
                            initialized = await session.initialize()
                            assert initialized.serverInfo.name == "Mozikit" and get_id()
                            tools = await session.list_tools()
                            assert len(tools.tools) == 7
                            listed = await session.call_tool("list_workflows", {})
                            path = listed.structuredContent["workflows"][0]["path"]
                            assert (await session.call_tool("validate_workflow", {"path": path})).structuredContent["valid"]
                            ran = await session.call_tool("run_workflow", {"path": path, "input_data": {"value": 42}})
                            assert not ran.isError, ran.content
                            assert ran.structuredContent["final_context"]["echo"] == "你好 MCP"
                            assert ran.structuredContent["final_context"]["value"] == 42
                            run_id = ran.structuredContent["run_id"]
                            report = await session.call_tool("get_run", {"path": path, "run_id": run_id})
                            assert report.structuredContent["success"]
                            logs = await session.call_tool("get_run_logs", {"path": path, "run_id": run_id})
                            assert "hello from node" in "\n".join(logs.structuredContent["lines"])
                            assert (await session.call_tool("list_runs", {"path": path})).structuredContent["runs"]
                            failed = await session.call_tool("run_workflow", {"path": path, "input_data": {"fail": True}})
                            assert failed.isError and "requested failure" in failed.structuredContent["error"]
                            assert (await session.call_tool("get_workflow", {"path": "../outside.json"})).isError
                            await session.send_ping()

    anyio.run(scenario)


@pytest.mark.parametrize("token", [None, "test-secret"])
def test_http_auth_host_origin_and_session_lifecycle(tmp_path, token):
    async def scenario():
        with anyio.fail_after(20):
            async with http_server(tmp_path, token=token) as url:
                authorization = {"Authorization": "Bearer " + token} if token else {}
                async with httpx.AsyncClient(trust_env=False, headers=authorization) as client:
                    if token:
                        async with httpx.AsyncClient(trust_env=False) as anonymous:
                            for method in ("GET", "POST", "DELETE"):
                                response = await anonymous.request(method, url)
                                assert response.status_code == 401
                                assert response.headers["www-authenticate"] == "Bearer"
                            assert (await anonymous.get(url, headers={"Authorization": "Bearer wrong"})).status_code == 401
                    assert (await client.get(url, headers={"Host": "evil.example"})).status_code == 421
                    assert (await client.get(url, headers={"Origin": "https://evil.example"})).status_code == 403
                    async with streamable_http_client(url, http_client=client) as (reader, writer, get_id):
                        async with ClientSession(reader, writer) as session:
                            await session.initialize()
                            session_id = get_id()
                            assert session_id
                            response = await client.delete(url, headers={"Mcp-Session-Id": "missing"})
                            assert response.status_code == 404
                            invalid = await session.call_tool("get_workflow", {})
                            assert invalid.isError
                            async with streamable_http_client(url, http_client=client) as (other_reader, other_writer, other_id):
                                async with ClientSession(other_reader, other_writer) as other_session:
                                    await other_session.initialize()
                                    assert other_id() != session_id
                                    await other_session.send_ping()
                            # Closing one session must not invalidate another.
                            await session.send_ping()
                    # Client context closure issues DELETE. The old ID must no
                    # longer be accepted by the stateful transport manager.
                    response = await client.get(url, headers={"Mcp-Session-Id": session_id})
                    assert response.status_code == 404

    anyio.run(scenario)
