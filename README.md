<div align="center">
  <img src="assets/mozikit_512.png" alt="Mozikit" width="120" />
  <h1>Mozikit</h1>
  <p><strong>Python 可视化工作流自动化工具</strong></p>
</div>

<p align="center">
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-3.8+-blue?logo=python&logoColor=white" alt="Python 3.8+" /></a>
  <a href="https://www.qt.io/qt-for-python"><img src="https://img.shields.io/badge/PySide6-Desktop%20UI-41CD52?logo=qt&logoColor=white" alt="PySide6" /></a>
  <a href="https://typer.tiangolo.com/"><img src="https://img.shields.io/badge/CLI-Typer%20%2B%20Rich-FF6F00" alt="CLI" /></a>
  <a href="https://fastapi.tiangolo.com/"><img src="https://img.shields.io/badge/API-FastAPI-009688?logo=fastapi&logoColor=white" alt="FastAPI" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-blue.svg" alt="License" /></a>
  <br/>
  <a href="#"><img src="https://img.shields.io/badge/version-0.2.5-8A2BE2" alt="Version" /></a>
  <a href="#"><img src="https://img.shields.io/badge/platform-Windows%20|%20macOS%20|%20Linux-lightgrey" alt="Platform" /></a>
</p>

---

Mozikit 是一个**现代化的 Python 可视化工作流自动化工具**。它提供直观的拖拽式节点画布，让您像搭积木一样构建自动化流程——不需要写大量胶水代码。无论您是开发者想快速原型化数据管道，还是自动化爱好者想编排日常任务，Mozikit 都能让您的工作流变得可视、可控、可复现。

> **设计哲学**：CLI 与 GUI 共享同一套核心引擎——您在画布上编排的工作流，同样可以在终端中通过一行命令执行，甚至通过 REST API 远程触发。

---

## ✨ 核心特性

### 🎨 可视化节点编辑器
- **拖拽式画布** — 直观的节点连线，支持参数配置与在线代码编辑
- **丰富的内置节点** — 变量赋值/计算、SQLite 操作、SQL 语句、Playwright 脚本、表格读写、文本模板 (Jinja2)、剪贴板、IM 通知等
- **自定义节点** — 通过 AI 或手动编写 Python 代码创建专属节点，支持代码安全审查
- **多标签页** — 同时编辑多个工作流，标签页拖拽排序，修改自动保存

### 🤖 AI 辅助
- **AI 智能聊天** — 内置对话面板，支持 OpenAI 兼容接口
- **AI 工具调用** — 通过对话直接操作画布：创建/删除/连接节点、自动布局
- **AI 节点生成** — 用自然语言描述需求，AI 自动生成节点代码

### ⏰ 定时调度
- 标准 Cron 表达式 + 预设间隔（每分钟 ~ 每月）
- 可视化任务管理：执行历史、启用/禁用、即时触发
- CLI 守护进程模式，支持后台持续运行

### 🐍 智能虚拟环境
- 每个工作流拥有独立的 **UV 虚拟环境**，共享缓存节省空间
- 自动检测 UV 路径，支持自定义 PyPI 镜像（清华、阿里云等）
- CLI 全生命周期管理：创建、删除、安装包、切换镜像

### 📦 节点生态
- **本地节点** — 创建、导入、导出，支持 ZIP 分享
- **GitHub 节点仓库** — 从社区拉取节点，支持 Device Flow OAuth 认证
- **版本管理** — 多版本共存、自动迁移、版本绑定
- **远程搜索** — 按类别浏览、关键词搜索

### 🌙 主题 & 体验
- 明暗主题一键切换，支持圆角、阴影、动画
- Toast 气泡提示替代阻塞弹窗，操作更流畅
- 系统托盘 — 最小化托盘后台运行，托盘快捷菜单

### 🌐 REST API
- 基于 FastAPI 的 HTTP 接口，提供工作流执行与定时任务管理
- 自动生成 OpenAPI 文档（`/docs`），健康检查端点（`/health`）

---

## 🏗️ 项目结构

