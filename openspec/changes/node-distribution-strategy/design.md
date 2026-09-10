## Context

Mozikit 的节点分发目前处于"半成品"状态：

- `official_nodes/` 目录被 gitignore（`.gitignore:231`，注释写明"构建时从 mozikit-official-nodes 仓库同步"），但**仓库内不存在任何同步脚本或构建步骤**——`build.py:129-132` 只是"目录存在就拷贝进包"。全新克隆后该目录不存在，打包出的应用也不含快照。
- 当前工作区里的 `official_nodes/manifest.json` 是空占位（`repo_version: "0.0.0", nodes: {}`），意味着首启用户一个官方节点都没有，必须联网从 GitHub 下载。
- 更新通道已存在：`NodeRepoManager`（`OFFICIAL_REPO_URL` 硬编码于 `node_repo_manager.py:207`）支持远程 manifest 拉取、版本对比、按版本安装（带 SHA-256 与安全审查）；GUI 启动检查更新但**不自动安装**（`node_browser.py`）。
- 兼容字段已有基础：远程清单的每个节点版本已含 `min_app_version`（`node_repo_manager.py:60,431`），但**清单级**（快照级）兼容声明缺失。
- 加载优先级已正确：`active_dir` 优先 `user_data/official_nodes`（非空时），否则回退内置快照（`node_repo_manager.py:237-240`）；`node_registry._load_official_nodes` 在目录都不存在时仅告警。

本变更把"内置快照兜底 + 官方仓库统一更新"的混合策略落地，核心缺口是：**快照的生成机制不存在**、**快照级兼容声明缺失**、**官方源不可配置（无镜像支持）**。

## Goals / Non-Goals

**Goals:**
- 建立可复现的官方节点快照生成机制（构建/发布时自动同步），使离线与首启用户开箱即有核心节点。
- 为快照增加清单级 `app_min_version` 兼容声明，加载时校验，避免旧 App 加载过新节点。
- 官方仓库地址可配置（环境变量 / 配置 / 默认值），支持镜像源（如 Gitee）。
- 固化"用户目录优先、内置仅 bootstrap、官方仓库是唯一更新通道、检查不自动安装"的规则，并写入文档。

**Non-Goals:**
- 不做节点市场/注册表 API（维持 GitHub 为第三方来源）。
- 不改变社区节点（任意 GitHub 仓库）的下载机制。
- 不改变依赖安装（uv venv）与执行机制。
- 不引入"内置节点独立更新入口"（正是要避免的）。

## Decisions

### D1: 快照同步用独立脚本，构建时调用

新增 `tools/sync_official_nodes.py`：从官方仓库（或配置的镜像）拉取远程 manifest 与各节点当前版本的文件（`node.json`、`node.py` 及附加文件），写入项目根 `official_nodes/`，并记录 `repo_version` + `snapshot_commit` 保证可复现。`build.py` 打包前自动调用（目录不存在时不再静默跳过），发布流程同样执行。

- **备选 A：GitHub Actions 定时同步** — 被否：构建必须能在本地/CI 任意环境可复现，脚本方式不依赖 CI 平台；且快照需要与具体发布版本绑定而非"最近一次定时同步"。
- **备选 B：手动维护快照** — 被否：必然遗忘/过期，正是当前空占位的成因。
- **备选 C：首启运行时自动下载** — 被否：违背离线兜底目标；与"检查更新不自动安装"的产品原则冲突。

脚本复用 `NodeRepoManager` 的 `urllib` 拉取与哈希逻辑（`_gh_get` / `compute_content_hash`），不引入新依赖。

### D2: 快照级 `app_min_version`（清单级），加载时校验

在 `RemoteManifest` 增加顶层 `app_min_version`（`from_dict` 用 `data.get` 解析，向后兼容旧清单）。`node_registry._load_official_nodes` 加载时（对内置快照与用户目录均生效）比较当前 App 版本（`src/core/__version__`）与清单声明：不满足则跳过该来源并给出明确提示，不静默失败。

- **备选：仅依赖现有 per-node `min_app_version`** — 不够：per-node 字段只在安装时生效，无法防护"用户目录被新版 App 更新过、随后降级 App"以及"内置快照整体过新"的情形；加载时校验需要清单级字段。
- 版本比较复用 `NodeRepoManager._sort_versions` 的解析思路做简单数值比较，不引入 semver 依赖。

### D3: 官方源地址三级可配置

`OFFICIAL_REPO_URL` 解析优先级：环境变量 `MOZIKIT_OFFICIAL_NODES_URL` > `ConfigManager` 配置项 > 硬编码默认。统一应用于 `check_for_updates`、`install_node_version` 与同步脚本。保留现有"本地 manifest 的 `repo_url` 覆盖"（`node_repo_manager.py:283-284`）——它是仓库侧的重定向能力，与用户侧配置互不冲突。

- **备选：仅配置文件** — 环境变量对 CI/企业部署/命令行场景更直接，两者叠加成本极低。
- 镜像只需与官方仓库保持同步的 fork（manifest 内 `repo_url` 指向镜像自身），更新检查天然以镜像为准。

### D4: 内置目录只读，写入只走用户目录

运行时所有写操作（安装、更新）只发生在 `user_data/official_nodes`；内置快照目录仅由同步脚本在构建期写入。代码上通过约定 + 注释固化，不新增强制写保护（避免过度工程）；在 `_find_bundled_dir` 与 `active_dir` 的注释中明确该规则。

### D5: 文档化分发策略

`docs/NODE_VERSION_SYSTEM.md` 新增"分发策略"章节，明确四规则：用户目录优先、内置仅 bootstrap、官方仓库唯一更新通道、检查不自动安装；README 补充镜像配置说明。

## Risks / Trade-offs

- [快照体积随官方节点增长，包变大] → 同步脚本先全量（当前节点量小）；后续可在 manifest 加 `core` 标记支持子集选择。
- [镜像与官方仓库漂移（不同步）] → manifest 记录 `snapshot_commit`；更新检查以镜像自身 manifest 为准，版本对不上自然不产生更新，无静默错误。
- [`app_min_version` 比较对预发布/非标准版本号处理不完美] → 复用现有简单数值比较；比较失败时按"不兼容"提示而非崩溃，用户可手动忽略。
- [快照为空/缺失时回退行为] → 维持现状（告警 + 无节点），不引入崩溃路径；同步脚本可随时补齐。
- [配置文件/环境变量优先级引入心智负担] → 优先级简单固定（env > config > default），文档一处写明。

## Migration Plan

1. 发布 `tools/sync_official_nodes.py` 并接入 `build.py`，首次发布时执行一次生成快照，随包内置。
2. 现有用户不受影响：`active_dir` 已优先用户目录，已安装的节点继续生效。
3. 回滚：删除/保留快照均可，代码路径在快照缺失时回到现有"告警 + 无节点"行为；配置项不设置即回退默认源。

## Open Questions

- 快照应包含全部官方节点还是核心子集？（当前建议全量，量小）
- 镜像仓库的具体托管位置（如 Gitee 上的组织/仓库名）由谁维护？镜像同步策略（手动 push / webhook）待定。
- `app_min_version` 的提示是否需要 UI 层（节点浏览器内）展示，还是仅日志/CLI 输出？（建议先 CLI + 日志）
