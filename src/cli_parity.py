"""Additional headless entry points for desktop operations.

Registration is explicit so importing the main CLI never loads Qt.
"""
import functools
import json
import subprocess
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Optional

import typer

from .core.config_manager import ConfigManager
from .core.node_registry import get_registry, NodeSource
from .core.workflow_service import WorkflowService
from .core.exceptions import MozikitError


def _json(value):
    typer.echo(json.dumps(value, ensure_ascii=False, indent=2))


def _errors(function):
    @functools.wraps(function)
    def invoke(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except (ValueError, OSError, SyntaxError, subprocess.SubprocessError, MozikitError) as exc:
            typer.echo(f"错误: {exc}", err=True)
            raise typer.Exit(1)
    return invoke


def _github_provider():
    from .core.providers.github_provider import GitHubNodeProvider
    return GitHubNodeProvider(get_registry()._user_data_dir, ConfigManager().get_github_token())


def _github_repos():
    repos = {}
    for node in get_registry().get_nodes_by_source(NodeSource.GITHUB):
        repos.setdefault(node.repo_url, []).append(node.node_type)
    return repos


def register(app, node_app, workflow_app, env_app, config_app):
    credentials = typer.Typer(help="安全管理自定义凭据", no_args_is_help=True)
    app.add_typer(credentials, name="credential")

    @credentials.command("list")
    def credential_list():
        """列出凭据名称，不输出凭据值。"""
        _json(sorted(ConfigManager().config.get("custom_credentials", {})))

    @credentials.command("set")
    @_errors
    def credential_set(name: str, value_file: Optional[Path] = typer.Option(None, "--value-file")):
        """保存凭据；默认隐藏输入，--value-file 从 UTF-8 文件读取。"""
        from .core.custom_credentials import set_custom_credential
        value = value_file.read_text(encoding="utf-8").rstrip("\r\n") if value_file else typer.prompt("凭据值", hide_input=True)
        set_custom_credential(ConfigManager(), name, value)
        typer.echo("凭据已安全保存")

    @credentials.command("remove")
    @_errors
    def credential_remove(name: str):
        from .core.custom_credentials import remove_custom_credential
        remove_custom_credential(ConfigManager(), name)
        typer.echo("凭据已删除")

    source = typer.Typer(help="查看和编辑节点源码", no_args_is_help=True)
    node_app.add_typer(source, name="source")

    @source.command("show")
    @_errors
    def source_show(node_type: str, output: Optional[Path] = typer.Option(None, "--output", "-o")):
        registry = get_registry()
        if not registry.get_node(node_type):
            raise ValueError(f"节点不存在: {node_type}")
        code = registry.get_display_source_code(node_type)
        if output:
            output.write_text(code, encoding="utf-8")
        else:
            typer.echo(code)

    @source.command("set")
    @_errors
    def source_set(node_type: str, file: Path):
        if not get_registry().save_display_source(node_type, file.read_text(encoding="utf-8")):
            raise ValueError(f"源码保存失败: {node_type}")
        typer.echo("源码已保存")

    @node_app.command("usage")
    @_errors
    def node_usage(node_type: str):
        from .core import resolve_workspace
        from .core.workflow_scanner import WorkflowScanner
        scanner = WorkflowScanner(str(resolve_workspace()))
        scanner.scan_all_workflows()
        _json([asdict(item) for item in scanner.get_workflows_using_node(node_type)])

    github = typer.Typer(help="管理第三方 GitHub 节点仓库", no_args_is_help=True)
    node_app.add_typer(github, name="github")

    @github.command("list")
    def github_list():
        _json(_github_repos())

    @github.command("import")
    @_errors
    def github_import(url: str):
        nodes = _github_provider().download_nodes(url)
        if not nodes:
            raise ValueError("未能导入节点，请检查 GitHub URL 和访问权限")
        for node in nodes:
            get_registry().register_external_node(node)
        _json([node.node_type for node in nodes])

    @github.command("update")
    @_errors
    def github_update(url: Optional[str] = typer.Argument(None)):
        """重新拉取指定或全部已导入的 GitHub 仓库。"""
        repos = _github_repos()
        if url and url not in repos:
            raise ValueError("仓库未导入，请先使用 node github import")
        failed = []
        for repo in ([url] if url else repos):
            nodes = _github_provider().download_nodes(repo)
            if not nodes:
                failed.append(repo)
            for node in nodes:
                get_registry().register_external_node(node)
        if failed:
            raise ValueError(f"更新失败: {', '.join(failed)}")
        typer.echo("GitHub 节点更新完成")

    @github.command("remove")
    @_errors
    def github_remove(url: str):
        nodes = _github_repos().get(url)
        if not nodes:
            raise ValueError("仓库未导入")
        provider = _github_provider()
        for node_type in nodes:
            if not provider.delete_node(node_type):
                raise ValueError(f"删除失败: {node_type}")
            get_registry().unregister_node(node_type)
        typer.echo("仓库节点已删除")

    history = typer.Typer(help="查询运行历史及完整报告", no_args_is_help=True)
    workflow_app.add_typer(history, name="history")

    @history.command("list")
    def history_list(workflow: Optional[str] = typer.Option(None, "--workflow"), limit: int = typer.Option(50, "--limit", min=1)):
        _json(ConfigManager().get_execution_history(workflow, limit))

    @history.command("show")
    @_errors
    def history_show(run_id: str):
        from .core.execution_history import read_report
        records = ConfigManager().get_execution_history(limit=500)
        matches = [r for r in records if r.get("id") == run_id or Path(r.get("artifact_dir", "")).name == run_id]
        if len(matches) != 1:
            raise ValueError("运行 ID 不存在或不唯一")
        _json(read_report(matches[0]))

    @config_app.command("test-ai")
    @_errors
    def test_ai():
        """使用已保存设置向 AI 服务发送一条简短测试请求。"""
        from .core.ai_connection import check_ai_connection
        settings = ConfigManager().get_ai_settings()
        success, message = check_ai_connection(settings.get("base_url", ""), settings.get("api_key", ""), settings.get("model", ""), settings.get("timeout_seconds", 30))
        _json({"success": success, "message": message})
        if not success:
            raise typer.Exit(1)

    @env_app.command("set-uv-path")
    @_errors
    def set_uv_path(path: Path):
        from .core.uv_manager import UVManager
        if not UVManager().set_custom_uv_path(str(path.resolve())):
            raise ValueError("路径不是可用的 UV 可执行文件")
        typer.echo("UV 路径已保存")

    @env_app.command("install-uv")
    @_errors
    def install_uv():
        """安装或确认 UV；正式 Desktop 版只使用随包提供的 UV。"""
        from .core.uv_manager import UVManager

        uv = UVManager()
        if getattr(sys, "frozen", False):
            bundled = uv.get_bundled_uv_path()
            if bundled and uv._verify_uv_executable(bundled):
                _json({"status": "bundled", "path": bundled})
                return
            raise ValueError("正式发行版未找到可用的内置 UV；不会在 frozen 环境调用 pip")

        subprocess.run([sys.executable, "-m", "pip", "install", "uv"], check=True)
        _json({
            "status": "installed",
            "path": uv.get_preferred_uv_path(),
        })

    script = typer.Typer(help="工作流 Playwright 脚本管理", no_args_is_help=True)
    workflow_app.add_typer(script, name="script")

    @script.command("install-runtime")
    @_errors
    def script_install_runtime():
        """通过 UV 安装 Playwright 录制工具。"""
        from .core.uv_manager import UVManager
        uv = UVManager().get_preferred_uv_path()
        if not uv:
            raise ValueError("请先安装 UV: env install-uv")
        subprocess.run([uv, "pip", "install", "--python", sys.executable, "playwright"], check=True)

    def script_node(workflow, node_id):
        path, document = WorkflowService().read(workflow)
        node = next((n for n in document.get("nodes", []) if n.get("node_id") == node_id), None)
        if node is None:
            raise ValueError(f"节点不存在: {node_id}")
        definition = get_registry().get_node(node["node_type"])
        from .core.playwright_node_utils import is_playwright_node
        if not definition or not (is_playwright_node(definition.metadata) or definition.metadata.get("editor_type") == "playwright"):
            raise ValueError("目标不是 Playwright 脚本节点")
        return path, document, node

    def save_script(workflow, node_id, source=None, validate_only=False, allow_empty=False):
        from .core.playwright_node_utils import apply_playwright_script
        from .core.workflow_executor import write_workflow_file
        path, document, node = script_node(workflow, node_id)
        config = node.get("config", {})
        source = config.get("script_source", "") if source is None else source
        if not source.strip() and not allow_empty:
            raise ValueError("请输入 Playwright Python 脚本；清空请使用 workflow script clear")
        updated = apply_playwright_script(config, source)
        if not validate_only:
            node["config"] = updated
            write_workflow_file(str(path), document)
        _json(updated["param_schema"])

    @script.command("set")
    @_errors
    def script_set(workflow: str, node_id: str, file: Path):
        save_script(workflow, node_id, file.read_text(encoding="utf-8"))

    @script.command("show")
    @_errors
    def script_show(workflow: str, node_id: str):
        _, _, node = script_node(workflow, node_id)
        typer.echo(node.get("config", {}).get("script_source", ""))

    @script.command("validate")
    @_errors
    def script_validate(workflow: str, node_id: str):
        save_script(workflow, node_id, validate_only=True)

    @script.command("rescan")
    @_errors
    def script_rescan(workflow: str, node_id: str):
        save_script(workflow, node_id)

    @script.command("clear")
    @_errors
    def script_clear(workflow: str, node_id: str):
        save_script(workflow, node_id, "", allow_empty=True)

    @script.command("record")
    @_errors
    def script_record(workflow: str, node_id: str, url: str = typer.Option("", "--url")):
        """启动 Playwright Codegen；正常退出后校验并保存录制脚本。"""
        script_node(workflow, node_id)
        with tempfile.TemporaryDirectory(prefix="mozikit-codegen-") as directory:
            output = Path(directory) / "recording.py"
            command = [sys.executable, "-m", "playwright", "codegen", "--target", "python", "-o", str(output), "--browser", "chromium", "--channel", "chrome"]
            subprocess.run(command + ([url] if url else []), check=True)
            if not output.exists() or not output.read_text(encoding="utf-8").strip():
                raise ValueError("录制未生成脚本，原有配置已保留")
            save_script(workflow, node_id, output.read_text(encoding="utf-8"))
