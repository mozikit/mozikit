"""GUI 启动入口 — 供 mozikit-gui 命令与 main.py 共用。"""

import os
import sys
from pathlib import Path


def _prepare_runtime_workdir() -> None:
    """Use a user-writable runtime directory when running from packaged EXE."""
    if not getattr(sys, "frozen", False):
        return

    appdata = os.environ.get("APPDATA")
    if not appdata:
        appdata = str(Path.home() / "AppData" / "Roaming")

    runtime_root = Path(appdata) / "Mozikit"
    runtime_root.mkdir(parents=True, exist_ok=True)
    os.chdir(runtime_root)


def run_gui() -> None:
    """启动 GUI 模式（未安装 PySide6 时给出安装提示后退出）。"""
    _prepare_runtime_workdir()
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        from rich.console import Console

        Console(stderr=True).print(
            "[red]错误:[/] 启动 GUI 需要 PySide6，请安装 GUI 扩展：\n"
            "  uv pip install -e .\\[gui]\n"
            "  或: pip install mozikit\\[gui]\n"
            "  或: pip install PySide6"
        )
        sys.exit(1)

    from src.core.log_manager import init_logging
    from src.core.runtime_client import RuntimeClient
    from src.core.theme_manager import ThemeManager
    from src.main_window import MainWindow

    init_logging()
    app = QApplication(sys.argv)
    RuntimeClient().ensure_running()
    # 应用主题
    ThemeManager.apply_theme(app)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())
