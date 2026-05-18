# LocalFlow 节点多版本系统

## 概述

LocalFlow 现在支持**节点多版本共存、按需选择更新、旧工作流不受更新影响**的完整方案。

## 核心特性

1. **多版本物理隔离** - 每个节点的多个版本独立存储，互不干扰
2. **工作流版本绑定** - 工作流可显式指定使用节点的特定版本
3. **选择性更新** - 用户可选择性安装特定版本，不强制全量更新
4. **自动迁移** - 旧结构节点自动迁移到新版本结构
5. **向后兼容** - 未指定版本的工作流继续使用默认版本

## 存储结构

### 官方节点

```
user_data/official_nodes/
└── my_node/
    ├── versions/
    │   ├── 1.0.0/
    │   │   ├── node.json
    │   │   └── node.py
    │   └── 1.2.0/
    │       ├── node.json
    │       └── node.py
    ├── current -> versions/1.2.0   (符号链接/junction/文本文件)
    └── .manifest                   (本地版本清单)
```

### 自定义节点

```
user_data/custom_nodes/
└── my_custom_node/
    ├── versions/
    │   ├── 1.0.0/
    │   │   ├── node.json
    │   │   └── node.py
    │   └── 2.0.0/
    │       ├── node.json
    │       └── node.py
    └── current -> versions/2.0.0
```

### 外部节点 (GitHub/Enterprise)

```
user_data/external_nodes/github/
└── my_github_node/
    ├── versions/
    │   ├── 1.0.0/
    │   │   ├── node.json
    │   │   └── node.py
    │   └── 1.1.0/
    │       ├── node.json
    │       └── node.py
    ├── current -> versions/1.1.0
    └── .manifest
```

## 核心模块

### NodeVersionManager

负责本地多版本存储的核心逻辑：

```python
from src.core.node_version_manager import NodeVersionManager

vm = NodeVersionManager(base_dir)

# 路径解析
vm.get_node_json_path(node_type, version)  # 获取 node.json 路径
vm.get_node_py_path(node_type, version)    # 获取 node.py 路径

# 版本解析
vm.resolve_current_version(node_type)      # 解析 current 指向的版本
vm.resolve_version_for_execution(node_type, requested_version)  # 执行时解析

# 版本操作
vm.list_local_versions(node_type)          # 列出所有本地版本
vm.set_current_version(node_type, version) # 设置默认版本
vm.write_version_files(node_type, version, node_json, node_py)  # 写入版本
vm.remove_version(node_type, version)      # 删除版本

# 迁移
vm.needs_migration(node_type)              # 检查是否需要迁移
vm.migrate_legacy_node(node_type)          # 迁移单个节点
vm.migrate_all_legacy_nodes()              # 迁移所有旧节点
```

### NodeRepoManager

负责远程仓库的版本发现和选择性安装：

```python
from src.core.node_repo_manager import NodeRepoManager

mgr = NodeRepoManager(user_data_dir)

# 检查更新
result = mgr.check_for_updates()
# result.has_updates: 是否有更新
# result.updates: 每个节点的版本更新信息
# result.new_nodes: 新节点列表

# 安装特定版本
success, message = mgr.install_node_version(node_type, version)

# 列出版本
remote_versions = mgr.list_remote_versions(node_type)
local_versions = mgr.list_local_versions(node_type)

# 旧方法兼容（不再自动安装）
result = mgr.pull_updates()  # 返回 dict，包含更新信息但不自动安装
```

### CustomNodeManager

支持多版本的自定义节点管理：

```python
from src.core.custom_node_manager import CustomNodeManager

mgr = CustomNodeManager(user_data_dir)

# 创建节点（自动使用版本目录）
node = mgr.create_node(name, description, version="1.0.0")

# 导出/导入
mgr.export_node(node_type, output_path, version=None, all_versions=False)
imported_type = mgr.import_node(zip_path, target_version=None)

# 版本管理
mgr.list_node_versions(node_type)
mgr.delete_node_version(node_type, version)
```

### GitHubNodeProvider

支持多版本的 GitHub 外部节点管理：

```python
from src.core.providers.github_provider import GitHubNodeProvider

provider = GitHubNodeProvider(user_data_dir, github_token)

# 下载节点（指定版本）
node_def = provider.download_node(url, version="1.0.0")

# 下载所有节点
nodes = provider.download_nodes(url, version="1.0.0")

# 版本管理
provider.list_node_versions(node_type)
provider.delete_node_version(node_type, version)

# 迁移旧结构
provider.migrate_legacy_nodes()
```

