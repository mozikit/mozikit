import sys
import os
from pathlib import Path


def _prepare_runtime_workdir() -> None:
    """Use a user-writable runtime directory when running from packaged EXE."""
    if not getattr(sys, "frozen", False):
        return

    appdata = os.environ.get("APPDATA")
    if not appdata:
        appdata = str(Path.home() / "AppData" / "Roaming")

    runtime_root = Path(appdata) / "LocalFlow"
    runtime_root.mkdir(parents=True, exist_ok=True)
    os.chdir(runtime_root)


# 已知 CLI 子命令（与 src/cli.py 保持一致）
_CLI_COMMANDS = {"run", "schedule", "env", "node", "config", "workflow", "serve"}


def _is_cli_mode() -> bool:
    """检测是否为 CLI 模式（不需要启动 Qt UI）"""
    # 显式 CLI 标志
    if "--cli" in sys.argv or "--run" in sys.argv:
        return True
    # 帮助请求
    if "--help" in sys.argv or "-h" in sys.argv:
        return True
    # 第一个非 Qt 选项参数是已知子命令
    for arg in sys.argv[1:]:
        if not arg.startswith("-") and arg in _CLI_COMMANDS:
            return True
    return False


def _run_cli():
    """运行 CLI 模式"""
    # 向后兼容: 将 --run WORKFLOW 转换为 run WORKFLOW
    if "--run" in sys.argv:
        idx = sys.argv.index("--run")
        sys.argv.pop(idx)  # 移除 --run
        sys.argv.insert(idx, "run")  # 插入 run 子命令

    from src.cli import run_cli

    run_cli()


def run_gui():
    """运行 GUI 模式（console_scripts 入口点）"""
    from PySide6.QtWidgets import QApplication
    from src.main_window import MainWindow
    from src.core.theme_manager import ThemeManager
    from src.core.log_manager import init_logging

    _prepare_runtime_workdir()
    init_logging()
    app = QApplication(sys.argv)

    # 应用主题
    ThemeManager.apply_theme(app)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    if _is_cli_mode():
        _run_cli()
    else:
        run_gui()
