# GUI 与 CLI 功能对应

业务操作通过 CLI 可执行；窗口停靠、标签页切换、缩放等显示操作仍由 GUI 提供。
CLI 编辑工作流时保留原有节点坐标和画布状态。

Windows Desktop 安装后直接使用 PATH 中的 `mozikit`；源码目录则使用 `.venv\Scripts\mozikit.exe`，或激活环境后使用 `mozikit`。
下文省略可执行文件前缀。Trigger、脚本命令的路径或名称应位于 `--workspace` 指定的工作区内。

| GUI 操作 | CLI |
| --- | --- |
| 创建、删除、重命名工作流 | `workflow create/delete/rename` |
| 添加、配置、删除节点 | `workflow add-node/update-node/remove-node` |
| 创建、移除连接 | `workflow connect/disconnect` |
| 执行整个工作流 | `run workflow.json` |
| 执行目标节点和所有必需上游 | `run workflow.json --node node_id` |
| 停止本次执行 | 在运行命令的终端按 Ctrl+C；通过执行器停止当前运行 |
| 完整执行报告 | `run workflow.json --json --output report.json` |
| 启停监听、查看状态 | `workflow activate/deactivate/status` |
| Trigger 配置 | `workflow trigger list/show/add/set/enable/disable/remove/status` |
| 定时任务 | `schedule list/add/update/remove/run/pause/resume` |
| 工作流 GitHub 同步 | `workflow sync push/pull/status/list/config` |
| 新建、AI 生成、导入导出节点 | `node create/generate/import/export`（import 为 ZIP） |
| 删除自定义或 GitHub 节点 | `node delete node_type` |
| 查看节点源代码 | `node source show node_type [--output node.py]` |
| 校验并保存节点源代码 | `node source set node_type node.py` |
| 查询节点引用 | `node usage node_type` |
| 官方节点更新检查、安装 | `node repo check-updates/install` |
| GitHub URL 导入 | `node github import https://github.com/owner/repo` |
| 列出、更新、删除已导入仓库 | `node github list/update/remove`；update 可省略 URL 更新全部 |
| 列出、保存、删除自定义凭据 | `credential list/set/remove` |
| 测试已保存的 AI 连接配置 | `config test-ai` |
| 历史记录列表 | `workflow history list [--workflow 名称] [--limit 50]` |
| 历史完整报告 | `workflow history show run_id` |
| UV 检测、镜像设置 | `env status/set-mirror` |
| 安装 UV、保存 UV 路径 | `env install-uv`、`env set-uv-path 可执行文件路径` |
| Playwright 脚本读取、保存 | `workflow script show 工作流 节点ID`、`workflow script set 工作流 节点ID script.py` |
| Playwright 校验、重扫参数、清空 | `workflow script validate/rescan/clear 工作流 节点ID` |
| Playwright 录制并回填 | `workflow script record 工作流 节点ID [--url 起始地址]` |
| 安装 Playwright 录制工具 | `workflow script install-runtime`（通过 UV 安装到当前 Python） |

## 配置值与连线规则

`add-node --config`、`update-node` 和 `run --args` 的 `key=value` 按 JSON 解析值：
`enabled=false` 是布尔值，`count=30` 是数字，`items=[1,2]` 是数组。
未使用 JSON 语法的普通文本保留为字符串。需要数字字符串时，将值编码为 JSON 字符串，
例如 PowerShell 中传入 `'count="30"'`。对象、数组也需作为一个完整参数传入。

CLI 连线会验证端口存在、禁止自连接、检查类型兼容性，并替换目标输入端口上的旧连接。
它与 GUI 使用相同的类型兼容规则。

## 凭据、源码和脚本

`credential set 名称` 默认隐藏输入；自动化可使用 `--value-file UTF8文件`。
`config set custom_credentials.名称 值` 也会走安全存储，但参数可能进入 shell 历史，优先使用隐藏输入或文件。
列表和配置查询不会显示自定义凭据内容。内置 AI/GitHub 凭据仍使用各自设置入口。

`node source set` 修改节点类型的源码，影响使用该节点类型的工作流。
`workflow script set` 只修改指定工作流中 Playwright 节点的内嵌脚本，自动同步参数 schema、
保留仍存在的参数值，并移除不再使用的参数。语法错误不会覆盖原配置。
录制会打开 Playwright 浏览器，正常退出且生成有效脚本后才写回；使用 Chrome channel，与 GUI 一致。

## 执行和历史

Ctrl+C 在执行阶段调用与 GUI 停止按钮相同的执行器停止接口；停止报告返回退出码 130。
准备阶段被中断同样返回 130。此操作只针对当前 CLI 运行，不会停止整个 Runtime Daemon。
不提供跨终端停止任意运行的命令，也不以 `runtime stop` 代替运行取消。

`run --json` 保留完整节点输入、输出、日志和报告字段，以及既有 CLI 摘要字段；
与 `--output` 联用时也会保存报告。GUI 历史页和 CLI 使用 ConfigManager 的同一份运行索引，
“查看”和 `history show` 读取该运行的 `run.json`。启动失败没有产物时返回索引记录；
已删除产物会明确报告不存在。

外部 AI、GitHub、UV 安装和浏览器录制依赖网络、凭据或本地安装条件。
自动化测试使用隔离数据及外部服务替身，不代表已完成这些服务的现场验收。
