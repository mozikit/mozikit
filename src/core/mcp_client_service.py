"""Synchronous bridge to the process-wide asynchronous MCP client manager."""
from __future__ import annotations

import asyncio
import threading
from typing import Any

from .mcp_client_manager import MCPClientManager
from .mcp_models import MCPConnectionTestResult, MCPToolDefinition, MCPToolResult


class MCPClientService:
    """Own one event loop for the lifetime of the embedding Mozikit process."""

    def __init__(self, manager: MCPClientManager | None = None):
        self.manager = manager or MCPClientManager()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ready = threading.Event()
        self._lock = threading.RLock()
        self._closed = False

    def _ensure_started(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if self._closed:
                raise RuntimeError("MCPClientService is closed")
            if self._thread and self._thread.is_alive():
                return self._loop  # type: ignore[return-value]
            self._ready.clear()
            self._thread = threading.Thread(target=self._run_loop,
                                            name="mozikit-mcp-loop", daemon=True)
            self._thread.start()
        if not self._ready.wait(5):
            raise RuntimeError("MCP client event loop failed to start")
        return self._loop  # type: ignore[return-value]

    def _run_loop(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._ready.set()
        try:
            loop.run_forever()
        finally:
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()
            self._loop = None

    def _submit(self, awaitable, timeout: float | None):
        if self._closed:
            close = getattr(awaitable, "close", None)
            if close:
                close()
            raise RuntimeError("MCPClientService is closed")
        loop = self._ensure_started()
        future = asyncio.run_coroutine_threadsafe(awaitable, loop)
        try:
            return future.result(timeout)
        except (TimeoutError, asyncio.TimeoutError):
            future.cancel()
            raise

    def list_tools(self, server_id: str, timeout: float = 15) -> list[MCPToolDefinition]:
        return self._submit(self.manager.list_tools(server_id, timeout=timeout), timeout)

    def call_tool(self, server_id: str, tool_name: str, arguments: dict,
                  timeout: float | None = None) -> MCPToolResult:
        wait_timeout = timeout if timeout is not None else self.manager.default_call_timeout + 5
        return self._submit(self.manager.call_tool(server_id, tool_name, arguments,
                                                   timeout=timeout), wait_timeout)

    def test_connection(self, server_id: str, timeout: float = 15) -> MCPConnectionTestResult:
        return self._submit(self.manager.test_connection(server_id, timeout=timeout), timeout + 1)

    def invalidate(self, server_id: str) -> None:
        self._submit(self.manager.invalidate(server_id), None)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            loop, thread = self._loop, self._thread
        if loop and loop.is_running():
            future = asyncio.run_coroutine_threadsafe(self.manager.close_all(), loop)
            try:
                future.result(10)
            finally:
                loop.call_soon_threadsafe(loop.stop)
        if thread and thread is not threading.current_thread():
            thread.join(10)


_default_service: MCPClientService | None = None
_default_lock = threading.Lock()


def get_mcp_client_service() -> MCPClientService:
    global _default_service
    with _default_lock:
        if _default_service is None:
            _default_service = MCPClientService()
        return _default_service
