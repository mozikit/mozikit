# MCP Server 接入

Mozikit 可作为 MCP Server，通过 stdio 或 Streamable HTTP 向支持 MCP 的客户端
提供工作流工具。两种传输共用同一套无界面工作流执行引擎，无需启动 Qt。

## 安装与启动

MCP 功能需要 **Python 3.10+**，使用官方 MCP Python SDK `>=1.30,<2`，作为可选依赖安装。
其他功能的依赖保持原样。
在源码目录执行：

```bash
python -m pip install -e ".[mcp]"
mozikit mcp --workspace /absolute/path/to/workflows
```

也支持以下等价入口：

```bash
mozikit-mcp --workspace /absolute/path/to/workflows
python -m src.mcp_server --workspace /absolute/path/to/workflows
python main.py mcp --workspace /absolute/path/to/workflows
```

`--workspace` 优先于环境变量 `MOZIKIT_WORKSPACE`；未指定时使用当前目录下的
`workflows/`。CLI 顶层的 `mozikit --workspace PATH mcp` 同样有效。
服务由 MCP 客户端启动并保持 stdin 打开；终端中直接运行时会等待协议输入。
stdout 专用于 UTF-8 JSON-RPC，应用日志和插件打印输出到 stderr。

### Streamable HTTP

需要常驻 HTTP 服务时，在平时使用 Mozikit 的工作目录启动：

```bash
mozikit mcp --transport streamable-http --workspace ./workflows --port 8000
```

客户端连接 `http://127.0.0.1:8000/mcp`。`mozikit-mcp`、`python -m src.mcp_server`
和 `python main.py mcp` 同样支持这些参数。默认传输仍是 stdio，HTTP 默认只监听本机。
`/mcp` 使用官方 SDK 处理 POST、GET 事件流及 DELETE 会话终止，与普通 REST API 的
`serve` 命令分别运行。

如需鉴权，在服务器环境设置 `MOZIKIT_MCP_TOKEN`，客户端每次请求携带
`Authorization: Bearer TOKEN`。使用静态共享 Token，当前不提供 OAuth 授权流程。
Token 通过环境变量读取，不作为命令行参数或启动日志输出。

非本机监听必须设置 Token。监听所有网卡时，还须显式提供客户端实际访问的 Host：

```bash
export MOZIKIT_MCP_TOKEN="replace-with-a-random-token"
mozikit mcp --transport streamable-http --host 0.0.0.0 --port 8000 \
  --allowed-host server.example:8000 --workspace ./workflows
```

将示例 Token 和主机名替换为自己的值。跨机器访问可通过 HTTPS 反向代理或 SSH 隧道。
`--allowed-host` 可重复，使用 HTTP Host 头中的主机名和端口；HTTPS 默认端口通常省略。
SDK 的 Host/Origin 校验始终开启；监听地址对应的 Host 和同源 Origin 自动允许。
`--allowed-origin https://client.example` 可增加允许的 Origin，不会自动启用跨域 CORS。
代理转发的 Host 也须在允许列表内。

会话保存在服务进程内，客户端退出时可通过 DELETE 释放；服务重启后需重新初始化。
运行报告仍持久化在工作空间，可跨重启读取。HTTP 当前不提供跨进程会话共享或事件重放。

## 客户端配置

在客户端支持的 MCP 配置文件中添加以下内容，并替换绝对路径：

```json
{
  "mcpServers": {
    "mozikit": {
      "command": "/absolute/path/to/venv/bin/mozikit-mcp",
      "args": ["--workspace", "/absolute/path/to/workflows"],
      "cwd": "/absolute/path/to/mozikit"
    }
  }
}
```

Windows 中命令通常是 `C:\\path\\to\\venv\\Scripts\\mozikit-mcp.exe`。
配置字段以具体客户端为准；如果客户端不支持 `cwd`，可用其启动脚本设置工作目录。
工作目录应是平时使用 Mozikit 的目录，因为 `config.json`、`user_data/` 节点库及日志
仍遵循应用现有的相对路径规则。`--workspace` 单独决定工作流根目录。

