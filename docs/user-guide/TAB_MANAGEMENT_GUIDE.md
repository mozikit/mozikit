# 标签页管理功能指南

## 功能概述

为 LocalFlow 工作流编辑器实现了完整的标签页管理功能，包括关闭操作、修改状态跟踪和保存提示。

## 新增功能

### 1. 标签页关闭功能

#### 基本关闭
- **关闭按钮**: 每个标签页（除 Overview 外）都有关闭按钮（X）
- **快捷关闭**: 点击关闭按钮可快速关闭标签页
- **保护机制**: Overview 标签页无法关闭

#### 右键菜单
在任意工作流标签页上右键点击，可使用以下选项：

- **关闭当前**: 关闭当前右键点击的标签页
- **关闭其他**: 关闭除当前标签页外的所有其他工作流标签
- **关闭所有**: 关闭所有工作流标签（保留 Overview）

### 2. 修改状态跟踪

#### 自动标记
工作流被修改时，标签页标题会自动添加 `*` 标识：

```
工作流 1     →  工作流 1 *  (有未保存的更改)
```

#### 触发修改的操作
以下操作会将工作流标记为已修改：
- 添加节点
- 删除节点
- 创建连接
- 修改节点配置

#### 清除标记
保存工作流后，`*` 标识会自动移除。

### 3. 保存提示

#### 关闭前提示
当尝试关闭有未保存更改的工作流时，会弹出对话框：

```
工作流 '工作流 1' 有未保存的更改。
是否保存？

[保存] [不保存] [取消]
```

**选项说明**:
- **保存**: 保存工作流后关闭标签页
- **不保存**: 直接关闭标签页，丢弃更改
- **取消**: 取消关闭操作，返回编辑

#### 窗口关闭保护
关闭主窗口时，会检查所有工作流标签：
- 如果有未保存的更改，依次提示保存
- 用户可以取消关闭，继续编辑
- 确保不会意外丢失工作成果

## 实现细节

### 代码结构

#### MainWindow (`src/main_window.py`)

```python
# 启用标签关闭和右键菜单
self.tabs.setTabsClosable(True)
self.tabs.setMovable(True)
self.tabs.tabCloseRequested.connect(self._close_tab)
self.tabs.setContextMenuPolicy(Qt.CustomContextMenu)
self.tabs.customContextMenuRequested.connect(self._show_tab_context_menu)
```

**关键方法**:
- `_close_tab(index)`: 关闭指定标签页
- `_show_tab_context_menu(pos)`: 显示右键菜单
- `_close_other_tabs(keep_index)`: 关闭其他标签
- `_close_all_tabs()`: 关闭所有标签
- `_check_save_before_close(widget)`: 保存前检查
- `_on_workflow_modified(is_modified)`: 处理修改状态变化
- `closeEvent(event)`: 窗口关闭事件处理

#### WorkflowTabWidget (`src/views/workflow_tab_widget.py`)

```python
# 新增信号
modified_changed = Signal(bool)  # 修改状态改变信号

# 修改状态跟踪
self._is_modified = False
```

**关键方法**:
- `_set_modified(modified)`: 设置修改状态并发射信号
- `is_modified()`: 获取当前修改状态
- 在节点操作后自动调用 `_set_modified(True)`
- 保存成功后调用 `_set_modified(False)`

### 修改状态触发点

```python
def _on_node_added(self, node_item):
    """节点添加 → 标记为已修改"""
    self.nodes[node_item.node_id] = node_item
    self._set_modified(True)

def _on_node_deleted(self, node_id):
    """节点删除 → 标记为已修改"""
    del self.nodes[node_id]
    self._set_modified(True)

def _on_connection_created(self, from_id, to_id):
    """连接创建 → 标记为已修改"""
    self.connections.append((from_id, to_id))
    self._set_modified(True)

def update_node_config(self, node_id, config):
    """配置更新 → 标记为已修改"""
    self.nodes[node_id].config = config
    self._set_modified(True)
```

### 保存提示流程

```python
def _check_save_before_close(self, workflow_widget):
    """保存检查流程"""
    if not workflow_widget.is_modified():
        return True  # 没有修改，直接关闭
    
    # 弹出保存对话框
    reply = QMessageBox.question(
        self,
        "保存工作流",
        f"工作流 '{workflow_widget.workflow_name}' 有未保存的更改。\n是否保存？",
        QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel
    )
    
    if reply == QMessageBox.Save:
        workflow_widget._save_workflow()
        return True
    elif reply == QMessageBox.Discard:
        return True
    else:  # Cancel
        return False
```

## 使用场景

### 场景 1: 快速关闭标签
1. 点击标签页的关闭按钮（X）
2. 如果没有修改，直接关闭
3. 如果有修改，显示保存提示

### 场景 2: 批量管理标签
1. 在标签页上右键点击
2. 选择"关闭其他"清理其他标签
3. 或选择"关闭所有"清空所有工作流标签

### 场景 3: 防止数据丢失
1. 编辑工作流（添加节点、创建连接等）
2. 标签页显示 `*` 标识
3. 尝试关闭时，弹出保存提示
4. 选择"保存"确保数据不丢失

### 场景 4: 关闭应用前检查
1. 点击窗口关闭按钮
2. 系统检查所有工作流标签
3. 依次提示保存未保存的工作流
4. 可以取消关闭，返回编辑

## 测试指南

### 自动化测试

运行测试脚本：
```bash
python test_tab_management.py
```

测试内容：
- ✓ 标签可关闭功能
- ✓ 多个工作流标签创建
- ✓ 修改时显示 * 标识
- ✓ 保存后移除 * 标识
- ✓ 标签关闭功能
- ✓ Overview 标签保护

### 手动测试

#### 测试 1: 修改标识
1. 创建新工作流
2. 添加一个节点
3. **预期**: 标签页显示 "工作流 X *"
4. 保存工作流
5. **预期**: 标识 `*` 消失

#### 测试 2: 关闭提示
1. 创建新工作流并添加节点
2. 点击标签页关闭按钮
3. **预期**: 弹出保存提示对话框
4. 点击"取消"
5. **预期**: 标签页不关闭

#### 测试 3: 右键菜单
1. 创建 3 个工作流标签
2. 在第二个标签上右键
3. 选择"关闭其他"
4. **预期**: 只保留 Overview 和第二个工作流标签

#### 测试 4: 窗口关闭保护
1. 创建工作流并修改
2. 点击窗口关闭按钮
3. **预期**: 提示保存工作流
4. 点击"取消"
5. **预期**: 窗口不关闭

## 注意事项

1. **Overview 标签**: Overview 标签永远不能关闭，这是设计保护
2. **修改跟踪**: 只跟踪结构性修改（节点、连接、配置），不跟踪视图操作（缩放、平移）
3. **保存路径**: 工作流保存在 `workflows/<工作流名称>/workflow.json`
4. **信号连接**: 新创建的工作流标签需要连接 `modified_changed` 信号

## 已知限制

1. **撤销/重做**: 当前没有撤销/重做功能，修改是即时的
2. **自动保存**: 没有自动保存功能，需要手动保存
3. **多实例**: 不支持多个应用实例同时编辑同一工作流

## 未来改进

- [ ] 添加自动保存功能（每 N 分钟或 N 次操作）
- [ ] 实现撤销/重做功能
- [ ] 添加标签页拖拽排序
- [ ] 支持标签页收藏/置顶
- [ ] 工作流版本历史管理
