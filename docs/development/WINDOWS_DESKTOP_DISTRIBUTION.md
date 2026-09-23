# Mozikit Desktop Windows 分发设计与实施

本文是 Windows 分发体系的当前设计基线。产品名仍为 **Mozikit**；完整安装版称为 **Mozikit Desktop**，但用户界面、开始菜单和 MSI 产品名均显示 **Mozikit**。

## 1. 当前问题与目标

旧构建只有一个隐藏控制台的 `Mozikit.exe`，GUI/CLI 入口、用户工作目录和安装器目标不一致，冻结环境还可能把自身 EXE 当成 Python 解释器去执行 `pip`。正式分发的安装后契约是：

```text
MozikitDesktop.exe = GUI，Windows GUI subsystem，无 console
mozikit.exe        = CLI，Windows console subsystem，保留 stdout/stderr/exit code
```

两个入口只负责适配，业务逻辑仍位于 `src/core`；本次不新增 Agent Runtime、LLM、MCP Server，也不拆出 `mozikit-cli` 产品。

## 2. 最终目录结构

PyInstaller 继续使用 directory distribution，并通过一个 checked-in multi-executable spec 生成共享目录：

```text
Mozikit/
├── MozikitDesktop.exe       # gui_launcher.py，console=False
├── mozikit.exe              # cli_launcher.py，console=True
├── runtime/
│   └── uv.exe                # 固定版本、CI 下载并校验 SHA256
├── official_nodes/           # 构建时同步的内置官方节点快照
├── assets/
├── examples/
├── _version.py               # 构建时注入的统一版本
└── _internal/                # Python、PySide6 和共享 DLL/模块
```

