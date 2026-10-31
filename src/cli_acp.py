"""CLI entry points for the headless ACP client (SDK imported on demand)."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from pathlib import Path
from typing import List, Optional

import typer

from .core.exceptions import ErrorCode, MozikitError


def register(app: typer.Typer) -> None:
    acp_app = typer.Typer(help="通过 ACP 连接外部 Agent", no_args_is_help=True)
    app.add_typer(acp_app, name="acp")

    @acp_app.command("check")
    def check(
        agent: str = typer.Option(..., "--agent", help="已安装的 ACP Agent 可执行文件"),
        agent_arg: Optional[List[str]] = typer.Option(
            None, "--agent-arg", help="Agent 参数，可重复传入"
        ),
        cwd: Optional[Path] = typer.Option(
            None, "--cwd", exists=True, file_okay=False, help="Agent 工作目录"
        ),
        timeout: float = typer.Option(
            15, "--timeout", min=0.001, help="连接和初始化超时（秒）"
        ),
        json_output: bool = typer.Option(False, "--json", "-j"),
    ):
        """启动 Agent 并检查协议版本、能力和认证方式。"""
        _execute(agent, agent_arg, cwd, timeout, json_output)

    @acp_app.command("prompt")
    def prompt(
        text: str = typer.Argument(..., help="发送给 Agent 的提示"),
        agent: str = typer.Option(..., "--agent", help="已安装的 ACP Agent 可执行文件"),
        agent_arg: Optional[List[str]] = typer.Option(
            None, "--agent-arg", help="Agent 参数，可重复传入"
        ),
        cwd: Optional[Path] = typer.Option(
            None, "--cwd", exists=True, file_okay=False, help="Agent 工作目录"
        ),
        auth_method: Optional[str] = typer.Option(
            None, "--auth-method", help="check 中 Agent 公布的认证方式 ID"
        ),
        session: Optional[str] = typer.Option(
            None, "--session", help="加载 Agent 保存的会话（需要 loadSession 能力）"
        ),
        timeout: Optional[float] = typer.Option(
            None, "--timeout", min=0.001, help="提示超时（秒）；默认不限制"
        ),
        json_output: bool = typer.Option(
            False, "--json", "-j", help="stdout 仅输出一个完整 JSON 结果"
        ),
    ):
        """创建或加载会话并发送提示；默认拒绝工具权限请求，Ctrl+C 取消。"""
        _execute(
            agent,
            agent_arg,
            cwd,
            15,
            json_output,
            text=text,
            auth_method=auth_method,
            session=session,
            prompt_timeout=timeout,
        )


def _execute(
    agent,
    agent_args,
    cwd,
    connect_timeout,
    json_output,
    *,
    text=None,
    auth_method=None,
    session=None,
    prompt_timeout=None,
) -> None:
    # Importing --help and unrelated commands must not load the ACP SDK.
    from .core.acp_client import ACPClient

    def on_update(event):
        update = event["update"]
        content = update.get("content") or {}
        if (
            not json_output
            and update.get("sessionUpdate") == "agent_message_chunk"
            and content.get("type") == "text"
        ):
            typer.echo(content["text"], nl=False)

    async def run():
        if text is not None and not text.strip():
            raise MozikitError(ErrorCode.INVALID_PARAMETER, "Prompt must not be empty")
        async with ACPClient(
            agent,
            agent_args or (),
            cwd=cwd,
            on_update=on_update,
            connect_timeout=connect_timeout,
        ) as client:
            if text is None:
                return {"success": True, **client.initialization}
            if auth_method:
                await client.authenticate(auth_method)
            if session:
                await client.load_session(session)
            else:
                await client.new_session()
            result = await client.prompt(text, timeout=prompt_timeout)
            return {"success": result.stop_reason != "cancelled", **asdict(result)}

    try:
        result = asyncio.run(run())
    except KeyboardInterrupt:
        if json_output:
            typer.echo(
                json.dumps(
                    {
                        "success": False,
                        "error_code": ErrorCode.ACP_CANCELLED.value,
                        "error": "ACP operation cancelled",
                    }
                )
            )
        raise typer.Exit(130)
    except MozikitError as exc:
        if json_output:
            typer.echo(json.dumps(exc.to_dict(), ensure_ascii=False))
        else:
            typer.echo(f"错误: {exc}", err=True)
        raise typer.Exit(1)
    if json_output or text is None:
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        typer.echo()
    if result.get("stop_reason") == "cancelled":
        raise typer.Exit(130)
