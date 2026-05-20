"""
LocalFlow CLI
完整的命令行接口，支持工作流执行、定时调度、环境与节点管理等操作。
"""
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Optional, List

import typer

from src.core.exceptions import LocalFlowError
from rich.console import Console
from rich.table import Table
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TimeElapsedColumn,
)
from rich.status import Status
from rich import box

from src.core.log_manager import init_logging, get_logger
from src.core.workflow_executor import WorkflowExecutor
from src.core.headless_scheduler import HeadlessScheduler
from src.core.config_manager import ConfigManager
from src.core.node_base import NodeBase
from src.core.node_registry import get_registry
from src.core.uv_manager import UVManager
from src.core import resolve_workspace

app = typer.Typer(
    name="localflow",
    help="LocalFlow — 工作流自动化工具",
    no_args_is_help=True,
)

console = Console()


def _version_callback(value: bool):
    if value:
        from src.core import __version__
        console.print(f"localflow v{__version__}")
        raise typer.Exit()


@app.callback()
def main_callback(
    ctx: typer.Context,
    workspace: Optional[str] = typer.Option(
        None, "--workspace", "-w",
        help="工作空间根目录（默认 ./workflows，可通过环境变量 LOCALFLOW_WORKSPACE 设置）",
        envvar="LOCALFLOW_WORKSPACE",
    ),
    version: bool = typer.Option(
        False, "--version", help="显示版本号并退出",
        callback=_version_callback,
        is_eager=True,
    ),
):
    """LocalFlow — 工作流自动化工具"""
    if workspace:
        os.environ["LOCALFLOW_WORKSPACE"] = workspace

logger = get_logger("cli")


# ── 敏感配置键 → ConfigManager setter 映射 ──────────
# 这些 key 的值包含凭证（API key、token 等），必须通过 store_credential 加密存储
_SENSITIVE_SETTERS: dict[str, str] = {
    "ai_settings": "set_ai_settings",
    "github_settings": "set_github_settings",
}


def _resolve_config_value(key: str, value: object, mgr: ConfigManager) -> bool:
    """将键值对写入 ConfigManager，敏感键自动路由到加密 setter。

    支持 dot-notation 路径（如 ``ai_settings.api_key``）。

    Args:
        key: 配置键，支持点号分隔的嵌套路径。
        value: 要设置的解析后的值。
        mgr: ConfigManager 实例。

    Returns:
        True 表示已通过 setter 处理（包括加密），
        False 表示需要调用方执行原始 ``mgr.config[key] = value`` 赋值。
    """
    # 顶层敏感键：直接调用 setter（处理加密）
    if key in _SENSITIVE_SETTERS:
        if isinstance(value, dict):
            getattr(mgr, _SENSITIVE_SETTERS[key])(value)
            return True
        console.print(f"[yellow]警告:[/] {key} 需要 JSON 对象，忽略: {value}")
        return True

    # dot-notation 路径：检查父键是否为敏感键
    parts = key.split(".")
    if len(parts) >= 2 and parts[0] in _SENSITIVE_SETTERS:
        setter_name = _SENSITIVE_SETTERS[parts[0]]
        getter_name = "get_" + parts[0]
        # 获取当前完整配置
        current = getattr(mgr, getter_name)()
        # 逐层导航，将 value 设置到嵌套路径的叶子节点
        target = current
        for p in parts[1:-1]:
            if p not in target or not isinstance(target[p], dict):
                target[p] = {}
            target = target[p]
        target[parts[-1]] = value
        # 通过 setter 写回（自动加密敏感字段）
        getattr(mgr, setter_name)(current)
        return True

    return False


# ── 辅助函数 ────────────────────────────────────────

def _init(verbose: bool = False):
    """初始化日志系统"""
    init_logging()
    if verbose:
        import logging
        root = logging.getLogger()
        root.setLevel(logging.DEBUG)
        for h in root.handlers:
            if isinstance(h, logging.StreamHandler):
                h.setLevel(logging.DEBUG)


def _load_workflow(path_str: str) -> WorkflowExecutor:
    """加载工作流文件，失败时退出进程"""
    path = Path(path_str)
    if not path.exists():
        console.print(f"[red]错误:[/] 工作流文件不存在: {path}")
        raise typer.Exit(code=1)
    if not path.is_file():
        console.print(f"[red]错误:[/] 路径不是文件: {path}")
        raise typer.Exit(code=1)

    try:
        executor = WorkflowExecutor.load_workflow(str(path))
        return executor
    except Exception as e:
        console.print(f"[red]错误:[/] 加载工作流失败: {e}")
        raise typer.Exit(code=1)


def _parse_kv_pairs(pairs: Optional[List[str]]) -> dict:
    """将 key=value 列表解析为字典"""
    if not pairs:
        return {}
    result = {}
    for pair in pairs:
        if "=" not in pair:
            console.print(f"[yellow]警告:[/] 忽略无效参数: {pair} (需要 key=value 格式)")
            continue
        key, _, value = pair.partition("=")
        result[key.strip()] = value.strip()
    return result


def _generate_node_id(existing_nodes: dict) -> str:
    """生成不重复的节点 ID"""
    n = 1
    while f"node{n}" in existing_nodes:
        n += 1
    return f"node{n}"


