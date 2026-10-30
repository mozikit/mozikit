# CLI / GUI 业务验收

本目录有 10 个中文 Gherkin feature、89 个场景定义、177 个展开用例。
`contracts.json` 中稳定 ID 对应 feature 标签，`*_cases.py` 是实际业务驱动。
Given 为隔离的真实目录和配置，When 执行业务，Then 核对文件、报告、模型、HTTP 请求或进程状态。
GUI 场景使用真实 Qt 控件与 worker；离线外部服务只替换 HTTP/UV 等边界，不替换被验收的业务结果。

## 复跑

安装 `pip install -e ".[test,gui,serve]"`。pytest 目前固定 `<9`，以兼容 pytest-bdd 9 的 fixture 接口。
Linux 设置 `QT_QPA_PLATFORM=offscreen`，测试凭据后端使用 `PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring`。

```bash
python -m pytest test/acceptance -q -m 'not packaged and not live and not windows' \
  --acceptance-report=acceptance.json
python tools/check_acceptance.py acceptance.json
python -m pytest -q -m 'not packaged and not live and not windows and not performance' \
  --cov=src --cov-branch --cov-report=json:coverage.json --acceptance-report=acceptance.json
python tools/check_coverage.py coverage.json
python -m pytest test/unit/test_cli_performance.py -q
```

Windows 离线执行移除 `not windows`，这样包括原生 Windows 文件覆盖检查。
不可设置全局 `MOZIKIT_CONFIG_PATH`，否则会覆盖测试自己的配置隔离。
`--acceptance-report` 明确表示本次选择的 cohort；未选择的成品和现场场景并不因此完成。
默认运行全部场景时，缺少前置条件会记录 `blocked`，验收门禁返回失败。

## 用例目录

| feature | ID | 定义 / 展开 |
| --- | --- | --- |
| workflow_lifecycle | WF | 15 / 40 |
| workflow_editing | EDIT | 6 / 15 |
| execution_history | RUN | 9 / 11 |
| execution_reuse | CACHE | 7 / 20 |
| ai_generation | AI | 6 / 13 |
| scheduling | SCH | 8 / 10 |
| playwright_runtime | PW | 8 / 20 |
| integrations | INT | 12 / 16 |
| persistence_ci | PERSIST、CI | 10 / 21 |
| desktop_distribution | DIST | 8 / 11 |

标题、预期或变体变更必须同步修改 feature 和 contracts.json。不能删除失败用例来满足计数。
`test_binding_integrity.py` 检查目录与驱动完整性；feature 本身由 pytest-bdd 解析执行。

## Windows 成品与现场前置条件

在可销毁的 Windows VM 中，从同一提交生成 MSI 与 portable ZIP，并实际安装 MSI。
保留安装器、ZIP、两个安装根目录及其中 exe 的 SHA-256。禁止用 `sys.frozen=True` 代替成品。
验收入口见 `external_cases.py` 与 `external-manifest.example.json`。
通过环境变量 `MOZIKIT_ACCEPTANCE_EXTERNAL_MANIFEST` 指定证据清单；未提供时明确阻塞。
自动化部分会直接执行成品 CLI，子进程清除 PYTHONPATH/VIRTUAL_ENV，仅保留系统目录与发行版 runtime 的 PATH。
PATH 注册操作仅允许清单中声明的 disposable Windows VM，并在 finally 恢复用户注册表原始值和类型。

现场清单包含 source_ref、操作者、UTC 时间、成品哈希、逐项观察和证据文件哈希。
人工 GUI/Chrome/更新验证只按该证据验收，报告注明 manual；不会表述为自动化已验证。
敏感凭据不得写入清单、日志或截图。隔离账号不应指向生产资源。

| ID | 必须观察及保留的证据 |
| --- | --- |
| DIST_005 | GUI 打开同一临时工作区，看到 CLI 运行记录；GUI 运行后 CLI history 能读取同一个 run.json；截图和报告 |
| DIST_006 | `--check` 不下载安装；无确认不交接；确认后返回 pending_install/3；安装器进程与更新日志 |
| DIST_007 | 错误哈希更新包被拒绝；安装器未启动；用户数据前后哈希一致；错误 JSON 和进程记录 |
| DIST_008 / msi、portable | 实际 Chrome 操作生成脚本，CLI 回填、rescan，GUI 打开并执行；代码、报告、截图或录像 |
| INT_012 | 分别验证 AI 生成、GitHub 私有节点、工作流 push/pull、官方节点、OAuth 登录退出、MCP 外部服务；逐项报告与脱敏请求日志 |

更详细的工作顺序和门槛见 [实施计划](../../docs/development/CLI_GUI_PARITY_PLAN.md)。
