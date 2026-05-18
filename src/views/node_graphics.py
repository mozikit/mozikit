"""
节点图形组件
用于在画板上显示和交互的节点
优化特性：
- 更丰富的视觉效果（渐变、阴影、发光）
- 流畅的动画过渡
- 改进的交互反馈
- 更好的视觉层次
"""

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QElapsedTimer,
    QPointF,
    QPropertyAnimation,
    QRectF,
    Qt,
    QTimer,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QCursor,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsRectItem,
    QGraphicsSceneHoverEvent,
    QGraphicsSceneMouseEvent,
    QGraphicsTextItem,
    QMenu,
)

from src.core.log_manager import get_logger
from src.core.theme_manager import ThemeManager

logger = get_logger("node_graphics")


class NodeActionButton(QGraphicsItem):
    """节点操作按钮 - 紧凑版"""

    def __init__(self, text, color, callback, parent=None):
        super().__init__(parent)
        self.text = text
        self.base_color = QColor(color)
        self.callback = callback
        self.width = 32
        self.height = 24
        self.hovered = False
        self.pressed = False
        self.setAcceptHoverEvents(True)
        self.setCursor(QCursor(Qt.PointingHandCursor))

        # 动画相关
        self._scale = 1.0
        self._opacity = 1.0

    def boundingRect(self) -> QRectF:
        padding = 2
        return QRectF(
            -padding, -padding, self.width + padding * 2, self.height + padding * 2
        )

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)

        # 保存 painter 状态
        painter.save()

        # 应用缩放动画
        center = self.boundingRect().center()
        painter.translate(center)
        painter.scale(self._scale, self._scale)
        painter.translate(-center)

        # 绘制阴影
        shadow_rect = QRectF(2, 2, self.width, self.height)
        shadow_color = QColor(0, 0, 0, 40)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(shadow_color))
        painter.drawRoundedRect(shadow_rect, 6, 6)

        # 背景色 - 根据状态调整
        if self.pressed:
            color = self.base_color.darker(120)
        elif self.hovered:
            color = self.base_color.lighter(115)
        else:
            color = self.base_color

        # 绘制渐变背景
        gradient = QLinearGradient(0, 0, 0, self.height)
        gradient.setColorAt(0, color.lighter(110))
        gradient.setColorAt(1, color)

        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(gradient))
        painter.drawRoundedRect(0, 0, self.width, self.height, 6, 6)

        # 文字 - 紧凑版
        painter.setPen(QPen(QColor("white")))
        font = QFont(
            ThemeManager.FONTS["family_primary"].split(",")[0].strip().strip("'"), 10
        )
        font.setWeight(QFont.Weight.Medium)
        painter.setFont(font)
        painter.drawText(
            QRectF(0, 0, self.width, self.height), Qt.AlignCenter, self.text
        )

        painter.restore()

    def hoverEnterEvent(self, event: QGraphicsSceneHoverEvent):
        self.hovered = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event: QGraphicsSceneHoverEvent):
        self.hovered = False
        self.pressed = False
        self.update()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent):
        if event.button() == Qt.LeftButton:
            self.pressed = True
            self.update()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent):
        if event.button() == Qt.LeftButton:
            self.pressed = False
            self.update()
            if self.hovered and self.callback:
                self.callback()
            event.accept()
        else:
            super().mouseReleaseEvent(event)


