# 主题支持 - 快速参考

## 🎨 主题颜色速查表

### 暗色主题
```
背景: #1e1e1e  文字: #e0e0e0  按钮: #0e639c
成功: #4ec9b0  错误: #f48771  边框: #3f3f3f
```

### 亮色主题
```
背景: #f5f5f5  文字: #000000  按钮: #007ACC
成功: #28a745  错误: #dc3545  边框: #cccccc
```

## 🚀 快速测试

```bash
# 测试主题功能
python test_themes.py

# 运行主应用
python main.py
```

## ✨ 主要特性

✅ **自动检测** - 根据系统 palette 自动判断主题  
✅ **完美适配** - 所有控件都有针对性优化  
✅ **护眼设计** - 暗色主题减少眩光  
✅ **高对比度** - 确保文字清晰可读  

## 📝 代码示例

```python
# 设置对话框自动适配主题
from src.dialogs.settings_dialog import SettingsDialog

dialog = SettingsDialog(parent)
dialog.exec()  # 自动检测并应用主题
```

## 🎯 检测逻辑

```python
# 亮度计算
brightness = (R + G + B) / 3

# 主题判定
is_dark = brightness < 128
```

---
**简单、优雅、自动化！** 🌟
