"""Real SDK client/server round trips over subprocess stdio, without Qt."""

import json
from pathlib import Path
import sys

import pytest

pytest.importorskip("mcp")
import anyio
from anyio.streams.buffered import BufferedByteReceiveStream
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("entry", ["module", "cli"])
def test_sdk_roundtrip_and_real_workflow_run(mcp_project, entry):
    runtime, workspace, env = mcp_project
    args = (["-m", "src.mcp_server"] if entry == "module" else [str(PROJECT_ROOT / "main.py"), "mcp"])

    async def scenario():
        with anyio.fail_after(45):
            params = StdioServerParameters(
                command=sys.executable, args=args + ["--workspace", str(workspace)],
                cwd=str(runtime), env=env,
            )
            async with stdio_client(params) as (reader, writer):
                async with ClientSession(reader, writer) as session:
                    initialized = await session.initialize()
                    assert initialized.serverInfo.name == "Mozikit"
                    assert initialized.capabilities.tools is not None
                    listing = await session.list_tools()
                    assert {tool.name for tool in listing.tools} == {
                        "list_workflows", "get_workflow", "validate_workflow", "run_workflow",
                        "list_runs", "get_run", "get_run_logs",
                    }
                    run_tool = next(tool for tool in listing.tools if tool.name == "run_workflow")
                    assert run_tool.annotations.readOnlyHint is False
                    listed = await session.call_tool("list_workflows", {})
                    path = listed.structuredContent["workflows"][0]["path"]
                    assert path == "demo/workflow.json"
                    fetched = await session.call_tool("get_workflow", {"path": path})
                    assert fetched.structuredContent["workflow"]["workflow_name"] == "demo"
                    checked = await session.call_tool("validate_workflow", {"path": path})
                    assert checked.structuredContent["valid"]
                    # Input schema validation, tool errors and session recovery.
                    for name, arguments in [
                        ("get_workflow", {}),
                        ("list_workflows", {"unexpected": True}),
                        ("get_workflow", {"path": "../outside.json"}),
                        ("run_workflow", {"path": path, "input_data": "bad"}),
                        ("unknown_tool", {}),
                    ]:
                        assert (await session.call_tool(name, arguments)).isError
                    ran = await session.call_tool("run_workflow", {"path": path, "input_data": {"value": 42}})
                    assert not ran.isError, ran.content
                    report = ran.structuredContent
                    assert report["success"] and report["trigger_type"] == "mcp"
                    assert report["final_context"]["echo"] == "你好 MCP"
                    assert report["final_context"]["value"] == 42
                    run_id = report["run_id"]
                    assert (workspace / "demo/runs" / run_id / "run.json").is_file()
                    historical = await session.call_tool("get_run", {"path": path, "run_id": run_id})
                    assert historical.structuredContent["run_id"] == run_id
                    logs = await session.call_tool("get_run_logs", {"path": path, "run_id": run_id})
                    assert "hello from node" in "\n".join(logs.structuredContent["lines"])
                    assert (await session.call_tool("list_runs", {"path": path})).structuredContent["runs"]
                    failed = await session.call_tool("run_workflow", {"path": path, "input_data": {"fail": True}})
                    assert failed.isError and not failed.structuredContent["success"]
                    assert "requested failure" in failed.structuredContent["error"]
                    # Read tools and ping continue to work after a failed run.
                    await session.send_ping()

    anyio.run(scenario)


def test_stdio_stdout_is_only_json_and_does_not_import_qt(mcp_project):
    runtime, workspace, env = mcp_project
    # Force application stdout noise and reject Qt imports in the child process.
    driver = runtime / "driver.py"
    driver.write_text(
        "import builtins\n"
        "original = builtins.__import__\n"
        "def guarded(name, *args, **kwargs):\n"
        "    if name.startswith('PySide6'):\n"
        "        raise RuntimeError('MCP must not import Qt')\n"
        "    return original(name, *args, **kwargs)\n"
        "builtins.__import__ = guarded\n"
        "from src.core.mcp_workflows import WorkflowService\n"
        "original_list = WorkflowService.list_workflows\n"
        "def noisy_list(self):\n"
        "    print('plugin diagnostic')\n"
        "    return original_list(self)\n"
        "WorkflowService.list_workflows = noisy_list\n"
        "from src.mcp_server import main\n"
        "main()\n"
    )
    async def scenario():
        with anyio.fail_after(15):
            async with await anyio.open_process(
                [sys.executable, str(driver), "--workspace", str(workspace)],
                cwd=runtime, env=env,
            ) as process:
                reader = BufferedByteReceiveStream(process.stdout)

                async def send(message):
                    await process.stdin.send((json.dumps(message) + "\n").encode())

                await send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                    "protocolVersion": "2025-06-18", "capabilities": {},
                    "clientInfo": {"name": "stdout-test", "version": "1"},
                }})
                initialized = json.loads(await reader.receive_until(b"\n", 100000))
                assert initialized["result"]["serverInfo"]["name"] == "Mozikit"
                await send({"jsonrpc": "2.0", "method": "notifications/initialized"})
                await send({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
                    "name": "list_workflows", "arguments": {},
                }})
                # Any stray print() line would fail this JSON decode.
                called = json.loads(await reader.receive_until(b"\n", 100000))
                assert called["id"] == 2 and not called["result"].get("isError")
                await process.stdin.aclose()
                stderr = await process.stderr.receive()
                assert b"plugin diagnostic" in stderr
                assert await process.wait() == 0

    anyio.run(scenario)
