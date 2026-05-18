"""
工作流画布组件
优化特性：
- 网格背景
- 平滑的缩放和拖拽
- 优化的交互体验
- 更好的视觉反馈
"""

import math
import time

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QLine,
    QPointF,
    QPropertyAnimation,
    QRectF,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPen,
    QPixmap,
    QTransform,
)
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsScene,
    QGraphicsView,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.core.config_manager import ConfigManager
from src.core.log_manager import get_logger
from src.core.theme_manager import ThemeManager

logger = get_logger("workflow_canvas")


class AutoLayoutButton(QGraphicsItem):
    """自动整理按钮 - 悬浮在画布右下角"""

    def __init__(self, canvas, parent=None):
        super().__init__(parent)
        self.canvas = canvas
        self._size = 44
        self._hovered = False
        self._pressed = False
        self._opacity = 1.0
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setZValue(1000)

    def boundingRect(self) -> QRectF:
        padding = 4
        return QRectF(
            -padding, -padding, self._size + padding * 2, self._size + padding * 2
        )

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setOpacity(self._opacity)

        rect = QRectF(0, 0, self._size, self._size)

        if self._pressed:
            bg_color = QColor(ThemeManager.COLORS["accent_pressed"])
        elif self._hovered:
            bg_color = QColor(ThemeManager.COLORS["accent_hover"])
        else:
            bg_color = QColor(ThemeManager.COLORS["accent"])

        shadow_color = QColor(0, 0, 0, 60)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(shadow_color))
        painter.drawRoundedRect(rect.adjusted(2, 2, 2, 2), 12, 12)

        gradient = QLinearGradient(0, 0, 0, self._size)
        gradient.setColorAt(0, bg_color.lighter(110))
        gradient.setColorAt(1, bg_color)
        painter.setBrush(QBrush(gradient))
        painter.drawRoundedRect(rect, 12, 12)

        painter.setPen(QPen(QColor(ThemeManager.COLORS["white"]), 2))
        painter.setBrush(Qt.NoBrush)

        cx = self._size / 2
        cy = self._size / 2

        painter.drawLine(int(cx - 8), int(cy - 4), int(cx + 8), int(cy - 4))
        painter.drawLine(int(cx - 8), int(cy), int(cx + 8), int(cy))
        painter.drawLine(int(cx - 8), int(cy + 4), int(cx + 8), int(cy + 4))

        painter.setPen(
            QPen(QColor(ThemeManager.COLORS["white"]), 2, Qt.SolidLine, Qt.RoundCap)
        )
        painter.drawLine(int(cx - 8), int(cy - 4), int(cx - 8), int(cy + 4))
        painter.drawLine(int(cx), int(cy - 4), int(cx), int(cy + 4))
        painter.drawLine(int(cx + 8), int(cy - 4), int(cx + 8), int(cy + 4))

    def hoverEnterEvent(self, event):
        self._hovered = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self._hovered = False
        self._pressed = False
        self.update()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._pressed = True
            self.update()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._pressed = False
            self.update()
            if self._hovered and self.canvas:
                self.canvas.auto_layout_nodes()
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def update_position(self):
        try:
            if self.canvas and self.scene():
                viewport_rect = self.canvas.viewport().rect()
                bottom_right = self.canvas.mapToScene(viewport_rect.bottomRight())
                margin = 20
                self.setPos(
                    bottom_right.x() - self._size - margin,
                    bottom_right.y() - self._size - margin,
                )
        except RuntimeError:
            pass