class NodeGraphicsItem(QGraphicsItem):
    """节点图形项 - 优化版"""

    def __init__(
        self,
        node_id: str,
        node_type,
        title: str = None,
        input_schema: dict = None,
        output_schema: dict = None,
        parent=None,
    ):
        super().__init__(parent)

        self.node_id = node_id
        self.node_type = node_type

        node_type_val = (
            node_type.value if hasattr(node_type, "value") else str(node_type)
        )
        self.title = title or node_type_val
        self.config = {}
        self.input_schema = input_schema or {}
        self.output_schema = output_schema or {}

        # 尺寸配置 - 动态高度
        self.width = 180
        self.header_height = 32
        self.corner_radius = 10
        self.height = self._calculate_body_height()

        # 颜色配置 - 使用统一的 professional 色调（靛蓝色主题）
        # 所有节点类型使用统一颜色，保持专业外观
        self.node_color_normal = QColor(ThemeManager.COLORS["accent"])
        self.node_color_hover = QColor(ThemeManager.COLORS["accent_hover"])
        self.node_color_dark = QColor(ThemeManager.COLORS["accent"])
        self.node_color_glow = QColor(f"{ThemeManager.COLORS['accent']}33")
        self.node_color_shadow = QColor(f"{ThemeManager.COLORS['accent']}88")

        # 标志设置
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsFocusable, True)

        self.setAcceptHoverEvents(True)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        # 状态变量
        self._is_hovered = False
        self._is_pressed = False
        self._shadow_offset = 4
        self._glow_intensity = 0.0

        # 动画相关
        self._hover_animation = None
        self._glow_animation = None

        # 状态
        self.is_executing = False
        self.is_error = False
        self.is_success = False
        self.run_state = "idle"
        self.last_run_summary = ""
        self.run_duration_ms = 0
        self.progress = -1
        self.progress_message = ""

        # 创建UI组件
        self._create_text_items()
        self.input_ports = []
        self.output_ports = []
        self._create_ports()
        self._create_action_buttons()

        # 选中样式
        self.selected_pen = QPen(QColor(ThemeManager.COLORS["accent"]), 3)
        self._update_tooltip()

        # 设置Z值，确保选中时在最上层
        self.setZValue(0)

    def _calculate_body_height(self) -> int:
        """根据端口数量动态计算节点高度"""
        max_ports = max(len(self.input_schema), len(self.output_schema))
        if max_ports <= 0:
            return 90
        port_spacing = 24
        ports_height = max_ports * port_spacing + 16
        return min(250, self.header_height + 28 + ports_height + 20)

    def _create_action_buttons(self):
        """创建操作按钮 - 紧凑版"""
        self.run_btn = NodeActionButton(
            "▶", ThemeManager.COLORS["success"], self.execute_node, self
        )
        self.run_btn.setPos(self.width - 80, -30)
        self.run_btn.hide()

        self.del_btn = NodeActionButton(
            "🗑", ThemeManager.COLORS["error"], self.delete_node, self
        )
        self.del_btn.setPos(self.width - 40, -30)
        self.del_btn.hide()

    def _create_text_items(self):
        """创建文本项 - 优化版"""
        # 标题文本 - 加大字体
        self.title_item = QGraphicsTextItem(self.title, self)
        self.title_item.setDefaultTextColor(QColor(ThemeManager.COLORS["white"]))
        font = QFont(
            ThemeManager.FONTS["family_primary"].split(",")[0].strip().strip("'"), 13
        )
        font.setWeight(QFont.Weight.Bold)
        self.title_item.setFont(font)

        title_width = self.title_item.boundingRect().width()
        self.title_item.setPos(
            (self.width - title_width) / 2,
            (self.header_height - self.title_item.boundingRect().height()) / 2 + 1,
        )

        # 节点类型文本 - 紧凑版
        node_type_val = (
            self.node_type.value
            if hasattr(self.node_type, "value")
            else str(self.node_type)
        )
        self.type_item = QGraphicsTextItem(node_type_val, self)
        self.type_item.setDefaultTextColor(
            QColor(ThemeManager.COLORS["text_secondary"])
        )
        font = QFont(
            ThemeManager.FONTS["family_primary"].split(",")[0].strip().strip("'"), 8
        )
        font.setWeight(QFont.Weight.Normal)
        self.type_item.setFont(font)

        # 居中类型
        type_width = self.type_item.boundingRect().width()
        self.type_item.setPos((self.width - type_width) / 2, self.header_height + 8)

        # 运行时间文本（右下角）
        self.duration_item = QGraphicsTextItem("", self)
        self.duration_item.setDefaultTextColor(
            QColor(ThemeManager.COLORS["text_muted"])
        )
        font = QFont(
            ThemeManager.FONTS["family_primary"].split(",")[0].strip().strip("'"), 12
        )
        font.setWeight(QFont.Weight.Bold)
        self.duration_item.setFont(font)
        self._position_duration_item()

        # 执行中动画文本（左下角，与 duration 分开避免冲突）
        self.running_anim_item = QGraphicsTextItem("", self)
        self.running_anim_item.setDefaultTextColor(
            QColor(ThemeManager.COLORS["text_muted"])
        )
        font = QFont(
            ThemeManager.FONTS["family_primary"].split(",")[0].strip().strip("'"), 12
        )
        font.setWeight(QFont.Weight.Bold)
        self.running_anim_item.setFont(font)
        self._position_running_anim_item()

        # 执行中动画计时器
        self._running_animation_timer = QTimer()
        self._running_animation_timer.timeout.connect(self._update_running_animation)
        self._running_animation_frame = 0
        self._elapsed_timer = QElapsedTimer()

    def _update_tooltip(self):
        """更新节点 tooltip，包含入参/出参信息"""
        lines = [self.title, f"节点ID: {self.node_id}"]

        if self.input_schema:
            lines.append("")
            lines.append("输入:")
            for key, schema in self.input_schema.items():
                if isinstance(schema, dict):
                    ptype = schema.get("type", "any")
                    desc = schema.get("description", "")
                    entry = f"  {key} ({ptype})"
                    if desc:
                        entry += f" - {desc}"
                    lines.append(entry)
                else:
                    lines.append(f"  {key}")

        if self.output_schema:
            lines.append("")
            lines.append("输出:")
            for key, schema in self.output_schema.items():
                if isinstance(schema, dict):
                    ptype = schema.get("type", "any")
                    desc = schema.get("description", "")
                    entry = f"  {key} ({ptype})"
                    if desc:
                        entry += f" - {desc}"
                    lines.append(entry)
                else:
                    lines.append(f"  {key}")

        self.setToolTip("\n".join(lines))

    def _create_ports(self):
        """根据 input_schema/output_schema 动态创建端口"""
        port_radius = 6

        # 输入端口
        if self.input_schema:
            for i, (name, schema) in enumerate(self.input_schema.items()):
                if isinstance(schema, dict):
                    data_type = schema.get("type", "any")
                    from_config = schema.get("from_config")
                else:
                    data_type = "any"
                    from_config = None
                port = PortGraphicsItem(
                    self,
                    PortType.INPUT,
                    QPointF(0, 0),  # 位置在 _update_port_positions 中设置
                    port_radius,
                    port_name=name,
                    data_type=data_type,
                    from_config=from_config,
                    port_index=i,
                )
                self.input_ports.append(port)
        else:
            # 无 schema：单通用端口（向后兼容）
            port = PortGraphicsItem(
                self,
                PortType.INPUT,
                QPointF(0, 0),
                port_radius,
                port_name="input",
                data_type="any",
                port_index=0,
            )
            self.input_ports.append(port)

        # 输出端口
        if self.output_schema:
            for i, (name, schema) in enumerate(self.output_schema.items()):
                if isinstance(schema, dict):
                    data_type = schema.get("type", "any")
                    from_config = schema.get("from_config")
                else:
                    data_type = "any"
                    from_config = None
                port = PortGraphicsItem(
                    self,
                    PortType.OUTPUT,
                    QPointF(0, 0),
                    port_radius,
                    port_name=name,
                    data_type=data_type,
                    from_config=from_config,
                    port_index=i,
                )
                self.output_ports.append(port)
        else:
            # 无 schema：单通用端口（向后兼容）
            port = PortGraphicsItem(
                self,
                PortType.OUTPUT,
                QPointF(0, 0),
                port_radius,
                port_name="output",
                data_type="any",
                port_index=0,
            )
            self.output_ports.append(port)

        self._update_port_positions()

    def _update_port_positions(self):
        """更新所有端口位置"""
        port_spacing = 24
        start_y = self.header_height + 28

        for port in self.input_ports:
            y = start_y + port.port_index * port_spacing
            port.setPos(0, y)

        for port in self.output_ports:
            y = start_y + port.port_index * port_spacing
            port.setPos(self.width, y)

    def get_input_port(self, port_name: str):
        """获取指定名称的输入端口"""
        for p in self.input_ports:
            if p.port_name == port_name:
                return p
        return None

    def get_output_port(self, port_name: str):
        """获取指定名称的输出端口"""
        for p in self.output_ports:
            if p.port_name == port_name:
                return p
        return None

    def boundingRect(self) -> QRectF:
        """返回边界矩形 - 包含发光效果区域"""
        glow_padding = 20
        return QRectF(
            -glow_padding,
            -glow_padding - 40,  # 为按钮留出空间
            self.width + glow_padding * 2,
            self.height + glow_padding * 2 + 40,
        )

    def paint(self, painter: QPainter, option, widget=None):
        """绘制节点 - 优化版，减少渲染状态切换"""
        # 仅在需要时启用抗锯齿
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 合并绘制：阴影 + 发光效果一次性处理
        self._draw_shadow(painter)

        if self._is_hovered and not self.isSelected():
            self._draw_glow(painter)

        if self.isSelected():
            self._draw_selection_glow(painter)

        # 绘制状态发光（错误/成功）
        if self.is_error:
            self._draw_status_glow(painter, ThemeManager.COLORS["error"], 6)
        elif self.is_success:
            self._draw_status_glow(painter, ThemeManager.COLORS["success"], 4)

        # 绘制主体背景和标题栏
        self._draw_body(painter)
        self._draw_header(painter)

        # 绘制状态指示器和进度条
        self._draw_status_indicator(painter)
        if self.run_state == "running" and self.progress >= 0:
            self._draw_progress_bar(painter)

    def _draw_shadow(self, painter: QPainter):
        """绘制阴影 - 单层简化版，性能更好"""
        shadow_color = QColor(self.node_color_shadow)
        shadow_color.setAlpha(25)
        shadow_rect = QRectF(
            self._shadow_offset, self._shadow_offset, self.width, self.height
        )
        painter.setBrush(QBrush(shadow_color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(
            shadow_rect, self.corner_radius + 2, self.corner_radius + 2
        )

    def _draw_glow(self, painter: QPainter):
        """绘制悬停发光效果 - 单层简化版"""
        glow_color = QColor(self.node_color_glow)
        glow_color.setAlpha(40)
        pen = QPen(glow_color, 8)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(
            -4,
            -4,
            self.width + 8,
            self.height + 8,
            self.corner_radius + 2,
            self.corner_radius + 2,
        )

    def _draw_selection_glow(self, painter: QPainter):
        """绘制选中状态发光 - 单层简化版"""
        accent_color = QColor(ThemeManager.COLORS["accent"])
        accent_color.setAlpha(60)
        pen = QPen(accent_color, 6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(
            -6,
            -6,
            self.width + 12,
            self.height + 12,
            self.corner_radius + 3,
            self.corner_radius + 3,
        )

    def _draw_status_glow(self, painter: QPainter, color_name: str, width: int):
        """绘制状态发光（执行中/错误）- 单层简化版"""
        status_color = QColor(color_name)
        status_color.setAlpha(80)
        pen = QPen(status_color, width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(
            2,
            2,
            self.width - 4,
            self.height - 4,
            self.corner_radius - 1,
            self.corner_radius - 1,
        )

    def _draw_body(self, painter: QPainter):
        """绘制节点主体"""
        # 主体背景 - 使用渐变
        body_gradient = QLinearGradient(0, self.header_height, 0, self.height)
        body_gradient.setColorAt(0, QColor(ThemeManager.COLORS["surface"]))
        body_gradient.setColorAt(1, QColor(ThemeManager.COLORS["surface_light"]))

        painter.setPen(QPen(QColor(ThemeManager.COLORS["border"]), 1))
        painter.setBrush(QBrush(body_gradient))
        painter.drawRoundedRect(
            0, 0, self.width, self.height, self.corner_radius, self.corner_radius
        )

    def _draw_header(self, painter: QPainter):
        """绘制标题栏 - 纯色版"""
        # 使用纯色填充，无渐变
        if self.run_state == "running":
            header_color = QColor(ThemeManager.COLORS["warning"])
        elif self._is_hovered:
            header_color = self.node_color_hover
        else:
            header_color = self.node_color_normal

        # 绘制标题栏
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(header_color))
        painter.drawRoundedRect(
            0, 0, self.width, self.header_height, self.corner_radius, self.corner_radius
        )

        # 填充标题栏下方区域
        painter.drawRect(
            0, self.header_height - self.corner_radius, self.width, self.corner_radius
        )

    def _draw_status_indicator(self, painter: QPainter):
        """绘制右上角状态点 - 优化版"""
        if self.run_state == "error":
            main_color = QColor(ThemeManager.COLORS["error"])
        elif self.run_state == "success":
            main_color = QColor(ThemeManager.COLORS["success"])
        else:
            return

        radius = 7
        center_x = self.width - 16
        center_y = 16

        # 外圈边框
        painter.setPen(QPen(QColor(ThemeManager.COLORS["surface"]), 2))
        painter.setBrush(QBrush(main_color))
        painter.drawEllipse(QPointF(center_x, center_y), radius, radius)

        # 内部高光
        highlight_color = QColor(255, 255, 255, 100)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(highlight_color))
        painter.drawEllipse(
            QPointF(center_x - 2, center_y - 2), radius / 2.5, radius / 2.5
        )

    def _draw_progress_bar(self, painter: QPainter):
        """绘制节点内进度条"""
        bar_height = 6
        bar_padding = 10
        bar_y = self.height - bar_height - 4
        bar_width = self.width - bar_padding * 2

        bg_rect = QRectF(bar_padding, bar_y, bar_width, bar_height)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(ThemeManager.COLORS["border"])))
        painter.drawRoundedRect(bg_rect, 3, 3)

        fill_width = bar_width * (self.progress / 100.0)
        if fill_width > 0:
            fill_rect = QRectF(bar_padding, bar_y, fill_width, bar_height)
            progress_color = QColor(ThemeManager.COLORS["warning"])
            painter.setBrush(QBrush(progress_color))
            painter.drawRoundedRect(fill_rect, 3, 3)

    def hoverEnterEvent(self, event):
        self._is_hovered = True
        # 仅在ZValue需要变化时才设置，减少场景重排序
        if self.zValue() < 5:
            self.setZValue(10)
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self._is_hovered = False
        target_z = 5 if self.isSelected() else 0
        if self.zValue() != target_z:
            self.setZValue(target_z)
        self.update()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent):
        """鼠标按下事件"""
        self._is_pressed = True
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        """鼠标释放事件"""
        self._is_pressed = False
        super().mouseReleaseEvent(event)

    def itemChange(self, change, value):
        """处理项目变化 - 减少不必要的更新"""
        if change == QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
            is_selected = value == 1
            target_z = 5 if is_selected else 0
            if self.zValue() != target_z:
                self.setZValue(target_z)

            if hasattr(self, "run_btn"):
                self.run_btn.setVisible(is_selected)
            if hasattr(self, "del_btn"):
                self.del_btn.setVisible(is_selected)
            self.update()
        elif change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            # 节点位置变化时，通知所有连接的连接线更新路径
            # 使用 QTimer.singleShot(0) 延迟到位置实际改变后执行
            QTimer.singleShot(0, self._update_connected_connections)
        return super().itemChange(change, value)

    def _update_connected_connections(self):
        """更新所有与当前节点相连的连接线"""
        for port in self.input_ports + self.output_ports:
            for connection in port.connections:
                if connection.scene():
                    connection._invalidate_cache()
                    connection.update_path()

    def contextMenuEvent(self, event):
        """右键菜单事件 - 优化版"""
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
                padding: 10px 24px;
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

        execute_action = menu.addAction("▶ 执行节点")
        config_action = menu.addAction("⚙ 配置节点")
        menu.addSeparator()
        delete_action = menu.addAction("🗑 删除节点")

        action = menu.exec_(event.screenPos())

        if action == execute_action:
            self.execute_node()
        elif action == config_action:
            self.configure_node()
        elif action == delete_action:
            self.delete_node()

    def execute_node(self):
        """执行节点"""
        logger.info("执行节点: %s", self.node_id)
        scene = self.scene()
        if scene:
            for view in scene.views():
                if hasattr(view, "execute_graphics_node"):
                    view.execute_graphics_node(self.node_id)
                    return

        self.is_executing = True
        self.update()

    def configure_node(self):
        """配置节点"""
        logger.info("配置节点: %s", self.node_id)

    def delete_node(self):
        """删除节点"""
        logger.info("删除节点: %s", self.node_id)

        # 删除所有相关连接
        for port in self.input_ports + self.output_ports:
            for connection in port.connections[:]:  # 复制列表以避免迭代时修改
                scene = connection.scene()
                if scene:
                    scene.removeItem(connection)

        # 从场景中移除节点
        scene = self.scene()
        if scene:
            # 通知Canvas节点被删除
            for view in scene.views():
                if hasattr(view, "on_node_deleted"):
                    view.on_node_deleted(self.node_id)
                    break

            # 从场景移除
            scene.removeItem(self)

    def _position_duration_item(self):
        """将运行时间文本定位到右下角"""
        text_width = self.duration_item.boundingRect().width()
        text_height = self.duration_item.boundingRect().height()
        padding = 6
        x = self.width - text_width - padding
        y = self.height - text_height - padding + 2
        self.duration_item.setPos(x, y)

    def _position_running_anim_item(self):
        """将执行中动画文本定位到左下角"""
        text_width = self.running_anim_item.boundingRect().width()
        text_height = self.running_anim_item.boundingRect().height()
        padding = 6
        x = padding
        y = self.height - text_height - padding + 2
        self.running_anim_item.setPos(x, y)

    def _update_duration_text(self):
        """更新运行时间显示文本"""
        if self.run_duration_ms > 0 and self.run_state in ("success", "error"):
            if self.run_duration_ms < 1000:
                text = f"{self.run_duration_ms}ms"
            else:
                text = f"{self.run_duration_ms / 1000:.2f}s"
            self.duration_item.setPlainText(text)
            self._position_duration_item()
            self.running_anim_item.setPlainText("")
        elif self.run_state == "running":
            if self.progress >= 0:
                self.duration_item.setPlainText(f"{self.progress}%")
                self._position_duration_item()
                if not self._running_animation_timer.isActive():
                    self._elapsed_timer.start()
                    self._running_animation_timer.start(200)
            else:
                self.duration_item.setPlainText("")
                self._start_running_animation()
        else:
            self.duration_item.setPlainText("")
            self.running_anim_item.setPlainText("")
            self._stop_running_animation()

    def _start_running_animation(self):
        """启动执行中动画"""
        if not self._running_animation_timer.isActive():
            self._elapsed_timer.start()
            self._running_animation_timer.start(200)

    def _stop_running_animation(self):
        """停止执行中动画"""
        if self._running_animation_timer.isActive():
            self._running_animation_timer.stop()
        self._running_animation_frame = 0

    def _update_running_animation(self):
        """更新执行中动画帧和已运行时间"""
        if self.run_state != "running":
            self._stop_running_animation()
            return
        frames = ["◐", "◓", "◑", "◒"]
        self._running_animation_frame = (self._running_animation_frame + 1) % len(
            frames
        )
        elapsed_ms = self._elapsed_timer.elapsed()
        if elapsed_ms < 1000:
            time_text = f"{elapsed_ms}ms"
        else:
            time_text = f"{elapsed_ms / 1000:.2f}s"
        self.running_anim_item.setPlainText(
            f"{frames[self._running_animation_frame]} {time_text}"
        )
        self._position_running_anim_item()

    def set_executing(self, executing: bool):
        """设置执行状态"""
        self.is_executing = executing
        if executing:
            self.is_error = False
            self.is_success = False
            self.run_state = "running"
            self.run_duration_ms = 0
            self.progress = -1
            self.progress_message = ""
            self._start_running_animation()
        elif self.run_state == "running":
            self.run_state = "idle"
            self.progress = -1
            self.progress_message = ""
            self._stop_running_animation()
        self._update_duration_text()
        self.update()

    def set_error(self, error: bool, duration_ms: int = 0):
        """设置错误状态"""
        self.is_error = error
        if error:
            self.is_executing = False
            self.is_success = False
            self.run_state = "error"
            self.run_duration_ms = duration_ms
            self.progress = -1
            self.progress_message = ""
        elif self.run_state == "error":
            self.run_state = "idle"
            self.run_duration_ms = 0
        self._update_duration_text()
        self.update()

    def set_success(self, success: bool, duration_ms: int = 0):
        """设置成功状态"""
        self.is_success = success
        if success:
            self.is_executing = False
            self.is_error = False
            self.run_state = "success"
            self.run_duration_ms = duration_ms
            self.progress = -1
            self.progress_message = ""
        elif self.run_state == "success":
            self.run_state = "idle"
            self.run_duration_ms = 0
        self._update_duration_text()
        self.update()

    def set_progress(self, percent: int, message: str = ""):
        """设置节点执行进度"""
        self.progress = max(0, min(100, int(percent)))
        self.progress_message = message
        self._update_duration_text()
        self.update()

    def set_run_summary(self, summary: str):
        """更新节点运行摘要提示"""
        self.last_run_summary = summary.strip()
        tooltip_lines = [self.title, f"节点ID: {self.node_id}"]
        if self.last_run_summary:
            tooltip_lines.extend(["", self.last_run_summary])
        self.setToolTip("\n".join(tooltip_lines))
        self.update()