`Mozikit.spec` 对 GUI 和 CLI 分别执行 `Analysis`，使用 `MERGE` 共享依赖，再由同一个 `COLLECT` 输出上述目录。PyInstaller 官方的 multi-program spec 说明见 [MERGE/COLLECT 文档](https://pyinstaller.org/en/stable/spec-files.html)。`normalize_distribution_layout()` 将用户可见的 runtime、assets、examples 和 official nodes 从 PyInstaller 6 的 `_internal` 默认位置提升到发行版根目录。

## 3. GUI、CLI 和共享数据

`src/gui_launcher.py` 只调用 `src.gui_entry:run_gui`，`src/cli_launcher.py` 只调用 `src.cli:run_cli`。GUI 启动时不导入 CLI；CLI 启动时不初始化 Qt。

冻结版默认使用：

```text
%LOCALAPPDATA%\Mozikit\
├── config.json
├── workflows\
├── runtime\
├── user_data\                # 自定义/外部节点和用户官方节点版本
├── mcp\
├── logs\
└── execution history（由现有 ConfigManager 管理）
```

安装目录只读。`runtime_paths.py` 提供统一路径；旧版本曾将冻结 GUI 工作目录放在 `%APPDATA%\Mozikit` 时，启动器会增量复制缺失文件到 LocalAppData，不覆盖新数据、不删除旧目录；进程本地的 `runtime`/`logs` 不迁移，以免恢复过期 PID 或连接状态。`MOZIKIT_APP_DATA_DIR` 和 `MOZIKIT_WORKSPACE` 仍可用于测试、企业部署和高级用户覆盖。

## 4. Bundled UV

版本和下载元数据位于 `tools/bundled_uv.json`，当前固定为 Windows x64 UV `0.12.17`，同时记录 `os`、`architecture` 和 Rust target platform。`scripts/download_uv.ps1` 从固定 release URL 下载 zip，校验 SHA256 后只将 `uv.exe` 放入 `build/bundled_uv/uv.exe`；二进制不提交到 Git。当前固定归档的官方 checksum 为 `a252121d5b59398fcb137c6ea448176459a44010f33f67e0072305a637119ca7`，来源为 [uv release archive](https://github.com/astral-sh/uv/releases/download/0.12.17/uv-x86_64-pc-windows-msvc.zip)。

`UVManager.get_bundled_uv_path()` 集中处理源码、frozen、`sys._MEIPASS` 和测试覆盖路径；`get_preferred_uv_path()` 的优先级是：

1. 调用者显式传入的路径（例如设置页当前选择）；
2. 配置中的 `custom_uv_path`；
3. Mozikit bundled UV；
4. 当前进程 PATH 中的 UV；
5. Windows 常见安装位置。

冻结版执行 `mozikit env install-uv` 时只确认内置 UV 并返回 JSON，不调用 `sys.executable -m pip`。源码/Python package 环境仍可通过当前 Python 的 pip 兼容安装路径。

## 5. MSI、PATH 和安装范围

当前保留 MSI 的 `perMachine`、既有 `UpgradeCode` 和现有 WiX/WinGet 自动化，理由是改变 Scope 会影响已发布产品的升级路径、机器级安装位置和 WinGet manifest。WiX 产品显示为 `Mozikit`，开始菜单快捷方式也显示 `Mozikit`，目标是 `MozikitDesktop.exe`。

MSI 通过 WiX `Environment` 表把安装目录加入机器 PATH：

```text
安装新终端 -> where mozikit -> ...\Mozikit\mozikit.exe
```

该条目由 MSI 在卸载时移除，PATH 中其他目录不重写；升级沿用同一条目，不重复追加。`src/core/cli_registration.py` 同时提供 `status/install/uninstall` 能力，使用当前用户 PATH，供 Portable ZIP 和未来安装方式复用。状态 JSON 会报告 `source`：`installer` 表示 machine PATH 由 MSI 管理，`user` 表示当前用户 PATH，`installer+user` 表示两者同时存在。Portable 的 `cli install` 不会在 MSI 已注册时重复写入 user PATH；`cli uninstall` 只移除自身的 user PATH，不会拆除 MSI 的 machine PATH。

## 6. Portable ZIP

`Mozikit-Windows-x64.zip` 与安装目录保持同一目录结构，包含 GUI、CLI、bundled UV、共享 `_internal` 和 official nodes。解压不会默认写 PATH、开始菜单或卸载注册；用户可直接运行：

```powershell
.\Mozikit\MozikitDesktop.exe
.\Mozikit\mozikit.exe --help
```

如需当前用户 PATH，可显式运行 `.\Mozikit\mozikit.exe cli install`；`cli status --json` 返回 `registered`、`not registered` 或 `broken`。

## 7. 版本、Release、WinGet 和签名

构建版本来源按以下顺序统一：`MOZIKIT_VERSION`、精确的 `vX.Y.Z` Git tag、构建生成的 `_version.py`、`pyproject.toml`。Release CI 从 tag 解析版本并注入 `MOZIKIT_VERSION`，因此 PyInstaller、CLI `--version`、MSI ProductVersion 和发布资产使用同一版本。

当前保留已有 MSI 资产命名 `mozikit-vX.Y.Z-x64.msi`，避免破坏现有 WinGet URL；Portable 资产为 `Mozikit-Windows-x64.zip`，并发布 `SHA256SUMS`。WinGet manifest 继续使用 `Mozikit.Mozikit`、machine scope 和同一 MSI SHA256；用户数据在 LocalAppData，升级不覆盖 config、workflows、credentials、MCP registry 或执行历史。

`scripts/sign_windows.ps1` 是可选 Authenticode 阶段：配置 `MOZIKIT_SIGNING_CERTIFICATE_BASE64` 和密码时依次签名/验证 GUI、CLI、bundled UV 和 MSI；未配置时构建明确输出 unsigned warning 并继续，不把证书或私钥提交到仓库。

## 8. CI 顺序

`.github/workflows/build_windows.yml` 的 Windows job 顺序为：

```text
checkout tag
-> 安装构建依赖
-> pytest
-> 解析版本
-> 下载固定 UV + SHA256
-> 同步 official nodes
-> PyInstaller MERGE/COLLECT
-> frozen CLI/UV/layout smoke
-> 可选 EXE 签名
-> WiX MSI
-> 可选 MSI 签名
-> Portable ZIP + SHA256SUMS
-> artifact
-> GitHub Release
-> WinGet manifest/submit
```

CLI smoke 失败会使 Windows build job 失败，因而不会进入发布 job。

## 9. 自动化覆盖和人工验收边界

`test/unit/test_desktop_distribution.py` 覆盖：launcher 委托、frozen bundled UV 查找、custom/bundled/PATH/common/no-UV 优先级、frozen `install-uv` 不运行 pip、PATH 注册纯函数、CLI `workflow list/status/run --json` 和 spec 结构。`build.py verify_build()` 另外运行冻结版 `--version`、`--help` 和 `runtime/uv.exe --version`，并验证双 EXE、官方节点和共享 `_internal`。

仍需在真实 Windows 机器/CI 上人工确认：UAC/管理员权限、安装/卸载后新终端的 PATH 广播、WinGet upgrade 后用户数据、开始菜单快捷方式、GUI 首次启动、代码签名证书链以及外部节点/凭据提供者行为。单元测试和结构检查不能替代这些验收。

## 10. 兼容风险

* 旧脚本直接启动 `Mozikit.exe` 的用户需要改用 `MozikitDesktop.exe`（GUI）或 `mozikit.exe`（CLI）；运行时对子旧 frozen GUI 命令保留了过渡回退。
* `mozikit-cli`、`mozikit-gui` Python entry point 暂不删除，避免破坏已有源码用户；正式文档只推荐 `mozikit` 和开始菜单 Mozikit。
* MSI 仍是 perMachine，因此首次安装可能需要管理员权限；Portable ZIP 可用于无管理员权限场景。
* signing secrets、WinGet token、GitHub release 权限和官方节点仓库访问仍需由发布环境配置；仓库不会内置这些凭据。
