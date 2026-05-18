"""
节点属性面板
用于编辑选中节点的属性
"""
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QFormLayout, QLabel,
                               QLineEdit, QComboBox, QTextEdit, QPushButton,
                               QScrollArea, QGroupBox, QHBoxLayout, QApplication,
                               QMessageBox, QFileDialog, QCheckBox, QSpinBox,
                               QDoubleSpinBox, QCompleter)
from PySide6.QtCore import Qt, Signal, QTimer, QThread
from PySide6.QtGui import QFont

from src.core.node_extension_registries import editors
from src.core.playwright_node_utils import (
    build_playwright_config_schema,
    build_playwright_default_config,
    extract_playwright_params,
)
from src.core.theme_manager import ThemeManager
from src.core.node_registry import get_registry, NODE_SOURCE_INFO, NodeSource
from src.core.log_manager import get_logger
from src.dialogs.source_code_dialog import SourceCodeDialog

logger = get_logger("node_properties")


class VarRefComboBox(QComboBox):
    """变量引用下拉框：支持从上游节点选择输出变量"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.InsertAtBottom)
        self.setToolTip("选择上游节点的输出变量，或手动输入变量名")

    def set_available_vars(self, vars_list: list):
        """设置可用的变量列表，按节点分组"""
        current_text = self.currentText()
        self.clear()

        if not vars_list:
            self.addItem("(无可用变量)")
            self.setItemData(0, False, Qt.UserRole)
            return

        # 添加分组标题和变量选项
        for item in vars_list:
            if item.get("is_header"):
                idx = self.count()
                self.addItem(f"  {item['label']}")
                # 分组标题不可选
                model = self.model()
                if model:
                    model.setData(model.index(idx, 0), False, Qt.UserRole + 1)
            else:
                display = f"    {item['var_name']}"
                if item.get("var_type"):
                    display += f"  ({item['var_type']})"
                self.addItem(display, item["var_name"])

        # 恢复之前输入的值（如果不在列表中也会保留）
        if current_text:
            idx = self.findData(current_text)
            if idx >= 0:
                self.setCurrentIndex(idx)
            else:
                self.setEditText(current_text)

    def get_var_name(self) -> str:
        """获取当前选中的变量名（原始值，非显示文本）"""
        data = self.currentData()
        if data:
            return data
        return self.currentText().strip()


class _SaveSourceCodeWorker(QThread):
    """在后台线程中保存节点源代码，避免阻塞UI"""

    saved = Signal()
    save_failed = Signal()
    validation_failed = Signal(str)

    def __init__(self, registry, node_type: str, source_code: str, parent=None):
        super().__init__(parent)
        self.registry = registry
        self.node_type = node_type
        self.source_code = source_code

    def run(self):
        try:
            if self.registry.save_display_source(self.node_type, self.source_code):
                self.saved.emit()
            else:
                self.save_failed.emit()
        except ValueError as e:
            self.validation_failed.emit(str(e))
        except Exception as e:
            self.validation_failed.emit(str(e))


class NodePropertiesWidget(QWidget):
    """节点属性面板"""

    # 信号：属性已更新
    properties_updated = Signal(str, dict)  # node_id, config

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_node_id = None
        self.current_node_type = None
        self.current_config = {}
        self._current_node_type_for_source = None
        self._current_node_source_is_playwright = False
        self._pending_load = None  # 待加载的节点数据
        self._load_timer = QTimer(self)
        self._load_timer.setSingleShot(True)
        self._load_timer.timeout.connect(self._do_load_node_properties)
        self._setup_ui()
    
    def _setup_ui(self):
        """设置UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 滚动区域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"""
            QScrollArea {{
                border: none;
                background-color: {ThemeManager.COLORS['background']};
            }}
        """)
        
        # 内容容器 - 紧凑版
        self.content_widget = QWidget()
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(8, 8, 8, 8)
        self.content_layout.setSpacing(8)
        
        # 默认提示
        self.empty_label = QLabel("请选择一个节点")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setStyleSheet(f"color: {ThemeManager.COLORS['text_secondary']}; font-size: 10pt; padding: 16px;")
        self.content_layout.addWidget(self.empty_label)
        
        self.content_layout.addStretch()
        
        scroll.setWidget(self.content_widget)
        layout.addWidget(scroll)
        
        # 应用通用样式
        combined_style = (
            ThemeManager.get_input_style() + "\n" +
            ThemeManager.get_button_style("primary") + "\n" +
            ThemeManager.get_group_box_style()
        )
        # Add label color
        combined_style += f"\nQLabel {{ color: {ThemeManager.COLORS['text']}; }}"
        
        self.setStyleSheet(combined_style)
    
    def _clear_content_immediately(self):
        """立即清空内容区域的所有控件"""
        # 强制停止计时器
        self._load_timer.stop()
        
        # 确保布局中的所有控件都被移除并销毁
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            if item.widget():
                widget = item.widget()
                widget.setParent(None)
                widget.deleteLater()
            elif item.layout():
                # 清除子布局
                self._clear_layout(item.layout())
    
    def _clear_layout(self, layout):
        """递归清除布局"""
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())
    
    def clear_properties(self):
        """清空属性面板"""
        self._clear_content_immediately()
        
        # 显示空提示 - 紧凑版
        self.empty_label = QLabel("请选择一个节点")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setStyleSheet(f"color: {ThemeManager.COLORS['text_secondary']}; font-size: 10pt; padding: 16px;")
        self.content_layout.addWidget(self.empty_label)
        self.content_layout.addStretch()
        
        self.current_node_id = None
        self.current_node_type = None
        self.current_config = {}
        self._current_node_type_for_source = None
        self._current_node_source_is_playwright = False
        self.config_widgets = {}
    
    def load_node_properties(self, node_id: str, node_type, config: dict):
        """加载节点属性（优化响应速度）"""
        # 停止之前的计时器
        self._load_timer.stop()
        
        # 保存待加载的数据
        self._pending_load = (node_id, node_type, config)
        
        # 极短延迟（10ms）用于防抖，减少肉眼可察觉的延迟
        self._load_timer.start(10)
    
    def _do_load_node_properties(self):
        """实际执行加载节点属性"""
        if not self._pending_load:
            return
        
        node_id, node_type, config = self._pending_load
        self._pending_load = None
        
        # 强制清除所有现有内容
        self._clear_content_immediately()
        
        self.current_node_id = node_id
        self.current_node_type = node_type
        self.current_config = dict(config or {})

        # 清空配置控件字典
        self.config_widgets = {}
        
        # 节点信息组
        info_group = QGroupBox("节点信息")
        info_layout = QFormLayout()
        
        # 节点ID
        id_label = QLabel(node_id)
        id_label.setStyleSheet(f"color: {ThemeManager.COLORS['text_secondary']};")
        info_layout.addRow("节点ID:", id_label)
        
        # 节点类型
        node_type_val = node_type.value if hasattr(node_type, "value") else str(node_type)
        type_label = QLabel(node_type_val)
        type_label.setStyleSheet(f"color: {ThemeManager.COLORS['text_secondary']};")
        info_layout.addRow("节点类型:", type_label)
        
        # 节点来源
        registry = get_registry()
        node_info = registry.get_node_info(node_type_val)
        source_info = node_info.get('source_info', NODE_SOURCE_INFO[NodeSource.OFFICIAL])
        source_label = QLabel(source_info['name'])
        source_label.setStyleSheet(f"color: {source_info['color']}; font-weight: bold;")
        info_layout.addRow("来源:", source_label)
        
        info_group.setLayout(info_layout)
        self.content_layout.addWidget(info_group)
        
        # 根据节点类型创建配置表单
        config_group = QGroupBox("节点配置")
        config_layout = QFormLayout()
        
        self.config_widgets = {}
        registry = get_registry()
        node_type_val = node_type.value if hasattr(node_type, "value") else str(node_type)
        node_def = registry.get_node(node_type_val)
        
        has_editor = editors.has(node_type_val)

        if has_editor:
            self.current_config = build_playwright_default_config(self.current_config)
            self._create_dynamic_schema_form(
                config_layout,
                self.current_config.get("param_schema") or node_def.config_schema,
                self.current_config,
            )
        elif node_def and node_def.config_schema:
            self._create_dynamic_schema_form(config_layout, node_def.config_schema, config)
        else:
            empty_label = QLabel("该节点没有可编辑配置")
            empty_label.setStyleSheet(f"color: {ThemeManager.COLORS['text_secondary']};")
            config_layout.addRow(empty_label)
        
        config_group.setLayout(config_layout)
        self.content_layout.addWidget(config_group)

        # ── 安全警告区域 ──
        safety_warning = node_def.metadata.get("safety_warning") if node_def else None
        if safety_warning:
            self._create_safety_warning_section(safety_warning, config)

        # 按钮组
        button_layout = QHBoxLayout()
        
        apply_btn = QPushButton("应用配置")
        apply_btn.clicked.connect(self._apply_changes)
        button_layout.addWidget(apply_btn)
        
        # 针对外部节点或自定义节点的额外操作
        if node_def and node_def.source in [NodeSource.CUSTOM, NodeSource.GITHUB]:
            if node_def.source == NodeSource.CUSTOM:
                export_btn = QPushButton("📦 导出节点")
                export_btn.setStyleSheet(ThemeManager.get_button_style("secondary"))
                export_btn.clicked.connect(self._export_custom_node)
                button_layout.addWidget(export_btn)
            
            delete_btn = QPushButton("🗑️ 删除节点")
            delete_btn.setStyleSheet(ThemeManager.get_button_style("danger") if hasattr(ThemeManager, "get_button_style") else "")
            delete_btn.clicked.connect(self._delete_external_node)
            button_layout.addWidget(delete_btn)
        
        self.content_layout.addLayout(button_layout)

        if node_def and node_def.examples:
            self._create_examples_section(node_def.examples)

        if editors.has(node_type_val):
            self._create_playwright_script_section(node_def)
        else:
            # 源代码区域（可折叠）
            node_type_val = node_type.value if hasattr(node_type, "value") else str(node_type)
            self._create_source_code_section(node_type_val, node_def)
        
        self.content_layout.addStretch()
    
    def _create_examples_section(self, examples: list):
        """创建使用示例区域"""
        examples_group = QGroupBox("使用示例")
        examples_layout = QVBoxLayout()
        examples_layout.setSpacing(6)

        for i, example in enumerate(examples):
            title = example.get("title", f"示例 {i + 1}")
            description = example.get("description", "")
            config_data = example.get("config", {})

            title_label = QLabel(f"{'📌' if i == 0 else '💡'} {title}")
            title_label.setStyleSheet(
                f"color: {ThemeManager.COLORS['text']}; font-weight: bold; font-size: 10pt;"
            )
            examples_layout.addWidget(title_label)

            if description:
                desc_label = QLabel(description)
                desc_label.setWordWrap(True)
                desc_label.setStyleSheet(
                    f"color: {ThemeManager.COLORS['text_secondary']}; font-size: 9pt;"
                )
                examples_layout.addWidget(desc_label)

            if config_data:
                config_text = QTextEdit()
                config_text.setReadOnly(True)
                config_text.setMaximumHeight(80)
                import json
                config_text.setPlainText(json.dumps(config_data, ensure_ascii=False, indent=2))
                config_text.setStyleSheet(
                    f"background-color: {ThemeManager.COLORS['background']}; "
                    f"color: {ThemeManager.COLORS['text_secondary']}; "
                    f"border: 1px solid {ThemeManager.COLORS.get('border', '#444')}; "
                    f"border-radius: 3px; font-family: Consolas, monospace; font-size: 9pt;"
                )
                examples_layout.addWidget(config_text)

        examples_group.setLayout(examples_layout)
        self.content_layout.addWidget(examples_group)

    def _create_safety_warning_section(self, safety_warning: dict, config: dict):
        """创建安全警告区域，显示风险描述和确认按钮"""
        risk_level = safety_warning.get("risk_level", "unknown")
        risks = safety_warning.get("risks", [])

        # 风险级别对应的颜色和标签
        risk_styles = {
            "high": {"color": "#F44336", "label": "高风险", "icon": "🔴"},
            "medium": {"color": "#FF9800", "label": "中风险", "icon": "🟠"},
            "low": {"color": "#FFC107", "label": "低风险", "icon": "🟡"},
            "unknown": {"color": "#9E9E9E", "label": "未知风险", "icon": "⚪"},
        }
        style_info = risk_styles.get(risk_level, risk_styles["unknown"])

        safety_group = QGroupBox(f"{style_info['icon']} 安全警告")
        safety_group.setStyleSheet(
            f"QGroupBox {{ color: {style_info['color']}; font-weight: bold; border: 1px solid {style_info['color']}; border-radius: 4px; margin-top: 8px; padding-top: 16px; }}"
            f"QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 5px; }}"
        )
        safety_layout = QVBoxLayout()
        safety_layout.setSpacing(4)

        # 风险级别标签
        level_label = QLabel(f"风险级别: {style_info['label']}")
        level_label.setStyleSheet(f"color: {style_info['color']}; font-weight: bold;")
        safety_layout.addWidget(level_label)

        # 风险描述列表
        for risk in risks:
            risk_label = QLabel(f"  • {risk}")
            risk_label.setWordWrap(True)
            risk_label.setStyleSheet(f"color: {ThemeManager.COLORS['text']};")
            safety_layout.addWidget(risk_label)

        # 确认状态或确认按钮
        is_confirmed = config.get("_safety_confirmed", False)
        if is_confirmed:
            confirmed_label = QLabel("✓ 已确认安全风险，节点可正常执行")
            confirmed_label.setStyleSheet(
                f"color: #4CAF50; font-weight: bold; padding: 4px;"
            )
            safety_layout.addWidget(confirmed_label)
        else:
            warning_note = QLabel("此节点在工作流执行时将被跳过，直到您确认风险。")
            warning_note.setWordWrap(True)
            warning_note.setStyleSheet(
                f"color: {style_info['color']}; font-size: 9pt; padding: 2px;"
            )
            safety_layout.addWidget(warning_note)

            confirm_btn = QPushButton("我已了解风险，确认执行")
            confirm_btn.setStyleSheet(ThemeManager.get_button_style("danger") if hasattr(ThemeManager, "get_button_style") else "")
            confirm_btn.setToolTip("确认后此节点可在工作流中正常执行")
            confirm_btn.clicked.connect(self._confirm_safety_warning)
            safety_layout.addWidget(confirm_btn)

        safety_group.setLayout(safety_layout)
        self.content_layout.addWidget(safety_group)

    def _confirm_safety_warning(self):
        """确认安全警告，设置 _safety_confirmed 标记并应用配置"""
        if self.current_node_id:
            self.current_config["_safety_confirmed"] = True
            self._apply_changes()

    def _get_available_vars(self) -> list:
        """扫描当前工作流中所有上游节点，收集可用的输出变量列表"""
        available_vars = []

        # 通过 parent 链找到 WorkflowTabWidget
        workflow_tab = None
        widget = self.parent()
        while widget:
            if hasattr(widget, 'nodes') and hasattr(widget, 'connections'):
                workflow_tab = widget
                break
            widget = widget.parent() if hasattr(widget, 'parent') else None

        if not workflow_tab or not self.current_node_id:
            return available_vars

        # 找到当前节点的所有上游节点
        upstream_nodes = set()
        stack = [self.current_node_id]
        visited = set()

        while stack:
            node_id = stack.pop()
            if node_id in visited:
                continue
            visited.add(node_id)

            for from_id, to_id in workflow_tab.connections:
                if to_id == node_id and from_id not in visited:
                    upstream_nodes.add(from_id)
                    stack.append(from_id)

        if not upstream_nodes:
            return available_vars

        # 收集每个上游节点的输出变量
        for upstream_id in sorted(upstream_nodes):
            node_item = workflow_tab.nodes.get(upstream_id)
            if not node_item:
                continue

            node_config = getattr(node_item, 'config', {}) or {}
            node_type_val = (
                node_item.node_type.value
                if hasattr(node_item.node_type, 'value')
                else str(node_item.node_type)
            )

            # 添加节点分组标题
            available_vars.append({
                "is_header": True,
                "label": f"{upstream_id} ({node_type_val})",
            })

            # 收集该节点的输出变量
            node_vars = []

            # 1. output_var / text_var / sql_var 等显式输出变量
            for key, value in node_config.items():
                if key.endswith('_var') and key != 'output_var':
                    continue
                if key == 'output_var' and value:
                    node_vars.append({
                        "var_name": str(value),
                        "var_type": "output",
                        "source_node": upstream_id,
                    })

            # 2. 从注册表的 output_schema 推导输出变量，兜底扫描 config
            node_def = registry.get_node(node_type_val)
            if node_def and node_def.output_schema:
                for var_name, var_schema in node_def.output_schema.items():
                    var_type = "any"
                    if isinstance(var_schema, dict):
                        var_type = var_schema.get("type", "any")
                    node_vars.append({
                        "var_name": str(var_name),
                        "var_type": var_type,
                        "source_node": upstream_id,
                    })
            else:
                # 兜底：从 config 中推导已知的输出变量字段
                # variable_assign 节点的输出是 variable_name 指向的变量
                if node_type_val == 'variable_assign':
                    var_name = node_config.get('variable_name')
                    if var_name:
                        node_vars.append({
                            "var_name": str(var_name),
                            "var_type": node_config.get('value_type', 'str'),
                            "source_node": upstream_id,
                        })
                # sqlite_connect 节点输出 connection_name 变量
                elif node_type_val == 'sqlite_connect':
                    conn_name = node_config.get('connection_name', 'db_conn')
                    node_vars.append({
                        "var_name": str(conn_name),
                        "var_type": "connection",
                        "source_node": upstream_id,
                    })
                # 其他节点：从 config 中找 output_var 字段
                else:
                    for key in ('output_var',):
                        val = node_config.get(key)
                        if val and isinstance(val, str) and val.strip():
                            node_vars.append({
                                "var_name": str(val),
                                "var_type": "any",
                                "source_node": upstream_id,
                            })

            # 去重并添加到总列表
            seen = set()
            for var in node_vars:
                if var["var_name"] not in seen:
                    seen.add(var["var_name"])
                    available_vars.append(var)

        return available_vars

    def _create_var_ref_widget(self, default_value: str) -> VarRefComboBox:
        """创建变量引用选择器，并自动填充上游可用变量"""
        widget = VarRefComboBox()
        available_vars = self._get_available_vars()
        widget.set_available_vars(available_vars)
        if default_value:
            widget.setEditText(default_value)
        return widget

    def _create_dynamic_schema_form(self, layout, config_schema: dict, config: dict):
        """根据 config_schema 动态创建配置表单"""
        for key, field_schema in config_schema.items():
            if not isinstance(field_schema, dict):
                continue

            label = field_schema.get("label", key)
            field_type = field_schema.get("type", "string")
            default_value = config.get(key, field_schema.get("default"))

            # 检测字段名是否以 _var 结尾，如果是则使用变量选择器
            is_var_ref = key.endswith('_var') and key != 'output_var'

            if is_var_ref:
                widget = self._create_var_ref_widget("" if default_value is None else str(default_value))
            elif field_type == "text":
                widget = QTextEdit()
                widget.setMaximumHeight(100)
                widget.setPlainText("" if default_value is None else str(default_value))
            elif field_type == "enum":
                widget = QComboBox()
                options = field_schema.get("options", [])
                widget.addItems([str(option) for option in options])
                if default_value is not None:
                    widget.setCurrentText(str(default_value))
            elif field_type == "bool":
                widget = QCheckBox()
                if isinstance(default_value, str):
                    checked = default_value.lower() in ("true", "1", "yes", "on")
                else:
                    checked = bool(default_value)
                widget.setChecked(checked)
            elif field_type == "json":
                widget = QTextEdit()
                widget.setMaximumHeight(100)
                if default_value in (None, ""):
                    widget.setPlainText("")
                elif isinstance(default_value, str):
                    widget.setPlainText(default_value)
                else:
                    import json

                    widget.setPlainText(json.dumps(default_value, ensure_ascii=False, indent=2))
            elif field_type == "int":
                widget = QSpinBox()
                widget.setRange(-999999999, 999999999)
                widget.setValue(int(default_value or 0))
            elif field_type == "float":
                widget = QDoubleSpinBox()
                widget.setRange(-999999999.0, 999999999.0)
                widget.setDecimals(6)
                widget.setValue(float(default_value or 0))
            else:
                widget = QLineEdit()
                widget.setText("" if default_value is None else str(default_value))

            placeholder = field_schema.get("placeholder", "")
            if placeholder and hasattr(widget, "setPlaceholderText"):
                widget.setPlaceholderText(placeholder)

            self.config_widgets[key] = widget
            layout.addRow(f"{label}:", widget)
    
    def _apply_changes(self):
        """应用更改"""
        self.sync_current_config()

    def _collect_current_config(self) -> dict:
        """收集当前表单中的配置值"""
        config = dict(self.current_config or {})

        for key, widget in self.config_widgets.items():
            if isinstance(widget, VarRefComboBox):
                config[key] = widget.get_var_name()
            elif isinstance(widget, QLineEdit):
                config[key] = widget.text()
            elif isinstance(widget, QTextEdit):
                field_type = self._get_field_type_for_widget(key)
                text_value = widget.toPlainText()
                if field_type == "json" or key == "actions":
                    import json

                    config[key] = json.loads(text_value) if text_value.strip() else {}
                else:
                    config[key] = text_value
            elif isinstance(widget, QComboBox):
                config[key] = widget.currentText()
            elif isinstance(widget, QCheckBox):
                config[key] = widget.isChecked()
            elif isinstance(widget, QSpinBox):
                config[key] = widget.value()
            elif isinstance(widget, QDoubleSpinBox):
                config[key] = widget.value()

        return config

    def _create_playwright_script_section(self, node_def):
        """为 Playwright 节点创建脚本操作区"""
        group = QGroupBox("Playwright 脚本")
        layout = QVBoxLayout(group)

        script_source = str(self.current_config.get("script_source", "") or "")
        param_names = extract_playwright_params(script_source)
        status_text = "已配置脚本" if script_source.strip() else "未配置脚本"
        summary = QLabel(
            f"{status_text}，识别到 {len(param_names)} 个业务参数。"
        )
        summary.setWordWrap(True)
        summary.setStyleSheet(f"color: {ThemeManager.COLORS['text_secondary']};")
        layout.addWidget(summary)

        button_layout = QHBoxLayout()

        edit_btn = QPushButton("📝 编辑脚本")
        edit_btn.setStyleSheet(ThemeManager.get_button_style("primary"))
        edit_btn.clicked.connect(self._open_playwright_script_dialog)
        button_layout.addWidget(edit_btn)

        rescan_btn = QPushButton("🔄 重新扫描参数")
        rescan_btn.setStyleSheet(ThemeManager.get_button_style("secondary"))
        rescan_btn.clicked.connect(self._rescan_playwright_inline_script)
        button_layout.addWidget(rescan_btn)

        clear_btn = QPushButton("🧹 清空脚本")
        clear_btn.setStyleSheet(ThemeManager.get_button_style("secondary"))
        clear_btn.clicked.connect(self._clear_playwright_script)
        button_layout.addWidget(clear_btn)

        button_layout.addStretch()
        layout.addLayout(button_layout)

        # ── 下载设置概览（简洁显示状态） ──
        auto_dl = self.current_config.get("playwright_auto_download", True)
        dl_dir = str(self.current_config.get("playwright_download_dir", "") or "").strip()
        timeout = self.current_config.get("playwright_timeout_seconds", 120)

        dl_summary = QLabel(
            f"📥 下载: {'开启' if auto_dl else '关闭'}  "
            f"| 超时: {timeout}秒"
            + (f"  | 目录: {dl_dir}" if dl_dir else "")
        )
        dl_summary.setWordWrap(True)
        dl_summary.setStyleSheet(
            f"color: {ThemeManager.COLORS['text_secondary']}; font-size: 9pt; padding: 4px 0;"
        )
        layout.addWidget(dl_summary)

        self.content_layout.addWidget(group)

    def sync_current_config(self) -> bool:
        """将当前属性面板中的编辑值同步回节点"""
        if not self.current_node_id:
            return False

        # 统一走 properties_updated，避免“应用配置”和“保存前同步”出现两套写回逻辑。
        config = self._collect_current_config()
        self.properties_updated.emit(self.current_node_id, config)
        logger.info("节点 %s 配置已更新: %s", self.current_node_id, config)
        return True
    
    def _get_field_type_for_widget(self, key: str) -> str:
        """获取当前字段类型"""
        if isinstance(self.current_config.get("param_schema"), dict):
            field_schema = self.current_config["param_schema"].get(key, {})
            if isinstance(field_schema, dict):
                return field_schema.get("type", "string")

        registry = get_registry()
        node_def = registry.get_node(self.current_node_type.value if hasattr(self.current_node_type, "value") else self.current_node_type)
        if node_def and isinstance(node_def.config_schema, dict):
            field_schema = node_def.config_schema.get(key, {})
            if isinstance(field_schema, dict):
                return field_schema.get("type", "string")
        return "string"

    def _create_source_code_section(self, node_type: str, node_def=None):
        """创建源代码展示区域（点击打开弹窗）"""
        has_editor = editors.has(node_type)

        # 加载源代码
        registry = get_registry()
        source_code = registry.get_display_source_code(node_type)
        self._current_source_code = source_code
        self._current_node_type_for_source = node_type
        self._current_node_source_is_playwright = has_editor
        
        # 打开弹窗按钮
        open_btn = QPushButton("📝 编辑 Playwright 脚本" if has_editor else "📝 查看源代码")
        open_btn.setStyleSheet(ThemeManager.get_button_style("secondary"))
        open_btn.clicked.connect(self._open_source_code_dialog)
        
        self.content_layout.addWidget(open_btn)

    def _open_source_code_dialog(self):
        """打开源代码编辑弹窗"""
        node_def = None
        if self._current_node_type_for_source:
            registry = get_registry()
            node_def = registry.get_node(self._current_node_type_for_source)
        
        node_name = node_def.name if node_def else self._current_node_type_for_source
        
        dialog = SourceCodeDialog(
            source_code=self._current_source_code,
            node_type=self._current_node_type_for_source,
            node_name=node_name,
            is_playwright=self._current_node_source_is_playwright,
            parent=self,
        )
        
        if dialog.exec():
            # 用户点击了保存
            if dialog.is_modified():
                new_source = dialog.get_source_code()
                self._save_source_code_from_dialog(new_source)

    def _save_source_code_from_dialog(self, source_code: str):
        """从弹窗保存源代码（异步，不阻塞UI）"""
        registry = get_registry()
        node_type = self._current_node_type_for_source
        is_playwright = self._current_node_source_is_playwright

        self._source_save_worker = _SaveSourceCodeWorker(registry, node_type, source_code, parent=self)
        self._source_save_worker.saved.connect(
            lambda: self._on_source_code_saved(source_code, is_playwright)
        )
        self._source_save_worker.save_failed.connect(self._on_source_code_save_failed)
        self._source_save_worker.validation_failed.connect(self._on_source_code_validation_failed)
        self._source_save_worker.start()

    def _on_source_code_saved(self, source_code: str, is_playwright: bool):
        """源代码保存成功回调（主线程）"""
        self._current_source_code = source_code
        if is_playwright:
            self._reload_current_node_properties()
            QMessageBox.information(
                self,
                "保存成功",
                "Playwright 脚本已保存，并已根据占位符刷新参数。",
            )
        else:
            QMessageBox.information(self, "保存成功", "源代码已保存！\n\n节点将在下次使用时应用新代码。")
        self._source_save_worker = None

    def _on_source_code_save_failed(self):
        """源代码保存失败回调（主线程）"""
        QMessageBox.warning(self, "保存失败", "无法保存源代码，请重试。")
        self._source_save_worker = None

    def _on_source_code_validation_failed(self, error_msg: str):
        """源代码验证失败回调（主线程）"""
        QMessageBox.warning(self, "代码验证失败", f"无法保存，代码存在错误：\n\n{error_msg}")
        self._source_save_worker = None

    def _open_playwright_script_dialog(self):
        """打开 Playwright 脚本编辑弹窗"""
        from src.dialogs.playwright_script_dialog import PlaywrightScriptDialog

        self.current_config = self._collect_current_config()
        dialog = PlaywrightScriptDialog(
            script_source=self.current_config.get("script_source", ""),
            existing_param_schema=self.current_config.get("param_schema", {}),
            node_name=self.current_node_id or "Playwright",
            parent=self,
        )
        if dialog.exec():
            result = dialog.get_result()
            self._apply_playwright_script_result(result)

    def _apply_playwright_script_result(self, result: dict):
        """应用 Playwright 脚本编辑结果"""
        merged_config = dict(self._collect_current_config())
        merged_config["script_source"] = result.get("script_source", "")
        merged_config["param_schema"] = result.get("param_schema", {})

        allowed_keys = {
            "script_source",
            "param_schema",
            *result.get("param_names", []),
            "playwright_headless",
            "playwright_timeout_seconds",
            "playwright_download_dir",
            "playwright_artifacts_dir",
            "playwright_auto_download",
            "playwright_browser_channel",
        }
        merged_config = {
            key: value
            for key, value in merged_config.items()
            if key in allowed_keys
        }
        merged_config = build_playwright_default_config(merged_config)
        self.current_config = merged_config
        self.properties_updated.emit(self.current_node_id, merged_config)
        self.load_node_properties(
            self.current_node_id,
            self.current_node_type,
            merged_config,
        )

    def _rescan_playwright_inline_script(self):
        """重新扫描当前 Playwright 脚本中的参数"""
        self.current_config = self._collect_current_config()
        script_source = self.current_config.get("script_source", "")
        try:
            import ast

            if not str(script_source).strip():
                raise ValueError("当前还没有配置 Playwright 脚本")
            ast.parse(script_source)
            param_names = extract_playwright_params(script_source)
            self._apply_playwright_script_result(
                {
                    "script_source": script_source,
                    "param_schema": build_playwright_config_schema(
                        param_names,
                        self.current_config.get("param_schema", {}),
                    ),
                    "param_names": param_names,
                }
            )
            QMessageBox.information(
                self,
                "扫描完成",
                f"已刷新参数，共识别 {len(param_names)} 个业务参数。",
            )
        except Exception as exc:
            QMessageBox.warning(self, "扫描失败", f"重新扫描参数失败：\n\n{exc}")

    def _clear_playwright_script(self):
        """清空当前 Playwright 脚本"""
        reply = QMessageBox.question(
            self,
            "清空脚本",
            "确定要清空当前 Playwright 脚本吗？这会移除已识别出的业务参数。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        self._apply_playwright_script_result(
            {
                "script_source": "",
                "param_schema": build_playwright_config_schema([]),
                "param_names": [],
            }
        )
        QMessageBox.information(self, "已清空", "Playwright 脚本已清空。")
    
    def _reset_source_code_to_original(self):
         """重置源代码到原始版本"""
         reply = QMessageBox.question(
             self, 
             "确认重置", 
             "确定要重置源代码到原始版本吗？\n\n您的修改将会丢失。",
             QMessageBox.Yes | QMessageBox.No,
             QMessageBox.No
         )
         
         if reply == QMessageBox.Yes:
             registry = get_registry()
             registry.reset_to_original(self._current_node_type_for_source)
 
             # Playwright 节点的脚本就是磁盘上的主资产，重置时只重新加载当前文件内容。
             source_code = registry.get_display_source_code(self._current_node_type_for_source)
             self._current_source_code = source_code
             
             logger.info("源代码已重置: %s", self._current_node_type_for_source)

    def _reload_current_node_properties(self):
        """重新加载当前节点属性，用于 schema 刷新后更新表单"""
        if not self.current_node_id or not self.current_node_type:
            return

        config = self._collect_current_config()
        self.load_node_properties(self.current_node_id, self.current_node_type, config)

    def _rescan_playwright_params(self):
        """重新扫描 Playwright 脚本中的参数占位符"""
        # 此功能现在通过弹窗编辑器处理，用户可以在弹窗中编辑并保存
        # 如果需要内联重新扫描，可以打开弹窗进行编辑
        self._open_source_code_dialog()

    def _export_custom_node(self):
        """导出自定义节点"""
        if not self._current_node_type_for_source:
            return
            
        file_path, _ = QFileDialog.getSaveFileName(
            self, "导出节点", f"{self._current_node_type_for_source}.zip", "ZIP 压缩包 (*.zip)"
        )
        
        if file_path:
            from src.core.custom_node_manager import CustomNodeManager
            registry = get_registry()
            manager = CustomNodeManager(registry._user_data_dir)
            
            if manager.export_node(self._current_node_type_for_source, file_path):
                QMessageBox.information(self, "导出成功", f"节点已成功导出到：\n{file_path}")
            else:
                QMessageBox.critical(self, "导出失败", "导出节点过程中发生错误。")

    def _delete_external_node(self):
        """删除外部或自定义节点"""
        if not self._current_node_type_for_source:
            return
            
        registry = get_registry()
        node_def = registry.get_node(self._current_node_type_for_source)
        if not node_def:
            return
            
        source_name = "GitHub" if node_def.source == NodeSource.GITHUB else "自定义"
        reply = QMessageBox.question(
            self, 
            "确认删除", 
            f"确定要永久删除{source_name}节点 '{node_def.name}' 吗？\n\n此操作不可撤销。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            success = False
            if node_def.source == NodeSource.CUSTOM:
                from src.core.custom_node_manager import CustomNodeManager
                manager = CustomNodeManager(registry._user_data_dir)
                success = manager.delete_node(self._current_node_type_for_source)
            elif node_def.source == NodeSource.GITHUB:
                from src.core.providers.github_provider import GitHubNodeProvider
                provider = GitHubNodeProvider(registry._user_data_dir)
                success = provider.delete_node(self._current_node_type_for_source)
                
            if success:
                registry.unregister_node(self._current_node_type_for_source)
                QMessageBox.information(self, "删除成功", "节点已成功删除。")
                self.clear_properties()
                
                # 尝试通知节点浏览器刷新
                widget = self.parent()
                while widget:
                    if hasattr(widget, 'node_browser'):
                        widget.node_browser._load_nodes()
                        break
                    widget = widget.parent() if hasattr(widget, 'parent') else None
            else:
                QMessageBox.critical(self, "删除失败", "无法删除节点目录。")