# 端口类型颜色映射 - 统一使用主题强调色
PORT_TYPE_COLORS = {
    "string": "#5B8DB8",  # accent blue
    "int": "#5B8DB8",  # accent blue
    "float": "#5B8DB8",  # accent blue
    "bool": "#5B8DB8",  # accent blue
    "array": "#5B8DB8",  # accent blue
    "object": "#5B8DB8",  # accent blue
    "connection": "#5B8DB8",  # accent blue
    "any": "#5B8DB8",  # accent blue
}


class PortType:
    """端口类型"""

    INPUT = "input"
    OUTPUT = "output"


class PortGraphicsItem(QGraphicsEllipseItem):
    """端口图形项 - 支持多端口、类型标识、名称标签"""

    def __init__(
        self,
        parent_node: NodeGraphicsItem,
        port_type: str,
        position: QPointF,
        radius: float = 6,
        port_name: str = "",
        data_type: str = "any",
        from_config: str = None,
        port_index: int = 0,
    ):
        super().__init__(
            position.x() - radius,
            position.y() - radius,
            radius * 2,
            radius * 2,
            parent_node,
        )

        self.parent_node = parent_node
        self.port_type = port_type
        self.port_name = port_name
        self.data_type = data_type
        self.from_config = from_config
        self.port_index = port_index
        self.radius = radius
        self._is_hovered = False

        # 设置接受悬停事件
        self.setAcceptHoverEvents(True)
        self.setCursor(QCursor(Qt.PointingHandCursor))

        # 样式
        self._update_appearance()

        # 连接线
        self.connections = []

        # 端口名称标签
        self._create_label()

        # Tooltip
        self._update_port_tooltip()

    def _create_label(self):
        """创建端口名称标签"""
        from PySide6.QtWidgets import QGraphicsSimpleTextItem

        self.label = QGraphicsSimpleTextItem(self)
        type_str = self.data_type if self.data_type != "any" else ""
        label_text = f"{self.port_name}"
        if type_str:
            label_text += f" : {type_str}"
        self.label.setText(label_text)

        font = QFont(
            ThemeManager.FONTS["family_primary"].split(",")[0].strip().strip("'"), 7
        )
        font.setWeight(QFont.Weight.Normal)
        self.label.setFont(font)
        self.label.setBrush(QBrush(QColor(ThemeManager.COLORS["text_muted"])))

        # 定位：输入端口标签在右侧，输出端口标签在左侧
        if self.port_type == PortType.INPUT:
            self.label.setPos(self.radius + 3, -self.label.boundingRect().height() / 2)
        else:
            self.label.setPos(
                -self.radius - self.label.boundingRect().width() - 3,
                -self.label.boundingRect().height() / 2,
            )

    def _update_appearance(self):
        """更新外观 - 根据数据类型着色"""
        type_color_str = PORT_TYPE_COLORS.get(self.data_type, PORT_TYPE_COLORS["any"])

        if self._is_hovered:
            border_color = QColor(ThemeManager.COLORS["accent"])
            fill_color = QColor(type_color_str).lighter(130)
            border_width = 3
        else:
            border_color = QColor(ThemeManager.COLORS["surface"])
            fill_color = QColor(type_color_str)
            border_width = 2

        self.setBrush(QBrush(fill_color))
        self.setPen(QPen(border_color, border_width))

    def _update_port_tooltip(self):
        """构建端口 tooltip"""
        label = "输入" if self.port_type == PortType.INPUT else "输出"
        tip = f"{label}端口: {self.port_name} ({self.data_type})"

        # 查找该端口在 schema 中的描述
        schema = (
            self.parent_node.input_schema
            if self.port_type == PortType.INPUT
            else self.parent_node.output_schema
        )
        if schema and self.port_name in schema:
            port_schema = schema[self.port_name]
            if isinstance(port_schema, dict):
                desc = port_schema.get("description", "")
                if desc:
                    tip += f"\n{desc}"

        self.setToolTip(tip)

    def get_scene_position(self) -> QPointF:
        """获取在场景中的位置"""
        return self.mapToScene(self.rect().center())

    def add_connection(self, connection):
        """添加连接"""
        self.connections.append(connection)

    def remove_connection(self, connection):
        """移除连接"""
        if connection in self.connections:
            self.connections.remove(connection)

    def hoverEnterEvent(self, event):
        """悬停进入"""
        self._is_hovered = True
        self._update_appearance()
        self.setRadius(self.radius + 1)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        """悬停离开"""
        self._is_hovered = False
        self._update_appearance()
        self.setRadius(self.radius)
        super().hoverLeaveEvent(event)

    def setRadius(self, radius: float):
        """设置半径"""
        rect = self.rect()
        center = rect.center()
        self.setRect(
            center.x() - radius,
            center.y() - radius,
            radius * 2,
            radius * 2,
        )