def _extract_node_positions(path_str: str) -> dict:
    """从工作流文件中提取节点位置映射 {node_id: {x, y}}"""
    try:
        with open(path_str, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return {
            nd["node_id"]: nd["position"]
            for nd in raw.get("nodes", [])
            if "position" in nd
        }
    except Exception:
        return {}


# ── run 命令 ───────────────────────────────────────

@app.command()
def run(
    workflow_path: Optional[str] = typer.Argument(None, help="工作流文件路径 (.json)"),
    name: Optional[str] = typer.Option(
        None, "--name", "-n", help="按工作流名称执行（替代文件路径）"
    ),
    input_data: Optional[str] = typer.Option(
        None, "--input", help='初始输入数据 (JSON 字符串或 key=value 对)'
    ),
    args: Optional[List[str]] = typer.Option(
        None, "--args", help='输入参数, 例如 --args key1=val1 key2=val2'
    ),
    output: Optional[str] = typer.Option(
        None, "--output", "-o", help="将执行结果输出到指定文件 (JSON)"
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="输出详细日志"
    ),
    json_output: bool = typer.Option(
        False, "--json", "-j", help="以 JSON 格式输出执行报告（适合管道/集成）"
    ),
):
    """执行工作流"""
    _init(verbose)

    # 解析工作流路径：--name 或位置参数
    if name:
        from src.core.workflow_scanner import scan_workflows
        from src.core import resolve_workspace

        wf_list = scan_workflows(str(resolve_workspace()))
        matches = [wf for wf in wf_list if wf["name"] == name]
        if not matches:
            console.print(f"[red]错误:[/] 未找到工作流: {name}")
            console.print(f"  使用 'workflow list' 查看可用工作流")
            raise typer.Exit(code=1)
        resolved_path = matches[0]["path"]
    elif workflow_path:
        resolved_path = workflow_path
    else:
        console.print("[red]错误:[/] 请指定工作流路径或使用 --name 指定工作流名称")
        console.print("  用法: localflow run <path> 或 localflow run --name <name>")
        raise typer.Exit(code=1)

    executor = _load_workflow(resolved_path)

    total_nodes = len(executor.nodes)

    # 合并输入数据
    initial_data = {}
    if input_data:
        try:
            parsed = json.loads(input_data)
            if isinstance(parsed, dict):
                initial_data.update(parsed)
            else:
                console.print(
                    "[yellow]警告:[/] --input JSON 不是对象，已忽略"
                )
        except json.JSONDecodeError:
            if "=" in input_data:
                k, _, v = input_data.partition("=")
                initial_data[k.strip()] = v.strip()
            else:
                console.print("[red]错误:[/] --input 无法解析为 JSON 或 key=value")
                raise typer.Exit(code=1)
    if args:
        initial_data.update(_parse_kv_pairs(args))

    if not json_output:
        console.print(f"[bold]工作流:[/] {executor.workflow_name}")
        console.print(f"[bold]节点数:[/] {total_nodes}")

    # 环境准备
    with Status("[bold yellow]准备执行环境...[/]", console=console) as status:
        env_success = executor.prepare_environment()
        if not env_success:
            msg = "环境准备失败，请检查 UV 安装和依赖配置"
            if json_output:
                console.print(json.dumps({"success": False, "error": msg}))
            else:
                console.print(f"[red]错误:[/] {msg}")
            raise typer.Exit(code=1)
        if not json_output:
            status.update("[green]环境准备完成[/]")

    # 执行进度
    completed_nodes = 0
    failed_nodes = []
    log_lines: list[str] = []

    if not json_output:
        progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            console=console,
            transient=False,
        )

        task_id = progress.add_task(
            f"[cyan]执行中 0/{total_nodes}",
            total=total_nodes,
        )

        def on_node_start(node_id: str):
            progress.update(task_id, description=f"[cyan]▶ {node_id}")

        def on_node_complete(report: dict):
            nonlocal completed_nodes
            nid = report.get("node_id", "unknown")
            success = report.get("success", False)
            duration = report.get("duration_ms", 0)
            if success:
                completed_nodes += 1
                progress.update(
                    task_id,
                    completed=completed_nodes,
                    description=f"[green]✓ {nid} ({duration}ms)",
                )
            else:
                error = report.get("error", "未知错误")
                failed_nodes.append(nid)
                progress.update(
                    task_id,
                    description=f"[red]✗ {nid}: {error}",
                )
                progress.advance(task_id)

        def on_node_progress(node_id: str, percent: int, message: str):
            if verbose:
                progress.update(
                    task_id,
                    description=f"[cyan]{node_id}: {percent}% {message}",
                )

        def on_node_log(node_id: str, line: str):
            log_lines.append(f"[{node_id}] {line}")
            if verbose:
                console.print(f"  [dim]{node_id}:[/] {line}")

        progress.start()
    else:
        # JSON mode: silent execution, collect logs
        def on_node_start(node_id: str): pass
        def on_node_complete(report: dict):
            nonlocal completed_nodes
            nid = report.get("node_id", "unknown")
            if report.get("success", False):
                completed_nodes += 1
            else:
                failed_nodes.append(nid)
        def on_node_progress(node_id: str, percent: int, message: str): pass
        def on_node_log(node_id: str, line: str):
            log_lines.append(f"[{node_id}] {line}")

    try:
        report = executor.execute(
            initial_data=initial_data,
            return_report=True,
            trigger_type="cli",
            on_node_start=on_node_start,
            on_node_complete=on_node_complete,
            on_node_progress=on_node_progress,
            on_node_log=on_node_log,
        )
    except Exception as e:
        if not json_output:
            progress.stop()
            console.print(f"\n[red]错误:[/] 工作流执行异常: {e}")
        else:
            console.print(json.dumps({"success": False, "error": str(e)}))
        raise typer.Exit(code=1)

    if not json_output:
        progress.stop()
        print()

    # JSON 模式输出
    if json_output:
        result = {
            "success": report.get("success", False),
            "workflow": executor.workflow_name,
            "duration_ms": report.get("duration_ms", 0),
            "completed_nodes": completed_nodes,
            "total_nodes": total_nodes,
            "failed_nodes": failed_nodes,
            "error": report.get("error"),
            "logs": log_lines,
        }
        console.print(json.dumps(result, ensure_ascii=False, indent=2))
        raise typer.Exit(code=0 if report.get("success") else 1)

    # 普通模式：结果摘要
    duration_ms = report.get("duration_ms", 0)
    if total_nodes > 0:
        summary = Table(box=box.ROUNDED, show_header=False)
        summary.add_column("指标", style="bold")
        summary.add_column("值")
        summary.add_row("状态", "[green]成功[/]" if report.get("success") else "[red]失败[/]")
        summary.add_row("总耗时", f"{duration_ms} ms")
        summary.add_row("节点", f"{completed_nodes}/{total_nodes} 完成")
        if failed_nodes:
            summary.add_row("失败节点", ", ".join(failed_nodes))
        if report.get("error"):
            summary.add_row("错误", report["error"])
        console.print(summary)

    if output:
        out_path = Path(output)
        try:
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
            console.print(f"\n[green]结果已保存到:[/] {out_path}")
        except Exception as e:
            console.print(f"\n[red]错误:[/] 保存结果失败: {e}")
            raise typer.Exit(code=1)
    else:
        console.print("\n[bold]执行报告:[/]")
        console.print_json(data=report)

    if report.get("success"):
        console.print("[green]工作流执行成功[/]")
        raise typer.Exit(code=0)
    else:
        error_msg = report.get("error", "未知错误")
        console.print(f"[red]工作流执行失败:[/] {error_msg}")
        raise typer.Exit(code=1)


# ── schedule 命令组 ─────────────────────────────────

schedule_app = typer.Typer(help="定时任务管理", no_args_is_help=True)
app.add_typer(schedule_app, name="schedule")


@schedule_app.command("list")
def schedule_list():
    """列出所有定时任务"""
    mgr = HeadlessScheduler()
    tasks = mgr.list_tasks()
    if not tasks:
        console.print("没有定时任务")
        return

    table = Table(title="定时任务列表", box=box.ROUNDED)
    table.add_column("ID", style="cyan")
    table.add_column("名称", style="white")
    table.add_column("Cron 表达式", style="yellow")
    table.add_column("启用", justify="center")
    table.add_column("上次运行")
    table.add_column("下次运行")

    for t in tasks:
        table.add_row(
            t.get("id", ""),
            t.get("workflow_name", ""),
            t.get("cron_expression", ""),
            "✓" if t.get("enabled", True) else "✗",
            t.get("last_run") or "-",
            t.get("next_run") or "-",
        )
    console.print(table)


@schedule_app.command("add")
def schedule_add(
    workflow_path: str = typer.Argument(..., help="工作流文件路径"),
    cron: str = typer.Option("0 * * * *", "--cron", "-c", help="Cron 表达式"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="任务名称（可选）"),
):
    """添加定时任务"""
    path = Path(workflow_path)
    if not path.exists():
        console.print(f"[red]错误:[/] 工作流文件不存在: {path}")
        raise typer.Exit(code=1)

    wf_name = name or path.stem
    mgr = HeadlessScheduler()
    try:
        task_id = mgr.add_task(wf_name, str(path), cron)
        console.print(f"[green]定时任务已添加:[/] {task_id}")
    except (ValueError, LocalFlowError) as e:
        console.print(f"[red]错误:[/] {e}")
        raise typer.Exit(code=1)


@schedule_app.command("remove")
def schedule_remove(
    task_id: str = typer.Argument(..., help="任务 ID"),
):
    """删除定时任务"""
    mgr = HeadlessScheduler()
    if mgr.remove_task(task_id):
        console.print(f"[green]定时任务已删除:[/] {task_id}")
    else:
        console.print(f"[red]错误:[/] 任务不存在: {task_id}")
        raise typer.Exit(code=1)


@schedule_app.command("update")
def schedule_update(
    task_id: str = typer.Argument(..., help="任务 ID"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="新任务名称"),
    cron: Optional[str] = typer.Option(None, "--cron", "-c", help="新 Cron 表达式"),
    enabled: Optional[bool] = typer.Option(None, "--enabled/--disabled", help="启用/禁用"),
):
    """更新定时任务"""
    mgr = HeadlessScheduler()
    task = mgr.get_task(task_id)
    if not task:
        console.print(f"[red]错误:[/] 任务不存在: {task_id}")
        raise typer.Exit(code=1)

    updates = {}
    if name is not None:
        updates["workflow_name"] = name
    if cron is not None:
        updates["cron_expression"] = cron
    if enabled is not None:
        updates["enabled"] = enabled

    if not updates:
        console.print("[yellow]未提供任何更新字段[/]")
        return

    if mgr.update_task(task_id, **updates):
        changed = ", ".join(f"{k}={v}" for k, v in updates.items())
        console.print(f"[green]定时任务已更新:[/] {task_id} ({changed})")
    else:
        console.print(f"[red]错误:[/] 更新失败: {task_id}")
        raise typer.Exit(code=1)


@schedule_app.command("run")
def schedule_run(
    task_id: str = typer.Argument(..., help="任务 ID"),
):
    """立即执行指定定时任务"""
    mgr = HeadlessScheduler()
    task = mgr.get_task(task_id)
    if not task:
        console.print(f"[red]错误:[/] 任务不存在: {task_id}")
        raise typer.Exit(code=1)
    mgr.run_now(task_id)


