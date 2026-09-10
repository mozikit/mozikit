## ADDED Requirements

### Requirement: Bundled snapshot availability

主程序 SHALL 随包内置一份官方节点快照（`official_nodes/`），作为离线与首次启动场景的兜底。当内置快照缺失或为空时，系统 SHALL 发出明确警告并继续运行（不崩溃、不阻塞其他功能）。

#### Scenario: Fresh install without network
- **WHEN** 用户全新安装主程序且无网络连接
- **THEN** 内置快照中的官方节点可被注册表加载并用于创建工作流

#### Scenario: Bundled snapshot missing or empty
- **WHEN** 内置快照目录不存在，或其 manifest 声明 `nodes` 为空
- **THEN** 系统记录警告日志，且注册表加载流程继续执行而不抛异常

### Requirement: Reproducible snapshot generation

系统 SHALL 提供快照同步脚本，从官方节点仓库（或配置的镜像源）拉取远程 manifest 与各节点当前版本文件，生成 `official_nodes/` 快照。生成的 manifest SHALL 记录 `repo_version` 与 `snapshot_commit` 以保证可复现。

#### Scenario: Run sync script
- **WHEN** 用户或构建流程运行同步脚本且源仓库可访问
- **THEN** `official_nodes/` 下生成 manifest.json 及各节点的版本目录（node.json、node.py 及附加文件）

#### Scenario: Sync uses configured source
- **WHEN** 官方源地址被配置为镜像（环境变量或配置文件）
- **THEN** 同步脚本从该镜像拉取清单与文件，而非硬编码的默认地址

#### Scenario: Manifest records provenance
- **WHEN** 同步脚本成功生成快照
- **THEN** manifest.json 包含 `repo_version` 与 `snapshot_commit` 字段，可据此重建同一快照

### Requirement: Snapshot version compatibility

清单级字段 `app_min_version` SHALL 声明快照要求的最低主程序版本。加载官方节点时，系统 SHALL 比较当前主程序版本与清单声明：不满足时 SHALL 跳过该来源并给出明确提示，而非静默加载。

#### Scenario: Snapshot requires newer app
- **WHEN** 快照 manifest 的 `app_min_version` 高于当前主程序版本
- **THEN** 系统跳过该快照来源并记录/输出明确的不兼容提示

#### Scenario: Snapshot is compatible
- **WHEN** 当前主程序版本满足快照的 `app_min_version`
- **THEN** 快照中的官方节点正常加载

#### Scenario: Legacy manifest without field
- **WHEN** manifest 不含 `app_min_version` 字段
- **THEN** 系统按兼容处理，正常加载（向后兼容旧清单）

### Requirement: Local-over-bundled priority and read-only bundled dir

官方节点的加载优先级 SHALL 为：`user_data/official_nodes`（用户目录）优先，内置快照仅作 bootstrap 回退。运行时 SHALL 只向用户目录写入（安装/更新），内置快照目录 SHALL 只由同步脚本在构建期写入。

#### Scenario: User directory has installed nodes
- **WHEN** `user_data/official_nodes` 非空且存在已安装节点
- **THEN** 注册表加载用户目录中的节点版本，而非内置快照版本

#### Scenario: User installs an official node update
- **WHEN** 用户确认安装某官方节点的新版本
- **THEN** 新版本写入 `user_data/official_nodes`，内置快照目录内容不被修改
