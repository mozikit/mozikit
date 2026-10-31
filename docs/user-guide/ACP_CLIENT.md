# ACP 外部 Agent 接入

Mozikit 可以作为 Agent Client Protocol（ACP）客户端，通过 stdio 连接本机已安装的 ACP Agent。
协议编解码由官方 Python SDK `agent-client-protocol` 负责，核心客户端不依赖 Qt。

## 安装与连接

源码环境使用项目依赖安装即可：

```bash
uv pip install -r requirements.txt
```

当前 ACP SDK 支持 Python 3.10–3.14；Python 3.15 及以上仍可安装 Mozikit，调用 ACP 时会提示缺少受支持的 SDK。
Agent 可执行文件需单独安装，并完成它自己的登录或凭据配置。Agent 继承启动 Mozikit 时的环境变量，
可继续使用现有的认证、代理和证书配置；Mozikit 不保存 Agent 登录凭据。

以下示例假设本机已安装 `codex-acp`：

```bash
# 检查协议版本、Agent 能力和认证方式，不创建会话
mozikit acp check --agent codex-acp --json

# 创建会话，流式显示文本；--cwd 是 Agent 的工作目录
mozikit acp prompt "概述当前目录的项目结构" --agent codex-acp --cwd .

# 单个 JSON 输出，包含回复、停止原因、会话 ID 和完整更新
mozikit acp prompt "解释这个项目" --agent codex-acp --cwd . --timeout 120 --json
```

从源码运行时可以用 `python main.py acp ...` 替代 `mozikit acp ...`。
Agent 参数使用可重复的 `--agent-arg`，不经过 shell，也不会拆分包含空格的参数：

```bash
mozikit acp check --agent python --agent-arg /absolute/path/to/agent.py --json
# 参数本身以 -- 开头时使用等号形式
mozikit acp check --agent my-acp-agent --agent-arg=--acp --json
```

如果 Agent 要求通过 ACP 认证，先查看 `check` 返回的 `authMethods`，再显式指定其中的 ID：

```bash
mozikit acp prompt "介绍这个项目" --agent my-acp-agent --auth-method agent-advertised-id
```

## 会话、更新与取消

每次 `prompt` 命令启动一个 Agent 进程，默认创建一个新会话。Agent 公布 `loadSession` 能力且保存了会话时，
可使用 `--session SESSION_ID` 加载之前的会话；Mozikit 不保证 Agent 会跨进程保存会话。
核心 `ACPClient` 支持在同一连接和会话中连续发送多轮提示，并阻止并发提示。

文本模式只显示 `agent_message_chunk` 的文本。`--json` 模式的 stdout 只有一个 JSON 文档：

```json
{
  "success": true,
  "session_id": "agent-session-id",
  "text": "Agent 的回复",
  "stop_reason": "end_turn",
  "updates": []
}
```

`updates` 保留当前轮次的文本、思考、工具调用、工具状态等协议更新。
Agent 诊断日志写入 stderr。协议或启动错误返回结构化的 `error_code`，退出码为 1。
Agent 的 `refusal`、`max_tokens` 等结果通过 `stop_reason` 表示，调用方应按该字段判断是否完成任务。

提示默认没有执行时间上限；`--timeout` 限制提示执行时间，初始化及认证等请求分别限时 15 秒。
超时或 Ctrl+C 会尝试发送 `session/cancel`。Agent 忽略取消时会关闭连接并回收子进程，避免继续复用状态不明的会话。
Ctrl+C 或 Agent 返回 `cancelled` 时退出码为 130。

## 权限与当前边界

CLI 默认选择 Agent 提供的 `reject_once` 权限选项；没有该选项则返回取消。
工作流 ACP 节点使用相同的默认拒绝策略。
嵌入场景可传入异步 `permission_handler`，返回本次请求中公布的选项 ID；无效 ID 会被拒绝。
取消期间的权限请求始终返回取消。

```python
from src.core.acp_client import ACPClient


async def ask_agent():
    async with ACPClient("codex-acp", cwd=".", on_update=print) as client:
        await client.new_session()
        first = await client.prompt("概述项目")
        second = await client.prompt("列出关键模块")
        return first.text, second.text
```

支持文本提示、stdio、初始化、认证、会话新建/加载、更新回调、取消以及原生工作流节点。
尚未提供独立的 GUI 聊天面板、Agent 注册表、ACP 服务端、会话列表、模式/模型切换、图片/音频输入或 MCP Server 转交。
客户端不公布文件读写和终端宿主能力；Agent 自身的本地工具仍遵循 Agent 的配置和进程权限，ACP 权限回调不是系统沙箱。

## 工作流中的 ACP Agent 节点

在节点浏览器的 **AI → ACP Agent** 中添加节点，用属性面板配置 Agent、参数、工作目录和提示。
配置字段与 CLI/调度执行使用同一套逻辑，无需给工作流创建 Python 虚拟环境或生成节点脚本。
Agent 可执行文件及它自身需要的运行环境仍需预先安装。

| 配置 | 含义 |
| --- | --- |
| `agent` | Agent 可执行文件，默认 `codex-acp`，不通过 shell 启动 |
| `args` | 字符串数组；GUI 每行填写一个参数，含空格的参数保持为一个参数 |
| `cwd` | 默认工作流运行目录，即存放 `assets`、`artifacts` 的目录；相对路径以该目录为基准，绝对路径直接使用 |
| `prompt` | 文本提示，支持 `{% input %}` 等上下文表达式；留空时使用 `prompt` 输入端口 |
| `auth_method` | 可选，只接受 Agent 公布的认证方式 ID |
| `session_id` | 可选，加载 Agent 保存的会话；Agent 必须支持 `loadSession` |
| `timeout` | 整个节点的执行期限，默认 120 秒，包含连接、认证和提示；不会超过应用设置的节点超时 |

节点提供 `prompt`、`input` 两个输入端口，以及 `text`、`session_id`、`stop_reason`、`updates` 四个输出端口。
将上游字符串连到 `prompt`，或在提示中用 `{% input %}` 引用 `input` 端口的数据。
回复文本可连接到 Debug、模板或其他下游节点。消息文本和工具状态进入实时日志、节点报告与运行历史，
`updates` 输出保留本轮协议更新。

每次执行节点启动一个独立 Agent 进程。只有 `stop_reason=end_turn` 才执行下游；拒绝、输出截断或取消会让节点失败，
报告保留 `ACP_TURN_INCOMPLETE` 或 `ACP_CANCELLED` 错误码。
超时会取消 Agent 并记录 `ACP_TIMEOUT`；GUI 的停止按钮和 CLI 的 Ctrl+C 会取消 Agent、回收进程并将工作流标记为停止。
进程退出和其他协议错误沿用核心客户端的结构化错误码。

仓库提供了 [ACP → Debug 示例](../../examples/acp_agent_workflow.json)。安装并登录 `codex-acp` 后可运行：

```bash
mozikit run examples/acp_agent_workflow.json --input '{"task":"用两句话解释 ACP"}' --json
```

示例的 Agent 默认在工作流运行目录执行。需要分析其他项目时，将节点的 `cwd` 配置为目标项目目录。