@schedule_app.command("status")
def schedule_status():
    """查看调度器状态"""
    mgr = HeadlessScheduler()
    tasks = mgr.list_tasks()
    enabled = sum(1 for t in tasks if t.get("enabled", True))
    console.print(f"[bold]定时任务总数:[/] {len(tasks)}")
    console.print(f"[bold]已启用:[/] {enabled}")
    console.print(f"[bold]已禁用:[/] {len(tasks) - enabled}")


@schedule_app.command("pause")
def schedule_pause(
    task_id: str = typer.Argument(..., help="任务 ID"),
):
    """暂停定时任务"""
    mgr = HeadlessScheduler()
    if mgr.update_task(task_id, enabled=False):
        console.print(f"[green]✓[/] 任务已暂停: {task_id}")
    else:
        console.print(f"[red]错误:[/] 任务不存在: {task_id}")
        raise typer.Exit(code=1)


@schedule_app.command("resume")
def schedule_resume(
    task_id: str = typer.Argument(..., help="任务 ID"),
):
    """恢复定时任务"""
    mgr = HeadlessScheduler()
    if mgr.update_task(task_id, enabled=True):
        console.print(f"[green]✓[/] 任务已恢复: {task_id}")
    else:
        console.print(f"[red]错误:[/] 任务不存在: {task_id}")
        raise typer.Exit(code=1)


@schedule_app.command("daemon")
def schedule_daemon(
    tick: int = typer.Option(10, "--tick", "-t", help="轮询间隔（秒）"),
    pidfile: Optional[str] = typer.Option(
        None, "--pidfile", "-p", help="PID 文件路径（默认: /tmp/localflow-scheduler.pid）"
    ),
    logfile: Optional[str] = typer.Option(
        None, "--logfile", "-l", help="日志文件路径（覆盖默认日志目录）"
    ),
):
    """启动调度器守护进程（持续运行）"""
    import os
    import signal
    import tempfile
    import time as _time

    if logfile:
        import logging
        from logging.handlers import TimedRotatingFileHandler
        root = logging.getLogger()
        handler = TimedRotatingFileHandler(
            logfile, when="midnight", interval=1, backupCount=30,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter(
            "[%(asctime)s][%(levelname)s][%(name)s] %(message)s"
        ))
        root.addHandler(handler)
        # 减少控制台输出
        for h in root.handlers:
            if isinstance(h, logging.StreamHandler):
                h.setLevel(logging.WARNING)

    _init(verbose=True)

    pid_path = Path(pidfile or os.path.join(tempfile.gettempdir(), "localflow-scheduler.pid"))

    # 检查已有进程
    if pid_path.exists():
        try:
            old_pid = int(pid_path.read_text().strip())
            os.kill(old_pid, 0)  # 检查进程是否存在
            console.print(
                f"[red]错误:[/] 调度器已在运行 (PID {old_pid})\n"
                f"  停止: kill {old_pid} 或删除 {pid_path}"
            )
            raise typer.Exit(code=1)
        except (ProcessLookupError, ValueError):
            # 进程不存在，清理 stale PID 文件
            pid_path.unlink(missing_ok=True)

    # 写入 PID
    pid_path.write_text(str(os.getpid()))
    console.print(f"[dim]PID: {os.getpid()} -> {pid_path}[/]")

    mgr = HeadlessScheduler(tick_interval=tick)

    # 注册任务生命周期回调
    mgr.on_task_start(lambda t: console.print(
        f"[cyan]▶[/] 任务开始: [bold]{t['workflow_name']}[/] ({t.get('id', '?')})"
    ))
    mgr.on_task_complete(lambda t, r: console.print(
        f"[green]✓[/] 任务完成: [bold]{t['workflow_name']}[/] "
        f"({'[green]成功[/]' if r.get('success') else '[red]失败[/]'}, "
        f"{r.get('duration_ms', 0)}ms)"
    ))
    mgr.on_task_failed(lambda t, e: console.print(
        f"[red]✗[/] 任务失败: [bold]{t['workflow_name']}[/]: {e}"
    ))

    running = True

    def _shutdown(signum, frame):
        nonlocal running
        if running:
            console.print(f"\n[yellow]收到信号 ({signum})，停止调度器...[/]")
            mgr.stop()
            running = False
            pid_path.unlink(missing_ok=True)
            console.print("[green]调度器已停止[/]")

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    mgr.start()
    console.print(
        f"[green]调度器守护进程已启动[/] (tick={tick}s)"
    )

    try:
        while running and mgr.is_running:
            _time.sleep(1)
    except KeyboardInterrupt:
        _shutdown(signal.SIGINT, None)

    raise typer.Exit(code=0)


# ── env 命令组 ─────────────────────────────────────

env_app = typer.Typer(help="虚拟环境管理", no_args_is_help=True)
app.add_typer(env_app, name="env")


@env_app.command("list")
def env_list():
    """列出所有虚拟环境"""
    uv = UVManager()
    envs = uv.list_environments() if hasattr(uv, 'list_environments') else []
    if not envs:
        console.print("没有虚拟环境")
        return

    table = Table(title="虚拟环境列表", box=box.ROUNDED)
    table.add_column("名称", style="cyan")
    table.add_column("Python 版本")
    table.add_column("路径")
    for env in envs:
        table.add_row(
            env.get("name", ""),
            env.get("python_version", "-"),
            env.get("path", ""),
        )
    console.print(table)


@env_app.command("create")
def env_create(
    name: str = typer.Argument(..., help="环境名称"),
    python_version: str = typer.Option("3.12", "--python", "-p", help="Python 版本"),
):
    """创建虚拟环境"""
    uv = UVManager()
    try:
        uv.create_environment(name, python_version)
        console.print(f"[green]虚拟环境已创建:[/] {name}")
    except Exception as e:
        console.print(f"[red]错误:[/] 创建环境失败: {e}")
        raise typer.Exit(code=1)


@env_app.command("remove")
def env_remove(
    name: str = typer.Argument(..., help="环境名称"),
):
    """删除虚拟环境"""
    uv = UVManager()
    try:
        uv.remove_environment(name)
        console.print(f"[green]虚拟环境已删除:[/] {name}")
    except Exception as e:
        console.print(f"[red]错误:[/] 删除环境失败: {e}")
        raise typer.Exit(code=1)


@env_app.command("status")
def env_status():
    """显示 UV 环境和安装状态"""
    uv = UVManager()
    installed = uv.check_uv_installed()
    uv_path = uv.get_preferred_uv_path()
    mirror = uv.get_current_mirror()
    uv_paths = uv.find_uv_installations()

    console.print("[bold]UV 状态[/]")
    console.print(f"  已安装: {'[green]✓[/]' if installed else '[red]✗[/]'}")
    console.print(f"  当前路径: {uv_path or '[dim]未找到[/]'}")
    console.print(f"  镜像地址: {mirror or '[dim]默认（官方 PyPI）[/]'}")

    if uv_paths:
        console.print(f"\n[bold]发现的所有 UV 安装:[/]")
        for p in uv_paths:
            marker = " [green]← 当前使用[/]" if p == uv_path else ""
            console.print(f"  • {p}{marker}")

    envs = uv.list_environments() if hasattr(uv, 'list_environments') else []
    if envs:
        console.print(f"\n[bold]虚拟环境 ({len(envs)}):[/]")
        for e in envs:
            console.print(f"  • [cyan]{e.get('name', '?')}[/] ({e.get('python_version', '?')})")
    else:
        console.print("\n[dim]没有虚拟环境[/]")


@env_app.command("set-mirror")
def env_set_mirror(
    url: str = typer.Argument(..., help="镜像地址，如 https://pypi.tuna.tsinghua.edu.cn/simple"),
):
    """设置 UV 包镜像地址"""
    uv = UVManager()
    try:
        uv.set_custom_mirror(url)
        console.print(f"[green]镜像已设置:[/] {url}")
    except Exception as e:
        console.print(f"[red]错误:[/] 设置镜像失败: {e}")
        raise typer.Exit(code=1)