class WorkflowCanvas(QGraphicsView):
    """工作流画布 - 优化版"""

    # 信号定义
    node_added = Signal(object)  # 节点被添加
    node_selected = Signal(object)  # 节点被选中
    node_deleted = Signal(str)  # 节点被删除 (node_id)
    connection_created = Signal(
        str, str, str, str
    )  # 连接被创建 (from_node_id, from_port_name, to_node_id, to_port_name)
    zoom_changed = Signal()  # 缩放比例发生变化

    def __init__(self, scene, parent=None):
        super().__init__(parent)
        self.father = parent
        self._scene = scene
        self.setScene(self._scene)

        # 渲染优化 - 使用智能视口更新策略
        self.setRenderHint(QPainter.Antialiasing)
        self.setRenderHint(QPainter.TextAntialiasing)
        # 仅在静态场景使用 SmoothPixmapTransform，动态时关闭以提升性能
        self.setViewportUpdateMode(QGraphicsView.BoundingRectViewportUpdate)
        self.setOptimizationFlags(
            QGraphicsView.DontSavePainterState | QGraphicsView.DontAdjustForAntialiasing
        )
        # 启用缓存模式，减少重复绘制
        self.setCacheMode(QGraphicsView.CacheBackground)

        # 隐藏滚动条
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        # 变换锚点
        # AnchorUnderMouse: 缩放时以鼠标位置为锚点，体验更自然
        # NoAnchor: 画布尺寸变化时不自动调整视图中心，避免dock显隐导致节点抖动
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.NoAnchor)

        # 拖拽模式
        self._drag_mode = False

        # 节点点击检测（区分点击和拖动）
        self._pending_node_click = None  # 待处理的节点点击
        self._mouse_press_pos = None  # 鼠标按下位置

        # 连线模式
        self.connection_mode = False
        self.connection_start_port = None
        self.temp_connection = None

        # 启用拖放
        self.setAcceptDrops(True)

        # 设置焦点策略
        self.setFocusPolicy(Qt.StrongFocus)

        # 网格配置
        self._grid_enabled = True
        self._grid_size = 20
        self._grid_color = QColor(ThemeManager.COLORS["border"])
        self._grid_color.setAlpha(35)

        # 动画定时器 - 使用自适应帧率，默认30fps降低CPU占用
        self._animation_timer = QTimer()
        self._animation_timer.timeout.connect(self._update_animations)
        self._animation_timer.start(33)  # ~30fps，平衡流畅度与性能
        self._active_animation_items = set()  # 追踪需要动画的项

        # 缩放限制
        self._min_zoom = 0.2
        self._max_zoom = 3.0
        self._current_zoom = 1.0

        # 缩放保存定时器（防抖）- 保存缩放配置
        self._zoom_save_timer = QTimer()
        self._zoom_save_timer.setSingleShot(True)
        self._zoom_save_timer.timeout.connect(self._save_zoom_to_config)
        self._config_manager = ConfigManager()

        # 缩放自动保存防抖定时器 - 避免连续缩放时频繁保存工作流
        self._zoom_auto_save_timer = QTimer()
        self._zoom_auto_save_timer.setSingleShot(True)
        self._zoom_auto_save_timer.timeout.connect(self._emit_zoom_changed)
        self._zoom_auto_save_pending = False

        # 自动整理按钮
        self._auto_layout_btn = AutoLayoutButton(self)
        self._scene.addItem(self._auto_layout_btn)
        self._auto_layout_btn.update_position()

    def drawBackground(self, painter: QPainter, rect: QRectF):
        """绘制背景 - 直接绘制网格，避免大Pixmap缓存导致的缩放卡顿"""
        super().drawBackground(painter, rect)

        if not self._grid_enabled:
            return

        # 绘制渐变背景
        background_gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        background_gradient.setColorAt(0, QColor(ThemeManager.COLORS["background"]))
        background_gradient.setColorAt(1, QColor(ThemeManager.COLORS["surface"]))
        painter.fillRect(rect, background_gradient)

        # 直接绘制网格（不使用Pixmap缓存，避免缩放时创建大位图）
        painter.setRenderHint(QPainter.Antialiasing, False)

        # 计算网格范围
        left = int(rect.left()) - (int(rect.left()) % self._grid_size)
        top = int(rect.top()) - (int(rect.top()) % self._grid_size)
        right = int(rect.right())
        bottom = int(rect.bottom())

        # 限制绘制范围，避免极端缩放时绘制过多元素
        max_lines = 200
        x_lines = (right - left) // self._grid_size
        y_lines = (bottom - top) // self._grid_size

        if x_lines <= max_lines and y_lines <= max_lines:
            # 绘制细网格线
            pen = QPen(self._grid_color, 1, Qt.DotLine)
            painter.setPen(pen)

            x = left
            while x < right:
                painter.drawLine(QLine(int(x), int(top), int(x), int(bottom)))
                x += self._grid_size

            y = top
            while y < bottom:
                painter.drawLine(QLine(int(left), int(y), int(right), int(y)))
                y += self._grid_size

            # 绘制主网格线（每5格一条）
            major_grid_size = self._grid_size * 5
            main_grid_color = QColor(ThemeManager.COLORS["accent"])
            main_grid_color.setAlpha(18)
            painter.setPen(QPen(main_grid_color, 2))

            x = left - (left % major_grid_size)
            while x < right:
                painter.drawLine(QLine(int(x), int(top), int(x), int(bottom)))
                x += major_grid_size

            y = top - (top % major_grid_size)
            while y < bottom:
                painter.drawLine(QLine(int(left), int(y), int(right), int(y)))
                y += major_grid_size

            # 绘制网格点（稀疏）
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(self._grid_color))
            dot_spacing = self._grid_size * 2
            for x in range(left, right, dot_spacing):
                for y in range(top, bottom, dot_spacing):
                    painter.drawEllipse(QPointF(x, y), 1.2, 1.2)

        # 绘制坐标轴
        axis_color = QColor(ThemeManager.COLORS["accent"])
        axis_color.setAlpha(25)
        painter.setPen(QPen(axis_color, 1))
        painter.drawLine(QPointF(rect.left(), 0), QPointF(rect.right(), 0))
        painter.drawLine(QPointF(0, rect.top()), QPointF(0, rect.bottom()))

    def wheelEvent(self, event):
        """滚轮缩放 - 优化版"""
        zoom_in_factor = 1.15
        zoom_out_factor = 1 / zoom_in_factor

        # 计算新的缩放比例
        if event.angleDelta().y() > 0:
            new_zoom = self._current_zoom * zoom_in_factor
            if new_zoom <= self._max_zoom:
                self._current_zoom = new_zoom
                self.scale(zoom_in_factor, zoom_in_factor)
        else:
            new_zoom = self._current_zoom * zoom_out_factor
            if new_zoom >= self._min_zoom:
                self._current_zoom = new_zoom
                self.scale(zoom_out_factor, zoom_out_factor)

        # 缩放变化时触发视口更新
        self.viewport().update()

        # 防抖保存缩放比例到全局配置
        self._zoom_save_timer.start(500)

        # 防抖发射缩放变化信号，避免连续缩放时频繁自动保存工作流
        # 用户停止缩放操作 5000ms (5秒) 后才真正发射信号
        self._zoom_auto_save_pending = True
        self._zoom_auto_save_timer.start(5000)

        # 更新自动整理按钮位置
        if hasattr(self, "_auto_layout_btn"):
            try:
                self._auto_layout_btn.update_position()
            except RuntimeError:
                pass

    def mousePressEvent(self, event):
        """鼠标按下事件 - 优化版"""
        item_at_pos = self.itemAt(event.pos())

        if event.button() == Qt.LeftButton:
            # 检查是否点击端口
            from src.views.node_graphics import PortGraphicsItem

            if isinstance(item_at_pos, PortGraphicsItem):
                self._start_connection(item_at_pos, event)
                return

            # 检查是否点击节点
            from src.views.node_graphics import NodeGraphicsItem

            node_item = item_at_pos
            while node_item and not isinstance(node_item, NodeGraphicsItem):
                node_item = node_item.parentItem()

            if node_item:
                # 记录待处理的节点点击，在 mouseRelease 中确认不是拖动后才触发
                self._pending_node_click = node_item
                self._mouse_press_pos = event.pos()
            else:
                self._scene.clearSelection()
                self._pending_node_click = None
                self._mouse_press_pos = None

            self.leftButtonPressed(event)

        if event.button() == Qt.RightButton:
            self._show_context_menu(event)

        return super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """鼠标移动事件"""
        if self.connection_mode and self.temp_connection:
            scene_pos = self.mapToScene(event.pos())
            self.temp_connection.set_end_pos(scene_pos)

        # 如果鼠标移动超过阈值，取消待处理的节点点击（判定为拖动）
        if self._pending_node_click and self._mouse_press_pos:
            move_distance = (event.pos() - self._mouse_press_pos).manhattanLength()
            if move_distance > 5:  # 5像素阈值，判定为拖动
                self._pending_node_click = None

        return super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        """鼠标释放事件"""
        if event.button() == Qt.LeftButton:
            if self.connection_mode:
                item_at_pos = self.itemAt(event.pos())
                from src.views.node_graphics import PortGraphicsItem, PortType

                if isinstance(item_at_pos, PortGraphicsItem):
                    self._finish_connection(item_at_pos)
                else:
                    self._cancel_connection()

            # 如果存在待处理的节点点击且未取消（即没有发生明显移动），则触发选中
            if self._pending_node_click:
                self.node_selected.emit(self._pending_node_click)
                self._pending_node_click = None
                self._mouse_press_pos = None

            self.leftButtonReleased(event)

        self._drag_mode = None
        return super().mouseReleaseEvent(event)

    def leftButtonPressed(self, event):
        if self.itemAt(event.pos()) is not None:
            return
        else:
            self._scene.clearSelection()
            self.setDragMode(QGraphicsView.ScrollHandDrag)
            self._drag_mode = True

    def leftButtonReleased(self, event):
        self.setDragMode(QGraphicsView.NoDrag)
        self._drag_mode = False

    def _start_connection(self, start_port, event):
        """开始创建连接"""
        from src.views.node_graphics import ConnectionGraphicsItem, PortType

        # 只能从输出端口开始连接
        if start_port.port_type != PortType.OUTPUT:
            return

        self.connection_mode = True
        self.connection_start_port = start_port

        # 创建临时连接线
        self.temp_connection = ConnectionGraphicsItem(start_port)
        self._scene.addItem(self.temp_connection)

    def _finish_connection(self, end_port):
        """完成连接 - 带类型兼容检查和单连接约束"""
        from src.views.node_graphics import PortType

        # 只能连接到输入端口
        if end_port.port_type != PortType.INPUT:
            self._cancel_connection()
            return

        # 不能连接到同一个节点
        if end_port.parent_node == self.connection_start_port.parent_node:
            self._cancel_connection()
            return

        # 类型兼容检查
        if not self._ports_compatible(self.connection_start_port, end_port):
            self._cancel_connection()
            return

        # 输入端口单连接约束：移除已有连接
        if end_port.connections:
            for old_conn in end_port.connections[:]:
                self._remove_connection_item(old_conn)

        # 完成连接
        self.temp_connection.set_end_port(end_port)

        # 发射连接创建信号（4参数）
        from_node_id = self.connection_start_port.parent_node.node_id
        from_port_name = self.connection_start_port.port_name
        to_node_id = end_port.parent_node.node_id
        to_port_name = end_port.port_name
        self.connection_created.emit(
            from_node_id, from_port_name, to_node_id, to_port_name
        )

        # 重置状态
        self.connection_mode = False
        self.connection_start_port = None
        self.temp_connection = None

    def _ports_compatible(self, out_port, in_port) -> bool:
        """检查两个端口是否类型兼容"""
        out_type = out_port.data_type
        in_type = in_port.data_type

        # any 类型兼容一切
        if out_type == "any" or in_type == "any":
            return True

        # 相同类型
        if out_type == in_type:
            return True

        # 子类型规则
        COMPATIBLE = {
            "int": {"float", "string"},
            "float": {"string"},
            "bool": {"string"},
        }
        if in_type in COMPATIBLE.get(out_type, set()):
            return True

        return False

    def _remove_connection_item(self, connection):
        """从场景中移除一条连接线"""
        # 从端口中移除引用
        if connection.start_port and connection in connection.start_port.connections:
            connection.start_port.connections.remove(connection)
        if connection.end_port and connection in connection.end_port.connections:
            connection.end_port.connections.remove(connection)
        # 从场景中移除
        if connection.scene():
            connection.scene().removeItem(connection)

    def _cancel_connection(self):
        """取消连接"""
        if self.temp_connection:
            self._scene.removeItem(self.temp_connection)

        self.connection_mode = False
        self.connection_start_port = None
        self.temp_connection = None

    def _show_context_menu(self, event):
        """显示上下文菜单 — 从注册表动态生成节点列表"""
        from PySide6.QtGui import QCursor

        from src.core.node_registry import get_registry

        menu = QMenu()
        menu.setStyleSheet(f"""
            QMenu {{
                background-color: {ThemeManager.COLORS["surface"]};
                color: {ThemeManager.COLORS["text"]};
                border: 1px solid {ThemeManager.COLORS["border"]};
                border-radius: 10px;
                padding: 8px;
            }}
            QMenu::item {{
                padding: 10px 20px;
                border-radius: 6px;
                margin: 2px 4px;
            }}
            QMenu::item:selected {{
                background: {ThemeManager.COLORS["accent"]};
            }}
            QMenu::separator {{
                height: 1px;
                background: {ThemeManager.COLORS["border"]};
                margin: 6px 12px;
            }}
        """)

        # 添加节点菜单 — 从注册表按分类动态生成
        add_menu = menu.addMenu("➕ 添加节点")
        add_menu.setStyleSheet(menu.styleSheet())

        registry = get_registry()
        nodes_by_category = {}
        for node_dict in registry.get_all_nodes():
            category = node_dict.get("category", "其他")
            if category not in nodes_by_category:
                nodes_by_category[category] = []
            nodes_by_category[category].append(node_dict)

        for category, nodes in sorted(nodes_by_category.items()):
            cat_menu = add_menu.addMenu(f"📁 {category}")
            cat_menu.setStyleSheet(menu.styleSheet())
            for node_dict in nodes:
                action = cat_menu.addAction(node_dict["name"])
                action.setData((node_dict["type_str"], node_dict["name"]))

        menu.addSeparator()

        # 视图操作
        reset_view_action = menu.addAction("🔍 重置视图")
        center_view_action = menu.addAction("🎯 居中显示")

        action = menu.exec_(QCursor.pos())

        scene_pos = self.mapToScene(event.pos())

        if action == reset_view_action:
            self.resetTransform()
            self._current_zoom = 1.0
        elif action == center_view_action:
            self.centerOn(0, 0)
        elif action:
            # 处理节点添加
            self._add_node_from_action(action, scene_pos)

    def _add_node_from_action(self, action, scene_pos):
        """根据菜单动作添加节点"""
        from src.core.node_registry import get_registry
        from src.views.node_graphics import NodeGraphicsItem

        action_data = action.data()
        if not action_data:
            return

        node_type_str, node_title = action_data
        node_id = f"node_{int(time.time() * 1000)}"

        # 从注册表获取 schema
        registry = get_registry()
        node_def = registry.get_node(node_type_str)
        input_schema = node_def.input_schema if node_def else {}
        output_schema = node_def.output_schema if node_def else {}

        node_item = NodeGraphicsItem(
            node_id, node_type_str, node_title, input_schema, output_schema
        )
        node_item.setPos(scene_pos)
        self._scene.addItem(node_item)
        self.node_added.emit(node_item)

    def dragEnterEvent(self, event):
        """拖拽进入事件"""
        if event.mimeData().hasText():
            event.setDropAction(Qt.CopyAction)
            event.accept()

    def dragMoveEvent(self, event):
        """拖拽移动事件"""
        if event.mimeData().hasText():
            event.setDropAction(Qt.CopyAction)
            event.accept()

    def dropEvent(self, event):
        """放置事件 — 统一从注册表获取节点信息"""
        if event.mimeData().hasText():
            node_type_str = event.mimeData().text()

            from src.core.node_registry import get_registry

            registry = get_registry()

            scene_pos = self.mapToScene(event.pos())
            node_id = f"node_{int(time.time() * 1000)}"

            node_type = None
            node_title = "未知节点"

            # 从注册表获取节点信息
            node_def = registry.get_node(node_type_str)
            if node_def:
                node_type = node_type_str
                node_title = node_def.name

            if node_type:
                from src.views.node_graphics import NodeGraphicsItem

                input_schema = node_def.input_schema if node_def else {}
                output_schema = node_def.output_schema if node_def else {}
                node_item = NodeGraphicsItem(
                    node_id, node_type, node_title, input_schema, output_schema
                )
                node_item.setPos(scene_pos)
                self._scene.addItem(node_item)
                self.node_added.emit(node_item)
                event.acceptProposedAction()

    def keyPressEvent(self, event):
        """键盘按下事件 - 优化版"""
        from src.views.node_graphics import NodeGraphicsItem

        # 删除选中的节点
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            selected_items = self._scene.selectedItems()
            for item in selected_items:
                if isinstance(item, NodeGraphicsItem):
                    item.delete_node()
        # 快捷键：Ctrl+A 全选
        elif event.key() == Qt.Key_A and event.modifiers() == Qt.ControlModifier:
            for item in self._scene.items():
                if isinstance(item, NodeGraphicsItem):
                    item.setSelected(True)
        # 快捷键：Esc 取消选择
        elif event.key() == Qt.Key_Escape:
            self._scene.clearSelection()
            if self.connection_mode:
                self._cancel_connection()
        # 快捷键：Ctrl+0 重置缩放
        elif event.key() == Qt.Key_0 and event.modifiers() == Qt.ControlModifier:
            self.resetTransform()
            self._current_zoom = 1.0
        else:
            super().keyPressEvent(event)

    def on_node_deleted(self, node_id: str):
        """节点被删除的回调"""
        logger.info("Canvas收到节点删除通知: %s", node_id)
        self.node_deleted.emit(node_id)

    def execute_graphics_node(self, node_id: str):
        """执行画布中的单个节点"""
        if self.father and hasattr(self.father, "execute_single_node"):
            self.father.execute_single_node(node_id)

    def highlight_nodes_by_type(self, node_type: str):
        """高亮指定类型的所有节点"""
        from src.views.node_graphics import NodeGraphicsItem

        self._scene.clearSelection()

        for item in self._scene.items():
            if isinstance(item, NodeGraphicsItem):
                curr_type = (
                    item.node_type.value
                    if hasattr(item.node_type, "value")
                    else str(item.node_type)
                )
                if curr_type == node_type:
                    item.setSelected(True)

    def select_nodes_by_ids(self, node_ids: list):
        """选中指定ID的节点"""
        from src.views.node_graphics import NodeGraphicsItem

        self._scene.clearSelection()

        for item in self._scene.items():
            if isinstance(item, NodeGraphicsItem):
                if item.node_id in node_ids:
                    item.setSelected(True)

    def get_all_nodes(self) -> list:
        """获取画布中所有节点 - 使用类型过滤提升性能"""
        from src.views.node_graphics import NodeGraphicsItem

        nodes = []
        # 使用 items() 的类过滤减少遍历开销
        for item in self._scene.items():
            if item.type() == QGraphicsItem.UserType + 1 or isinstance(
                item, NodeGraphicsItem
            ):
                nodes.append(
                    {
                        "node_id": item.node_id,
                        "node_type": item.node_type.value
                        if hasattr(item.node_type, "value")
                        else str(item.node_type),
                        "config": item.config,
                    }
                )

        return nodes

    def get_canvas_state(self) -> dict:
        """获取画布的当前视图状态"""
        transform = self.transform()
        return {
            "scale": transform.m11(),
            "scroll_x": self.horizontalScrollBar().value(),
            "scroll_y": self.verticalScrollBar().value(),
        }

    def set_canvas_state(self, canvas_state: dict):
        """恢复画布的视图状态"""
        if not canvas_state:
            return

        scale = canvas_state.get("scale", 1.0)
        self._current_zoom = scale
        self.setTransform(QTransform().scale(scale, scale))

        scroll_x = canvas_state.get("scroll_x", 0)
        scroll_y = canvas_state.get("scroll_y", 0)
        self.horizontalScrollBar().setValue(scroll_x)
        self.verticalScrollBar().setValue(scroll_y)

    def _update_animations(self):
        """更新动画帧 - 仅更新活跃项，避免遍历全部"""
        # 使用活跃项集合，避免每次遍历整个场景
        active_items = self._active_animation_items
        if not active_items:
            # 回退：仅查找可见区域内的连接线
            visible_rect = self.mapToScene(self.viewport().rect()).boundingRect()
            for item in self._scene.items(visible_rect):
                if hasattr(item, "_animation_offset") and getattr(
                    item, "_is_active", False
                ):
                    active_items.add(item)

        for item in list(active_items):
            try:
                if item.scene() is None:
                    active_items.discard(item)
                    continue
                item._animation_offset = (
                    getattr(item, "_animation_offset", 0) + 2
                ) % 100
                if getattr(item, "_is_active", False):
                    # 使用轻量更新，仅重绘该项的边界矩形
                    item.update()
                else:
                    active_items.discard(item)
            except RuntimeError:
                active_items.discard(item)

    def set_grid_enabled(self, enabled: bool):
        """设置网格显示"""
        self._grid_enabled = enabled
        self.viewport().update()

    def resizeEvent(self, event):
        """窗口大小变化时更新按钮位置"""
        super().resizeEvent(event)
        if hasattr(self, "_auto_layout_btn"):
            try:
                self._auto_layout_btn.update_position()
            except RuntimeError:
                pass

    def auto_layout_nodes(self):
        """自动整理节点布局 - 基于拓扑排序的层次布局算法"""
        from src.views.node_graphics import ConnectionGraphicsItem, NodeGraphicsItem

        # 批量操作：关闭场景更新以提升性能
        self._scene.setItemIndexMethod(QGraphicsScene.NoIndex)

        nodes = []
        connections = []
        for item in self._scene.items():
            if isinstance(item, NodeGraphicsItem):
                nodes.append(item)
            elif isinstance(item, ConnectionGraphicsItem):
                connections.append(item)

        if len(nodes) <= 1:
            self._scene.setItemIndexMethod(QGraphicsScene.BspTreeIndex)
            return

        # 构建邻接表和入度表
        node_ids = {node.node_id: node for node in nodes}
        adjacency = {node.node_id: [] for node in nodes}
        in_degree = {node.node_id: 0 for node in nodes}

        for item in connections:
            if item.start_port and item.end_port:
                from_id = item.start_port.parent_node.node_id
                to_id = item.end_port.parent_node.node_id
                if from_id in adjacency and to_id in adjacency:
                    adjacency[from_id].append(to_id)
                    in_degree[to_id] += 1

        # 拓扑排序（Kahn算法）
        layers = []
        current_layer = [nid for nid, deg in in_degree.items() if deg == 0]
        remaining = set(in_degree.keys()) - set(current_layer)

        while current_layer:
            layers.append(current_layer)
            next_layer = []
            for nid in current_layer:
                for neighbor in adjacency[nid]:
                    in_degree[neighbor] -= 1
                    if in_degree[neighbor] == 0:
                        next_layer.append(neighbor)
                        remaining.discard(neighbor)
            current_layer = next_layer

        # 处理循环依赖（剩余节点）
        if remaining:
            layers.append(list(remaining))

        # 计算布局参数
        node_width = 180
        node_height = 90
        horizontal_gap = 250
        vertical_gap = 150

        # 计算每层的节点位置
        positions = {}
        max_layer_height = 0

        for layer_idx, layer in enumerate(layers):
            layer_width = len(layer) * vertical_gap
            start_y = -layer_width / 2

            for node_idx, node_id in enumerate(layer):
                x = layer_idx * horizontal_gap
                y = start_y + node_idx * vertical_gap
                positions[node_id] = (x, y)

            max_layer_height = max(max_layer_height, len(layer))

        # 应用位置
        for node in nodes:
            if node.node_id in positions:
                x, y = positions[node.node_id]
                # 对齐到网格
                x = round(x / self._grid_size) * self._grid_size
                y = round(y / self._grid_size) * self._grid_size

                node.setPos(QPointF(x, y))

        # 恢复场景索引并更新
        self._scene.setItemIndexMethod(QGraphicsScene.BspTreeIndex)
        self._scene.update()
        self.zoom_changed.emit()

        logger.info("自动整理完成: %d 个节点, %d 层", len(nodes), len(layers))

    def scrollContentsBy(self, dx, dy):
        """滚动时更新按钮位置"""
        super().scrollContentsBy(dx, dy)
        if hasattr(self, "_auto_layout_btn"):
            try:
                self._auto_layout_btn.update_position()
            except RuntimeError:
                pass

    def fit_to_content(self):
        """自适应内容"""
        self.fitInView(self._scene.itemsBoundingRect(), Qt.KeepAspectRatio)
        self._current_zoom = self.transform().m11()

    def _emit_zoom_changed(self):
        """防抖后真正发射缩放变化信号"""
        if self._zoom_auto_save_pending:
            self._zoom_auto_save_pending = False
            self.zoom_changed.emit()

    def _save_zoom_to_config(self):
        """保存当前缩放比例到全局配置"""
        try:
            self._config_manager.set_canvas_zoom(self._current_zoom)
        except Exception as e:
            logger.error("保存缩放比例失败: %s", e)

    def apply_default_zoom(self):
        """应用全局默认缩放比例"""
        try:
            default_zoom = self._config_manager.get_canvas_zoom()
            if default_zoom != 1.0:
                self._current_zoom = default_zoom
                self.setTransform(QTransform().scale(default_zoom, default_zoom))
        except Exception as e:
            logger.error("应用默认缩放比例失败: %s", e)


class WorkflowGraphicsScene(QGraphicsScene):
    """工作流图形场景 - 优化版"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSceneRect(-5000, -5000, 10000, 10000)

        # 设置背景色
        from src.core.theme_manager import ThemeManager

        self.setBackgroundBrush(QColor(ThemeManager.COLORS["background"]))