Codex 的 `config.toml` 示例：

```toml
[mcp_servers.mozikit]
command = "/absolute/path/to/venv/bin/mozikit-mcp"
args = ["--workspace", "/absolute/path/to/workflows"]
cwd = "/absolute/path/to/mozikit"
tool_timeout_sec = 300
```

使用 HTTP 时，改为 URL 配置，并预先启动 HTTP 服务：

```toml
[mcp_servers.mozikit]
url = "http://127.0.0.1:8000/mcp"
tool_timeout_sec = 300
```

服务器启用了 Token 时，在这个配置段加入
`bearer_token_env_var = "MOZIKIT_MCP_TOKEN"`，并在 Codex 的运行环境设置相同 Token。

按工作流耗时调整客户端的工具调用超时。`run_workflow` 等待执行结束后返回；
当前版本不会把调用转为后台任务。客户端取消调用不保证终止正在执行的节点。

## 可用工具

| 工具 | 参数 | 返回内容 |
|---|---|---|
| `list_workflows` | 无 | 工作空间下 `*/workflow.json` 的名称、相对路径、节点数 |
| `get_workflow` | `path` | 原始工作流 JSON |
| `validate_workflow` | `path` | `valid`、错误列表、执行顺序和节点/连接数 |
| `run_workflow` | `path`、可选 `input_data` 对象 | 完整报告：`success`、`run_id`、节点结果、`final_context`、stdout/stderr |
| `list_runs` | `path`、可选 `limit`（1–100，默认 20） | 按运行标识从新到旧排列的历史摘要 |
| `get_run` | `path`、`run_id` | 已持久化的完整运行报告 |
| `get_run_logs` | `path`、`run_id`、可选 `stream`、`offset`、`limit` | 日志行、`next_offset`、`has_more` |

先调用 `list_workflows` 获取 `path`，例如 `demo/workflow.json`。路径相对于所选
工作空间，也接受位于该空间内的绝对路径。路径遍历和指向空间外部的符号链接会被拒绝。
日志 `stream` 为 `stdout`（默认）或 `stderr`，`offset` 是从零开始的行偏移，
`limit` 默认 200、最大 1000。运行报告兼容 GUI/CLI 已有格式，可跨服务重启查询。

校验检查版本 1/2 文件结构、唯一节点 ID、连接引用和循环依赖；它不会执行节点，
也不验证节点代码、依赖是否已安装或外部服务是否可访问。

执行前会通过 uv 准备工作流环境并安装声明的依赖。必须已有可用节点库及 uv。
运行使用本地用户权限，节点可访问其正常运行所需的文件、网络和应用；工作空间路径限制
约束工具选择的工作流和报告，不构成节点代码沙箱。`run_workflow` 标注为有副作用，
其余工具标注为只读。执行失败时返回 MCP `isError: true` 并保留运行报告。

报告与日志存放在 `WORKSPACE/工作流名称/runs/RUN_ID/`。为避免覆盖共享脚本和环境，
同一服务进程中的执行请求串行处理；查询工具和 MCP ping 可在执行时继续响应。

本版本提供 stdio、Streamable HTTP MCP Server 和上述工具；第三方 MCP Client、
MCP Resources/Prompts 尚未实现。

## 验证

```bash
python -m pytest test/unit/test_mcp_workflows.py test/unit/test_mcp_http_config.py \
  test/integration/test_mcp_stdio.py test/integration/test_mcp_http.py -q
```

集成测试使用官方 SDK 客户端连接真实子进程，覆盖初始化、工具发现、参数错误、
实际工作流成功/失败执行、历史与日志读取、stdout 纯协议输出及无 Qt 启动。
测试在临时目录创建无第三方依赖的节点和虚拟环境，不下载节点依赖。
HTTP 测试使用实际本机 TCP 连接，覆盖共享工具、鉴权、Host/Origin 校验及多会话清理。