@env_app.command("install")
def env_install(
    name: str = typer.Argument(..., help="环境名称"),
    packages: List[str] = typer.Argument(..., help="要安装的包名（可多个）"),
):
    """在虚拟环境中安装包"""
    uv = UVManager()
    try:
        for pkg in packages:
            with Status(f"[bold yellow]正在安装 {pkg}...[/]", console=console):
                if not uv.install_packages(name, [pkg]):
                    console.print(f"[red]错误:[/] {pkg} 安装失败")
                    raise typer.Exit(code=1)
            console.print(f"[green]✓[/] {pkg} 安装成功")
    except Exception as e:
        console.print(f"[red]错误:[/] 安装失败: {e}")
        raise typer.Exit(code=1)


def _source_display(source) -> str:
    """将 NodeSource 枚举转为带颜色的可读中文标签"""
    from src.core.node_registry import NODE_SOURCE_INFO
    if source in NODE_SOURCE_INFO:
        info = NODE_SOURCE_INFO[source]
        return f"[{info['color']}]{info['name']}[/]"
    if hasattr(source, "value"):
        return source.value
    return str(source)


# ── node 命令组 ────────────────────────────────────

node_app = typer.Typer(help="节点管理", no_args_is_help=True)
app.add_typer(node_app, name="node")


@node_app.command("list")
def node_list():
    """列出所有可用节点"""
    try:
        registry = get_registry()
    except Exception:
        console.print("[red]错误:[/] 无法加载节点注册表")
        raise typer.Exit(code=1)

    nodes = registry.get_all_nodes()
    if not nodes:
        console.print("没有可用节点")
        return

    table = Table(title="可用节点", box=box.ROUNDED)
    table.add_column("名称", style="cyan")
    table.add_column("来源", style="white")
    table.add_column("分类", style="yellow")
    table.add_column("描述")
    table.add_column("版本")

    for node in sorted(nodes, key=lambda n: n.get("category", "") + n.get("name", "")):
        source_label = _source_display(node.get("source"))
        table.add_row(
            node.get("name", ""),
            source_label,
            node.get("category", "-"),
            node.get("description", "") or "",
            str(node.get("version", "1.0")),
        )
    console.print(table)


@node_app.command("info")
def node_info(
    name: str = typer.Argument(..., help="节点类型"),
):
    """查看节点详细信息"""
    try:
        registry = get_registry()
    except Exception:
        console.print("[red]错误:[/] 无法加载节点注册表")
        raise typer.Exit(code=1)

    # 先用 get_node_info 获取显示信息
    info = registry.get_node_info(name)
    if not info:
        console.print(f"[red]错误:[/] 节点不存在: {name}")
        raise typer.Exit(code=1)

    console.print(f"[bold]名称:[/] {info.get('name', name)}")
    console.print(f"[bold]来源:[/] {_source_display(info.get('source'))}")

    # 再用 get_all_nodes 找出详细字典
    node_dict = None
    for n in registry.get_all_nodes():
        if n.get("name") == name or n.get("type") == name or n.get("type_str") == name:
            node_dict = n
            break

    if node_dict:
        console.print(f"[bold]分类:[/] {node_dict.get('category', '-')}")
        console.print(f"[bold]描述:[/] {node_dict.get('description', '')}")
        console.print(f"[bold]版本:[/] {node_dict.get('version', '1.0')}")

        inputs = node_dict.get("input_schema", [])
        if inputs:
            console.print("\n[bold]输入:[/]")
            for inp in (inputs if isinstance(inputs, list) else inputs.values()):
                if isinstance(inp, dict):
                    console.print(f"  - {inp.get('name', '?')} ({inp.get('type', 'any')})")

        outputs = node_dict.get("output_schema", [])
        if outputs:
            console.print("\n[bold]输出:[/]")
            for out in (outputs if isinstance(outputs, list) else outputs.values()):
                if isinstance(out, dict):
                    console.print(f"  - {out.get('name', '?')} ({out.get('type', 'any')})")


# ── 辅助函数：获取 CustomNodeManager ────────────────

def _get_custom_mgr():
    """获取 CustomNodeManager 实例"""
    from src.core.custom_node_manager import CustomNodeManager
    registry = get_registry()
    return CustomNodeManager(registry._user_data_dir)


# ── node create ────────────────────────────────────

@node_app.command("create")
def node_create(
    name: str = typer.Argument(..., help="节点名称"),
    description: str = typer.Option("", "--desc", "-d", help="节点描述"),
    category: str = typer.Option("自定义", "--category", "-c", help="节点分类"),
):
    """创建自定义节点"""
    mgr = _get_custom_mgr()
    try:
        node_def = mgr.create_node(name, description, category)
        if node_def:
            registry = get_registry()
            registry.register_external_node(node_def)
            console.print(f"[green]✓[/] 节点已创建: [bold]{node_def.name}[/] ({node_def.node_type})")
        else:
            console.print("[red]错误:[/] 创建失败，节点可能已存在")
            raise typer.Exit(code=1)
    except Exception as e:
        console.print(f"[red]错误:[/] {e}")
        raise typer.Exit(code=1)


# ── node delete ────────────────────────────────────

@node_app.command("delete")
def node_delete(
    node_type: str = typer.Argument(..., help="节点类型（如 custom_my_node_123456）"),
):
    """删除自定义节点（所有版本）"""
    mgr = _get_custom_mgr()
    try:
        if mgr.delete_node(node_type):
            registry = get_registry()
            registry.unregister_node(node_type)
            console.print(f"[green]✓[/] 节点已删除: {node_type}")
        else:
            console.print(f"[red]错误:[/] 节点不存在: {node_type}")
            raise typer.Exit(code=1)
    except Exception as e:
        console.print(f"[red]错误:[/] {e}")
        raise typer.Exit(code=1)


# ── node export ────────────────────────────────────

@node_app.command("export")
def node_export(
    node_type: str = typer.Argument(..., help="节点类型"),
    output: str = typer.Argument(..., help="输出 ZIP 文件路径"),
    all_versions: bool = typer.Option(False, "--all", "-a", help="导出所有版本"),
):
    """导出节点为 ZIP 包"""
    mgr = _get_custom_mgr()
    try:
        if mgr.export_node(node_type, output, all_versions=all_versions):
            console.print(f"[green]✓[/] 节点已导出: {output}")
        else:
            console.print(f"[red]错误:[/] 导出失败，节点不存在: {node_type}")
            raise typer.Exit(code=1)
    except Exception as e:
        console.print(f"[red]错误:[/] {e}")
        raise typer.Exit(code=1)


# ── node import ────────────────────────────────────

@node_app.command("import")
def node_import(
    path: str = typer.Argument(..., help="ZIP 包路径"),
):
    """从 ZIP 包导入节点"""
    mgr = _get_custom_mgr()
    try:
        node_type = mgr.import_node(path)
        if node_type:
            registry = get_registry()
            registry._load_external_nodes()
            console.print(f"[green]✓[/] 节点已导入: {node_type}")
        else:
            console.print("[red]错误:[/] 导入失败，请检查 ZIP 包格式")
            raise typer.Exit(code=1)
    except Exception as e:
        console.print(f"[red]错误:[/] {e}")
        raise typer.Exit(code=1)


# ── node generate ──────────────────────────────────

@node_app.command("generate")
def node_generate(
    name: str = typer.Argument(..., help="节点名称"),
    description: str = typer.Option("", "--desc", "-d", help="用途描述"),
    input_spec: str = typer.Option("", "--input", "-i", help="输入说明"),
    output_spec: str = typer.Option("", "--output", "-o", help="输出说明"),
    constraints: str = typer.Option("", "--constraints", "-c", help="约束条件"),
):
    """AI 生成自定义节点（需在配置中设置 AI 接口）"""
    mgr = ConfigManager()
    ai_settings = mgr.get_ai_settings()
    if not ai_settings.get("api_key"):
        console.print("[red]错误:[/] 未配置 AI 接口，请先运行: config set ai_settings '{\"api_key\":\"...\",\"model\":\"...\",\"base_url\":\"...\"}'")
        raise typer.Exit(code=1)

    from src.core.ai_node_generator import AINodeGenerationService, AINodeGenerationError

    service = AINodeGenerationService(ai_settings)
    spec = {
        "name": name,
        "description": description,
        "input_spec": input_spec,
        "output_spec": output_spec,
        "constraints": constraints,
    }

    with Status("[bold yellow]AI 生成中...[/]", console=console) as status:
        try:
            result = service.generate_node(spec)
        except AINodeGenerationError as e:
            console.print(f"\n[red]错误:[/] {e}")
            raise typer.Exit(code=1)

    if result.safety_review and result.safety_review.high_risks:
        console.print(f"\n[red]安全审查未通过:[/] {'; '.join(result.safety_review.high_risks)}")
        raise typer.Exit(code=1)

    # 创建节点
    from src.core.custom_node_manager import CustomNodeManager
    registry = get_registry()
    custom_mgr = CustomNodeManager(registry._user_data_dir)

    try:
        node_def = custom_mgr.create_generated_node(
            name=result.name,
            description=result.description,
            source_code=result.source_code,
            config_schema=result.config_schema,
            dependencies=result.dependencies,
            category=result.category,
        )
        if not node_def:
            console.print("[red]错误:[/] 节点创建失败（可能已存在同名节点）")
            raise typer.Exit(code=1)
        registry.register_external_node(node_def)

        console.print(f"\n[green]✓[/] AI 节点已创建: [bold]{node_def.name}[/] ({node_def.node_type})")
        console.print(f"  [dim]描述:[/] {result.description}")
        if result.dependencies:
            console.print(f"  [dim]依赖:[/] {', '.join(result.dependencies)}")
        if result.safety_review and result.safety_review.risk_level == "medium":
            console.print(f"  [yellow]⚠ 低风险:[/] {'; '.join(result.safety_review.all_risks())}")
    except (ValueError, LocalFlowError) as e:
        console.print(f"[red]错误:[/] {e}")
        raise typer.Exit(code=1)


