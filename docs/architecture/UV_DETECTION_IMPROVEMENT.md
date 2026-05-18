# UV 检测功能改进

## 问题描述

之前的 UV 检测逻辑存在问题：
1. 仅通过简单的 `uv --version` 命令检测，可能因 PATH 环境变量问题而检测失败
2. 无法检测多个 UV 安装
3. 用户无法选择使用哪个 UV 路径

## 解决方案

### 1. 改进的检测算法

新的 UV 检测功能采用多层检测策略：

#### 第一步：PATH 环境变量检测
- 使用 `where` (Windows) 或 `which` (Unix) 命令检测 PATH 中的 uv
- 支持检测多个 PATH 中的 uv 路径

#### 第二步：常见安装路径搜索
- **Windows**:
  - 用户级别：`%LOCALAPPDATA%\uv\uv.exe`
  - 系统级别：`%ProgramFiles%\uv\uv.exe`
  - Python Scripts 目录：`Python\Scripts\uv.exe`
- **Unix/Linux**:
  - 用户级别：`~/.local/bin/uv`, `~/.cargo/bin/uv`
  - 系统级别：`/usr/local/bin/uv`, `/usr/bin/uv`

#### 第三步：验证可执行性
- 对每个找到的路径执行 `uv --version` 验证
- 确保文件存在且可执行

### 2. 多路径支持

新的设置界面提供：
- **下拉选择框**：显示所有检测到的 UV 安装
- **详细信息显示**：显示选中路径的完整路径和版本信息
- **实时切换**：用户可以即时切换不同的 UV 安装

### 3. 核心类更新

#### UVManager 类新增方法

```python
def find_uv_installations(self) -> List[str]
    """查找系统中所有可用的uv安装路径"""

def get_preferred_uv_path(self, selected_path: str = None) -> Optional[str]
    """获取首选的uv路径，支持用户指定路径"""

def set_custom_uv_path(self, uv_path: str) -> bool
    """设置自定义的uv路径"""

def _get_common_uv_paths(self) -> List[str]
    """获取常见的uv安装路径"""

def _verify_uv_executable(self, uv_path: str) -> bool
    """验证uv可执行文件是否可用"""
```

### 4. 设置界面改进

#### 新增组件
- `QComboBox`：用于选择 UV 路径
- `QLineEdit`：显示选中路径的详细信息
- 状态显示：显示找到的 UV 数量和状态

#### 交互流程
1. 启动时自动检测所有 UV 安装
2. 在下拉框中显示所有可用选项
3. 用户选择不同路径时，自动更新 UVManager 的配置
4. 提供"重新检测"按钮刷新检测结果

## 使用方法

### 基本使用
```python
from src.core.uv_manager import UVManager

# 创建管理器
uv_manager = UVManager()

# 检查是否安装
if uv_manager.check_uv_installed():
    print("UV 已安装")
    
    # 获取所有安装路径
    paths = uv_manager.find_uv_installations()
    print(f"找到 {len(paths)} 个 UV 安装")
    
    # 获取首选路径
    preferred = uv_manager.get_preferred_uv_path()
    print(f"首选路径: {preferred}")
```

### 设置自定义路径
```python
# 设置自定义 UV 路径
if uv_manager.set_custom_uv_path("C:\\custom\\path\\uv.exe"):
    print("自定义路径设置成功")
else:
    print("路径无效")
```

## 测试

### 运行检测测试
```bash
python test_uv_detection.py
```

### 测试设置界面
```bash
python test_uv_settings.py
```

## 兼容性说明

- 向后兼容：原有的 `check_uv_installed()` 方法仍然可用
- 自动回退：如果找不到 UV，系统会使用当前 Python 环境
- 跨平台：支持 Windows、Linux 和 macOS

## 优势

1. **更可靠**：多层检测策略减少误报
2. **更灵活**：支持多个 UV 安装共存
3. **用户友好**：提供直观的界面选择
4. **可配置**：支持自定义 UV 路径
5. **向后兼容**：不影响现有代码

## 未来扩展

- 支持配置文件保存用户选择
- 添加 UV 版本兼容性检查
- 集成 UV 更新检查功能
- 支持远程 UV 环境