# Mozikit 打包指南

Windows 当前分发基线请以 [WINDOWS_DESKTOP_DISTRIBUTION.md](WINDOWS_DESKTOP_DISTRIBUTION.md) 为准。本页中的单文件 `Mozikit.exe`、`quick_build.py` 和旧目录名是历史记录，不代表当前 Desktop 发行版。

## 当前 Windows 构建入口

先下载固定版本的 bundled UV，再使用共享 GUI/CLI spec：

```bash
powershell -File .\scripts\download_uv.ps1
python auto_build.py
```

构建结果：

```text
dist/Mozikit/
├── MozikitDesktop.exe
├── mozikit.exe
├── runtime/uv.exe
├── official_nodes/
└── _internal/
```

`release/Mozikit-Windows-x64.zip` 是不修改 PATH 的 Portable ZIP；MSI 使用 `scripts/build_msi.ps1` 生成。

## 常见问题

### 1. 打包体积过大

使用完整打包脚本中的优化配置：
- 排除不需要的模块
- 使用 UPX 压缩
- 仅包含必要的依赖

### 2. 运行时错误

如果打包后运行出错：
1. 先测试目录版本 (`dist/Mozikit/`)
2. 检查控制台输出（临时移除 `--windowed` 参数）
3. 添加缺失的模块到 `hiddenimports`

### 3. 资源文件缺失

确保资源文件正确包含：
```python
# 在 Mozikit.spec 的 datas 中
datas = [
    ('assets/Mozikit_64.png', 'assets'),
    ('assets/icons', 'assets/icons'),
]
```

### 4. UV 命令找不到

不要把 `uv` 当作 PyInstaller hidden import。运行 `scripts/download_uv.ps1`，确认 `build/bundled_uv/uv.exe` 存在后再构建；正式 Desktop 产物会将它放到 `runtime/uv.exe`。

### 5. 图标格式问题

PyInstaller 在 Windows 上需要：
- ✅ **ICO 格式**（推荐，无需额外依赖）
- ⚠️ **PNG 格式**（需要 Pillow）
- 🔧 **自动降级**：如果 Pillow 不可用，跳过图标

**解决方案：**
```python
# 打包脚本会自动检查和安装 Pillow
# 或优先使用 ICO 格式：assets/Mozikit.ico
```

## 自定义配置

### 修改图标
替换 `assets/Mozikit_64.png` 为你的图标文件

### 添加额外文件
在 `Mozikit.spec` 中修改 `datas` 列表：

```python
datas = [
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
- 推荐使用 MSI；开始菜单显示为 Mozikit，CLI 入口为 `mozikit`
- 无管理员权限时可使用 `Mozikit-Windows-x64.zip`

### 开发/测试
- 推荐使用目录版本 `dist/Mozikit/`
- 启动更快，便于调试

### 企业分发
- 使用完整打包脚本生成便携版本
- 包含启动脚本，更专业

## 版本兼容性

- **Python**: 3.8+
- **PySide6**: 6.0+
- **PyInstaller**: 6.13+

正式 Desktop 产物自带 Python、PySide6、运行时、官方节点和 bundled UV；发布验收仍应在干净 Windows 机器上验证 VC++/签名/权限环境。

## 许可证

打包的可执行文件应包含原始许可证信息。确保在分发时遵守相关许可证要求。