# ── node check-safety ──────────────────────────────

@node_app.command("check-safety")
def node_check_safety(
    path: str = typer.Argument(..., help="Python 文件路径"),
):
    """检查节点代码安全性"""
    from src.core.code_safety import review_code_safety, safety_review_to_warning

    try:
        with open(path, "r", encoding="utf-8") as f:
            code = f.read()
    except FileNotFoundError:
        console.print(f"[red]错误:[/] 文件不存在: {path}")
        raise typer.Exit(code=1)
    except Exception as e:
        console.print(f"[red]错误:[/] 读取文件失败: {e}")
        raise typer.Exit(code=1)

    result = review_code_safety(code)
    console.print(f"[bold]安全等级:[/] ", end="")
    if result.risk_level == "low":
        console.print("[green]低风险[/]")
    elif result.risk_level == "medium":
        console.print("[yellow]中风险[/]")
    elif result.risk_level == "high":
        console.print("[red]高风险[/]")

    if result.all_risks():
        console.print(f"\n[bold]检测到的问题:[/]")
        for risk in result.all_risks():
            console.print(f"  [yellow]⚠[/] {risk}")
    else:
        console.print("[green]✓[/] 未检测到安全问题")


# ── node repo 子命令组 ─────────────────────────────

repo_app = typer.Typer(help="远程节点仓库管理", no_args_is_help=True)
node_app.add_typer(repo_app, name="repo")


def _get_repo_mgr():
    """获取 NodeRepoManager 实例"""
    from src.core.node_repo_manager import NodeRepoManager
    registry = get_registry()
    mgr = NodeRepoManager(registry._user_data_dir)
    config = ConfigManager()
    token = config.get_github_token()
    if token:
        mgr.set_github_token(token)
    return mgr


@repo_app.command("list")
def repo_list():
    """列出远程仓库中的可用节点"""
    mgr = _get_repo_mgr()
    with Status("[bold yellow]获取远程清单...[/]", console=console) as status:
        owner_repo = mgr._parse_github_url(mgr.OFFICIAL_REPO_URL)
        if not owner_repo:
            console.print("[red]错误:[/] 无法解析仓库 URL")
            raise typer.Exit(code=1)
        remote = mgr._fetch_remote_manifest(owner_repo)

    if not remote:
        console.print("[red]错误:[/] 无法获取远程节点清单")
        raise typer.Exit(code=1)

    local_nodes = mgr._version_mgr.scan_all_nodes()

    table = Table(title=f"远程仓库: {remote.repo_name} (v{remote.repo_version})", box=box.ROUNDED)
    table.add_column("节点类型", style="cyan")
    table.add_column("远程版本")
    table.add_column("本地版本")
    table.add_column("状态")

    for node_type, info in sorted(remote.nodes.items()):
        latest = info.latest_version() or "-"
        local_vers = local_nodes.get(node_type, [])
        local_str = ", ".join(local_vers) if local_vers else "[dim]未安装[/]"
        if not local_vers:
            status_str = "[yellow]可安装[/]"
        elif latest not in local_vers:
            status_str = "[green]可更新[/]"
        else:
            status_str = "[dim]已最新[/]"
        table.add_row(node_type, latest, local_str, status_str)
    console.print(table)


@repo_app.command("check-updates")
def repo_check_updates():
    """检查官方节点更新"""
    mgr = _get_repo_mgr()
    with Status("[bold yellow]检查更新...[/]", console=console) as status:
        result = mgr.check_for_updates()

    if result.error:
        console.print(f"[red]错误:[/] {result.error}")
        raise typer.Exit(code=1)

    if not result.has_updates and not result.new_nodes:
        console.print("[green]✓[/] 所有节点已是最新")
        return

    if result.new_nodes:
        console.print(f"\n[bold]新节点可用 ({len(result.new_nodes)}):[/]")
        for n in result.new_nodes:
            console.print(f"  [yellow]{n}[/]")

    if result.updates:
        console.print(f"\n[bold]可更新节点 ({len(result.updates)}):[/]")
        table = Table(box=box.ROUNDED)
        table.add_column("节点", style="cyan")
        table.add_column("当前版本")
        table.add_column("新版本")
        for u in result.updates:
            local_str = ", ".join(u.local_versions) if u.local_versions else "-"
            new_str = ", ".join(u.new_versions)
            table.add_row(u.node_type, local_str, new_str)
        console.print(table)

    console.print(f"\n仓库: v{result.repo_version} → [green]v{result.remote_repo_version}[/]")


@repo_app.command("install")
def repo_install(
    node_type: str = typer.Argument(..., help="节点类型"),
    version: Optional[str] = typer.Option(None, "--version", "-v", help="版本号（默认最新）"),
):
    """从远程仓库安装/更新节点"""
    mgr = _get_repo_mgr()

    remote_versions = mgr.list_remote_versions(node_type)
    if not remote_versions:
        console.print(f"[red]错误:[/] 远程仓库中未找到节点: {node_type}")
        raise typer.Exit(code=1)

    target_version = version or remote_versions[-1]
    if target_version not in remote_versions:
        console.print(f"[red]错误:[/] 版本 {target_version} 不可用，可选: {', '.join(remote_versions)}")
        raise typer.Exit(code=1)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task(f"[cyan]安装 {node_type}@{target_version}...", total=2)

        def progress_cb(current, total, msg):
            progress.update(task, completed=current, description=f"[cyan]{msg}")

        success, message = mgr.install_node_version(node_type, target_version, progress_cb)

    if success:
        registry = get_registry()
        registry._load_external_nodes()
        console.print(f"[green]✓[/] {message}")
    else:
        console.print(f"[red]错误:[/] {message}")
        raise typer.Exit(code=1)


# ── config 命令组 ──────────────────────────────────

config_app = typer.Typer(help="配置管理", no_args_is_help=True)
app.add_typer(config_app, name="config")


@config_app.command("show")
def config_show():
    """显示当前配置（敏感字段自动解密显示）"""
    mgr = ConfigManager()
    conf = mgr.config

    table = Table(title="配置概览", box=box.ROUNDED)
    table.add_column("键", style="cyan")
    table.add_column("值", style="white")

    for key, value in conf.items():
        # 敏感键使用 getter 解密后显示
        if key == "ai_settings":
            decrypted = mgr.get_ai_settings()
            display = _redact_sensitive(decrypted)
        elif key == "github_settings":
            decrypted = mgr.get_github_settings()
            display = _redact_sensitive(decrypted)
        elif isinstance(value, dict) or isinstance(value, list):
            display = json.dumps(value, ensure_ascii=False)[:60]
        else:
            display = str(value)
        table.add_row(key, display)
    console.print(table)
    # 显示执行摘要
    stats = mgr.get_execution_stats()
    if stats["total_runs"] > 0:
        console.print(f"\n[bold]执行摘要:[/] {stats['total_runs']} 次运行, "
                      f"成功率 {stats['success_rate']:.1f}%")


