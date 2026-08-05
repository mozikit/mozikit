import sys


# 已知 CLI 子命令（与 src/cli.py 保持一致）
_CLI_COMMANDS = {"run", "schedule", "env", "node", "config", "workflow", "serve", "help"}


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
    from src.gui_entry import run_gui as _run_gui

    _run_gui()


if __name__ == "__main__":
    if _is_cli_mode():
        _run_cli()
    else:
        run_gui()