```
Mozikit/
├── main.py                       # 应用入口（自动识别 CLI/GUI 模式）
├── pyproject.toml                # 项目元数据与构建配置
├── requirements.txt              # Python 依赖
├── LICENSE                       # Apache 2.0
├── build.py                      # PyInstaller 构建脚本
├── auto_build.py                 # 非交互式自动构建
│
├── src/                          # 源代码
│   ├── cli.py                    # CLI 入口（Typer 命令树，50+ 子命令）
│   ├── main_window.py            # PySide6 主窗口
│   │
│   ├── core/                     # ★ 核心逻辑层（CLI 与 GUI 共享）
│   │   ├── workflow_executor.py  #   工作流执行引擎（拓扑排序 + 节点执行）
│   │   ├── uv_manager.py         #   UV 虚拟环境管理
│   │   ├── node_base.py          #   节点基类
│   │   ├── node_registry.py      #   节点注册表
│   │   ├── config_manager.py     #   配置管理器
│   │   ├── credential_store.py   #   凭据加密存储
│   │   ├── ai_chat_service.py    #   AI 聊天服务
│   │   ├── ai_node_generator.py  #   AI 节点生成
│   │   ├── ai_tool_executor.py   #   AI 工具调用执行器
│   │   ├── code_safety.py        #   代码安全审查
│   │   ├── scheduler_manager.py  #   定时任务管理器
│   │   ├── headless_scheduler.py #   无头调度器（CLI）
│   │   ├── theme_manager.py      #   主题管理器
│   │   ├── node_repo_manager.py  #   节点仓库管理器
│   │   ├── node_version_manager.py # 节点版本管理
│   │   ├── custom_node_manager.py #  自定义节点管理
│   │   ├── github_oauth.py       #   GitHub Device Flow OAuth
│   │   ├── expression_engine.py  #   表达式引擎
│   │   ├── cron_utils.py         #   Cron 工具
│   │   ├── log_manager.py        #   日志初始化
│   │   ├── exceptions.py         #   统一错误码
│   │   ├── playwright_node_utils.py
│   │   ├── python_syntax_highlighter.py
│   │   ├── workflow_runner.py
│   │   ├── workflow_run_worker.py
│   │   ├── workflow_scanner.py
│   │   ├── workflow_sync.py
│   │   └── providers/
│   │       └── github_provider.py
│   │
│   ├── views/                    # GUI 视图组件
│   │   ├── workflow_canvas.py    #   工作流画布
│   │   ├── workflow_tab_widget.py#   多标签页
│   │   ├── node_graphics.py      #   节点图形
│   │   ├── node_properties.py    #   节点属性面板
│   │   ├── node_browser.py       #   节点浏览器
│   │   ├── ai_chat_widget.py     #   AI 聊天面板
│   │   ├── overview_widget.py    #   总览面板（含调度管理）
│   │   ├── execution_results_widget.py
│   │   ├── toast_widget.py       #   Toast 提示
│   │   └── _canvas_adapter.py    #   画布适配器（AI 桥接）
│   │
│   └── dialogs/                  # 对话框
│       ├── settings_dialog.py
│       ├── add_node_dialog.py
│       ├── source_code_dialog.py
│       └── playwright_script_dialog.py
│
├── test/                         # 测试
│   ├── unit/                     # 单元测试（20 文件）
│   ├── integration/              # 集成测试（10 文件）
│   ├── ui/                       # UI 测试（3 文件）
│   ├── conftest.py
│   └── run_tests.py
│
├── docs/                         # 文档
│   ├── user-guide/               # 用户指南
│   ├── development/              # 开发指南
│   ├── architecture/             # 架构文档
│   └── NODE_VERSION_SYSTEM.md
│
├── assets/                       # 资源
│   ├── icons/                    # SVG 图标集
│   ├── mozikit.ico               # Windows 应用图标
│   └── mozikit_512.png           # 高清图标
│
├── workflows/                    # 工作流数据存储
│   └── example_*/                #   示例工作流
│
├── examples/                     # 示例代码
│   └── simple_workflow_example.py
│
├── scripts/                      # 构建/部署脚本
│   ├── build_msi.ps1             #   MSI 安装包
│   └── generate_winget_manifest.ps1
│
└── wix/
    └── main.wxs                  # WiX 安装模板
```

