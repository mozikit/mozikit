# CLI / GUI 等价性验证记录

2026-10-30，Linux / Python 3.12。审计基线 dev：`368c143f739444070a4bce02aa61cec39eff50b4`。
以下结果来自实际测试命令；Windows、成品和现场验证单独记录。

| 验证 | 结果 |
| --- | --- |
| 全量离线功能测试，排除 packaged/live/windows/performance | 760 passed，17 skipped，18 deselected |
| 中文业务 feature | 164 个离线展开用例全部通过；10 个 feature / 89 个定义 / 177 个展开用例全部有业务绑定 |
| CLI 语句 / 分支覆盖率 | 90.33% / 78.60%，门槛 85% / 75% |
| 新核心服务语句 / 分支覆盖率 | 95.84% / 91.84%，门槛 90% / 85% |
| 业务证据门禁 | selected offline cohort 通过，每项有非零业务断言 |
| 无 Qt 独立安装 | 未安装 PySide6；6 条真实 CLI 命令完成中文工作流创建、添加节点、执行与历史报告往返 |
| 性能 | 单独运行 5 项真实执行、渲染和持久化测试，不开启 coverage |

核心服务覆盖率包含 workflow_lifecycle、execution_snapshots、playwright_runtime、config_transactions。
CLI 覆盖率包含 cli.py 与 cli_parity.py；语句和分支按实际数量分别汇总。

复跑命令见 [验收 README](../../test/acceptance/README.md)。CI 产物名为 `coverage.json`、`tests.xml`、`acceptance.json`。
本地完整日志和 JSON 位于 `/workspace/work/mozikit-implementation/`；不将本地绝对路径视作远端 CI 证据。

17 个旧测试跳过的分类：9 个需要官方节点仓库定义，6 个历史人工 GUI 检查，1 个 UV 设置人工对话框，1 个 Windows AppData 迁移。
新验收已覆盖生命周期、节点删除、真实配置表单、脚本编辑与 GUI 重开；旧人工检查不用于证明新场景通过。

尚待外部验证的 13 个展开用例：Windows 原生保存 PERSIST_005（1）、Windows 成品 DIST_001–008（11）、外部服务现场 INT_012（1）。
实际 Windows CI 可以完成原生保存项；MSI/portable、PATH 注册、真实 Chrome 和测试账号项需要对应环境及可追溯的现场证据。
验收全目录运行会将缺少前置条件的项目记为 blocked；完整目录门禁应拒绝通过，不得把离线 cohort 成功写成全场景成功。

跨版本补充验证：独立 Python 3.10 与 3.11 环境各有 12 项 MCP 实际 stdio/HTTP、作用域所有权与 Worker 管道测试通过。
修复了 SDK cancel scope 在不同 task 关闭的问题，以及 Windows 主线程阻塞读管道时无法及时处理中断的问题。
另修复了系统 PATH 的 HKLM 注册表键读取，并添加真实 MSI/portable 构建、安装、验收、卸载的 CI 入口。
自定义工作区的 GUI 保存、运行、重命名和删除已统一到工作区解析器；对应真实窗口回归通过。

草稿 PR：https://github.com/mozikit/mozikit/pull/2 。首轮 Python 3.12 CI 成功；后续跨平台修复的远端结果仍需单独确认。

发布门禁另要求同源提交的 Linux 和 Windows 最新 CI 都成功；不能用此本地记录放行发布。
