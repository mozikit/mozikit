"""Mozikit MCP server using the official stdio and Streamable HTTP transports."""

import argparse
from contextlib import asynccontextmanager, redirect_stdout
from functools import partial
from hmac import compare_digest
from ipaddress import ip_address
from io import TextIOWrapper
import json
import os
import sys


def create_server(workspace=None):
    import anyio
    from mcp.server import Server
    from mcp.types import CallToolResult, TextContent, Tool, ToolAnnotations
    from src.core import __version__, resolve_workspace
    from src.core.mcp_workflows import WorkflowService

    service = WorkflowService(workspace if workspace is not None else resolve_workspace())
    server = Server(
        "Mozikit", version=__version__,
        instructions="先列出工作流以获取相对路径。执行使用本地已安装节点和 uv 环境；运行结果包含 run_id。",
    )
    path_property = {"type": "string", "description": "工作流 JSON 路径，相对于所选工作空间"}
    run_property = {"type": "string", "description": "由 run_workflow 或 list_runs 返回的 run_id"}
    definitions = [
        ("list_workflows", "列出工作空间中已保存的工作流", {}, []),
        ("get_workflow", "读取工作流原始 JSON 定义", {"path": path_property}, ["path"]),
        ("validate_workflow", "校验工作流结构、节点标识、连接及循环依赖，不执行节点",
         {"path": path_property}, ["path"]),
        ("run_workflow", "执行工作流并等待完成；可安装声明的依赖，并产生节点定义的外部操作。返回完整运行报告，包括 run_id、输出和日志",
         {"path": path_property, "input_data": {"type": "object", "description": "初始输入数据"}}, ["path"]),
        ("list_runs", "列出工作流最近的运行记录（新到旧）",
         {"path": path_property, "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20}}, ["path"]),
        ("get_run", "读取完整持久化运行报告，包含节点结果、输出、stdout 和 stderr",
         {"path": path_property, "run_id": run_property}, ["path", "run_id"]),
        ("get_run_logs", "分页读取运行的 stdout 或 stderr 日志，offset 为从零开始的行偏移",
         {"path": path_property, "run_id": run_property,
          "stream": {"type": "string", "enum": ["stdout", "stderr"], "default": "stdout"},
          "offset": {"type": "integer", "minimum": 0, "default": 0},
          "limit": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 200}}, ["path", "run_id"]),
    ]
    tools = [Tool(
        name=name, description=description,
        inputSchema={"type": "object", "properties": properties,
                     "required": required, "additionalProperties": False},
        annotations=ToolAnnotations(
            readOnlyHint=name != "run_workflow", destructiveHint=name == "run_workflow",
            idempotentHint=name != "run_workflow", openWorldHint=name == "run_workflow",
        ),
    ) for name, description, properties, required in definitions]
    handlers = {tool.name: getattr(service, tool.name) for tool in tools}

    @server.list_tools()
    async def list_tools():
        return tools

    @server.call_tool()
    async def call_tool(name, arguments):
        if name not in handlers:
            raise ValueError("未知工具: " + name)
        # Keep the SDK session responsive while the synchronous engine runs.
        result = await anyio.to_thread.run_sync(partial(handlers[name], **arguments))
        return CallToolResult(
            content=[TextContent(type="text", text=json.dumps(result, ensure_ascii=False))],
            structuredContent=result,
            isError=name == "run_workflow" and not result.get("success", False),
        )

    return server


def run_stdio(workspace=None):
    if sys.version_info < (3, 10):
        raise RuntimeError("MCP 服务需要 Python 3.10 或更高版本")
    try:
        import anyio
        from mcp.server.stdio import stdio_server
    except ImportError as exc:
        raise RuntimeError(
            '请安装 MCP 可选依赖: pip install "mozikit[mcp]"；源码目录使用 pip install -e ".[mcp]"'
        ) from exc

    # Bind the protocol writer before redirecting application/plugin print()
    # calls. The SDK and all workflow threads share this redirect for the full
    # server lifetime, so no per-call global stdout swaps can race each other.
    protocol_stdout = TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    async def serve():
        server = create_server(workspace)
        async with stdio_server(stdout=anyio.wrap_file(protocol_stdout)) as (reader, writer):
            await server.run(reader, writer, server.create_initialization_options())

    try:
        with redirect_stdout(sys.stderr):
            anyio.run(serve)
    finally:
        # Leave the original process handle open for CLI callers/embedders.
        protocol_stdout.detach()


def _http_settings(host, port, token, allowed_hosts=None, allowed_origins=None):
    """Build explicit SDK Host/Origin checks for this listening address."""
    if not host or any(char in host for char in ("/", "\\", " ", "\r", "\n")):
        raise ValueError("host 必须是 IP 地址或主机名")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("port 必须在 1 到 65535 之间")
    try:
        loopback = ip_address(host).is_loopback
    except ValueError:
        loopback = host.lower() == "localhost"
    if token is not None and (
        not token or any(ord(char) <= 32 or ord(char) >= 127 for char in token)
    ):
        raise ValueError("MOZIKIT_MCP_TOKEN 必须是非空、无空格的 ASCII token")
    if not loopback and not token:
        raise ValueError("非本机 HTTP 监听必须设置 MOZIKIT_MCP_TOKEN")
    if host in ("0.0.0.0", "::") and not allowed_hosts:
        raise ValueError("监听所有网卡时，请用 --allowed-host 指定客户端访问的主机名及端口")

    hosts = [host, "127.0.0.1", "localhost", "::1"] if loopback else [host]
    authorities = ["[{}]:{}".format(name, port) if ":" in name else "{}:{}".format(name, port)
                   for name in hosts]
    if port in (80, 443):
        authorities.extend("[{}]".format(name) if ":" in name else name for name in hosts)
    authorities.extend(allowed_hosts or [])
    origins = [scheme + authority for authority in authorities for scheme in ("http://", "https://")]
    origins.extend(allowed_origins or [])
    return list(dict.fromkeys(authorities)), list(dict.fromkeys(origins))


class _MCPHTTPHandler:
    """ASGI endpoint; authenticate every request, including session deletion."""

    def __init__(self, manager, token):
        self.manager = manager
        self._authorization = ("Bearer " + token).encode("ascii") if token else None

    async def __call__(self, scope, receive, send):
        if self._authorization is not None:
            from starlette.responses import JSONResponse

            values = [value for name, value in scope.get("headers", []) if name.lower() == b"authorization"]
            scheme, _, credential = values[0].partition(b" ") if len(values) == 1 else (b"", b"", b"")
            if scheme.lower() != b"bearer" or not compare_digest(credential, self._authorization[7:]):
                response = JSONResponse(
                    {"error": "Bearer token required"}, status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )
                await response(scope, receive, send)
                return
        await self.manager.handle_request(scope, receive, send)


def create_http_app(workspace=None, host="127.0.0.1", port=8000, token=None,
                    allowed_hosts=None, allowed_origins=None):
    """Create a stateful ASGI MCP app. Its lifespan must run before requests."""
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    from mcp.server.transport_security import TransportSecuritySettings
    from starlette.applications import Starlette
    from starlette.routing import Route

    hosts, origins = _http_settings(host, port, token, allowed_hosts, allowed_origins)
    manager = StreamableHTTPSessionManager(
        app=create_server(workspace),
        security_settings=TransportSecuritySettings(
            enable_dns_rebinding_protection=True, allowed_hosts=hosts, allowed_origins=origins,
        ),
    )

    @asynccontextmanager
    async def lifespan(app):
        async with manager.run():
            yield

    return Starlette(
        routes=[Route("/mcp", endpoint=_MCPHTTPHandler(manager, token))], lifespan=lifespan,
    )


def run_http(workspace=None, host="127.0.0.1", port=8000, allowed_hosts=None, allowed_origins=None):
    if sys.version_info < (3, 10):
        raise RuntimeError("MCP 服务需要 Python 3.10 或更高版本")
    try:
        import uvicorn
        app = create_http_app(
            workspace, host=host, port=port, token=os.environ.get("MOZIKIT_MCP_TOKEN"),
            allowed_hosts=allowed_hosts, allowed_origins=allowed_origins,
        )
    except ImportError as exc:
        raise RuntimeError('请安装 MCP 可选依赖: pip install -e ".[mcp]"') from exc
    uvicorn.run(app, host=host, port=port, access_log=False)


def run_server(workspace=None, transport="stdio", host="127.0.0.1", port=8000,
               allowed_hosts=None, allowed_origins=None):
    if transport == "stdio":
        run_stdio(workspace)
    elif transport == "streamable-http":
        run_http(workspace, host, port, allowed_hosts, allowed_origins)
    else:
        raise ValueError("transport 必须是 stdio 或 streamable-http")


def main():
    parser = argparse.ArgumentParser(description="Mozikit MCP Server (stdio / Streamable HTTP)")
    parser.add_argument("--workspace", "-w", help="工作流根目录（默认 MOZIKIT_WORKSPACE 或 ./workflows）")
    parser.add_argument("--transport", choices=("stdio", "streamable-http"), default="stdio")
    parser.add_argument("--host", default="127.0.0.1", help="HTTP 监听地址（默认 127.0.0.1）")
    parser.add_argument("--port", type=int, default=8000, help="HTTP 端口（默认 8000）")
    parser.add_argument("--allowed-host", action="append", help="额外允许的 Host，含端口，可重复")
    parser.add_argument("--allowed-origin", action="append", help="额外允许的 Origin，可重复")
    args = parser.parse_args()
    try:
        run_server(args.workspace, args.transport, args.host, args.port, args.allowed_host, args.allowed_origin)
    except (RuntimeError, ValueError) as exc:
        parser.exit(1, str(exc) + "\n")


if __name__ == "__main__":
    main()