---

## 🚀 快速开始

### 环境要求

| 项目 | 要求 |
|------|------|
| **Python** | ≥ 3.8 |
| **操作系统** | Windows 10/11, macOS 10.15+, Linux (Ubuntu 18.04+) |
| **内存** | 最低 4 GB，推荐 8 GB |
| **UV**（推荐） | 安装 [UV 包管理器](https://docs.astral.sh/uv/) `pip install uv` |

### 安装

```bash
# 1. 克隆仓库
git clone https://github.com/Mozikit-app/Mozikit.git
cd Mozikit

# 2. 创建虚拟环境并安装依赖（推荐使用 UV）
uv venv
source .venv/bin/activate        # Linux/macOS
# .venv\Scripts\activate         # Windows

uv pip install -r requirements.txt

# 如需 REST API 服务，额外安装
uv pip install fastapi uvicorn
```

### 运行

```bash
# ── GUI 模式（桌面应用）──
python main.py

# ── CLI 模式 ──
python main.py --help
python main.py run workflows/example_basic_calc/workflow.json
python main.py schedule list
python main.py serve --port 8080
```

### 打包为可执行文件

```bash
python build.py              # 交互式构建
python auto_build.py         # 非交互式自动构建
# 输出：dist/Mozikit/Mozikit.exe
```

---

## 💻 CLI 命令参考

Mozikit 提供完整的 CLI（基于 Typer + Rich），**无需启动 GUI** 即可完成所有操作。

```
Mozikit
├── run <path> | --name <name>     执行工作流
├── schedule                       定时任务管理
│   ├── list                       列出所有任务
│   ├── add <path>                 添加任务（--cron, --name）
│   ├── remove <id>                删除任务
│   ├── update <id>                更新任务
│   ├── run <id>                   立即执行
│   ├── pause/resume <id>          暂停/恢复
│   └── daemon                     启动调度守护进程
├── env                            虚拟环境管理
│   ├── list                       列出所有环境
│   ├── create <name>              创建环境（--python）
│   ├── remove <name>              删除环境
│   ├── install <name> <pkgs...>   安装包
│   ├── status                     查看 UV 状态
│   └── set-mirror <url>           设置镜像源
├── node                           节点管理
│   ├── list                       列出可用节点
│   ├── info <name>                查看详情
│   ├── create <name>              创建自定义节点
│   ├── delete <type>              删除节点
│   ├── export <type> <path>       导出为 ZIP
│   ├── import <path>              从 ZIP 导入
│   ├── generate <name>            AI 生成节点
│   ├── check-safety <path>        代码安全检查
│   └── repo                       远程仓库
│       ├── list                   列出远程节点
│       ├── check-updates          检查更新
│       └── install <type>         安装远程节点
├── config                         配置管理
│   ├── show                       显示所有配置（敏感字段脱敏）
│   ├── get <key>                  获取单条配置
│   ├── set <key> <value>          设置配置（敏感键自动加密）
│   ├── unset <key>                删除配置项
│   ├── github-login               GitHub OAuth 登录
│   └── github-logout              清除 GitHub 凭证
├── workflow                       工作流管理
│   ├── list                       列出工作流
│   ├── create <name>              创建空工作流
│   ├── copy/rename/delete         复制/重命名/删除
│   ├── validate <file>            验证格式
│   ├── describe <file>            查看详情
│   ├── stats                      执行统计
│   ├── add-node/remove-node       增删节点
│   ├── update-node <id> <kv...>   更新节点配置
│   └── connect/disconnect         连接/断开节点
└── serve                          启动 REST API 服务
```

### 常用示例

```bash
# 执行工作流并输出 JSON（适合 CI/脚本）
Mozikit run workflow.json --json | jq '.duration_ms'

# 按名称查找并执行
Mozikit run --name my_workflow

# 添加定时任务（工作日早 9 点执行）
Mozikit schedule add workflow.json --cron "0 9 * * 1-5" --name "每日报告"

# 守护进程模式运行调度器
Mozikit schedule daemon --tick 5 --logfile scheduler.log

# 通过 API 执行
curl -X POST http://localhost:8080/workflows/run \
  -H "Content-Type: application/json" \
  -d '{"path": "workflows/my_wf/workflow.json"}'
```

---

## 📝 使用示例

### 用 Python API 构建工作流

```python
from src.core.workflow_executor import WorkflowExecutor
from src.core.node_base import NodeBase
from src.core.uv_manager import UVManager

# 准备工作流执行器
uv_manager = UVManager()
executor = WorkflowExecutor("my_workflow", uv_manager)
executor.prepare_environment()

# 创建节点：x = 10
node1 = NodeBase.from_dict({
    "node_id": "input_x",
    "node_type": "variable_assign",
    "config": {"variable_name": "x", "value": "10", "value_type": "int"},
})
# 创建节点：y = 20
node2 = NodeBase.from_dict({
    "node_id": "input_y",
    "node_type": "variable_assign",
    "config": {"variable_name": "y", "value": "20", "value_type": "int"},
})
# 创建节点：result = x + y * 2
node3 = NodeBase.from_dict({
    "node_id": "calc",
    "node_type": "variable_calc",
    "config": {"expression": "x + y * 2", "output_var": "result"},
})

# 组装并执行
executor.add_node(node1)
executor.add_node(node2)
executor.add_node(node3)
executor.add_edge("input_x", "calc")
executor.add_edge("input_y", "calc")

result = executor.execute()
print(result)  # → {"x": 10, "y": 20, "result": 50}
```

### 工作流 JSON 格式

工作流以 JSON 文件定义，以下是一个基础计算工作流的示例：

```json
{
  "id": "example_basic_calc",
  "name": "基础计算",
  "nodes": [
    {
      "id": "n1",
      "type": "variable_assign",
      "config": { "variable_name": "x", "value": "10", "value_type": "int" },
      "position": { "x": 100, "y": 100 }
    },
    {
      "id": "n2",
      "type": "variable_assign",
      "config": { "variable_name": "y", "value": "20", "value_type": "int" },
      "position": { "x": 100, "y": 250 }
    },
    {
      "id": "n3",
      "type": "variable_calc",
      "config": { "expression": "x + y * 2", "output_var": "result" },
      "position": { "x": 400, "y": 175 }
    }
  ],
  "edges": [
    { "from": "n1", "to": "n3" },
    { "from": "n2", "to": "n3" }
  ]
}
```

---

## 🧪 测试

```bash
# 运行全部测试
python test/run_tests.py

# 按类别运行
python test/run_tests.py unit
python test/run_tests.py integration

# 或直接使用 pytest
pytest test/unit/ -v
```

测试覆盖：CLI 解析、UV 检测与镜像配置、工作流执行引擎、节点增删改查、AI 节点生成、GitHub OAuth、定时调度器、配置加密、UI 主题切换等。

---

## 🤝 参与贡献

我们欢迎所有类型的贡献！

1. **Fork** 本仓库
2. 创建特性分支：`git checkout -b feature/amazing-feature`
3. 提交更改：`git commit -m 'Add some feature'`
4. 推送到分支：`git push origin feature/amazing-feature`
5. 提交 **Pull Request**

详细开发指南请参阅 [docs/development/](docs/development/)。

---

## 📄 许可证

本项目采用 **Apache License 2.0** 开源许可证。详见 [LICENSE](LICENSE) 文件。

```
Copyright [2025] [lilinfangrelax]

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

   http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
```

---

## 🙏 致谢

- [PySide6](https://www.qt.io/qt-for-python) — 强大且成熟的 Qt for Python 绑定
- [UV](https://github.com/astral-sh/uv) — 闪电般快速的 Python 包管理器
- [Typer](https://typer.tiangolo.com/) — 优雅的 CLI 框架
- [Rich](https://rich.readthedocs.io/) — 终端富文本与精美表格
- [FastAPI](https://fastapi.tiangolo.com/) — 高性能 REST API 框架
- [PyInstaller](https://www.pyinstaller.org/) — Python 应用打包工具

---

<p align="center">
  <strong>⭐ 如果 Mozikit 对你有帮助，欢迎点个 Star！</strong><br/>
  有问题或建议？请提交 <a href="#">GitHub Issue</a>
</p>

