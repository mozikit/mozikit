"""Headless ACP client. The official SDK owns JSON-RPC and stdio transport.

One instance owns one agent process and one current session. Callers may send
multiple turns, consume updates, and decide permission requests without Qt.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping, Sequence

from .exceptions import ErrorCode, MozikitError


@dataclass
class ACPTurnResult:
    session_id: str
    text: str
    stop_reason: str
    updates: list[dict[str, Any]]


class ACPClient:
    """Connect to an installed ACP executable, never through a shell.

    ``on_update`` receives wire-shaped session updates. ``permission_handler``
    is async and returns an advertised option ID, or None to cancel the request.
    Without a handler, requests select reject_once when available, or cancel.
    Filesystem and terminal host capabilities are deliberately not advertised.
    """

    def __init__(
        self,
        command: str,
        args: Sequence[str] = (),
        *,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
        on_update: Callable[[dict[str, Any]], None] | None = None,
        permission_handler: Callable[[dict[str, Any]], Awaitable[str | None]]
        | None = None,
        connect_timeout: float = 15,
        cancel_timeout: float = 3,
    ):
        if not command.strip() or connect_timeout <= 0 or cancel_timeout <= 0:
            raise MozikitError(
                ErrorCode.INVALID_PARAMETER,
                "Agent command and positive timeouts are required",
            )
        self.command = command
        self.args = tuple(args)
        self.cwd = Path(cwd or Path.cwd()).resolve()
        if not self.cwd.is_dir():
            raise MozikitError(
                ErrorCode.INVALID_PARAMETER, "ACP working directory does not exist"
            )
        self.env = dict(os.environ)
        self.env.update(env or {})
        self.on_update = on_update
        self.permission_handler = permission_handler
        self.connect_timeout = connect_timeout
        self.cancel_timeout = cancel_timeout
        self.initialization: dict[str, Any] = {}
        self.session_id: str | None = None
        self._connection = None
        self._transport = None
        self._process = None
        self._prompt_task: asyncio.Task | None = None
        self._prompt_started = asyncio.Event()
        self._updates: list[dict[str, Any]] = []
        self._text: list[str] = []
        self._cancelling = False
        self._request_pending = False

    async def __aenter__(self) -> ACPClient:
        await self.connect()
        return self

    async def __aexit__(self, *_):
        await self.close()

    async def connect(self) -> dict[str, Any]:
        if self._transport is not None:
            raise MozikitError(
                ErrorCode.ACP_INVALID_STATE, "ACP client is already connected"
            )
        try:
            from acp import PROTOCOL_VERSION, spawn_agent_process
            from acp.schema import ClientCapabilities, Implementation
        except ImportError as exc:
            raise MozikitError(
                ErrorCode.ACP_DEPENDENCY_MISSING,
                "Install agent-client-protocol>=0.12.1,<0.13 (Python 3.10–3.14)",
                cause=exc,
            ) from exc
        from . import __version__

        self._transport = contextlib.AsyncExitStack()
        try:
            self._connection, self._process = await self._transport.enter_async_context(
                spawn_agent_process(
                    self,
                    self.command,
                    *self.args,
                    cwd=self.cwd,
                    env=self.env,
                    transport_kwargs={"stderr": None},
                )
            )
            response = await self._request(
                self._connection.initialize(
                    protocol_version=PROTOCOL_VERSION,
                    client_capabilities=ClientCapabilities(),
                    client_info=Implementation(name="mozikit", version=__version__),
                ),
                "initialize",
            )
            if response.protocol_version != PROTOCOL_VERSION:
                raise MozikitError(
                    ErrorCode.ACP_PROTOCOL_ERROR,
                    "Agent negotiated an unsupported ACP protocol version",
                )
            self.initialization = _wire(response)
            return self.initialization
        except BaseException as exc:
            await self.close()
            if isinstance(exc, OSError):
                raise MozikitError(
                    ErrorCode.ACP_PROCESS_START_FAILED,
                    "Unable to start ACP agent; check the executable and working directory",
                    cause=exc,
                ) from exc
            raise

    async def authenticate(self, method_id: str) -> None:
        self._require_idle()
        methods = self.initialization.get("authMethods") or []
        if not any(method.get("id") == method_id for method in methods):
            raise MozikitError(
                ErrorCode.ACP_AUTHENTICATION_FAILED,
                "Authentication method was not advertised by the agent",
            )
        await self._request(
            self._connection.authenticate(method_id=method_id), "authenticate"
        )

    async def new_session(self) -> str:
        self._require_idle()
        response = await self._request(
            self._connection.new_session(cwd=str(self.cwd), mcp_servers=[]),
            "session/new",
        )
        self.session_id = response.session_id
        return self.session_id

    async def load_session(self, session_id: str) -> str:
        self._require_idle()
        if not session_id.strip():
            raise MozikitError(
                ErrorCode.INVALID_PARAMETER, "Session ID must not be empty"
            )
        if not (self.initialization.get("agentCapabilities") or {}).get("loadSession"):
            raise MozikitError(
                ErrorCode.ACP_CAPABILITY_UNSUPPORTED,
                "Agent does not support session/load",
            )
        # session/load replays history before its response; route those updates
        # immediately, without including them in the next prompt's result.
        previous_session = self.session_id
        self.session_id = session_id
        try:
            await self._request(
                self._connection.load_session(
                    session_id=session_id, cwd=str(self.cwd), mcp_servers=[]
                ),
                "session/load",
            )
        except BaseException:
            if self._connection is not None:
                self.session_id = previous_session
            raise
        return session_id

    async def prompt(self, text: str, *, timeout: float | None = None) -> ACPTurnResult:
        self._require_idle()
        if not self.session_id:
            raise MozikitError(
                ErrorCode.ACP_INVALID_STATE, "Create or load an ACP session first"
            )
        if not text.strip() or (timeout is not None and timeout <= 0):
            raise MozikitError(
                ErrorCode.INVALID_PARAMETER,
                "Prompt must not be empty and timeout must be positive",
            )
        from acp.schema import TextContentBlock

        session_id = self.session_id
        self._updates, self._text = [], []
        self._cancelling = False
        self._prompt_started.clear()

        async def send_prompt():
            self._prompt_started.set()
            return await self._connection.prompt(
                session_id=session_id,
                prompt=[TextContentBlock(type="text", text=text)],
            )

        task = asyncio.create_task(send_prompt())
        self._prompt_task = task
        try:
            # Shield keeps the protocol request alive until session/cancel is sent.
            response = await asyncio.wait_for(asyncio.shield(task), timeout)
            return ACPTurnResult(
                session_id,
                "".join(self._text),
                response.stop_reason,
                list(self._updates),
            )
        except asyncio.TimeoutError as exc:
            await self.cancel()
            raise MozikitError(
                ErrorCode.ACP_TIMEOUT,
                "ACP prompt timed out; cancellation was requested",
                cause=exc,
            ) from exc
        except asyncio.CancelledError:
            await self.cancel()
            raise
        except Exception as exc:
            raise self._translate(exc, "session/prompt") from exc
        finally:
            if self._prompt_task is task:
                self._prompt_task = None

    async def cancel(self) -> None:
        """Cancel the active turn; disconnect an agent that ignores cancellation."""
        task = self._prompt_task
        if task is None or task.done():
            return
        self._cancelling = True
        try:
            # An immediate host cancellation must follow the prompt on the wire.
            await asyncio.wait_for(self._prompt_started.wait(), self.cancel_timeout)
            await asyncio.wait_for(
                self._connection.cancel(session_id=self.session_id), self.cancel_timeout
            )
            await asyncio.wait_for(asyncio.shield(task), self.cancel_timeout)
        except Exception:
            if not task.done():
                await self.close()

    async def close(self) -> None:
        task, self._prompt_task = self._prompt_task, None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        transport, self._transport = self._transport, None
        self._connection = None
        self.session_id = None
        self.initialization = {}
        if transport is not None:
            await transport.aclose()
        self._process = None

    async def session_update(self, session_id: str, update: Any, **kwargs: Any) -> None:
        if session_id != self.session_id:
            return
        event = {"sessionId": session_id, "update": _wire(update)}
        if self._prompt_task is not None:
            self._updates.append(event)
            content = event["update"].get("content") or {}
            if (
                event["update"].get("sessionUpdate") == "agent_message_chunk"
                and content.get("type") == "text"
            ):
                self._text.append(content["text"])
        if self.on_update:
            self.on_update(event)

    async def request_permission(
        self, session_id: str, tool_call: Any, options: list[Any], **kwargs: Any
    ):
        from acp.schema import AllowedOutcome, DeniedOutcome, RequestPermissionResponse

        selected = None
        if session_id == self.session_id and not self._cancelling:
            event = {
                "sessionId": session_id,
                "toolCall": _wire(tool_call),
                "options": [_wire(o) for o in options],
            }
            if self.permission_handler:
                selected = await self.permission_handler(event)
            else:
                selected = next(
                    (o.option_id for o in options if o.kind == "reject_once"), None
                )
        if self._cancelling or not any(o.option_id == selected for o in options):
            selected = None
        outcome = (
            AllowedOutcome(outcome="selected", option_id=selected)
            if selected is not None
            else DeniedOutcome(outcome="cancelled")
        )
        return RequestPermissionResponse(outcome=outcome)

    def _require_idle(self) -> None:
        if self._connection is None:
            raise MozikitError(
                ErrorCode.ACP_INVALID_STATE, "ACP client is not connected"
            )
        if self._prompt_task is not None:
            raise MozikitError(
                ErrorCode.ACP_PROMPT_RUNNING, "An ACP prompt is already running"
            )
        if self._request_pending:
            raise MozikitError(
                ErrorCode.ACP_INVALID_STATE, "Another ACP session operation is running"
            )

    async def _request(self, awaitable, operation: str):
        self._request_pending = True
        try:
            return await asyncio.wait_for(awaitable, self.connect_timeout)
        except asyncio.TimeoutError as exc:
            await self.close()
            raise MozikitError(
                ErrorCode.ACP_TIMEOUT, f"ACP {operation} timed out", cause=exc
            ) from exc
        except asyncio.CancelledError:
            await self.close()
            raise
        except Exception as exc:
            raise self._translate(exc, operation) from exc
        finally:
            self._request_pending = False

    @staticmethod
    def _translate(exc: Exception, operation: str) -> MozikitError:
        from acp import RequestError
        from pydantic import ValidationError

        if isinstance(exc, MozikitError):
            return exc
        if isinstance(exc, RequestError):
            if exc.code == -32000:
                return MozikitError(
                    ErrorCode.ACP_AUTH_REQUIRED,
                    "Agent requires authentication; log in with its CLI or select --auth-method",
                    cause=exc,
                )
            code = (
                ErrorCode.ACP_AUTHENTICATION_FAILED
                if operation == "authenticate"
                else ErrorCode.ACP_REQUEST_FAILED
            )
            return MozikitError(
                code, f"ACP {operation} failed (JSON-RPC {exc.code})", cause=exc
            )
        if isinstance(exc, (ConnectionError, EOFError, BrokenPipeError)):
            return MozikitError(
                ErrorCode.ACP_PROCESS_EXITED, "ACP agent disconnected", cause=exc
            )
        code = (
            ErrorCode.ACP_PROTOCOL_ERROR
            if isinstance(exc, ValidationError)
            else ErrorCode.ACP_REQUEST_FAILED
        )
        return MozikitError(code, f"ACP {operation} failed", cause=exc)


def _wire(model: Any) -> dict[str, Any]:
    return model.model_dump(mode="json", by_alias=True, exclude_none=True)
