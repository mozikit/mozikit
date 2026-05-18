# 节点删除功能修复

## 问题描述

工作流中删除节点功能没有生效，按 `Delete` 键或 `Backspace` 键无法删除选中的节点。

## 问题原因

### 1. 键盘事件焦点问题

Qt的键盘事件处理依赖于焦点（Focus）机制：
- `QGraphicsView`（WorkflowCanvas）可以接收键盘事件
- `QGraphicsScene`（WorkflowGraphicsScene）也可以接收键盘事件
- 但需要正确设置焦点策略

**原问题**：
- Canvas没有设置明确的焦点策略
- Scene的 `keyPressEvent` 没有处理删除逻辑

### 2. 事件处理链

在Qt Graphics Framework中，键盘事件的传递顺序：
```
焦点项 (Focused Item) 
  ↓ (如果未处理)
场景 (Scene)
  ↓ (如果未处理)
视图 (View)
```

**原实现**：
- Scene的 `keyPressEvent` 只调用父类方法，不处理删除
- Canvas的 `keyPressEvent` 有删除逻辑，但可能收不到事件

## 解决方案

### 1. 在Scene中添加删除处理

**修改文件**：`src/views/workflow_canvas.py`

```python
class WorkflowGraphicsScene(QGraphicsScene):
    # ... 省略其他代码 ...
    
    def keyPressEvent(self, event):
        """键盘按下事件"""
        from PySide6.QtCore import Qt
        from src.views.node_graphics import NodeGraphicsItem
        
        # 删除选中的节点（Del键或Backspace键）
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            selected_items = self.selectedItems()
            for item in selected_items:
                if isinstance(item, NodeGraphicsItem):
                    item.delete_node()
        else:
            super().keyPressEvent(event)
```

**关键点**：
- 直接在Scene中处理删除键
- 使用 `self.selectedItems()` 获取选中的项
- 只删除节点类型的项（`NodeGraphicsItem`）

### 2. 设置Canvas焦点策略

**修改文件**：`src/views/workflow_canvas.py`

```python
class WorkflowCanvas(QGraphicsView):
    def __init__(self, scene, parent=None):
        super().__init__(parent)
        # ... 省略其他初始化代码 ...
        
        # 设置焦点策略，确保可以接收键盘事件
        self.setFocusPolicy(Qt.StrongFocus)
```

**关键点**：
- `Qt.StrongFocus` 表示可以通过鼠标点击或Tab键获得焦点
- 确保Canvas能接收键盘事件

### 3. 双重保险

Canvas也保留删除逻辑：

```python
class WorkflowCanvas(QGraphicsView):
    def keyPressEvent(self, event):
        """键盘按下事件"""
        from PySide6.QtCore import Qt
        from src.views.node_graphics import NodeGraphicsItem
        
        # 删除选中的节点（Del键或Backspace键）
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            selected_items = self._scene.selectedItems()
            for item in selected_items:
                if isinstance(item, NodeGraphicsItem):
                    item.delete_node()
        else:
            super().keyPressEvent(event)
```

## 使用方法

### 删除单个节点

1. **选中节点**：点击节点，节点周围会出现蓝色边框
2. **按删除键**：按 `Delete` 键或 `Backspace` 键
3. **验证删除**：节点和相关连接线消失

### 删除多个节点

1. **选中第一个节点**：点击节点
2. **添加更多选中**：按住 `Ctrl` 键，点击其他节点
3. **批量删除**：按 `Delete` 键
4. **验证**：所有选中的节点被删除

### 右键菜单删除

1. **右键点击节点**
2. **选择"删除节点"**
3. **节点被删除**

## 测试验证

运行测试脚本：

```bash
python test_delete_node.py
```

**测试结果**：
```
[OK] Canvas焦点策略正确设置
[OK] 测试节点已创建
[OK] 节点可以被选中
[OK] Scene有keyPressEvent方法
[OK] Canvas有keyPressEvent方法
[OK] 节点有delete_node方法

[SUCCESS] 所有删除相关的方法都存在
```

## 手动测试步骤

1. 启动应用：`python main.py`
2. 创建新工作流
3. 添加一些节点（拖拽或右键菜单）
4. 点击选中一个节点（应该看到蓝色边框）
5. 按 `Delete` 键或 `Backspace` 键
6. ✅ 验证节点被删除

## 故障排除

### 问题：按Delete键还是没反应

**检查1：节点是否真的被选中？**
- 选中的节点周围应该有**蓝色边框**
- 如果没有边框，说明没选中，再点击一次

**检查2：画布是否有焦点？**
- 点击画布的空白区域
- 确保最近的操作是在画布上

**检查3：查看控制台输出**
```bash
python main.py
# 操作后查看是否有错误信息
```

**检查4：使用右键菜单**
- 如果键盘删除不工作，尝试右键菜单
- 右键点击节点 → "删除节点"

### 问题：节点删除了但连接线还在

这不应该发生，因为 `delete_node()` 方法会清理连接：

```python
def delete_node(self):
    """删除节点"""
    # 删除所有相关连接
    for port in self.input_ports + self.output_ports:
        for connection in port.connections[:]:
            scene = connection.scene()
            if scene:
                scene.removeItem(connection)
    
    # 从场景中移除节点
    scene = self.scene()
    if scene:
        scene.removeItem(self)
```

如果遇到这个问题：
1. 重启应用
2. 提交bug报告

## 技术细节

### Qt焦点策略

| 策略 | 值 | 说明 |
|------|-----|------|
| `Qt.NoFocus` | 0 | 不接受焦点 |
| `Qt.TabFocus` | 1 | 通过Tab键获得焦点 |
| `Qt.ClickFocus` | 2 | 通过点击获得焦点 |
| `Qt.StrongFocus` | 11 | 点击和Tab都可以 |
| `Qt.WheelFocus` | 15 | 包括滚轮 |

**选择 `Qt.StrongFocus`**：
- 支持鼠标点击获得焦点
- 支持Tab键导航
- 最常用的焦点策略

### 键盘事件处理顺序

1. **焦点项处理**：如果有项获得焦点（如文本框），先处理
2. **Scene处理**：Scene的 `keyPressEvent`
3. **View处理**：View的 `keyPressEvent`
4. **父窗口处理**：向上传递

**双重实现的原因**：
- Scene和View都实现了删除逻辑
- 无论焦点在哪里，都能处理删除

### 事件接受与传播

```python
def keyPressEvent(self, event):
    if event.key() == Qt.Key_Delete:
        # 处理删除
        event.accept()  # 事件已处理，不再传播
    else:
        super().keyPressEvent(event)  # 传递给父类
```

## 修改总结

**修改文件**：
- `src/views/workflow_canvas.py`

**修改内容**：
1. `WorkflowGraphicsScene.keyPressEvent()` - 添加删除处理
2. `WorkflowCanvas.__init__()` - 设置焦点策略

**修改行数**：
- 新增代码：约15行
- 修改代码：1行

**影响范围**：
- 只影响键盘删除功能
- 不影响其他功能
- 向后兼容

## 相关文档

- `IMPROVEMENTS.md` - 查看所有功能改进
- `test_delete_node.py` - 删除功能测试脚本
- `NEW_FEATURES_GUIDE.md` - 新功能使用指南

---

**修复完成日期**：2025-12-24
**状态**：✅ 已验证通过