def _redact_sensitive(d: dict) -> str:
    """对敏感字段脱敏显示"""
    redacted = {}
    for k, v in d.items():
        if any(s in k.lower() for s in ("api_key", "token", "password", "secret")):
            redacted[k] = "******" if v else ""
        else:
            redacted[k] = v
    return json.dumps(redacted, ensure_ascii=False)[:120]


@config_app.command("set")
def config_set(
    key: str = typer.Argument(..., help="配置键（支持点号分隔的嵌套路径，如 ai_settings.api_key）"),
    value: str = typer.Argument(..., help="配置值（JSON 值或字符串）"),
):
    """设置配置项

    敏感字段（API key、GitHub token 等）自动通过操作系统密钥链或本地加密存储。
    """
    mgr = ConfigManager()

    # 尝试解析为 JSON 值
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, ValueError):
        parsed = value

    # 敏感键路由到加密 setter，其余使用原始赋值
    if not _resolve_config_value(key, parsed, mgr):
        # 支持点号分隔的嵌套路径
        keys = key.split(".")
        target = mgr.config
        for k in keys[:-1]:
            if k not in target or not isinstance(target[k], dict):
                target[k] = {}
            target = target[k]
        target[keys[-1]] = parsed
        mgr.save_config_sync()

    # 对敏感字段做显示脱敏
    if any(s in key.lower() for s in ("api_key", "token", "password", "secret")):
        display_val = "******"
    elif key in _SENSITIVE_SETTERS and isinstance(parsed, dict):
        # 顶层敏感键（如 ai_settings），对内部敏感字段做脱敏
        redacted = {}
        for k, v in parsed.items():
            if any(s in k.lower() for s in ("api_key", "token", "password", "secret")):
                redacted[k] = "******"
            else:
                redacted[k] = v
        display_val = json.dumps(redacted, ensure_ascii=False)
    else:
        display_val = json.dumps(parsed, ensure_ascii=False)
    console.print(f"[green]配置已更新:[/] {key} = {display_val}")


@config_app.command("get")
def config_get(
    key: str = typer.Argument(..., help="配置键名（支持点号分隔的嵌套路径）"),
):
    """获取单条配置值"""
    mgr = ConfigManager()
    conf = mgr.config

    # 敏感键使用 getter 解密
    if key == "ai_settings":
        value = mgr.get_ai_settings()
    elif key == "github_settings":
        value = mgr.get_github_settings()
    else:
        # 支持点号路径
        keys = key.split(".")
        target = conf
        for k in keys:
            if isinstance(target, dict) and k in target:
                target = target[k]
            else:
                console.print(f"[red]错误:[/] 配置键不存在: {key}")
                raise typer.Exit(code=1)
        value = target

    # 脱敏显示
    display = _redact_sensitive(value) if isinstance(value, dict) else json.dumps(value, ensure_ascii=False)
    console.print(f"{key} = {display}")


@config_app.command("unset")
def config_unset(
    key: str = typer.Argument(..., help="要删除的配置键名"),
):
    """删除配置项"""
    mgr = ConfigManager()
    if key in mgr.config:
        del mgr.config[key]
        mgr.save_config_sync()
        console.print(f"[green]✓[/] 配置已删除: {key}")
    else:
        console.print(f"[red]错误:[/] 配置键不存在: {key}")
        raise typer.Exit(code=1)


@config_app.command("github-login")
def config_github_login(
    timeout: int = typer.Option(300, "--timeout", "-t", help="授权超时秒数（默认 300）"),
):
    """通过 GitHub Device Flow 登录（无需 client_secret）

    在浏览器中打开 GitHub 验证页面，输入显示的设备码完成授权。
    成功后自动保存 Token 到配置中（加密存储）。
    """
    from src.core.github_oauth import GitHubOAuth

    console.print("[bold]正在请求 GitHub 设备码...[/]")

    def _on_user_code(user_code: str, verification_uri: str):
        console.print()
        console.print("=" * 50)
        console.print("[bold yellow]GitHub 设备授权[/]")
        console.print()
        console.print(f"  1. 打开浏览器访问: [cyan underline]{verification_uri}[/]")
        console.print(f"  2. 输入设备码: [bold green]{user_code}[/]")
        console.print()
        console.print("[dim]浏览器标签页已自动打开（如未打开，请手动访问）[/]")
        console.print("[dim]等待授权中...（超时设置: {}秒）[/]".format(timeout))
        console.print("=" * 50)
        console.print()

    oauth = GitHubOAuth()
    success, token, username = oauth.authorize(
        timeout=timeout,
        on_user_code=_on_user_code,
    )

    if not success:
        console.print(f"[red]错误:[/] GitHub 授权失败: {username}")
        raise typer.Exit(code=1)

    mgr = ConfigManager()
    mgr.set_github_settings({
        "token": token,
        "username": username,
        "connected": True,
    })
    console.print(f"[green]✓[/] GitHub 授权成功！")
    console.print(f"  已登录为: [bold]{username}[/]")
    console.print(f"  凭证已通过加密存储到配置中")


@config_app.command("github-logout")
def config_github_logout():
    """清除 GitHub 登录凭证"""
    mgr = ConfigManager()
    mgr.set_github_settings({
        "token": "",
        "username": "",
        "connected": False,
    })
    console.print("[green]✓[/] 已断开 GitHub 连接")


# ── workflow 命令组 ────────────────────────────────

workflow_app = typer.Typer(help="工作流管理", no_args_is_help=True)
app.add_typer(workflow_app, name="workflow")


@workflow_app.command("list")
def workflow_list(
    json_output: bool = typer.Option(
        False, "--json", "-j", help="以 JSON 格式输出（适合管道/集成）"
    ),
):
    """列出已保存的工作流"""
    from src.core.workflow_scanner import scan_workflows
    from src.core import resolve_workspace
    wf_list = scan_workflows(str(resolve_workspace()))
    if not wf_list:
        console.print("没有找到已保存的工作流")
        return

    if json_output:
        console.print(json.dumps(wf_list, ensure_ascii=False, indent=2))
        return

    table = Table(title="已保存的工作流", box=box.ROUNDED)
    table.add_column("名称", style="cyan")
    table.add_column("路径", style="white")
    table.add_column("节点数", justify="right")
    table.add_column("更新时间")

    for wf in wf_list:
        table.add_row(
            wf["name"],
            wf["path"],
            str(wf.get("node_count", 0)),
            (wf.get("updated_at") or "")[:19],
        )
    console.print(table)


@workflow_app.command("validate")
def workflow_validate(
    workflow_path: str = typer.Argument(..., help="工作流文件路径"),
):
    """验证工作流文件格式"""
    executor = _load_workflow(workflow_path)

    try:
        # 尝试执行拓扑排序，检测循环依赖
        order = executor._topological_sort()
        console.print(f"[green]✓[/] 工作流格式有效")
        console.print(f"  名称: {executor.workflow_name}")
        console.print(f"  节点数: {len(executor.nodes)}")
        console.print(f"  连接数: {len(executor.edges)}")
        console.print(f"  执行顺序: {order}")
    except Exception as e:
        console.print(f"[red]✗[/] 工作流验证失败: {e}")
        raise typer.Exit(code=1)


@workflow_app.command("describe")
def workflow_describe(
    workflow_path: str = typer.Argument(..., help="工作流文件路径"),
    json_output: bool = typer.Option(False, "--json", "-j", help="以 JSON 格式输出"),
):
    """显示工作流详情"""
    executor = _load_workflow(workflow_path)

    if json_output:
        nodes_info = [
            {
                "node_id": n.node_id,
                "node_type": n.node_type,
                "config": getattr(n, 'config', {}),
            }
            for n in executor.nodes.values()
        ]
        edges_info = [
            {
                "from_node": e.from_node,
                "from_port": e.from_port,
                "to_node": e.to_node,
                "to_port": e.to_port,
            }
            for e in executor.edges
        ]
        result = {
            "workflow_name": executor.workflow_name,
            "node_count": len(executor.nodes),
            "edge_count": len(executor.edges),
            "nodes": nodes_info,
            "edges": edges_info,
        }
        console.print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    console.print(f"[bold]名称:[/] {executor.workflow_name}")
    console.print(f"[bold]节点数:[/] {len(executor.nodes)}")
    console.print(f"[bold]连接数:[/] {len(executor.edges)}")

    if executor.nodes:
        table = Table(title="节点列表", box=box.ROUNDED)
        table.add_column("ID", style="cyan")
        table.add_column("类型", style="yellow")
        table.add_column("名称/标签")
        for n in executor.nodes.values():
            label = getattr(n, 'label', None) or n.node_id
            table.add_row(n.node_id, n.node_type, label)
        console.print(table)

    if executor.edges:
        table = Table(title="连接列表", box=box.ROUNDED)
        table.add_column("从", style="cyan")
        table.add_column("端口", style="yellow")
        table.add_column("到", style="cyan")
        table.add_column("端口", style="yellow")
        for e in executor.edges:
            table.add_row(
                e.from_node, e.from_port, e.to_node, e.to_port
            )
        console.print(table)


