## ADDED Requirements

### Requirement: Configurable official source

官方节点仓库地址 SHALL 可配置。解析优先级 SHALL 为：环境变量 `MOZIKIT_OFFICIAL_NODES_URL` > 配置文件（`ConfigManager`）> 硬编码默认值。更新检查与安装操作 SHALL 使用解析后的源地址。

#### Scenario: Environment variable set
- **WHEN** 环境变量 `MOZIKIT_OFFICIAL_NODES_URL` 被设置为镜像地址
- **THEN** 更新检查与安装均从该镜像地址拉取清单与文件

#### Scenario: Only config file set
- **WHEN** 未设置环境变量但配置文件包含官方源地址
- **THEN** 使用配置文件中的地址

#### Scenario: No override configured
- **WHEN** 环境变量与配置文件均未设置
- **THEN** 使用默认官方仓库地址（https://github.com/mozikit/mozikit-official-nodes）

### Requirement: Single update channel for official nodes

官方节点（含内置快照中的节点）的更新来源 SHALL 唯一：官方仓库（或其配置的镜像）。系统 SHALL NOT 提供针对内置快照的独立更新入口或更新路径。

#### Scenario: Check for updates
- **WHEN** 用户触发官方节点更新检查
- **THEN** 系统仅对比解析后的官方源 manifest 与本地版本，无其他来源参与

#### Scenario: No separate bundled update entry
- **WHEN** 用户在 GUI 中浏览官方节点
- **THEN** 不存在"内置节点更新"之类的独立入口；内置快照中的节点与已下载节点共用同一检查/安装流程

### Requirement: User-confirmed installation

系统 SHALL 在启动或手动检查时发现官方节点新版本，但 SHALL NOT 自动安装；安装 SHALL 仅在用户确认后进行，且写入用户目录。

#### Scenario: Updates found on startup
- **WHEN** 启动时检查发现官方仓库存在本地没有的新版本
- **THEN** 系统仅提示用户有可用更新，不自动安装

#### Scenario: User confirms installation
- **WHEN** 用户在确认后选择安装某节点的新版本
- **THEN** 系统下载并写入 `user_data/official_nodes`，注册表随后可加载新版本

### Requirement: Consistent source across operations

更新检查与版本安装 SHALL 在单次会话内使用同一解析后的源地址，避免检查与安装指向不同来源导致的不一致。

#### Scenario: Mirror configured for both
- **WHEN** 官方源被配置为镜像地址
- **THEN** 更新检查、版本安装与快照同步均使用该镜像地址，行为一致
