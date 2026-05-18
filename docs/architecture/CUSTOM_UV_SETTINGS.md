# 自定义 UV 路径和镜像功能

## 功能概述

现在 LocalFlow 支持：
1. **自定义 UV 路径**：用户可以手动指定 UV 可执行文件的路径
2. **自定义镜像地址**：用户可以选择预设镜像或输入自定义镜像地址
3. **配置持久化**：配置会保存到 `~/.uv/uv.toml` 文件和环境变量

## 使用方法

### 1. 打开设置界面

在 LocalFlow 主界面中，打开设置对话框，在"UV 包管理工具"部分可以看到：

- **UV 路径下拉框**：显示所有检测到的 UV 安装和自定义选项
- **镜像地址下拉框**：显示预设镜像和自定义选项

### 2. 自定义 UV 路径

#### 方法一：选择检测到的路径
1. 点击 UV 路径下拉框
2. 从列表中选择一个检测到的 UV 安装
3. 选择后会在下方显示完整路径和版本信息

#### 方法二：手动指定路径
1. 在下拉框中选择"自定义路径..."
2. 在弹出的对话框中输入 UV 可执行文件的完整路径
3. 系统会自动验证路径的有效性

### 3. 配置镜像地址

#### 选择预设镜像
可用的预设镜像包括：
- 默认镜像（官方 PyPI）
- 清华大学镜像：`https://pypi.tuna.tsinghua.edu.cn/simple`
- 阿里云镜像：`https://mirrors.aliyun.com/pypi/simple`
- 中科大镜像：`https://pypi.mirrors.ustc.edu.cn/simple`
- 腾讯云镜像：`https://mirrors.cloud.tencent.com/pypi/simple`

#### 使用自定义镜像
1. 在下拉框中选择"自定义镜像..."
2. 在弹出的对话框中输入镜像地址
3. 格式应为：`https://example.com/simple`

## 配置存储

### 配置文件位置
- **文件路径**：`~/.uv/uv.toml`
- **环境变量**：`UV_INDEX_URL`

### 配置文件格式
```toml
[pip]
index-url = "https://pypi.tuna.tsinghua.edu.cn/simple"
```

## 技术实现

### 1. UV 检测算法

采用多层检测策略：

#### 第一层：PATH 环境变量检测
```python
# Windows
result = subprocess.run(["where", "uv"], ...)
# Unix/Linux
result = subprocess.run(["which", "uv"], ...)
```

#### 第二层：常见安装路径搜索
- **Windows**：
  - `%LOCALAPPDATA%\uv\uv.exe`
  - `%ProgramFiles%\uv\uv.exe`
  - `Python\Scripts\uv.exe`
- **Unix/Linux**：
  - `~/.local/bin/uv`
  - `~/.cargo/bin/uv`
  - `/usr/local/bin/uv`

#### 第三层：路径验证
```python
def _verify_uv_executable(self, uv_path: str) -> bool:
    try:
        result = subprocess.run([uv_path, "--version"], ...)
        return result.returncode == 0
    except:
        return False
```

### 2. 镜像配置实现

#### 配置管理
```python
def _save_mirror_config(self):
    # 设置环境变量
    os.environ["UV_INDEX_URL"] = self.custom_mirror
    
    # 保存到配置文件
    config_file = os.path.join(os.path.expanduser("~"), ".uv", "uv.toml")
    # ... 写入 TOML 格式
```

#### 使用镜像
```python
def install_packages(self, workflow_name: str, packages: List[str]):
    current_mirror = self.get_current_mirror()
    if current_mirror:
        cmd.extend(["--index-url", current_mirror])
```

## 测试验证

### 1. 基本功能测试
```bash
python test_uv_detection.py      # 测试 UV 检测
python test_custom_settings.py   # 测试自定义设置
python test_mirror_effectiveness.py  # 测试镜像有效性
```

### 2. UI 功能测试
```bash
python test_settings_ui.py       # 测试设置界面
```

## 兼容性说明

### 支持的操作系统
- ✅ Windows 10/11
- ✅ Linux (Ubuntu, CentOS, 等)
- ✅ macOS

### 支持的 UV 版本
- ✅ UV 0.9.0+
- 推荐使用最新版本

### 向后兼容性
- ✅ 现有项目无需修改
- ✅ 自动检测现有配置
- ✅ 如果找不到 UV，自动回退到系统 Python

## 故障排除

### 1. 检测不到 UV
- 确保 UV 已正确安装
- 检查 UV 是否在 PATH 环境变量中
- 尝试手动指定 UV 路径

### 2. 镜像不生效
- 检查网络连接
- 验证镜像地址是否正确
- 查看配置文件 `~/.uv/uv.toml`

### 3. 权限问题
- 确保有写入 `~/.uv/` 目录的权限
- 在 Windows 上可能需要管理员权限

## 高级用法

### 1. 命令行验证
```bash
# 验证 UV 安装
uv --version

# 验证镜像配置
uv pip install --dry-run requests

# 查看配置文件
cat ~/.uv/uv.toml
```

### 2. 程序化使用
```python
from src.core.uv_manager import UVManager

uv_manager = UVManager()

# 设置自定义路径
uv_manager.set_custom_uv_path("C:\\custom\\uv.exe")

# 设置自定义镜像
uv_manager.set_custom_mirror("https://custom-mirror.com/simple")

# 安装包（会自动使用配置）
success = uv_manager.install_packages("my_workflow", ["requests", "numpy"])
```

## 未来规划

### 计划中的功能
1. **镜像速度测试**：自动检测最快的镜像
2. **配置导入/导出**：方便在不同设备间同步设置
3. **团队配置模板**：支持为不同团队配置不同的设置
4. **自动更新检查**：定期检查 UV 更新

### 可能的改进
1. 支持 HTTP 代理配置
2. 支持认证镜像源
3. 支持配置文件版本管理
4. 添加配置验证和错误提示

---

## 总结

通过这次改进，LocalFlow 的 UV 管理功能变得更加灵活和强大：

1. **解决了检测问题**：多层检测策略确保能找到所有 UV 安装
2. **增加了自定义能力**：用户可以自由选择 UV 路径和镜像源
3. **提供了友好的界面**：直观的下拉框和对话框操作
4. **确保了配置生效**：通过实际测试验证镜像配置的有效性
5. **保持了兼容性**：现有代码无需修改即可使用新功能

这些改进使得 LocalFlow 能够更好地适应不同的开发环境和网络条件，提供更好的用户体验。