@workflow_app.command("stats")
def workflow_stats():
    """显示工作流执行统计"""
    mgr = ConfigManager()
    stats = mgr.get_execution_stats()
    history = mgr.get_execution_history(limit=5)

    console.print("[bold]执行统计[/]")
    console.print(f"  总运行次数: {stats['total_runs']}")
    console.print(f"  成功次数: {stats['successful_runs']}")
    console.print(f"  失败次数: {stats['failed_runs']}")
    console.print(f"  成功率: {stats['success_rate']:.1f}%")

    if history:
        console.print(f"\n[bold]最近执行:[/]")
        for rec in history:
            status_icon = "✓" if rec.get("status") == "success" else "✗"
            name = rec.get("workflow_name", "?")
            dur = rec.get("duration_ms", 0)
            console.print(f"  {status_icon} {name} ({dur}ms)")
    else:
        console.print("\n[dim]暂无执行记录[/]")


# ── workflow create ─────────────────────────────────

@workflow_app.command("create")
def workflow_create(
    name: str = typer.Argument(..., help="工作流名称"),
):
    """创建新的空工作流"""
    from src.core import resolve_workspace
    ws = resolve_workspace()
    wf_dir = ws / name
    wf_path = wf_dir / "workflow.json"

    if wf_path.exists():
        console.print(f"[red]错误:[/] 工作流已存在: {wf_path}")
        raise typer.Exit(code=1)

    executor = WorkflowExecutor(name)
    os.makedirs(str(wf_dir), exist_ok=True)
    executor.save_workflow(str(wf_path))
    console.print(f"[green]✓[/] 工作流已创建: [bold]{name}[/]")
    console.print(f"  路径: {wf_path}")


# ── workflow delete ─────────────────────────────────

@workflow_app.command("delete")
def workflow_delete(
    workflow_path: str = typer.Argument(..., help="工作流文件路径"),
):
    """删除工作流"""
    path = Path(workflow_path)
    if not path.exists():
        console.print(f"[red]错误:[/] 工作流文件不存在: {path}")
        raise typer.Exit(code=1)

    wf_dir = path.parent
    name = wf_dir.name
    shutil.rmtree(str(wf_dir))
    console.print(f"[green]✓[/] 工作流已删除: [bold]{name}[/]")


# ── workflow rename ─────────────────────────────────

@workflow_app.command("rename")
def workflow_rename(
    workflow_path: str = typer.Argument(..., help="工作流文件路径"),
    new_name: str = typer.Argument(..., help="新工作流名称"),
):
    """重命名工作流"""
    executor = _load_workflow(workflow_path)

    from src.core import resolve_workspace
    ws = resolve_workspace()
    new_dir = ws / new_name
    new_path = new_dir / "workflow.json"

    if new_path.exists():
        console.print(f"[red]错误:[/] 目标名称已存在: {new_path}")
        raise typer.Exit(code=1)

    old_dir = Path(workflow_path).parent
    old_name = executor.workflow_name

    executor.workflow_name = new_name
    os.makedirs(str(new_dir), exist_ok=True)
    executor.save_workflow(str(new_path))
    shutil.rmtree(str(old_dir))
    console.print(f"[green]✓[/] 工作流已重命名: [bold]{old_name}[/] → [bold]{new_name}[/]")


# ── workflow copy ───────────────────────────────────

@workflow_app.command("copy")
def workflow_copy(
    workflow_path: str = typer.Argument(..., help="源工作流文件路径"),
    new_name: str = typer.Argument(..., help="新工作流名称"),
):
    """复制工作流"""
    executor = _load_workflow(workflow_path)

    from src.core import resolve_workspace
    ws = resolve_workspace()
    new_dir = ws / new_name
    new_path = new_dir / "workflow.json"

    if new_path.exists():
        console.print(f"[red]错误:[/] 目标名称已存在: {new_path}")
        raise typer.Exit(code=1)

    old_name = executor.workflow_name
    executor.workflow_name = new_name
    os.makedirs(str(new_dir), exist_ok=True)
    executor.save_workflow(str(new_path))
    console.print(f"[green]✓[/] 工作流已复制: [bold]{old_name}[/] → [bold]{new_name}[/]")
    console.print(f"  路径: {new_path}")


# ── workflow add-node ───────────────────────────────

@workflow_app.command("add-node")
def workflow_add_node(
    workflow_path: str = typer.Argument(..., help="工作流文件路径"),
    node_type: str = typer.Argument(..., help="节点类型（如 variable_assign）"),
    config: Optional[List[str]] = typer.Option(None, "--config", "-c", help="配置项 key=value 对（可重复）"),
    x: float = typer.Option(100.0, "--x", help="画布 X 坐标"),
    y: float = typer.Option(100.0, "--y", help="画布 Y 坐标"),
):
    """在工作流中添加一个节点"""
    executor = _load_workflow(workflow_path)
    registry = get_registry()

    node_def = registry.get_node(node_type)
    if not node_def:
        console.print(f"[yellow]警告:[/] 节点类型 '{node_type}' 未在注册表中找到，将创建空壳节点")
        console.print(f"  请确保该类型存在（使用 'node repo install {node_type}' 安装）")
        console.print(f"  或通过 'node list' 查看已注册的类型")

    node_id = _generate_node_id(executor.nodes)

    default_config = registry.build_default_config(node_type)
    custom_config = _parse_kv_pairs(config)
    default_config.update(custom_config)

    node = NodeBase.from_dict({
        "node_id": node_id,
        "node_type": node_type,
        "config": default_config,
    })
    executor.add_node(node)

    positions = _extract_node_positions(workflow_path)
    positions[node_id] = {"x": x, "y": y}
    executor.save_workflow(workflow_path, node_positions=positions)

    console.print(f"[green]✓[/] 节点已添加: [bold]{node_id}[/] ({node_type})")
    console.print(f"  配置: {json.dumps(default_config, ensure_ascii=False)}")
    console.print(f"  位置: ({x}, {y})")


# ── workflow remove-node ────────────────────────────

@workflow_app.command("remove-node")
def workflow_remove_node(
    workflow_path: str = typer.Argument(..., help="工作流文件路径"),
    node_id: str = typer.Argument(..., help="要删除的节点 ID"),
):
    """从工作流中删除节点及所有关联连接"""
    executor = _load_workflow(workflow_path)

    if node_id not in executor.nodes:
        console.print(f"[red]错误:[/] 节点不存在: {node_id}")
        console.print(f"  现有节点: {', '.join(executor.nodes.keys())}")
        raise typer.Exit(code=1)

    # 删除节点
    del executor.nodes[node_id]

    # 清理涉及该节点的边
    executor.edges = [
        e for e in executor.edges
        if e.from_node != node_id and e.to_node != node_id
    ]

    # 清理其他节点的 inputs/outputs 引用
    for n in executor.nodes.values():
        n.inputs = [i for i in n.inputs if i != node_id]
        n.outputs = [o for o in n.outputs if o != node_id]

    positions = _extract_node_positions(workflow_path)
    positions.pop(node_id, None)
    executor.save_workflow(workflow_path, node_positions=positions)

    console.print(f"[green]✓[/] 节点已删除: [bold]{node_id}[/]")


# ── workflow update-node ────────────────────────────