## 工作流版本绑定

### 工作流 JSON 格式

```json
{
  "version": 2,
  "workflow_name": "my_workflow",
  "nodes": [
    {
      "node_id": "node_1",
      "node_type": "my_node",
      "version": "1.0.0",
      "config": {},
      "inputs": [],
      "outputs": []
    }
  ],
  "edges": []
}
```

### 版本解析策略

1. **工作流指定版本** - 优先使用工作流中 `version` 字段指定的版本
2. **current 指向版本** - 未指定时使用 `current` 链接指向的版本
3. **旧结构回退** - 如果节点尚未迁移，直接使用旧路径

### 执行时版本解析

```python
# WorkflowExecutor._get_versioned_script_path()
# 自动根据 node.version 加载对应版本的源代码
```

## 配置

### 默认版本策略

在 `ConfigManager` 中配置：

```python
config = ConfigManager()

# 获取策略
policy = config.get_node_version_policy()  # "latest" | "current" | "prompt"

# 设置策略
config.set_node_version_policy("current")  # 使用 current 指向的版本
```

策略说明：
- `latest` - 使用最新安装的版本（默认）
- `current` - 使用 current 链接指向的版本
- `prompt` - 提示用户选择（预留，需 UI 支持）

## 向后兼容

### 旧节点自动迁移

启动时自动检测并迁移：

```python
# NodeRegistry.__init__() 中调用
self._migrate_legacy_nodes()
```

迁移范围：
- `official_nodes/` - 官方节点
- `custom_nodes/` - 自定义节点
- `external_nodes/github/` - GitHub 外部节点
- `external_nodes/enterprise/` - 企业内网节点

迁移逻辑：
1. 扫描所有节点目录
2. 发现直接放置 `node.json` 的旧结构
3. 创建 `versions/<version>/` 目录
4. 移动文件到新目录
5. 创建 `.manifest` 和 `current` 链接

### 旧工作流兼容

加载工作流时：
- 节点无 `version` 字段 → 使用 `current` 或默认策略
- 节点有 `version` 字段 → 尝试加载该版本，不存在则回退

### 旧 API 兼容

`NodeRepoManager.pull_updates()` 仍然可用，但行为改变：
- 不再自动下载和覆盖节点
- 只返回更新检查结果
- 调用方需使用 `install_node_version()` 手动安装

## 远程仓库清单格式

### 新格式（多版本）

```json
{
  "repo_version": "2025-06-01",
  "nodes": {
    "my_node": {
      "versions": [
        {
          "version": "1.0.0",
          "min_app_version": "2.0.0",
          "files": {
            "node.json": {"hash": "sha256:abc123", "url": "https://..."},
            "node.py": {"hash": "sha256:def456", "url": "https://..."}
          }
        },
        {
          "version": "1.2.0",
          "min_app_version": "2.1.0",
          "files": { ... }
        }
      ]
    }
  }
}
```

### 旧格式兼容

如果远程仓库仍使用旧格式（`nodes` 为字符串列表），系统会自动降级处理：
- 将唯一版本视为 `"latest"`
- 只允许下载该唯一版本

## UI/UX 建议

### 节点库面板

- 每个节点显示可切换版本的下拉菜单
- "安装其他版本..." 按钮
- "设为此节点默认版本" 按钮
- 显示已安装版本列表

### 工作流编辑

- 添加节点时可指定版本（默认使用全局策略）
- 节点属性面板显示当前绑定版本
- 版本缺失时提示下载或切换

### 更新提示

- 通知区域显示"3 个节点有新版本可用"
- 点击进入选择界面
- 勾选需要下载的版本，可单独安装

## 实施路线图

### Phase 1 - 底层存储与清单重构 ✅
- [x] 修改远程 manifest 生成（支持多版本格式）
- [x] 实现本地多版本目录结构
- [x] 实现迁移脚本

### Phase 2 - 节点管理器改造 ✅
- [x] 实现按版本下载、安装
- [x] 移除自动全量更新逻辑
- [x] 兼容单版本清单

### Phase 3 - 工作流版本绑定 ✅
- [x] 工作流 schema 增加 `version` 字段
- [x] 修改运行时加载逻辑
- [x] 增加缺失版本处理

### Phase 4 - UI 与交互完善（待实现）
- [ ] 更新节点库界面，增加版本管理入口
- [ ] 工作流编辑器集成版本选择
- [ ] 更新通知与选择性安装流程
