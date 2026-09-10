## Why

节点分发策略目前悬而未决：内置快照 `official_nodes/manifest.json` 是空占位（`repo_version: "0.0.0", nodes: {}`），全新安装的用户打开软件时**一个节点都没有**，必须依赖网络从 GitHub 下载才能开始使用；而 GitHub 在国内访问不稳定，首启体验差且离线环境完全不可用。需要明确"内置最小快照兜底 + 官方仓库统一更新"的混合策略，并修复快照为空的问题。

## What Changes

- 构建/发布流程中增加一步：从 `mozikit/mozikit-official-nodes` 仓库同步一份**版本固定的最小核心节点快照**，随主程序内置，作为离线/首启兜底。
- 内置快照的 `manifest.json` 增加 `app_min_version` 兼容声明，旧版主程序加载到过新节点时给出明确提示而非静默失败。
- 官方节点仓库地址改为**可配置**（环境变量/配置文件），支持镜像源（如 Gitee），国内用户可切换到镜像下载。
- 明确并固化分发规则：注册表永远优先 `user_data/official_nodes`（用户可写目录），内置快照仅作 bootstrap；官方节点的唯一更新通道是官方仓库（含镜像），不引入第二条更新路径。
- 保持现状：GUI 启动时检查更新但**不自动安装**，由用户确认后安装。
- 将上述策略写入文档（`docs/NODE_VERSION_SYSTEM.md` 或新增分发策略章节）。

## Capabilities

### New Capabilities
- `official-node-bundling`: 内置官方节点快照的生成、同步、版本兼容声明与回退加载规则
- `official-node-updates`: 官方节点的统一更新通道、镜像源配置与检查/安装流程

### Modified Capabilities
<!-- 无现有 spec，暂无修改 -->

## Impact

- `src/core/node_repo_manager.py`：`OFFICIAL_REPO_URL` 可配置化；内置快照路径解析与版本校验；manifest 兼容性检查
- 构建/发布流程：新增"同步官方节点快照"步骤（GitHub Actions 或发布脚本）
- `src/core/node_registry.py`：加载时校验内置快照的 `app_min_version`
- `docs/NODE_VERSION_SYSTEM.md`：补充分发策略章节
- 配置层：新增镜像源配置项（`ConfigManager` 或环境变量）
