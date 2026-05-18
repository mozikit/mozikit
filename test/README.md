# 测试结构说明

## 目录结构

```
test/
├── __init__.py              # 测试配置文件
├── test_config.py           # 测试路径配置
├── run_tests.py             # 测试运行器
├── README.md                # 本文件
├── unit/                    # 单元测试
│   ├── test_uv_detection.py      # UV 检测功能测试
│   ├── test_custom_settings.py   # 自定义设置测试
│   ├── test_uv_settings.py       # UV 设置对话框测试
│   ├── verify_fixes.py           # 修复验证脚本
│   └── verify_delete_fix.py      # 删除修复验证脚本
├── integration/             # 集成测试
│   ├── test_mirror_effectiveness.py  # 镜像有效性测试
│   ├── test_workflow.py            # 工作流测试
│   ├── test_tab_management.py      # 标签管理测试
│   ├── test_fixes.py               # 修复测试
│   ├── test_improvements.py        # 改进测试
│   ├── test_final_fixes.py         # 最终修复测试
│   ├── test_save_fix.py            # 保存修复测试
│   └── test_delete_node.py         # 删除节点测试
└── ui/                      # UI 测试
    ├── test_settings_ui.py          # 设置界面测试
    ├── test_settings_fix.py         # 设置界面修复测试
    └── test_themes.py              # 主题测试
```

## 测试分类

### 单元测试 (Unit Tests)
- 测试单个组件的功能
- 独立于其他模块运行
- 快速执行，便于调试

### 集成测试 (Integration Tests)
- 测试多个组件之间的交互
- 验证整体功能流程
- 可能需要外部依赖

### UI 测试 (UI Tests)
- 测试用户界面交互
- 验证界面显示和响应
- 通常需要图形界面环境

## 使用方法

### 运行所有测试
```bash
python test/run_tests.py
```

### 运行特定类别的测试
```bash
# 单元测试
python test/run_tests.py unit

# 集成测试
python test/run_tests.py integration

# UI 测试
python test/run_tests.py ui
```

### 运行单个测试文件
```bash
# 从项目根目录运行
python test/unit/test_uv_detection.py

# 从测试目录运行
cd test/unit && python test_uv_detection.py
```

## 测试规范

### 文件命名
- 所有测试文件以 `test_` 开头
- 使用描述性名称，如 `test_uv_detection.py`

### 测试结构
```python
#!/usr/bin/env python3
"""
测试描述
"""
import sys
import os

# 添加项目根目录到路径
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

def test_function():
    """测试函数"""
    pass

if __name__ == "__main__":
    test_function()
```

### 最佳实践
1. **路径管理**: 使用相对路径导入项目模块
2. **编码处理**: 避免使用特殊Unicode字符，确保Windows兼容性
3. **错误处理**: 添加适当的异常处理
4. **清理资源**: 测试后清理临时文件和资源
5. **独立性**: 每个测试应该是独立的，不依赖其他测试

## 测试覆盖范围

### UV 功能测试
- UV 检测和路径管理
- 自定义路径配置
- 镜像配置和验证
- 虚拟环境管理

### 工作流测试
- 工作流执行
- 节点管理
- 标签页功能
- 数据持久化

### 用户界面测试
- 设置对话框
- 主题切换
- 用户交互
- 界面响应

### 系统集成测试
- 组件间交互
- 配置管理
- 错误处理
- 性能验证

## 持续集成

测试可以集成到CI/CD流水线中：

```yaml
# 示例 GitHub Actions 配置
- name: Run Unit Tests
  run: python test/run_tests.py unit

- name: Run Integration Tests
  run: python test/run_tests.py integration

- name: Run UI Tests (if supported)
  run: python test/run_tests.py ui
```

## 故障排除

### 常见问题
1. **导入错误**: 检查sys.path配置
2. **编码问题**: 避免特殊字符，使用ASCII或UTF-8
3. **依赖缺失**: 确保所有依赖已安装
4. **权限问题**: 检查文件和目录权限

### 调试技巧
1. 使用print语句输出调试信息
2. 检查测试文件的实际执行路径
3. 验证项目结构是否正确
4. 确保Python环境和依赖正确配置

## 贡献指南

添加新测试时：
1. 选择合适的测试类别（unit/integration/ui）
2. 遵循命名规范
3. 添加适当的文档
4. 确保测试独立性和可重复性
5. 更新此README文件

## 更新历史

- 2024-01-XX: 创建标准化测试结构
- 2024-01-XX: 添加UV功能测试
- 2024-01-XX: 重构测试目录结构