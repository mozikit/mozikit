# 构建参考指南

## 构建文件说明

LocalFlow 项目包含以下构建相关文件：

### 核心构建文件

- **`build.py`** - 主要的 PyInstaller 构建脚本
- **`build.bat`** - Windows 批处理构建脚本
- **`build.sh`** - Linux/Mac Shell 构建脚本
- **`LocalFlow.spec`** - PyInstaller 规范文件

### 已删除的重复文件

为了简化项目结构，以下构建文件已被删除：

- `quick_build.py` - 快速构建脚本（功能已整合到 build.py）
- `final_build.py` - 最终构建脚本（功能已整合到 build.py）
- `auto_build.py` - 自动构建脚本（功能已整合到 build.py）
- `fix_icon_build.py` - 图标修复脚本（功能已整合到 build.py）
- `install_pillow.py` - Pillow 安装脚本（不再需要）
- `create_settings_icon.py` - 空文件（无用文件）

## 构建方法

### 方法一：使用 Python 脚本（推荐）

```bash
python build.py
```

这个脚本会：
1. 检查必要的依赖
2. 清理之前的构建
3. 创建 PyInstaller 规范文件
4. 执行构建
5. 验证构建结果
6. 创建便携包

### 方法二：使用批处理脚本（Windows）

```bash
build.bat
```

Windows 用户可以直接双击运行。

### 方法三：使用 Shell 脚本（Linux/Mac）

```bash
./build.sh
```

确保脚本有执行权限：
```bash
chmod +x build.sh
```

### 方法四：直接使用 PyInstaller

```bash
pyinstaller LocalFlow.spec
```

## 构建输出

构建完成后，可执行文件位于：
- **Windows**: `dist/LocalFlow.exe`
- **Linux**: `dist/LocalFlow`
- **Mac**: `dist/LocalFlow.app`

## 故障排除

### 常见问题

1. **PyInstaller 未安装**
   ```bash
   pip install pyinstaller
   ```

2. **权限问题（Linux/Mac）**
   ```bash
   chmod +x build.sh
   ```

3. **依赖缺失**
   - 确保已安装所有 `requirements.txt` 中的依赖
   - 检查 Python 环境是否正确

4. **图标问题**
   - 确保 `assets/` 目录中存在图标文件
   - 检查图标格式是否支持

### 调试模式

如果构建失败，可以使用调试模式：

```bash
pyinstaller --clean --onefile --debug=all main.py
```

## 自定义构建

### 修改图标

1. 替换 `assets/icon.ico` (Windows) 或 `assets/icon.png` (Linux/Mac)
2. 重新运行构建脚本

### 修改规范文件

编辑 `LocalFlow.spec` 来自定义构建选项：

```python
# 修改基本信息
name = "LocalFlow"
icon = "assets/icon.ico"

# 添加数据文件
datas = [
    ('assets', 'assets'),
    # ('其他路径', '目标路径'),
]

# 添加隐藏导入
hiddenimports = [
    'PySide6.QtCore',
    'PySide6.QtWidgets',
    # 其他需要的模块,
]
```

## 自动化构建

### CI/CD 集成

可以在 CI/CD 流水线中自动构建：

```yaml
# GitHub Actions 示例
- name: Build Executable
  run: |
    python build.py
    ls -la dist/
```

### 批量构建多平台

```bash
# Linux
docker run --rm -v $(pwd):/app python:3.9 bash -c "cd /app && python build.py"

# Windows (PowerShell)
python build.py

# Mac
./build.sh
```

## 发布准备

构建完成后，建议：

1. **测试可执行文件**
   - 在干净的系统中测试
   - 验证所有功能正常

2. **创建安装包**
   ```bash
   python build.py --package
   ```

3. **生成校验和**
   ```bash
   sha256sum dist/LocalFlow.exe > checksum.txt
   ```

4. **文档更新**
   - 更新版本号
   - 更新发布说明

## 版本管理

### 版本号位置

- `src/__init__.py` - 应用版本
- `LocalFlow.spec` - 构建版本
- `README.md` - 文档版本

### 发布流程

1. 更新版本号
2. 运行构建测试
3. 提交代码
4. 创建 Git 标签
5. 构建发布包
6. 创建 GitHub Release

## 性能优化

### 减小文件大小

1. **排除不必要的模块**
   ```python
   # LocalFlow.spec
   exclusions = ['tkinter', 'unittest', 'test']
   ```

2. **启用 UPX 压缩**
   ```python
   # LocalFlow.spec
   upx = True
   ```

3. **移除调试信息**
   ```python
   # LocalFlow.spec
   debug = False
   ```

### 加快启动速度

1. **使用单文件模式**
   ```python
   # LocalFlow.spec
   onefile = True
   ```

2. **优化导入**
   - 避免在模块级别进行重型操作
   - 延迟导入非必要模块

## 最佳实践

1. **定期清理构建缓存**
   ```bash
   pyinstaller --clean LocalFlow.spec
   ```

2. **使用虚拟环境**
   ```bash
   python -m venv build_env
   source build_env/bin/activate  # Linux/Mac
   # build_env\Scripts\activate   # Windows
   pip install -r requirements.txt
   python build.py
   ```

3. **版本控制**
   - 将 `LocalFlow.spec` 加入版本控制
   - 忽略 `build/` 和 `dist/` 目录

4. **文档同步**
   - 保持文档与构建脚本同步
   - 记录构建过程中的重要变更

---

如有构建相关问题，请查看 [BUILD_GUIDE.md](BUILD_GUIDE.md) 或提交 Issue。