"""Native ACP workflow node shared by desktop, CLI and scheduled runs."""

from __future__ import annotations

import asyncio
import contextlib
import math
from dataclasses import asdict
from pathlib import Path

from .acp_client import ACPClient
from .exceptions import ErrorCode, MozikitError
from .expression_engine import render_expressions


ACP_AGENT_CONFIG_SCHEMA = {
    "agent": {
        "type": "string",
        "label": "Agent 可执行文件",
        "default": "codex-acp",
        "required": True,
    },
    "args": {"type": "string_list", "label": "Agent 参数（每行一个）", "default": []},
    "cwd": {
        "type": "path",
        "label": "工作目录",
        "default": "",
        "placeholder": "默认为工作流运行目录",
    },
    "prompt": {
        "type": "text",
        "label": "提示",
        "default": "",
        "placeholder": "填写提示或连接 prompt 输入端口；支持 {% input %} 等表达式",
    },
    "auth_method": {"type": "string", "label": "认证方式 ID（可选）", "default": ""},
    "session_id": {"type": "string", "label": "加载会话 ID（可选）", "default": ""},
    "timeout": {
        "type": "int",
        "label": "节点超时（秒）",
        "default": 120,
        "minimum": 1,
        "maximum": 3600,
    },
}
ACP_AGENT_INPUT_SCHEMA = {
    "prompt": {"type": "string", "description": "配置提示为空时，使用此端口传入的提示"},
    "input": {"type": "any", "description": "可通过 {% input %} 引用的上游数据"},
}
ACP_AGENT_OUTPUT_SCHEMA = {
    "text": {"type": "string", "description": "Agent 回复文本"},
    "session_id": {"type": "string"},
    "stop_reason": {"type": "string"},
    "updates": {"type": "array", "description": "本轮消息和工具状态更新"},
}


class ACPAgentNativeExecutor:
    # Native extensions that opt in receive host cancellation and directory
    # context; existing executors keep their original call signature.
    supports_execution_context = True

    def execute(
        self,
        *,
        node,
        input_data: dict,
        context: dict,
        timeout=None,
        progress_callback=None,
        log_callback=None,
        execution_context=None,
    ) -> dict:
        config = render_expressions(node.config or {}, {**context, **input_data})
        agent = _string(config.get("agent", "codex-acp"), "agent", required=True)
        prompt = config.get("prompt")
        if prompt in (None, ""):
            prompt = input_data.get("prompt", "")
        prompt = _string(prompt, "prompt", required=True)
        args = config.get("args", [])
        if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
            raise _invalid("args must be an array of strings")
        auth = _string(config.get("auth_method", ""), "auth_method")
        session = _string(config.get("session_id", ""), "session_id")
        working_dir = _string(config.get("cwd", ""), "cwd")
        base = Path(
            execution_context.workflow_dir if execution_context else Path.cwd()
        ).resolve()
        cwd = Path(working_dir).expanduser() if working_dir else Path(base)
        if not cwd.is_absolute():
            cwd = Path(base) / cwd
        if not cwd.is_dir():
            raise _invalid("ACP working directory does not exist")
        limit = _positive_timeout(config.get("timeout", 120))
        if timeout is not None:
            limit = min(limit, _positive_timeout(timeout))
        stop_event = execution_context.stop_event if execution_context else None

        def update(event):
            if not log_callback:
                return
            message = event["update"]
            kind = message.get("sessionUpdate")
            if kind == "agent_message_chunk":
                content = message.get("content") or {}
                if content.get("type") == "text":
                    log_callback(content["text"])
            elif kind in {"tool_call", "tool_call_update"}:
                log_callback(
                    f"[ACP tool] {message.get('title') or message.get('toolCallId', '')}: {message.get('status', '')}"
                )

        async def talk():
            if progress_callback:
                progress_callback(0, "连接 ACP Agent")
            async with ACPClient(
                agent,
                args,
                cwd=cwd.resolve(),
                on_update=update,
                connect_timeout=min(15, limit),
            ) as client:
                if auth:
                    await client.authenticate(auth)
                if session:
                    await client.load_session(session)
                else:
                    await client.new_session()
                if progress_callback:
                    progress_callback(20, "等待 Agent 回复")
                result = await client.prompt(prompt)
                if result.stop_reason == "cancelled":
                    raise MozikitError(
                        ErrorCode.ACP_CANCELLED, "ACP agent cancelled the turn"
                    )
                if result.stop_reason != "end_turn":
                    raise MozikitError(
                        ErrorCode.ACP_TURN_INCOMPLETE,
                        f"ACP turn did not complete: {result.stop_reason}",
                    )
                if progress_callback:
                    progress_callback(100, "Agent 已完成")
                return asdict(result)

        async def run():
            if stop_event is not None and stop_event.is_set():
                raise MozikitError(ErrorCode.ACP_CANCELLED, "Workflow stop requested")
            operation = asyncio.create_task(talk())

            async def watch_stop():
                while not stop_event.is_set():
                    await asyncio.sleep(0.05)
                operation.cancel()

            watcher = (
                asyncio.create_task(watch_stop()) if stop_event is not None else None
            )
            try:
                return await asyncio.wait_for(operation, limit)
            except asyncio.TimeoutError as exc:
                raise MozikitError(
                    ErrorCode.ACP_TIMEOUT,
                    "ACP node timed out; agent cancellation was requested",
                    cause=exc,
                ) from exc
            except asyncio.CancelledError as exc:
                if stop_event is not None and stop_event.is_set():
                    raise MozikitError(
                        ErrorCode.ACP_CANCELLED, "Workflow stop requested", cause=exc
                    ) from exc
                raise
            finally:
                if watcher is not None:
                    watcher.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await watcher

        return asyncio.run(run())


def _string(value, field: str, *, required: bool = False) -> str:
    if not isinstance(value, str) or (required and not value.strip()):
        raise _invalid(
            f"{field} must be {'a non-empty string' if required else 'a string'}"
        )
    return value


def _positive_timeout(value) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise _invalid("timeout must be a positive finite number") from None
    if isinstance(value, bool) or not math.isfinite(number) or number <= 0:
        raise _invalid("timeout must be a positive finite number")
    return number


def _invalid(message: str) -> MozikitError:
    return MozikitError(ErrorCode.NODE_VALIDATION_FAILED, message)


def register_acp_agent_executor() -> None:
    from .node_extension_registries import native_executors

    native_executors.register("acp_agent", ACPAgentNativeExecutor())
