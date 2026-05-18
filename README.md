# LocalFlow

[![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://www.python.org/)
[![PySide6](https://img.shields.io/badge/PySide6-UI%20Framework-green.svg)](https://www.qt.io/qt-for-python)
[![CLI](https://img.shields.io/badge/CLI-Typer%2BRich-orange.svg)](https://typer.tiangolo.com/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)

一个现代化的基于 Python 的可视化工作流管理工具，采用 PySide6 构建，提供直观的拖拽式节点编辑体验、智能的 UV 虚拟环境管理、灵活的多标签页工作流支持、AI 辅助功能、定时任务调度、以及强大的节点扩展能力。

## ✨ 核心特性

### 🎨 可视化节点编辑器
- 直观的拖拽式界面，支持节点连接和参数配置
- 丰富的内置节点类型（变量赋值、变量计算、SQLite、SQL 语句、Playwright 脚本、表格读写、文本模板渲染、剪贴板操作、IM 控制等）
- 自定义节点支持，可通过 AI 或手动编写 Python 代码创建
- 节点源代码在线编辑和调试
- 代码安全审查机制

### 🔄 多标签页工作流管理
- 同时编辑和管理多个工作流，提升工作效率
- 标签页拖拽排序和批量关闭
- 修改状态自动保存和恢复
- 工作流导入导出功能

### 🤖 AI 辅助功能
- **AI 智能聊天** - 内置 AI 对话界面，支持自然语言交互
- **AI 工具调用** - 通过对话直接操作工作流（创建节点、删除节点、连接节点、自动布局等）
- **AI 节点生成** - 自然语言描述自动生成自定义节点代码
- 支持 OpenAI 兼容接口的多种 AI 服务
- 对话历史保存和导出

### ⏰ 定时任务调度
- Cron 表达式支持，灵活定义执行周期
- 预设时间间隔（每分钟、每小时、每天、每周、每月）
- 可视化任务管理器，查看执行历史和状态
- 任务启用/禁用控制

### 🐍 智能 UV 虚拟环境
- 自动化的 Python 环境管理，支持共享缓存
- 自动检测或手动指定 UV 路径
- 自定义 PyPI 镜像源（清华、阿里云等）
- 每个工作流独立虚拟环境隔离

### 📦 节点仓库管理
- **本地自定义节点** - 创建、导入、导出自定义节点
- **GitHub 节点仓库** - 从 GitHub 导入社区节点（支持 OAuth 认证）
- **节点搜索和分类浏览** - 快速查找所需节点
- **节点分享功能** - 打包节点为 zip 格式分享

### 🌙 主题系统
- 明暗主题切换
- 现代化 UI 设计，支持圆角、阴影、动画效果
- 自定义主题颜色配置
- Toast 气泡提示替代阻塞弹窗

### 💾 数据持久化
- 自动保存工作流和界面状态
- 执行结果历史记录和详情查看
- 配置数据本地存储
- 工作流版本管理

### 🔧 系统托盘
- 最小化到系统托盘运行
- 托盘快捷菜单控制
- 后台定时任务持续运行
- 强制退出保护机制

## 📋 目录

- [快速开始](#快速开始)
- [环境要求](#环境要求)
- [安装指南](#安装指南)
- [使用说明](#使用说明)
- [核心功能详解](#核心功能详解)
- [项目结构](#项目结构)
- [开发指南](#开发指南)
- [测试](#测试)
- [配置](#配置)
- [贡献](#贡献)
- [许可证](#许可证)
- [问题反馈](#问题反馈)

## 🚀 快速开始

### 方式一：直接运行源代码

```bash
# 克隆项目仓库
git clone <repository-url>
cd localflow

# 安装依赖（推荐使用 UV）
uv venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
uv pip install -r requirements.txt

# 启动应用
python main.py
```

### 方式二：使用可执行文件

#### 生成可执行文件

```bash
# 使用 Python 构建脚本
python build.py

# 或使用批处理脚本 (Windows)
build.bat

# 或使用 Shell 脚本 (Linux/Mac)
./build.sh
```

构建完成后，可执行文件位于 `dist/LocalFlow/` 目录。

#### 运行应用
- **目录版本**（推荐，符合 PySide6 LGPL 要求）：
  ```bash
  cd dist/LocalFlow
  ./LocalFlow  # Linux/Mac
  LocalFlow.exe  # Windows
  ```

- **便携版本**：
  ```bash
  cd dist/LocalFlow_Portable
  ./Start_LocalFlow.bat  # Windows
  ./start_localflow.sh   # Linux/Mac
  ```

## 🖥️ 环境要求

- **Python**: 3.8 或更高版本
- **依赖库**: 
  - PySide6 (Qt for Python)
  - Pillow (图像处理)
  - UV (现代 Python 包管理器)
- **操作系统**: Windows 10/11, macOS 10.15+, Linux (Ubuntu 18.04+)
- **内存**: 最低 4GB RAM，推荐 8GB+

## 📦 安装指南

### 使用 pip (传统方式)

```bash
# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt
```

### 使用 UV (推荐)

```bash
# 创建并激活虚拟环境
uv venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 安装依赖（UV 提供更快的安装速度）
uv pip install -r requirements.txt
```

### 验证安装

```bash
# 检查 PySide6 安装
python -c "import PySide6; print(f'PySide6 {PySide6.__version__} installed successfully')"

# 检查 UV 安装
uv --version
```

### 安装和运行

1. **克隆项目**
```bash
git clone <repository-url>
cd localflow
```

2. **安装依赖**
```bash
# 使用 pip
pip install -r requirements.txt

# 或使用 uv (推荐)
uv venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
uv pip install -r requirements.txt
```

3. **运行应用**
```bash
python main.py              # 启动 GUI
python main.py --help       # 查看 CLI 帮助
python main.py run <file>   # 命令行执行工作流
```

## 💻 CLI 命令行接口

LocalFlow 提供完整的命令行接口（CLI），无需启动 GUI 即可完成工作流执行、定时调度、节点管理、环境配置等所有操作。基于 [Typer](https://typer.tiangolo.com/) + [Rich](https://rich.readthedocs.io/) 构建，支持彩色输出、进度条、表格展示。

### 用法

```bash
# 方式一：通过 pip 安装后直接使用
localflow [命令] [选项]

# 方式二：从源码运行
python -m src.cli [命令] [选项]
# 或通过入口模块
python main.py [命令] [选项]
```

无参数时自动启动 GUI 模式（`python main.py`），或显示 CLI 帮助（`localflow` / `localflow --help`）。

### 命令树（39 条）

```
localflow
├── run <workflow.json> [选项]      执行工作流
├── schedule                        定时任务管理
│   ├── list                        列出所有定时任务
│   ├── add <path> [选项]           添加定时任务
│   ├── remove <id>                 删除定时任务
│   ├── update <id> [选项]          更新定时任务（name/cron/enabled）
│   ├── run <id>                    立即执行指定任务
│   ├── status                      查看调度器状态
│   └── daemon [选项]               启动调度器守护进程（带实时回调通知）
├── env                             虚拟环境管理
│   ├── list                        列出所有虚拟环境
│   ├── create <name> [选项]        创建虚拟环境
│   ├── remove <name>               删除虚拟环境
│   ├── status                      显示 UV 安装状态/路径/镜像/环境列表
│   └── set-mirror <url>            设置 UV 包镜像地址
├── node                            节点管理
│   ├── list                        列出所有可用节点（含彩色来源标签）
│   ├── info <name>                 查看节点详细信息
│   ├── create <name> [选项]        创建自定义节点
│   ├── delete <type>               删除自定义节点
│   ├── export <type> <path> [选项] 导出节点为 ZIP 包
│   ├── import <path>               从 ZIP 包导入节点
│   ├── generate <name> [选项]      AI 生成自定义节点
│   ├── check-safety <path>         检查 Python 代码安全性
│   └── repo                        远程节点仓库管理
│       ├── list                    列出远程仓库可用节点
│       ├── check-updates           检查官方节点更新
│       └── install <type> [选项]   从远程仓库安装/更新节点
├── config                          配置管理
│   ├── show                        显示配置（敏感字段自动解密脱敏）
│   ├── set <key> <value>           设置配置项（敏感字段加密存储）
│   ├── github-login [选项]         GitHub Device Flow 登录
│   └── github-logout               清除 GitHub 登录凭证
├── workflow                        工作流管理
│   ├── list                        列出已保存的工作流
│   ├── validate <file>             验证工作流格式
│   └── describe <file>             显示工作流详情
└── serve [选项]                    启动 FastAPI REST API 服务
```

### 常用示例

**执行工作流：**
```bash
# 基本执行
localflow run workflows/my_workflow/workflow.json

# 带输入数据
localflow run workflow.json --input '{"key": "value"}' --verbose

# 命令行参数输入
localflow run workflow.json --args name=alice count=42

# 保存结果到文件
localflow run workflow.json --output result.json

# JSON 管道模式（适合 CI/脚本集成）
localflow run workflow.json --json | jq '.duration_ms'
```

**管理定时任务：**
```bash
# 添加定时任务
localflow schedule add workflow.json --cron "0 9 * * 1-5" --name "工作日执行"

# 列出所有任务
localflow schedule list

# 更新任务
localflow schedule update abc12345 --cron "*/30 * * * *" --name "每半小时"

# 启用/禁用
localflow schedule update abc12345 --enabled
localflow schedule update abc12345 --disabled

# 删除任务
localflow schedule remove abc12345

# 启动守护进程（终端实时显示执行状态）
localflow schedule daemon --tick 5 --logfile scheduler.log
```

**节点管理：**
```bash
# 列出所有节点
localflow node list

# 查看节点详情
localflow node info sqlite_connect

# 创建自定义节点
localflow node create "数据处理" --desc "清洗CSV数据"

# AI 生成节点（需配置 AI 接口）
localflow node generate "网页抓取" --desc "抓取新闻标题" --output "标题列表"

# 代码安全检查
localflow node check-safety my_node.py

# 导出/导入节点
localflow node export custom_mynode_123456 ./my_node.zip
localflow node import ./my_node.zip

# 远程仓库操作
localflow node repo list
localflow node repo check-updates
localflow node repo install http_request --version 2.0.0
```

**虚拟环境管理：**
```bash
# 列出所有环境
localflow env list

# 创建/删除环境
localflow env create my_project --python 3.12
localflow env remove my_project

# 查看 UV 状态
localflow env status

# 设置镜像
localflow env set-mirror https://pypi.tuna.tsinghua.edu.cn/simple
```

**配置管理：**
```bash
# 显示配置（API key 等明文自动脱敏）
localflow config show

# 设置普通配置
localflow config set node_timeout_seconds 300

# 设置 AI 配置（api_key 自动加密存储）
localflow config set ai_settings '{"api_key":"sk-xxx","model":"gpt-4","base_url":"https://api.openai.com/v1"}'

# 点路径写法
localflow config set ai_settings.api_key sk-xxx

# GitHub OAuth 登录（Device Flow）
localflow config github-login --timeout 600

# 断开 GitHub
localflow config github-logout
```

**工作流管理：**
```bash
# 列出已保存的工作流
localflow workflow list

# 验证工作流格式
localflow workflow validate workflows/my_wf/workflow.json

# 查看工作流详情
localflow workflow describe workflows/my_wf/workflow.json
```

**启动 API 服务：**
```bash
# 启动 REST API（提供工作流执行和定时任务管理的 HTTP 接口）
localflow serve --port 8080 --host 0.0.0.0

# 接口文档：http://localhost:8080/docs
# 健康检查：http://localhost:8080/health

# 使用 API 执行工作流：
# curl -X POST http://localhost:8080/workflows/run \
#   -H "Content-Type: application/json" \
#   -d '{"path": "workflows/my_wf/workflow.json", "input_data": "{\"key\": \"value\"}"}'
```

### 特性

| 特性 | 说明 |
|---|---|
| **敏感字段加密** | `config set` 自动识别 api_key/token 等字段，通过操作系统密钥链或本地 PBKDF2 加密存储 |
| **JSON 管道模式** | `run --json` 输出结构化 JSON，便于 `jq` 等工具链处理 |
| **实时日志** | `run --verbose` 流式显示节点执行日志 |
| **彩色输出** | Rich 表格、进度条、彩色标签（节点来源颜色区分） |
| **守护进程** | `schedule daemon` 带实时任务回调通知，支持 PID 文件防重复启动 |
| **--version** | 显示版本号 |

### 自动模式选择

- **无参数** → 启动 GUI 模式（PySide6 桌面应用）
- **含子命令** → 启动 CLI 模式
- 通过 `localflow` 或 `localflow-cli` 入口始终启动 CLI 模式

### 环境变量

| 变量 | 说明 |
|---|---|
| `LOCALFLOW_WORKSPACE` | 工作空间根目录（默认 `./workflows`），所有命令可用 `--workspace` / `-w` 覆盖 |

## 📚 详细文档

本项目提供完整的文档体系：

### 用户文档
- **[用户指南](docs/user-guide/)** - 详细使用说明和教程
  - [快速开始](docs/user-guide/QUICK_START.md) - 5分钟快速上手
  - [UI 使用指南](docs/user-guide/UI_GUIDE.md) - 界面操作详解
  - [工作流执行](docs/user-guide/WORKFLOW_EXECUTION.md) - 工作流运行与管理
  - [标签页管理](docs/user-guide/TAB_MANAGEMENT_GUIDE.md) - 多标签页操作指南
  - [主题支持](docs/user-guide/THEME_SUPPORT.md) - 主题配置与使用
  - [主题速查](docs/user-guide/THEME_QUICK_REFERENCE.md) - 主题配置速查表

### 开发文档
- **[开发文档](docs/development/)** - 开发和构建指南
  - [构建指南](docs/development/BUILD_GUIDE.md) - 项目构建和打包详解
  - [构建参考](docs/development/BUILD_REFERENCE.md) - 构建配置参考
  - [新功能开发指南](docs/development/NEW_FEATURES_GUIDE.md) - 功能开发流程
  - [实现总结](docs/development/IMPLEMENTATION_SUMMARY.md) - 技术实现总结
  - [改进说明](docs/development/IMPROVEMENTS.md) - 系统改进记录
  - [设置功能](docs/development/SETTINGS_FEATURE.md) - 设置功能实现
  - [Bug 修复汇总](docs/development/BUG_FIXES_SUMMARY.md) - 已知问题修复记录

### 架构文档
- **[架构文档](docs/architecture/)** - 系统架构和设计
  - [UV 检测改进](docs/architecture/UV_DETECTION_IMPROVEMENT.md) - UV 检测算法
  - [自定义 UV 设置](docs/architecture/CUSTOM_UV_SETTINGS.md) - 自定义功能实现

### 测试文档
- **[测试文档](test/README.md)** - 测试说明和运行指南

## 🎯 核心功能详解

### AI 智能聊天

LocalFlow 内置 AI 聊天功能，支持自然语言与工作流交互：

1. **智能对话** - 在 AI 面板与 AI 助手对话
2. **工具调用** - AI 可直接操作工作流：
   - 创建节点、删除节点
   - 连接节点端口
   - 自动布局节点
   - 查询节点信息
3. **节点生成** - 描述需求即可自动生成自定义节点代码
4. **多服务支持** - 兼容 OpenAI、Azure、Claude 等多种 AI 服务

配置方法：设置 → AI 配置 → 填写 API 地址、密钥和模型名称

### 定时任务调度

设置工作流自动执行：

1. **打开总览面板** - 查看所有工作流和定时任务
2. **添加定时任务** - 选择工作流和执行周期
3. **Cron 表达式** - 支持标准 Cron 语法（如 `0 9 * * 1-5` 工作日9点执行）
4. **预设间隔** - 快速选择每分钟/小时/天/周/月
5. **任务管理** - 启用/禁用任务、立即执行、查看历史

### 自定义节点开发

创建专属节点：

1. **AI 生成** - 自然语言描述需求，AI 自动生成节点代码
2. **代码编辑** - 内置代码编辑器支持语法高亮
3. **安全审查** - 自动检测代码安全风险
4. **依赖管理** - 自动安装节点所需 Python 包
5. **节点分享** - 导出为 zip 文件与他人分享

### 主题与个性化

自定义界面外观：

1. **明暗切换** - 一键切换亮色/暗色主题
2. **UI 优化** - 现代化设计，支持圆角、阴影、平滑动画
3. **Toast 提示** - 非阻塞式气泡提示，操作更流畅
4. **面板布局** - 可拖拽调整面板宽度，支持收起/展开

### 节点仓库

扩展节点库：

1. **本地节点** - 管理用户自定义节点
2. **GitHub 节点** - 从 GitHub 仓库导入社区节点
3. **OAuth 认证** - 安全连接 GitHub 账号
4. **节点搜索** - 快速查找所需节点
5. **分类浏览** - 按类别查看节点

## 🏗️ 项目结构

```
LocalFlow/
├── src/                           # 源代码
│   ├── core/                     # 核心逻辑层（CLI 和 GUI 共享）
│   │   ├── node_base.py         # 节点基类定义
│   │   ├── node_registry.py     # 节点注册表
│   │   ├── uv_manager.py        # UV 虚拟环境管理
│   │   ├── workflow_executor.py # 工作流执行引擎
│   │   ├── workflow_scanner.py  # 工作流扫描器
│   │   ├── workflow_runner.py   # 工作流运行器
│   │   ├── config_manager.py    # 配置管理器
│   │   ├── cron_utils.py        # Cron 表达式工具（无 PySide6 依赖）
│   │   ├── headless_scheduler.py# 无头调度器（CLI 用）
│   │   ├── scheduler_manager.py # 定时任务管理器（GUI 用）
│   │   ├── theme_manager.py     # 主题管理器
│   │   ├── ai_chat_service.py   # AI 聊天服务
│   │   ├── ai_node_generator.py # AI 节点生成服务
│   │   ├── ai_chat_context.py   # AI 对话上下文构建
│   │   ├── custom_node_manager.py # 自定义节点管理器
│   │   ├── node_repo_manager.py # 节点仓库管理器
│   │   ├── credential_store.py  # 凭据存储（GitHub OAuth等）
│   │   ├── code_safety.py       # 代码安全审查
│   │   ├── playwright_node_utils.py # Playwright 节点工具
│   │   └── providers/           # 外部节点提供者
│   │       └── github_provider.py # GitHub 节点提供者
│   ├── cli.py                   # CLI 入口（Typer 命令树）
│   ├── dialogs/                  # 对话框组件
│   │   ├── settings_dialog.py   # 设置对话框
│   │   ├── add_node_dialog.py   # 添加节点对话框
│   │   ├── source_code_dialog.py # 源代码编辑对话框
│   │   └── playwright_script_dialog.py # Playwright 脚本对话框
│   ├── views/                    # 视图组件
│   │   ├── main_window.py       # 主窗口（已迁移到 src/main_window.py）
│   │   ├── workflow_canvas.py   # 工作流画布
│   │   ├── workflow_tab_widget.py # 标签页组件
│   │   ├── node_graphics.py     # 节点图形
│   │   ├── node_browser.py      # 节点浏览器
│   │   ├── node_properties.py   # 节点属性面板
│   │   ├── execution_results_widget.py # 执行结果面板
│   │   ├── ai_chat_widget.py    # AI 聊天面板
│   │   ├── overview_widget.py   # 总览面板（含定时任务管理）
│   │   └── toast_widget.py      # Toast 气泡提示
│   └── main_window.py           # 主窗口
├── test/                         # 测试套件
│   ├── unit/                    # 单元测试
│   ├── integration/             # 集成测试
│   ├── ui/                      # UI 测试
│   └── run_tests.py            # 测试运行器
├── docs/                         # 文档
│   ├── user-guide/              # 用户指南
│   ├── development/             # 开发文档
│   └── architecture/            # 架构文档
├── assets/                       # 资源文件
│   ├── icons/                   # 图标资源
│   └── localflow.ico           # 应用图标
├── workflows/                    # 工作流数据存储
│   ├── example_basic_calc/      # 示例：基础计算
│   ├── IntegrationFlow/         # 示例：集成工作流
│   └── test_opt_workflow/       # 测试工作流
├── examples/                     # 示例代码
├── user_data/                    # 用户数据（配置、节点、历史等）
├── config.json                  # 应用配置文件
├── requirements.txt             # Python 依赖
├── build.py                     # 构建脚本
├── auto_build.py               # 自动构建脚本
├── LocalFlow.spec               # PyInstaller 配置
├── main.py                      # 应用入口
├── LICENSE                      # Apache 2.0 许可证
└── README.md                    # 本文档
```

## 🧪 测试

### 运行测试

```bash
# 运行所有测试
python test/run_tests.py

# 运行特定类型测试
python test/run_tests.py unit         # 单元测试
python test/run_tests.py integration  # 集成测试
python test/run_tests.py ui           # UI 测试

# 使用测试运行脚本 (Windows)
run_tests.bat
```

### 测试覆盖

- **UV 功能测试** - UV 检测、路径管理、镜像配置
- **工作流测试** - 工作流执行、节点管理、标签页功能
- **用户界面测试** - 设置对话框、主题切换、用户交互
- **系统集成测试** - 组件间交互、配置管理、错误处理

详细测试说明请查看 [测试文档](test/README.md)。

## ⚙️ 配置

### UV 配置

LocalFlow 提供灵活的 UV 配置选项：

1. **自动检测**：自动发现系统中安装的 UV
2. **自定义路径**：手动指定 UV 可执行文件路径
3. **镜像配置**：支持自定义 PyPI 镜像源（如清华源、阿里云等）

#### 配置方法

**图形界面方式**：
1. 打开 `设置` 对话框（菜单：工具 → 设置）
2. 选择 `UV 包管理工具` 选项卡
3. 配置 UV 路径和镜像源
4. 配置自动保存到 `~/.uv/uv.toml`

**配置文件方式**：
```toml
# ~/.uv/uv.toml
index-url = "https://pypi.tuna.tsinghua.edu.cn/simple"
```

### 应用配置

应用配置文件 `config.json` 存储：
- 窗口几何信息（位置、大小）
- Dock 面板状态（可见性、宽度）
- 用户偏好设置

示例配置：
```json
{
  "dock_states": {
    "node_browser": {
      "visible": true,
      "width": 300
    },
    "node_properties": {
      "visible": true,
      "width": 300
    }
  },
  "window_geometry": {
    "x": 0,
    "y": 23,
    "width": 1707,
    "height": 889
  }
}
```

### 工作流配置

工作流数据存储在 `workflows/` 目录下：
- 每个工作流有独立的子目录
- 包含工作流定义文件（JSON）
- 拥有独立的 `.venv` 虚拟环境
- 支持导入导出和版本控制

## 💻 开发指南

### 开发环境搭建

```bash
# 克隆仓库
git clone <repository-url>
cd localflow

# 创建开发环境
uv venv --python 3.11
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 安装开发依赖
uv pip install -r requirements.txt
uv pip install pytest pytest-qt  # 测试依赖

# 安装 pre-commit 钩子（如果有）
pre-commit install
```

### 代码结构

- **MVC 架构**：模型（Model）-视图（View）-控制器（Controller）分离
- **模块化设计**：核心功能按模块组织，便于维护和扩展
- **事件驱动**：基于 PySide6 信号槽机制的事件处理
- **插件系统**：支持外部节点提供者（如 GitHubProvider）

### 添加新节点

1. 继承 `NodeBase` 类实现节点逻辑
2. 在 `node_registry.py` 中注册节点
3. 添加节点图标到 `assets/icons/`
4. 编写单元测试

示例：
```python
from src.core.node_base import NodeBase, NodeType

class MyCustomNode(NodeBase):
    def __init__(self, node_id):
        super().__init__(node_id, "My Custom Node", NodeType.PROCESSOR)
        self.add_input_port("input_data")
        self.add_output_port("output_data")
    
    def execute(self):
        # 节点执行逻辑
        input_data = self.get_input("input_data")
        output_data = self.process(input_data)
        self.set_output("output_data", output_data)
```

详细开发指南请查看 [开发文档](docs/development/)。

## 🤝 贡献

我们欢迎所有形式的贡献！

### 贡献方式
- 🐛 **报告 Bug** - 提交 Issue 并描述问题
- 💡 **建议功能** - 提出新功能想法
- 📝 **改进文档** - 完善文档和示例
- 🔧 **代码贡献** - 修复 Bug 或实现新功能
- 🌍 **翻译** - 帮助项目国际化

### 贡献流程
1. Fork 项目仓库
2. 创建特性分支 (`git checkout -b feature/amazing-feature`)
3. 提交更改 (`git commit -m 'Add amazing feature'`)
4. 推送到分支 (`git push origin feature/amazing-feature`)
5. 创建 Pull Request

详细贡献指南请查看 [开发文档](docs/development/NEW_FEATURES_GUIDE.md)。

## 📄 许可证

本项目采用 [Apache License 2.0](LICENSE) 开源许可证。

```
Copyright [yyyy] [name of copyright owner]

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

## 🐛 问题反馈

如遇到问题，请通过以下方式反馈：

- 📧 **提交 Issue** - [GitHub Issues](https://github.com/username/repo/issues)
- 📖 **查看文档** - [故障排除指南](docs/user-guide/)
- 💬 **社区讨论** - [Discussions](https://github.com/username/repo/discussions)

提交 Issue 时，请包含：
- 问题描述和重现步骤
- 错误日志和截图
- 环境信息（OS、Python 版本等）
- 配置文件（脱敏后）

## 🙏 致谢

- [PySide6](https://www.qt.io/qt-for-python) - 强大的 Python UI 框架
- [UV](https://github.com/astral-sh/uv) - 现代化的 Python 包管理器
- [PyInstaller](https://www.pyinstaller.org/) - Python 打包工具
- [Apache 2.0](https://www.apache.org/licenses/LICENSE-2.0) - 开源许可证

---

<div align="center">

**⭐ 如果这个项目对你有帮助，请给我们一个 Star！** 

Made with ❤️ by LocalFlow Contributors

</div>