## 1. 快照同步脚本

- [x] 1.1 新增 `tools/sync_official_nodes.py`：复用 `NodeRepoManager` 的 `_gh_get` / `compute_content_hash` 逻辑拉取远程 manifest（支持镜像地址）
- [x] 1.2 实现节点文件下载：按远程清单中每个节点的当前版本下载 `node.json`、`node.py` 及附加文件，写入 `official_nodes/<node_type>/versions/<version>/` 并设置 `current`
- [x] 1.3 生成 `official_nodes/manifest.json`：包含 `repo_name`、`repo_url`、`repo_version`、`snapshot_commit`、`app_min_version`、`nodes`
- [x] 1.4 支持 `--source <url>` 参数与 `MOZIKIT_OFFICIAL_NODES_URL` 环境变量覆盖源地址

## 2. 清单级 app_min_version 兼容校验

- [x] 2.1 `RemoteManifest.from_dict` / `to_dict` 增加顶层 `app_min_version` 字段（`data.get` 解析，向后兼容旧清单）
- [x] 2.2 实现主程序版本比较工具（复用 `_sort_versions` 的数值解析思路，比较失败按不兼容处理）
- [x] 2.3 `node_registry._load_official_nodes` 加载时校验清单 `app_min_version`，不满足则跳过该来源并输出明确提示
- [x] 2.4 确认该校验对用户目录与内置快照两个来源均生效

## 3. 官方源地址可配置

- [x] 3.1 `NodeRepoManager` 新增 `resolve_official_repo_url()`：优先级 环境变量 > `ConfigManager` > 默认值
- [x] 3.2 `check_for_updates` 与 `install_node_version` 改用解析后的源地址
- [x] 3.3 `ConfigManager` 增加官方节点源地址配置项的读写
- [x] 3.4 保留现有"本地 manifest 的 `repo_url` 覆盖"逻辑，补充注释说明其与用户配置的职责区分

## 4. 构建接入与文档

- [x] 4.1 `build.py` 打包前调用同步脚本生成快照（目录不存在时不再静默跳过）
- [x] 4.2 `docs/NODE_VERSION_SYSTEM.md` 新增"分发策略"章节：用户目录优先、内置仅 bootstrap、官方仓库唯一更新通道、检查不自动安装
- [x] 4.3 `README.md` 补充镜像源配置说明（环境变量与配置文件用法）

## 5. 验证

- [x] 5.1 运行同步脚本生成快照，核对 `manifest.json` 字段与节点目录结构
- [x] 5.2 验证空快照/无快照场景：注册表加载仅告警、不崩溃、其余功能正常
- [x] 5.3 验证 `app_min_version` 不兼容场景：来源被跳过且提示明确
- [x] 5.4 验证镜像源（环境变量与配置两种方式）下 `node repo check-updates` / `install` 均走镜像
- [x] 5.5 冒烟测试：`mozikit node repo list` 与 GUI 启动加载官方节点正常