@workflow_app.command("update-node")
def workflow_update_node(
    workflow_path: str = typer.Argument(..., help="工作流文件路径"),
    node_id: str = typer.Argument(..., help="节点 ID"),
    config: List[str] = typer.Argument(..., help="配置项 key=value 对（可多个）"),
):
    """更新工作流节点的配置参数"""
    executor = _load_workflow(workflow_path)

    if node_id not in executor.nodes:
        console.print(f"[red]错误:[/] 节点不存在: {node_id}")
        console.print(f"  现有节点: {', '.join(executor.nodes.keys())}")
        raise typer.Exit(code=1)

    updates = _parse_kv_pairs(config)
    if not updates:
        console.print("[red]错误:[/] 未提供任何配置项")
        raise typer.Exit(code=1)

    executor.nodes[node_id].config.update(updates)
    positions = _extract_node_positions(workflow_path)
    executor.save_workflow(workflow_path, node_positions=positions)

    console.print(f"[green]✓[/] 节点 [bold]{node_id}[/] 配置已更新")
    for k, v in updates.items():
        console.print(f"  {k} = {v}")


# ── workflow connect ────────────────────────────────

@workflow_app.command("connect")
def workflow_connect(
    workflow_path: str = typer.Argument(..., help="工作流文件路径"),
    from_id: str = typer.Argument(..., help="上游节点 ID"),
    to_id: str = typer.Argument(..., help="下游节点 ID"),
    from_port: str = typer.Option("output", "--from-port", help="上游端口名"),
    to_port: str = typer.Option("input", "--to-port", help="下游端口名"),
):
    """连接两个节点"""
    executor = _load_workflow(workflow_path)

    if from_id not in executor.nodes:
        console.print(f"[red]错误:[/] 上游节点不存在: {from_id}")
        raise typer.Exit(code=1)
    if to_id not in executor.nodes:
        console.print(f"[red]错误:[/] 下游节点不存在: {to_id}")
        raise typer.Exit(code=1)

    # 检查重复连接
    for edge in executor.edges:
        if edge.from_node == from_id and edge.from_port == from_port \
           and edge.to_node == to_id and edge.to_port == to_port:
            console.print(f"[red]错误:[/] 连接已存在: {from_id}:{from_port} → {to_id}:{to_port}")
            raise typer.Exit(code=1)

    executor.add_edge(from_id, from_port, to_id, to_port)
    positions = _extract_node_positions(workflow_path)
    executor.save_workflow(workflow_path, node_positions=positions)

    console.print(f"[green]✓[/] 已连接: [bold]{from_id}[/]:{from_port} → [bold]{to_id}[/]:{to_port}")


# ── workflow disconnect ─────────────────────────────

@workflow_app.command("disconnect")
def workflow_disconnect(
    workflow_path: str = typer.Argument(..., help="工作流文件路径"),
    from_id: str = typer.Argument(..., help="上游节点 ID"),
    to_id: str = typer.Argument(..., help="下游节点 ID"),
    from_port: str = typer.Option("output", "--from-port", help="上游端口名"),
    to_port: str = typer.Option("input", "--to-port", help="下游端口名"),
):
    """断开两个节点的连接"""
    executor = _load_workflow(workflow_path)

    # 查找匹配的边
    edge_to_remove = None
    for edge in executor.edges:
        if edge.from_node == from_id and edge.from_port == from_port \
           and edge.to_node == to_id and edge.to_port == to_port:
            edge_to_remove = edge
            break

    if not edge_to_remove:
        console.print(f"[red]错误:[/] 未找到连接: {from_id}:{from_port} → {to_id}:{to_port}")
        raise typer.Exit(code=1)

    executor.edges.remove(edge_to_remove)

    # 更新节点的 inputs/outputs
    if to_id in executor.nodes and from_id in executor.nodes[to_id].inputs:
        executor.nodes[to_id].inputs.remove(from_id)
    if from_id in executor.nodes and to_id in executor.nodes[from_id].outputs:
        executor.nodes[from_id].outputs.remove(to_id)

    positions = _extract_node_positions(workflow_path)
    executor.save_workflow(workflow_path, node_positions=positions)

    console.print(f"[green]✓[/] 已断开: [bold]{from_id}[/]:{from_port} → [bold]{to_id}[/]:{to_port}")


# ── serve 命令 ─────────────────────────────────────

@app.command()
def serve(
    port: int = typer.Option(5000, "--port", "-p", help="监听端口"),
    host: str = typer.Option("127.0.0.1", "--host", "-H", help="监听地址"),
):
    """启动轻量 API 服务"""
    try:
        from fastapi import FastAPI, HTTPException
        from fastapi.responses import JSONResponse
        import uvicorn
    except ImportError:
        console.print("[red]错误:[/] 需要 fastapi 和 uvicorn:\n  pip install localflow[serve]\n  或: pip install fastapi uvicorn")
        raise typer.Exit(code=1)

    _init(verbose=True)

    api = FastAPI(
        title="LocalFlow API",
        description="LocalFlow 工作流自动化引擎 REST API",
        version="0.1.0",
    )

    @api.get("/health")
    def health():
        """健康检查"""
        return {"status": "ok", "service": "localflow"}

    @api.get("/workflows")
    def list_workflows():
        """列出工作流目录"""
        from src.core.workflow_scanner import scan_workflows
        from src.core import resolve_workspace
        wf_list = scan_workflows(str(resolve_workspace()))
        results = [
            {"name": w["name"], "path": w["path"], "nodes": w.get("node_count", 0)}
            for w in wf_list
        ]
        return {"workflows": results}

    @api.post("/workflows/run")
    def run_workflow(path: str, input_data: str = "{}"):
        """执行工作流

        Args:
            path: 工作流 JSON 文件路径
            input_data: JSON 字符串格式的输入数据
        """
        wf_path = Path(path)
        if not wf_path.exists():
            raise HTTPException(404, f"工作流文件不存在: {path}")

        try:
            executor = WorkflowExecutor.load_workflow(str(wf_path))
            env_ok = executor.prepare_environment()
            if not env_ok:
                raise HTTPException(500, "环境准备失败")

            initial = json.loads(input_data) if input_data else {}
            _api_logs = []
            report = executor.execute(
                initial_data=initial,
                return_report=True,
                trigger_type="api",
                on_node_start=lambda n: None,
                on_node_complete=lambda r: None,
                on_node_progress=lambda n, p, m: None,
                on_node_log=lambda n, l: _api_logs.append(f"[{n}] {l}"),
            )
            return {
                "success": report.get("success", False),
                "run_id": report.get("run_id"),
                "duration_ms": report.get("duration_ms"),
                "error": report.get("error"),
                "output": report.get("final_context"),
                "logs": _api_logs,
            }
        except json.JSONDecodeError as e:
            raise HTTPException(400, f"参数解析失败: {e}")
        except Exception as e:
            raise HTTPException(500, str(e))

    @api.get("/tasks")
    def list_tasks():
        """列出所有定时任务"""
        mgr = HeadlessScheduler()
        return {"tasks": mgr.list_tasks()}

    @api.post("/tasks")
    def add_task(
        workflow_path: str,
        cron: str = "0 * * * *",
        name: str = None,
    ):
        """添加定时任务"""
        if not Path(workflow_path).exists():
            raise HTTPException(404, f"工作流文件不存在: {workflow_path}")
        mgr = HeadlessScheduler()
        try:
            task_id = mgr.add_task(name or Path(workflow_path).stem, workflow_path, cron)
            return {"task_id": task_id}
        except (ValueError, LocalFlowError) as e:
            raise HTTPException(400, str(e))

    @api.delete("/tasks/{task_id}")
    def remove_task(task_id: str):
        """删除定时任务"""
        mgr = HeadlessScheduler()
        if mgr.remove_task(task_id):
            return {"status": "deleted", "task_id": task_id}
        raise HTTPException(404, f"任务不存在: {task_id}")

    console.print(f"[green]API 服务已启动:[/] http://{host}:{port}")
    console.print("[dim]接口文档: http://{0}:{1}/docs[/]".format(host, port))
    console.print("[dim]健康检查: http://{0}:{1}/health[/]".format(host, port))
    console.print("[yellow]按 Ctrl+C 停止[/]")

    try:
        uvicorn.run(api, host=host, port=port, log_level="warning")
    except KeyboardInterrupt:
        console.print("\n[yellow]服务已停止[/]")


# ── help 命令 ──────────────────────────────────────

@app.command()
def help():
    """显示帮助信息"""
    from typer.main import get_command
    import click

    click_group = get_command(app)
    ctx = click.Context(click_group, info_name="localflow")
    console.print(click_group.get_help(ctx))
    raise typer.Exit()


# ── 直接执行入口 ──────────────────────────────────

def run_cli():
    """由 main.py 调用的入口函数"""
    app()
