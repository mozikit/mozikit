# LocalFlow 打包指南

本指南介绍如何将 LocalFlow 项目打包为可执行文件。

## 🎉 打包状态：已完成

PyInstaller 打包功能已完全实现并测试成功！可以生成：
- ✅ 单文件可执行文件 (43.3 MB)
- ✅ 目录版本（更快启动）
- ✅ 便携版本（带启动脚本）

## 方法一：完整打包 (推荐)

使用完整的打包脚本，包含所有优化和配置：

```bash
python build.py
```

**特点：**
- ✅ 自动检查和安装依赖
- ✅ 创建详细的 PyInstaller spec 配置
- ✅ 优化包大小和性能
- ✅ 生成多种版本
- ✅ 创建便携版本

## 方法二：快速打包

使用快速打包脚本，适合测试：

```bash
python quick_build.py
```

**特点：**
- ⚡ 打包速度快
- 🎯 配置简单
- 📦 适合快速测试

## 方法三：手动打包

如果需要自定义配置，可以手动运行 PyInstaller：

```bash
# 安装 PyInstaller
pip install pyinstaller

# 基础打包
pyinstaller --name=LocalFlow --windowed --add-data="assets;assets" main.py

# 包含图标的打包
pyinstaller --name=LocalFlow --windowed --icon=assets/localflow_64.png --add-data="assets;assets" main.py
```

## 输出文件说明

打包完成后，会在 `dist/` 目录下生成以下文件：

### 🎯 主要输出
- **`LocalFlow.exe`** - 单文件版本，适合分发
- **`LocalFlow_dir/`** - 目录版本，启动更快，适合调试

### 📦 便携版本 (仅完整打包)
- **`LocalFlow_Portable/`** - 包含启动脚本的便携版本
  - Windows: `启动LocalFlow.bat`
  - Linux/Mac: `start_localflow.sh`

## 常见问题

### 1. 打包体积过大

使用完整打包脚本中的优化配置：
- 排除不需要的模块
- 使用 UPX 压缩
- 仅包含必要的依赖

### 2. 运行时错误

如果打包后运行出错：
1. 先测试目录版本 (`LocalFlow_dir/`)
2. 检查控制台输出（临时移除 `--windowed` 参数）
3. 添加缺失的模块到 `hiddenimports`

### 3. 资源文件缺失

确保资源文件正确包含：
```python
# 在 spec 文件中
added_files = [
    ('assets/localflow_64.png', 'assets'),
    ('assets/icons', 'assets/icons'),
]
```

### 4. UV 命令找不到

确保 UV 相关模块被正确导入：
```python
hiddenimports = [
    'uv',
    'src.core.uv_manager',
]
```

### 5. 图标格式问题

PyInstaller 在 Windows 上需要：
- ✅ **ICO 格式**（推荐，无需额外依赖）
- ⚠️ **PNG 格式**（需要 Pillow）
- 🔧 **自动降级**：如果 Pillow 不可用，跳过图标

**解决方案：**
```python
# 打包脚本会自动检查和安装 Pillow
# 或优先使用 ICO 格式：assets/localflow.ico
```

## 自定义配置

### 修改图标
替换 `assets/localflow_64.png` 为你的图标文件

### 添加额外文件
在打包脚本中修改 `added_files` 列表：

```python
added_files = [
    ('assets', 'assets'),
    ('examples', 'examples'),
    ('docs', 'docs'),  # 添加文档
    ('config.json', '.'),  # 添加配置文件
]
```

### 隐藏导入模块
如果打包后运行时模块找不到，添加到 `hiddenimports`：

```python
hiddenimports = [
    'your_missing_module',
    'another_module',
]
```

## 分发建议

### Windows 用户
- 推荐使用单文件版本 `LocalFlow.exe`
- 可直接发送给其他用户使用

### 开发/测试
- 推荐使用目录版本 `LocalFlow_dir/`
- 启动更快，便于调试

### 企业分发
- 使用完整打包脚本生成便携版本
- 包含启动脚本，更专业

## 版本兼容性

- **Python**: 3.8+
- **PySide6**: 6.0+
- **PyInstaller**: 5.0+

确保目标机器安装了必要的运行时库：
- Windows: Visual C++ Redistributable
- Linux: 相应的 Qt 库依赖

## 许可证

打包的可执行文件应包含原始许可证信息。确保在分发时遵守相关许可证要求。