class ConnectionGraphicsItem(QGraphicsItem):
    """连接线图形项 - 支持端口级连接信息"""

    def __init__(self, start_port: PortGraphicsItem, end_port: PortGraphicsItem = None):
        super().__init__()

        self.start_port = start_port
        self.end_port = end_port
        self.end_pos = None

        self._is_hovered = False
        self._is_selected = False
        self._animation_offset = 0.0

        # 路径缓存 - 避免每次重绘都重新计算
        self._cached_path = None
        self._cached_path_key = None

        if self.start_port:
            self.start_port.add_connection(self)
        if self.end_port:
            self.end_port.add_connection(self)

        self.setZValue(-1)
        self.setAcceptHoverEvents(True)
        self.setCursor(QCursor(Qt.PointingHandCursor))

    @property
    def from_port_name(self) -> str:
        """起始端口名称"""
        return self.start_port.port_name if self.start_port else ""

    @property
    def to_port_name(self) -> str:
        """目标端口名称"""
        return self.end_port.port_name if self.end_port else ""

    def set_end_port(self, end_port: PortGraphicsItem):
        if self.end_port:
            self.end_port.remove_connection(self)

        self.end_port = end_port

        if self.end_port:
            self.end_port.add_connection(self)

        self._invalidate_cache()
        self.update_path()

    def set_end_pos(self, pos: QPointF):
        self.end_pos = pos
        self._invalidate_cache()
        self.update_path()

    def _invalidate_cache(self):
        """使路径缓存失效"""
        self._cached_path = None
        self._cached_path_key = None

    def update_path(self):
        self.prepareGeometryChange()
        self.update()

    def boundingRect(self) -> QRectF:
        """返回边界矩形 - 使用场景坐标，确保ViewportUpdate正确计算重绘区域"""
        if not self.start_port:
            return QRectF()

        start = self.start_port.get_scene_position()

        if self.end_port:
            end = self.end_port.get_scene_position()
        elif self.end_pos:
            end = self.end_pos
        else:
            end = start

        # 计算贝塞尔曲线控制点，确保边界矩形能完全覆盖曲线
        dx = abs(end.x() - start.x())
        offset = min(dx * 0.5, 120)

        # 控制点位置
        ctrl1_x = start.x() + offset
        ctrl1_y = start.y()
        ctrl2_x = end.x() - offset
        ctrl2_y = end.y()

        # 收集所有关键点的坐标
        all_x = [start.x(), end.x(), ctrl1_x, ctrl2_x]
        all_y = [start.y(), end.y(), ctrl1_y, ctrl2_y]

        # 计算包含所有点的边界矩形
        min_x, max_x = min(all_x), max(all_x)
        min_y, max_y = min(all_y), max(all_y)

        rect = QRectF(min_x, min_y, max_x - min_x, max_y - min_y)

        # 添加足够的padding以覆盖曲线弯曲、发光效果和动画点
        padding_x = max(30, offset * 0.3 + 20)
        padding_y = max(50, abs(end.y() - start.y()) * 0.5 + 30)

        return rect.adjusted(-padding_x, -padding_y, padding_x, padding_y)

    def _get_path(self) -> QPainterPath:
        """获取缓存的路径，仅在端点变化时重新计算"""
        if not self.start_port:
            return QPainterPath()

        start = self.start_port.get_scene_position()

        if self.end_port:
            end = self.end_port.get_scene_position()
        elif self.end_pos:
            end = self.end_pos
        else:
            return QPainterPath()

        # 使用端点坐标作为缓存键（降低精度避免微小抖动导致频繁重建）
        path_key = (
            round(start.x(), 0),
            round(start.y(), 0),
            round(end.x(), 0),
            round(end.y(), 0),
        )

        if self._cached_path is None or self._cached_path_key != path_key:
            self._cached_path = self._create_curve_path(start, end)
            self._cached_path_key = path_key

        return self._cached_path

    def paint(self, painter: QPainter, option, widget=None):
        if not self.start_port:
            return

        path = self._get_path()
        if path.isEmpty():
            return

        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 确定颜色
        if self._is_hovered or self._is_selected:
            pen_color = QColor(ThemeManager.COLORS["accent"])
            pen_width = 3.5
        else:
            pen_color = QColor(ThemeManager.COLORS["accent"])
            pen_width = 2.5

        # 绘制发光效果（仅悬停时）
        if self._is_hovered:
            self._draw_glow(painter, path, pen_color)

        # 绘制主线
        pen = QPen(pen_color, pen_width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

        # 绘制流动动画效果（如果正在执行）
        if getattr(self, "_is_active", False):
            self._draw_flow_animation(painter, path)

        # 悬停或选中时显示端口名称标签
        if (
            (self._is_hovered or self._is_selected)
            and self.start_port
            and self.end_port
        ):
            self._draw_midpoint_label(painter, path)

    def _create_curve_path(self, start: QPointF, end: QPointF) -> QPainterPath:
        """创建贝塞尔曲线路径"""
        dx = abs(end.x() - start.x())
        offset = min(dx * 0.5, 120)

        ctrl1 = QPointF(start.x() + offset, start.y())
        ctrl2 = QPointF(end.x() - offset, end.y())

        path = QPainterPath()
        path.moveTo(start)
        path.cubicTo(ctrl1, ctrl2, end)

        return path

    def _draw_glow(self, painter: QPainter, path: QPainterPath, color: QColor):
        """绘制发光效果 - 简化为单层"""
        glow_color = QColor(color)
        glow_color.setAlpha(30)
        glow_pen = QPen(glow_color, 6)
        glow_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(glow_pen)
        painter.drawPath(path)

    def _draw_flow_animation(self, painter: QPainter, path: QPainterPath):
        """绘制流动动画效果 - 优化版"""
        length = path.length()
        if length < 1:
            return

        # 限制流动点数量，减少绘制开销
        num_dots = min(3, max(1, int(length / 80)))
        for i in range(num_dots):
            offset = (self._animation_offset + i * (length / num_dots)) % length
            percent = path.percentAtLength(offset)
            point = path.pointAtPercent(percent)

            dot_color = QColor(ThemeManager.COLORS["accent"])
            dot_color.setAlpha(180 - i * 40)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(dot_color))
            dot_radius = max(2, 4 - i)
            painter.drawEllipse(point, dot_radius, dot_radius)

    def _draw_midpoint_label(self, painter: QPainter, path: QPainterPath):
        """在连接线中点绘制端口名称标签"""
        length = path.length()
        if length < 1:
            return
        mid_point = path.pointAtPercent(path.percentAtLength(length / 2))

        label_text = f"{self.from_port_name} -> {self.to_port_name}"
        font = QFont(
            ThemeManager.FONTS["family_primary"].split(",")[0].strip().strip("'"), 8
        )
        font.setWeight(QFont.Weight.Normal)
        painter.setFont(font)

        fm = QFontMetrics(font)
        text_width = fm.horizontalAdvance(label_text)
        text_height = fm.height()

        # 背景
        bg_rect = QRectF(
            mid_point.x() - text_width / 2 - 4,
            mid_point.y() - text_height / 2 - 2,
            text_width + 8,
            text_height + 4,
        )
        bg_color = QColor(ThemeManager.COLORS["surface"])
        bg_color.setAlpha(220)
        painter.setPen(QPen(QColor(ThemeManager.COLORS["border"]), 1))
        painter.setBrush(QBrush(bg_color))
        painter.drawRoundedRect(bg_rect, 4, 4)

        # 文字
        painter.setPen(QPen(QColor(ThemeManager.COLORS["text_secondary"])))
        painter.drawText(bg_rect, Qt.AlignCenter, label_text)

    def hoverEnterEvent(self, event):
        self._is_hovered = True
        self.setZValue(0)
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self._is_hovered = False
        self.setZValue(-1)
        self.update()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent):
        if event.button() == Qt.LeftButton:
            self._is_selected = not self._is_selected
            self.update()
            event.accept()
        else:
            super().mousePressEvent(event)
