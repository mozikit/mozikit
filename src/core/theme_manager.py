from PySide6.QtGui import QPalette, QColor, QFont, QLinearGradient, QPainter, QFontDatabase
from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve, QRect


class ThemeManager:
    """主题管理器
    
    负责管理应用程序的全局样式、颜色和控件风格。
    提供统一的配色方案和可复用的样式模板，确保整个应用程序的视觉效果一致性。
    
    优化特性：
    - 现代化的深色主题配色
    - 增强的视觉层次感
    - 流畅的动画过渡效果
    - 更好的可访问性支持
    """
    
    # 全局颜色配置 - 科技蓝灰主题（与软件图标风格一致）
    COLORS = {
        # 基础背景色
        "background": "#0c1218",         # 主背景色（深蓝黑底色）
        "surface": "#141e2b",            # 表面色（卡片、面板背景）
        "surface_light": "#1c2a3d",      # 浅表面色（悬停、高亮区域）
        "surface_lighter": "#253a52",    # 更浅表面色（按钮悬停、分隔线）
        "surface_highlight": "#2d4666",  # 高亮表面色
        
        # 边框和分隔
        "border": "#2a3f5a",             # 边框色（柔和的分隔线）
        "border_light": "#3d5a7d",       # 浅色边框
        "divider": "#1a2636",            # 分隔线
        
        # 文字颜色
        "text": "#e8f0f8",               # 主文字色（高对比度白蓝）
        "text_secondary": "#8aa3bf",     # 次级文字色（蓝灰提示文字）
        "text_muted": "#5a7a9a",         # 弱化文字色
        "text_disabled": "#4a6078",      # 禁用状态文字
        
        # 主题强调色 - 科技蓝灰（与图标一致）
        "accent": "#5B8DB8",             # 主题强调色（蓝灰色）
        "accent_hover": "#7BA3C8",       # 强调色悬停状态（亮蓝灰）
        "accent_pressed": "#4A7A9E",     # 强调色按下状态（深蓝灰）
        "accent_light": "#9BC0D8",       # 浅色强调色
        "accent_dark": "#3D6A8A",        # 深色强调色
        
        # 状态颜色
        "success": "#2DD4A8",            # 成功状态色（青绿色）
        "success_light": "#4EE0B8",      # 浅色成功色
        "success_dark": "#1FB08C",       # 深色成功色
        "warning": "#F0A030",            # 警告状态色（琥珀色）
        "warning_light": "#F5B850",      # 浅色警告色
        "warning_dark": "#D48820",       # 深色警告色
        "error": "#E85D5D",              # 错误状态色（柔和红色）
        "error_light": "#F07878",        # 浅色错误色
        "error_dark": "#C84848",         # 深色错误色
        "info": "#4A90A4",               # 信息色（青蓝色）
        "info_light": "#6AA8BC",         # 浅色信息色
        
        # 选中和高亮
        "selection": "#3D6A8A",          # 选中状态色（深蓝灰）
        "selection_light": "#5B8DB8",    # 浅色选中
        "highlight": "#2D5A7A",          # 高亮色
        
        # 特殊颜色
        "white": "#ffffff",              # 纯白色
        "black": "#000000",              # 纯黑色
        "transparent": "transparent",    # 透明
        
        # 渐变色彩
        "gradient_start": "#4A90A4",     # 渐变起始色
        "gradient_end": "#5B8DB8",       # 渐变结束色
        "gradient_accent_start": "#5B8DB8",  # 强调渐变起始
        "gradient_accent_end": "#7BA3C8",    # 强调渐变结束
        "gradient_success_start": "#2DD4A8", # 成功渐变起始
        "gradient_success_end": "#1FB08C",   # 成功渐变结束
        "gradient_warning_start": "#F0A030", # 警告渐变起始
        "gradient_warning_end": "#D48820",   # 警告渐变结束
        "gradient_error_start": "#E85D5D",   # 错误渐变起始
        "gradient_error_end": "#C84848",     # 错误渐变结束
    }

    # 节点类型专用颜色映射 - 科技蓝灰统一风格
    NODE_COLORS = {
        "variable_assign": {
            "normal": "#2DD4A8",
            "hover": "#4EE0B8",
            "light": "#1FB08C",
            "gradient_start": "#4EE0B8",
            "gradient_end": "#2DD4A8",
            "glow": "#2DD4A833",
            "shadow": "#1FB08C88",
        },
        "variable_calc": {
            "normal": "#5B8DB8",
            "hover": "#7BA3C8",
            "light": "#4A7A9E",
            "gradient_start": "#7BA3C8",
            "gradient_end": "#5B8DB8",
            "glow": "#5B8DB833",
            "shadow": "#4A7A9E88",
        },
        "sqlite_connect": {
            "normal": "#F0A030",
            "hover": "#F5B850",
            "light": "#D48820",
            "gradient_start": "#F5B850",
            "gradient_end": "#F0A030",
            "glow": "#F0A03033",
            "shadow": "#D4882088",
        },
        "sqlite_execute": {
            "normal": "#4A90A4",
            "hover": "#6AA8BC",
            "light": "#3D7A8E",
            "gradient_start": "#6AA8BC",
            "gradient_end": "#4A90A4",
            "glow": "#4A90A433",
            "shadow": "#3D7A8E88",
        },
        "sql_statement": {
            "normal": "#6AA8BC",
            "hover": "#8ABDD0",
            "light": "#5A98AC",
            "gradient_start": "#8ABDD0",
            "gradient_end": "#6AA8BC",
            "glow": "#6AA8BC33",
            "shadow": "#5A98AC88",
        },
        "custom": {
            "normal": "#7BA3C8",
            "hover": "#9BC0D8",
            "light": "#6A93B8",
            "gradient_start": "#9BC0D8",
            "gradient_end": "#7BA3C8",
            "glow": "#7BA3C833",
            "shadow": "#6A93B888",
        },
        "playwright_script": {
            "normal": "#E85D5D",
            "hover": "#F07878",
            "light": "#C84848",
            "gradient_start": "#F07878",
            "gradient_end": "#E85D5D",
            "glow": "#E85D5D33",
            "shadow": "#C8484888",
        },
        "table_reader": {
            "normal": "#4A90A4",
            "hover": "#6AA8BC",
            "light": "#3D7A8E",
            "gradient_start": "#6AA8BC",
            "gradient_end": "#4A90A4",
            "glow": "#4A90A433",
            "shadow": "#3D7A8E88",
        },
        "table_aggregate": {
            "normal": "#2DD4A8",
            "hover": "#4EE0B8",
            "light": "#1FB08C",
            "gradient_start": "#4EE0B8",
            "gradient_end": "#2DD4A8",
            "glow": "#2DD4A833",
            "shadow": "#1FB08C88",
        },
        "text_template_render": {
            "normal": "#F0A030",
            "hover": "#F5B850",
            "light": "#D48820",
            "gradient_start": "#F5B850",
            "gradient_end": "#F0A030",
            "glow": "#F0A03033",
            "shadow": "#D4882088",
        },
        "clipboard_send": {
            "normal": "#2DD4A8",
            "hover": "#4EE0B8",
            "light": "#1FB08C",
            "gradient_start": "#4EE0B8",
            "gradient_end": "#2DD4A8",
            "glow": "#2DD4A833",
            "shadow": "#1FB08C88",
        },
        "im_control": {
            "normal": "#8B5CF6",
            "hover": "#A78BFA",
            "light": "#7C3AED",
            "gradient_start": "#A78BFA",
            "gradient_end": "#8B5CF6",
            "glow": "#8B5CF633",
            "shadow": "#7C3AED88",
        },
    }

    # 字体配置 - 紧凑专业版
    FONTS = {
        "family_primary": "'Segoe UI', 'Microsoft YaHei', 'PingFang SC', sans-serif",
        "family_mono": "'JetBrains Mono', 'Fira Code', 'Consolas', monospace",
        "size_tiny": "8pt",
        "size_small": "9pt",
        "size_normal": "10pt",
        "size_medium": "11pt",
        "size_large": "12pt",
        "size_xlarge": "13pt",
        "size_title": "14pt",
        "weight_normal": "400",
        "weight_medium": "500",
        "weight_semibold": "600",
        "weight_bold": "700",
    }

    # 间距和尺寸配置
    SPACING = {
        "xs": "2px",
        "sm": "4px",
        "md": "8px",
        "lg": "12px",
        "xl": "16px",
        "xxl": "20px",
        "xxxl": "24px",
    }

        # 圆角配置
    RADIUS = {
        "sm": "4px",
        "md": "6px",
        "lg": "8px",
        "xl": "10px",
        "xxl": "12px",
        "full": "9999px",
    }

    # 阴影配置
    SHADOWS = {
        "sm": "0 1px 2px 0 rgba(0, 0, 0, 0.05)",
        "md": "0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06)",
        "lg": "0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05)",
        "xl": "0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04)",
        "node": "0 8px 25px -8px rgba(0, 0, 0, 0.3)",
        "dock": "0 8px 32px rgba(0, 0, 0, 0.15), 0 4px 16px rgba(0, 0, 0, 0.1)",
    }

    @staticmethod
    def apply_theme(app):
        """应用全局主题到应用程序
        
        Args:
            app: QApplication 实例
        """
        app.setStyle("Fusion")

        palette = QPalette()
        palette.setColor(
            QPalette.ColorRole.Window, QColor(ThemeManager.COLORS["background"])
        )
        palette.setColor(
            QPalette.ColorRole.WindowText, QColor(ThemeManager.COLORS["text"])
        )
        palette.setColor(
            QPalette.ColorRole.Base, QColor(ThemeManager.COLORS["surface"])
        )
        palette.setColor(
            QPalette.ColorRole.AlternateBase,
            QColor(ThemeManager.COLORS["surface_light"]),
        )
        palette.setColor(
            QPalette.ColorRole.ToolTipBase, QColor(ThemeManager.COLORS["surface"])
        )
        palette.setColor(
            QPalette.ColorRole.ToolTipText, QColor(ThemeManager.COLORS["text"])
        )
        palette.setColor(QPalette.ColorRole.Text, QColor(ThemeManager.COLORS["text"]))
        palette.setColor(
            QPalette.ColorRole.Button, QColor(ThemeManager.COLORS["surface_light"])
        )
        palette.setColor(
            QPalette.ColorRole.ButtonText, QColor(ThemeManager.COLORS["text"])
        )
        palette.setColor(
            QPalette.ColorRole.BrightText, QColor(ThemeManager.COLORS["white"])
        )
        palette.setColor(QPalette.ColorRole.Link, QColor(ThemeManager.COLORS["accent"]))
        palette.setColor(
            QPalette.ColorRole.Highlight, QColor(ThemeManager.COLORS["selection"])
        )
        palette.setColor(
            QPalette.ColorRole.HighlightedText, QColor(ThemeManager.COLORS["white"])
        )
        palette.setColor(
            QPalette.ColorGroup.Disabled,
            QPalette.ColorRole.WindowText,
            QColor(ThemeManager.COLORS["text_disabled"]),
        )
        palette.setColor(
            QPalette.ColorGroup.Disabled,
            QPalette.ColorRole.Text,
            QColor(ThemeManager.COLORS["text_disabled"]),
        )
        palette.setColor(
            QPalette.ColorGroup.Disabled,
            QPalette.ColorRole.ButtonText,
            QColor(ThemeManager.COLORS["text_disabled"]),
        )

        app.setPalette(palette)

        app.setStyleSheet(f"""
            QWidget {{
                font-family: {ThemeManager.FONTS["family_primary"]};
                font-size: {ThemeManager.FONTS["size_normal"]};
            }}

            QMainWindow::separator {{
                background-color: {ThemeManager.COLORS["border"]};
                width: 2px;
                height: 2px;
            }}
            
            QMainWindow::separator:hover {{
                background-color: {ThemeManager.COLORS["accent"]};
            }}

            QScrollBar:vertical {{
                border: none;
                background: {ThemeManager.COLORS["background"]};
                width: 12px;
                margin: 0px;
                border-radius: 6px;
            }}

            QScrollBar::handle:vertical {{
                background: {ThemeManager.COLORS["surface_lighter"]};
                min-height: 24px;
                border-radius: 6px;
                margin: 2px 4px;
            }}

            QScrollBar::handle:vertical:hover {{
                background: {ThemeManager.COLORS["accent"]};
            }}
            
            QScrollBar::handle:vertical:pressed {{
                background: {ThemeManager.COLORS["accent_pressed"]};
            }}

            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                border: none;
                background: none;
                height: 0px;
            }}
            
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: none;
            }}

            QScrollBar:horizontal {{
                border: none;
                background: {ThemeManager.COLORS["background"]};
                height: 12px;
                margin: 0px;
                border-radius: 6px;
            }}

            QScrollBar::handle:horizontal {{
                background: {ThemeManager.COLORS["surface_lighter"]};
                min-width: 24px;
                border-radius: 6px;
                margin: 4px 2px;
            }}

            QScrollBar::handle:horizontal:hover {{
                background: {ThemeManager.COLORS["accent"]};
            }}
            
            QScrollBar::handle:horizontal:pressed {{
                background: {ThemeManager.COLORS["accent_pressed"]};
            }}

            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
                border: none;
                background: none;
                width: 0px;
            }}
            
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
                background: none;
            }}

            QToolTip {{
                color: {ThemeManager.COLORS["text"]};
                background-color: {ThemeManager.COLORS["surface_lighter"]};
                border: 1px solid {ThemeManager.COLORS["border"]};
                border-radius: 8px;
                padding: 8px 12px;
                font-size: {ThemeManager.FONTS["size_small"]};
            }}

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
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                    stop:0 {ThemeManager.COLORS["accent"]}, 
                    stop:1 {ThemeManager.COLORS["accent_hover"]});
            }}
            
            QMenu::item:hover {{
                background-color: {ThemeManager.COLORS["surface_light"]};
            }}

            QMenu::separator {{
                height: 1px;
                background: {ThemeManager.COLORS["border"]};
                margin: 6px 12px;
            }}

            QMenuBar {{
                background-color: {ThemeManager.COLORS["background"]};
                color: {ThemeManager.COLORS["text"]};
                border-bottom: 1px solid {ThemeManager.COLORS["border"]};
                padding: 4px;
            }}

            QMenuBar::item {{
                padding: 8px 16px;
                background: transparent;
                border-radius: 6px;
                margin: 2px 4px;
            }}

            QMenuBar::item:selected {{
                background: {ThemeManager.COLORS["surface_light"]};
            }}
            
            QMenuBar::item:pressed {{
                background: {ThemeManager.COLORS["surface_lighter"]};
            }}

            QMessageBox {{
                background-color: {ThemeManager.COLORS["surface"]};
                border-radius: 12px;
                border: 1px solid {ThemeManager.COLORS["border"]};
            }}
            
            QMessageBox QPushButton {{
                min-width: 80px;
                padding: 8px 20px;
            }}
            
            QDialog {{
                background-color: {ThemeManager.COLORS["background"]};
                border-radius: 12px;
            }}
            
            QDialogButtonBox QPushButton {{
                min-width: 80px;
            }}

            /* 自定义提示框样式 */
            .ModernToolTip {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 {ThemeManager.COLORS["surface"]},
                    stop:1 {ThemeManager.COLORS["surface_light"]});
                border: 1px solid {ThemeManager.COLORS["accent"]};
                border-radius: 8px;
                padding: 12px 16px;
                color: {ThemeManager.COLORS["text"]};
                font-size: {ThemeManager.FONTS["size_small"]};
            }}

             /* 加载动画样式 */
             .LoadingIndicator {{
                 border: 3px solid {ThemeManager.COLORS["surface_lighter"]};
                 border-top: 3px solid {ThemeManager.COLORS["accent"]};
                 border-radius: 50%;
             }}
        """)

    @staticmethod
    def get_toolbar_style(border_side="bottom"):
        border_css = f"border-{border_side}: 1px solid {ThemeManager.COLORS['border']};"

        return f"""
            QToolBar {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 {ThemeManager.COLORS["surface"]}, 
                    stop:1 {ThemeManager.COLORS["surface_light"]});
                border: none;
                {border_css}
                padding: 4px;
                spacing: 4px;
            }}

            QToolButton {{
                background: transparent;
                border: none;
                border-radius: 6px;
                padding: 6px 4px;
                color: {ThemeManager.COLORS["text_secondary"]};
                min-width: 48px;
                min-height: 48px;
                font-size: {ThemeManager.FONTS["size_tiny"]};
                font-weight: {ThemeManager.FONTS["weight_medium"]};
            }}

            QToolButton:hover {{
                background: {ThemeManager.COLORS["surface_lighter"]};
                color: {ThemeManager.COLORS["text"]};
            }}
            
            QToolButton:pressed {{
                background: {ThemeManager.COLORS["accent_pressed"]};
                color: {ThemeManager.COLORS["white"]};
            }}

            QToolButton:checked {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 {ThemeManager.COLORS["accent"]}, 
                    stop:1 {ThemeManager.COLORS["accent_pressed"]});
                color: {ThemeManager.COLORS["white"]};
            }}
        """

    @staticmethod
    def get_group_box_style():
        return f"""
            QGroupBox {{
                font-weight: {ThemeManager.FONTS["weight_semibold"]};
                border: 1px solid {ThemeManager.COLORS["border"]};
                border-radius: 10px;
                margin-top: 28px;
                padding-top: 20px;
                background-color: transparent;
            }}

            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 16px;
                padding: 0 12px;
                color: {ThemeManager.COLORS["text"]};
                font-size: {ThemeManager.FONTS["size_medium"]};
            }}

            QGroupBox {{
                border: 1px solid {ThemeManager.COLORS["border"]};
                border-radius: 10px;
                background-color: {ThemeManager.COLORS["surface_light"]};
            }}
        """

    @staticmethod
    def get_dock_widget_style():
        """获取停靠窗口样式（节点面板、属性面板、运行结果面板）- 紧凑版
        
        Returns:
            str: QDockWidget 的 QSS 样式字符串
        """
        return f"""
            QDockWidget {{
                color: {ThemeManager.COLORS["text"]};
                border: 1px solid {ThemeManager.COLORS["border"]};
                border-radius: 8px;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {ThemeManager.COLORS["surface"]},
                    stop:1 {ThemeManager.COLORS["surface_light"]});
            }}

            QDockWidget::title {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {ThemeManager.COLORS["surface"]},
                    stop:1 {ThemeManager.COLORS["surface_light"]});
                padding: 0px;
                border-bottom: 1px solid {ThemeManager.COLORS["border"]};
                font-weight: {ThemeManager.FONTS["weight_semibold"]};
                font-size: {ThemeManager.FONTS["size_normal"]};
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                color: {ThemeManager.COLORS["text"]};
            }}

            QDockWidget::close-button, QDockWidget::float-button {{
                background: transparent;
                border: none;
                border-radius: 6px;
                padding: 4px;
                icon-size: 14px;
            }}

            QDockWidget::close-button:hover, QDockWidget::float-button:hover {{
                background: {ThemeManager.COLORS["surface_lighter"]};
            }}

            QDockWidget::close-button:pressed, QDockWidget::float-button:pressed {{
                background: {ThemeManager.COLORS["accent"]};
            }}

            QDockWidget > QWidget {{
                background: transparent;
            }}
        """

    @staticmethod
    def get_main_window_tab_bar_style():
        """获取主窗口 dock 标签栏样式（用于 tabifyDockWidget 后的标签栏）

        QMainWindow 在 tabifyDockWidget 后会在 dock 区域内部生成 QTabBar，
        该标签栏属于主窗口的子控件，需要通过主窗口的样式表来设置。

        Returns:
            str: 主窗口级别的 QTabBar QSS 样式字符串
        """
        return f"""
            QMainWindow QTabBar::tab {{
                background: {ThemeManager.COLORS["surface"]};
                color: {ThemeManager.COLORS["text_secondary"]};
                padding: 8px 20px;
                border: none;
                border-bottom: 2px solid transparent;
                font-weight: {ThemeManager.FONTS["weight_medium"]};
                font-size: {ThemeManager.FONTS["size_small"]};
                min-width: 80px;
            }}

            QMainWindow QTabBar::tab:hover {{
                background: {ThemeManager.COLORS["surface_light"]};
                color: {ThemeManager.COLORS["text"]};
            }}

            QMainWindow QTabBar::tab:selected {{
                background: {ThemeManager.COLORS["surface_light"]};
                color: {ThemeManager.COLORS["accent"]};
                font-weight: {ThemeManager.FONTS["weight_semibold"]};
                border-bottom: 2px solid {ThemeManager.COLORS["accent"]};
            }}

            QMainWindow QTabBar::tab:!selected {{
                margin-top: 2px;
            }}
        """

    @staticmethod
    def get_card_style():
        """获取卡片样式（工作流卡片等）
        
        Returns:
            str: QFrame 的 QSS 样式字符串
        """
        return f"""
            QFrame {{
                background-color: {ThemeManager.COLORS["surface"]};
                border: 1px solid {ThemeManager.COLORS["border"]};
                border-radius: 12px;
            }}
            QFrame:hover {{
                border: 1px solid {ThemeManager.COLORS["accent"]};
                background-color: {ThemeManager.COLORS["surface_light"]};
            }}
        """

    @staticmethod
    def get_card_style_advanced():
        """获取高级卡片样式（带阴影效果）
        
        Returns:
            str: QFrame 的高级 QSS 样式字符串
        """
        return f"""
            QFrame {{
                background-color: {ThemeManager.COLORS["surface"]};
                border: 1px solid {ThemeManager.COLORS["border"]};
                border-radius: 12px;
                padding: 16px;
            }}
            QFrame:hover {{
                border: 1px solid {ThemeManager.COLORS["accent"]};
                background-color: {ThemeManager.COLORS["surface_light"]};
            }}
        """

    @staticmethod
    def get_table_style():
        """获取表格样式（定时任务表、运行历史表等）
        
        Returns:
            str: QTableWidget 的 QSS 样式字符串
        """
        return f"""
            QTableWidget {{
                background-color: {ThemeManager.COLORS["surface"]};
                color: {ThemeManager.COLORS["text"]};
                border: 1px solid {ThemeManager.COLORS["border"]};
                border-radius: 10px;
                gridline-color: {ThemeManager.COLORS["border"]};
                selection-background-color: {ThemeManager.COLORS["selection"]};
                selection-color: {ThemeManager.COLORS["white"]};
                outline: none;
            }}
            QHeaderView::section {{
                background-color: {ThemeManager.COLORS["surface_light"]};
                color: {ThemeManager.COLORS["text"]};
                padding: 12px 16px;
                border: none;
                border-bottom: 2px solid {ThemeManager.COLORS["border"]};
                font-weight: {ThemeManager.FONTS["weight_semibold"]};
            }}
            QTableWidget::item {{
                padding: 10px 14px;
                border-bottom: 1px solid {ThemeManager.COLORS["divider"]};
            }}
            QTableWidget::item:selected {{
                background-color: {ThemeManager.COLORS["selection"]};
            }}
            QTableWidget::item:hover {{
                background-color: {ThemeManager.COLORS["surface_light"]};
            }}
            QTableWidget::item:selected:hover {{
                background-color: {ThemeManager.COLORS["selection_light"]};
            }}
        """

    @staticmethod
    def get_list_style():
        """获取列表样式（节点列表、使用统计列表等）
        
        Returns:
            str: QListWidget 的 QSS 样式字符串
        """
        return f"""
            QListWidget {{
                background-color: {ThemeManager.COLORS['surface']};
                border: 1px solid {ThemeManager.COLORS['border']};
                border-radius: 10px;
                color: {ThemeManager.COLORS['text']};
                outline: none;
                padding: 6px;
            }}
            QListWidget::item {{
                padding: 12px 16px;
                border-radius: 8px;
                margin: 3px 6px;
                border-bottom: 1px solid {ThemeManager.COLORS['divider']};
            }}
            QListWidget::item:hover {{
                background-color: {ThemeManager.COLORS['surface_light']};
            }}
            QListWidget::item:selected {{
                background-color: {ThemeManager.COLORS['selection']};
                color: {ThemeManager.COLORS['white']};
            }}
            QListWidget::item:selected:hover {{
                background-color: {ThemeManager.COLORS['selection_light']};
            }}
        """
        
    @staticmethod
    def get_list_style_compact():
        """获取紧凑列表样式
        
        Returns:
            str: QListWidget 的紧凑 QSS 样式字符串
        """
        return f"""
            QListWidget {{
                background-color: {ThemeManager.COLORS['surface']};
                border: 1px solid {ThemeManager.COLORS['border']};
                border-radius: 10px;
                color: {ThemeManager.COLORS['text']};
                outline: none;
                padding: 4px;
            }}
            QListWidget::item {{
                padding: 8px 12px;
                border-radius: 6px;
                margin: 2px 4px;
            }}
            QListWidget::item:hover {{
                background-color: {ThemeManager.COLORS['surface_light']};
            }}
            QListWidget::item:selected {{
                background-color: {ThemeManager.COLORS['selection']};
                color: {ThemeManager.COLORS['white']};
            }}
        """

    @staticmethod
    def get_tab_widget_style():
        """获取标签页控件样式（Overview标签、工作流标签等）- 紧凑版
        
        Returns:
            str: QTabWidget 的 QSS 样式字符串
        """
        return f"""
            QTabWidget::pane {{
                border: none;
                background: {ThemeManager.COLORS["background"]};
                border-top: 1px solid {ThemeManager.COLORS["border"]};
            }}

            QTabWidget::tab-bar {{
                left: 0;
            }}

            QTabBar::tab {{
                background: {ThemeManager.COLORS["surface"]};
                color: {ThemeManager.COLORS["text_secondary"]};
                padding: 10px 20px;
                border: none;
                border-right: 1px solid {ThemeManager.COLORS["border"]};
                min-width: 100px;
                font-weight: {ThemeManager.FONTS["weight_medium"]};
                font-size: {ThemeManager.FONTS["size_small"]};
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                margin-right: 2px;
            }}

            QTabBar::tab:hover {{
                background: {ThemeManager.COLORS["surface_light"]};
                color: {ThemeManager.COLORS["text"]};
            }}

            QTabBar::tab:selected {{
                background: {ThemeManager.COLORS["background"]};
                color: {ThemeManager.COLORS["accent"]};
                font-weight: {ThemeManager.FONTS["weight_semibold"]};
            }}

            QTabBar::tab:!selected {{
                margin-top: 2px;
            }}

            QTabBar::close-button {{
                image: none;
                width: 16px;
                height: 16px;
                border-radius: 4px;
                margin-left: 8px;
                background-color: transparent;
                color: {ThemeManager.COLORS["text_secondary"]};
                border: 1px solid transparent;
            }}

            QTabBar::close-button:hover {{
                background-color: {ThemeManager.COLORS["error"]};
                color: {ThemeManager.COLORS["white"]};
                border-color: {ThemeManager.COLORS["error"]};
            }}

            QTabBar::close-button:pressed {{
                background-color: {ThemeManager.COLORS["error_dark"]};
            }}
        """

    @staticmethod
    def get_button_style(variant="primary"):
        """获取按钮样式 - 紧凑版
        
        Args:
            variant: 按钮类型，可选值：
                - "primary": 主按钮（强调色渐变）
                - "secondary": 次要按钮
                - "danger": 危险按钮（红色渐变，用于删除等操作）
                - "success": 成功按钮（绿色渐变）
                - "warning": 警告按钮（橙色渐变）
                - "ghost": 幽灵按钮（透明背景）
                - "icon": 图标按钮（透明背景，用于工具栏）
                - 其他: 次要按钮（灰色渐变）
        
        Returns:
            str: QPushButton 的 QSS 样式字符串
        """
        base_style = f"""
            QPushButton {{
                border: none;
                padding: 6px 16px;
                border-radius: 6px;
                font-weight: {ThemeManager.FONTS["weight_medium"]};
                min-width: 70px;
                font-size: {ThemeManager.FONTS["size_small"]};
            }}
            QPushButton:hover {{
                transform: translateY(-1px);
            }}
            QPushButton:pressed {{
                transform: translateY(0px);
            }}
            QPushButton:disabled {{
                background: {ThemeManager.COLORS["surface_light"]};
                color: {ThemeManager.COLORS["text_disabled"]};
                border: 1px solid {ThemeManager.COLORS["border"]};
            }}
        """
        
        if variant == "primary":
            return f"""
                QPushButton {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                        stop:0 {ThemeManager.COLORS["accent_hover"]}, 
                        stop:1 {ThemeManager.COLORS["accent"]});
                    color: {ThemeManager.COLORS["white"]};
                    border: none;
                    padding: 6px 16px;
                    border-radius: 6px;
                    font-weight: {ThemeManager.FONTS["weight_medium"]};
                    min-width: 70px;
                    font-size: {ThemeManager.FONTS["size_small"]};
                }}
                QPushButton:hover {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                        stop:0 {ThemeManager.COLORS["accent"]}, 
                        stop:1 {ThemeManager.COLORS["accent_hover"]});
                }}
                QPushButton:pressed {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                        stop:0 {ThemeManager.COLORS["accent_pressed"]}, 
                        stop:1 {ThemeManager.COLORS["accent"]});
                }}
                QPushButton:disabled {{
                    background: {ThemeManager.COLORS["surface_light"]};
                    color: {ThemeManager.COLORS["text_disabled"]};
                    border: 1px solid {ThemeManager.COLORS["border"]};
                }}
            """
        elif variant == "secondary":
            return f"""
                QPushButton {{
                    background: {ThemeManager.COLORS["surface_light"]};
                    color: {ThemeManager.COLORS["text"]};
                    border: 1px solid {ThemeManager.COLORS["border"]};
                    padding: 6px 16px;
                    border-radius: 6px;
                    font-weight: {ThemeManager.FONTS["weight_medium"]};
                    min-width: 70px;
                    font-size: {ThemeManager.FONTS["size_small"]};
                }}
                QPushButton:hover {{
                    background: {ThemeManager.COLORS["surface_lighter"]};
                    border-color: {ThemeManager.COLORS["accent"]};
                }}
                QPushButton:pressed {{
                    background: {ThemeManager.COLORS["surface"]};
                }}
                QPushButton:disabled {{
                    background: {ThemeManager.COLORS["surface"]};
                    color: {ThemeManager.COLORS["text_disabled"]};
                    border: 1px solid {ThemeManager.COLORS["border"]};
                }}
            """
        elif variant == "danger":
            return f"""
                QPushButton {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                        stop:0 {ThemeManager.COLORS["error_light"]}, 
                        stop:1 {ThemeManager.COLORS["error"]});
                    color: {ThemeManager.COLORS["white"]};
                    border: none;
                    padding: 6px 16px;
                    border-radius: 6px;
                    font-weight: {ThemeManager.FONTS["weight_medium"]};
                    min-width: 70px;
                    font-size: {ThemeManager.FONTS["size_small"]};
                }}
                QPushButton:hover {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                        stop:0 {ThemeManager.COLORS["error"]}, 
                        stop:1 {ThemeManager.COLORS["error_dark"]});
                }}
                QPushButton:pressed {{
                    background: {ThemeManager.COLORS["error_dark"]};
                }}
            """
        elif variant == "success":
            return f"""
                QPushButton {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                        stop:0 {ThemeManager.COLORS["success_light"]}, 
                        stop:1 {ThemeManager.COLORS["success"]});
                    color: {ThemeManager.COLORS["white"]};
                    border: none;
                    padding: 6px 16px;
                    border-radius: 6px;
                    font-weight: {ThemeManager.FONTS["weight_medium"]};
                    min-width: 70px;
                    font-size: {ThemeManager.FONTS["size_small"]};
                }}
                QPushButton:hover {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                        stop:0 {ThemeManager.COLORS["success"]}, 
                        stop:1 {ThemeManager.COLORS["success_dark"]});
                }}
                QPushButton:pressed {{
                    background: {ThemeManager.COLORS["success_dark"]};
                }}
            """
        elif variant == "warning":
            return f"""
                QPushButton {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                        stop:0 {ThemeManager.COLORS["warning_light"]}, 
                        stop:1 {ThemeManager.COLORS["warning"]});
                    color: {ThemeManager.COLORS["white"]};
                    border: none;
                    padding: 6px 16px;
                    border-radius: 6px;
                    font-weight: {ThemeManager.FONTS["weight_medium"]};
                    min-width: 70px;
                    font-size: {ThemeManager.FONTS["size_small"]};
                }}
                QPushButton:hover {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                        stop:0 {ThemeManager.COLORS["warning"]}, 
                        stop:1 {ThemeManager.COLORS["warning_dark"]});
                }}
                QPushButton:pressed {{
                    background: {ThemeManager.COLORS["warning_dark"]};
                }}
            """
        elif variant == "ghost":
            return f"""
                QPushButton {{
                    background: transparent;
                    color: {ThemeManager.COLORS["text_secondary"]};
                    border: 1px solid transparent;
                    padding: 6px 16px;
                    border-radius: 6px;
                    font-weight: {ThemeManager.FONTS["weight_medium"]};
                    min-width: 70px;
                    font-size: {ThemeManager.FONTS["size_small"]};
                }}
                QPushButton:hover {{
                    background: {ThemeManager.COLORS["surface_light"]};
                    color: {ThemeManager.COLORS["text"]};
                    border-color: {ThemeManager.COLORS["border"]};
                }}
                QPushButton:pressed {{
                    background: {ThemeManager.COLORS["surface_lighter"]};
                }}
            """
        elif variant == "icon":
            return f"""
                QPushButton {{
                    background-color: transparent;
                    color: {ThemeManager.COLORS["text_secondary"]};
                    border: 1px solid transparent;
                    padding: 6px;
                    border-radius: 6px;
                    min-width: 32px;
                    min-height: 32px;
                }}
                QPushButton:hover {{
                    background-color: {ThemeManager.COLORS["surface_light"]};
                    color: {ThemeManager.COLORS["text"]};
                    border-color: {ThemeManager.COLORS["border"]};
                }}
                QPushButton:pressed {{
                    background-color: {ThemeManager.COLORS["surface_lighter"]};
                    color: {ThemeManager.COLORS["accent"]};
                }}
            """
        else:
            return f"""
                QPushButton {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                        stop:0 {ThemeManager.COLORS["surface_light"]}, 
                        stop:1 {ThemeManager.COLORS["surface"]});
                    color: {ThemeManager.COLORS["text"]};
                    border: 1px solid {ThemeManager.COLORS["border"]};
                    padding: 6px 16px;
                    border-radius: 6px;
                    font-weight: {ThemeManager.FONTS["weight_medium"]};
                    min-width: 70px;
                    font-size: {ThemeManager.FONTS["size_small"]};
                }}
                QPushButton:hover {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                        stop:0 {ThemeManager.COLORS["surface_lighter"]}, 
                        stop:1 {ThemeManager.COLORS["surface_light"]});
                    border-color: {ThemeManager.COLORS["accent"]};
                }}
                QPushButton:pressed {{
                    background: {ThemeManager.COLORS["surface"]};
                }}
            """

    @staticmethod
    def get_input_style():
        """获取输入控件样式（文本框、下拉框、数字框等）- 紧凑版
        
        Returns:
            str: 输入控件的 QSS 样式字符串
        """
        return f"""
            QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox {{
                background-color: {ThemeManager.COLORS["surface"]};
                color: {ThemeManager.COLORS["text"]};
                border: 1px solid {ThemeManager.COLORS["border"]};
                padding: 6px 10px;
                border-radius: 6px;
                selection-background-color: {ThemeManager.COLORS["selection"]};
                selection-color: {ThemeManager.COLORS["white"]};
                font-size: {ThemeManager.FONTS["size_small"]};
                min-height: 20px;
            }}

            QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
                border: 2px solid {ThemeManager.COLORS["accent"]};
                background-color: {ThemeManager.COLORS["surface_light"]};
            }}
            
            QLineEdit:hover, QTextEdit:hover, QPlainTextEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover {{
                border-color: {ThemeManager.COLORS["border_light"]};
            }}

            QLineEdit:read-only, QTextEdit:read-only, QPlainTextEdit:read-only {{
                background-color: {ThemeManager.COLORS["surface_light"]};
                color: {ThemeManager.COLORS["text_secondary"]};
                border-color: {ThemeManager.COLORS["border"]};
            }}
            
            QLineEdit:disabled, QTextEdit:disabled, QPlainTextEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
                background-color: {ThemeManager.COLORS["surface_light"]};
                color: {ThemeManager.COLORS["text_disabled"]};
                border-color: {ThemeManager.COLORS["border"]};
            }}

            QComboBox {{
                background-color: {ThemeManager.COLORS["surface"]};
                color: {ThemeManager.COLORS["text"]};
                border: 1px solid {ThemeManager.COLORS["border"]};
                padding: 6px 10px;
                border-radius: 6px;
                min-width: 80px;
                font-size: {ThemeManager.FONTS["size_small"]};
                min-height: 20px;
            }}

            QComboBox:focus {{
                border: 2px solid {ThemeManager.COLORS["accent"]};
            }}
            
            QComboBox:hover {{
                border-color: {ThemeManager.COLORS["border_light"]};
            }}

            QComboBox::drop-down {{
                border: none;
                width: 20px;
            }}

            QComboBox::down-arrow {{
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 5px solid {ThemeManager.COLORS["text_secondary"]};
                margin-right: 6px;
            }}
            
            QComboBox::down-arrow:on {{
                border-top: none;
                border-bottom: 5px solid {ThemeManager.COLORS["accent"]};
            }}

            QComboBox QAbstractItemView {{
                background-color: {ThemeManager.COLORS["surface"]};
                color: {ThemeManager.COLORS["text"]};
                border: 1px solid {ThemeManager.COLORS["border"]};
                border-radius: 6px;
                selection-background-color: {ThemeManager.COLORS["selection"]};
                padding: 4px;
            }}
            
            QComboBox QAbstractItemView::item {{
                padding: 6px 10px;
                border-radius: 4px;
                min-height: 16px;
            }}
            
            QComboBox QAbstractItemView::item:hover {{
                background-color: {ThemeManager.COLORS["surface_light"]};
            }}
            
            QComboBox QAbstractItemView::item:selected {{
                background-color: {ThemeManager.COLORS["selection"]};
            }}

            QTextEdit, QPlainTextEdit {{
                padding: 8px;
                line-height: 1.4;
            }}
        """

    @staticmethod
    def get_checkbox_style():
        """获取复选框样式
        
        Returns:
            str: QCheckBox 的 QSS 样式字符串
        """
        return f"""
            QCheckBox {{
                color: {ThemeManager.COLORS["text"]};
                spacing: 8px;
                font-size: {ThemeManager.FONTS["size_normal"]};
            }}
            
            QCheckBox::indicator {{
                width: 20px;
                height: 20px;
                border-radius: 4px;
                border: 2px solid {ThemeManager.COLORS["border"]};
                background-color: {ThemeManager.COLORS["surface"]};
            }}
            
            QCheckBox::indicator:hover {{
                border-color: {ThemeManager.COLORS["accent"]};
            }}
            
            QCheckBox::indicator:checked {{
                background-color: {ThemeManager.COLORS["accent"]};
                border-color: {ThemeManager.COLORS["accent"]};
                image: url(data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTQiIGhlaWdodD0iMTQiIHZpZXdCb3g9IjAgMCAxNCAxNCIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KPHBhdGggZD0iTTMgN0w2IDEwTDExIDQiIHN0cm9rZT0id2hpdGUiIHN0cm9rZS13aWR0aD0iMiIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIi8+Cjwvc3ZnPgo=);
            }}
            
            QCheckBox::indicator:indeterminate {{
                background-color: {ThemeManager.COLORS["accent"]};
                border-color: {ThemeManager.COLORS["accent"]};
            }}
            
            QCheckBox::indicator:disabled {{
                border-color: {ThemeManager.COLORS["surface_lighter"]};
                background-color: {ThemeManager.COLORS["surface_light"]};
            }}
            
            QCheckBox::indicator:checked:disabled {{
                background-color: {ThemeManager.COLORS["surface_lighter"]};
                border-color: {ThemeManager.COLORS["surface_lighter"]};
            }}
        """

    @staticmethod
    def get_radio_style():
        """获取单选按钮样式
        
        Returns:
            str: QRadioButton 的 QSS 样式字符串
        """
        return f"""
            QRadioButton {{
                color: {ThemeManager.COLORS["text"]};
                spacing: 8px;
                font-size: {ThemeManager.FONTS["size_normal"]};
            }}
            
            QRadioButton::indicator {{
                width: 20px;
                height: 20px;
                border-radius: 10px;
                border: 2px solid {ThemeManager.COLORS["border"]};
                background-color: {ThemeManager.COLORS["surface"]};
            }}
            
            QRadioButton::indicator:hover {{
                border-color: {ThemeManager.COLORS["accent"]};
            }}
            
            QRadioButton::indicator:checked {{
                border-color: {ThemeManager.COLORS["accent"]};
                background-color: {ThemeManager.COLORS["surface"]};
            }}
            
            QRadioButton::indicator::checked::content {{
                background-color: {ThemeManager.COLORS["accent"]};
                width: 10px;
                height: 10px;
                border-radius: 5px;
            }}
        """

    @staticmethod
    def get_slider_style():
        """获取滑块样式
        
        Returns:
            str: QSlider 的 QSS 样式字符串
        """
        return f"""
            QSlider::groove:horizontal {{
                border: none;
                height: 6px;
                background: {ThemeManager.COLORS["surface_lighter"]};
                border-radius: 3px;
            }}
            
            QSlider::sub-page:horizontal {{
                background: {ThemeManager.COLORS["accent"]};
                border-radius: 3px;
            }}
            
            QSlider::handle:horizontal {{
                background: {ThemeManager.COLORS["white"]};
                border: 2px solid {ThemeManager.COLORS["accent"]};
                width: 18px;
                height: 18px;
                margin: -6px 0;
                border-radius: 9px;
            }}
            
            QSlider::handle:horizontal:hover {{
                background: {ThemeManager.COLORS["accent"]};
                border-color: {ThemeManager.COLORS["accent_hover"]};
            }}
        """

    @staticmethod
    def get_progress_style():
        """获取进度条样式
        
        Returns:
            str: QProgressBar 的 QSS 样式字符串
        """
        return f"""
            QProgressBar {{
                border: none;
                border-radius: 4px;
                background-color: {ThemeManager.COLORS["surface_lighter"]};
                text-align: center;
                color: {ThemeManager.COLORS["text"]};
                font-weight: {ThemeManager.FONTS["weight_medium"]};
                height: 8px;
            }}
            
            QProgressBar::chunk {{
                background-color: {ThemeManager.COLORS["accent"]};
                border-radius: 4px;
            }}
            
            QProgressBar::chunk:disabled {{
                background-color: {ThemeManager.COLORS["surface_lighter"]};
            }}
        """

    @staticmethod
    def get_node_color(node_type: str, state: str = "normal") -> str:
        """获取节点颜色
        
        Args:
            node_type: 节点类型
            state: 状态 (normal, hover, light)
            
        Returns:
            str: 颜色值
        """
        colors = ThemeManager.NODE_COLORS.get(node_type, ThemeManager.NODE_COLORS.get("custom"))
        return colors.get(state, colors["normal"])

    @staticmethod
    def get_node_gradient(node_type: str) -> tuple:
        """获取节点渐变颜色
        
        Args:
            node_type: 节点类型
            
        Returns:
            tuple: (gradient_start, gradient_end)
        """
        colors = ThemeManager.NODE_COLORS.get(node_type, ThemeManager.NODE_COLORS.get("custom"))
        return (colors.get("gradient_start", colors["normal"]), 
                colors.get("gradient_end", colors["normal"]))
