"""Process-scoped runtime ownership and localhost HTTP transport."""

from __future__ import annotations

import json
import hmac
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, Optional, Tuple
from urllib.parse import unquote, urlsplit

from .runtime_base import RuntimeBase
from .runtime_registry import RuntimeRegistry, runtime_registry


class RuntimeManager:
    """Own runtime instances independently from any WorkflowExecutor run."""

    def __init__(self, registry: Optional[RuntimeRegistry] = None) -> None:
        self.registry = registry or runtime_registry
        self.instances: Dict[str, RuntimeBase] = {}
        self._instance_locks: Dict[str, threading.RLock] = {}
        self._lock = threading.RLock()

    def start_runtime(
        self,
        runtime_type: str,
        runtime_id: str,
        config: Optional[dict] = None,
    ) -> RuntimeBase:
        runtime_class = self.registry.get(runtime_type)
        if runtime_class is None:
            raise KeyError(f"unknown runtime type: {runtime_type}")

        with self._lock:
            if runtime_id in self.instances:
                raise ValueError(f"runtime already started: {runtime_id}")
            runtime = runtime_class(runtime_id, config or {})
            runtime.start()
            self.instances[runtime_id] = runtime
            self._instance_locks[runtime_id] = threading.RLock()
            return runtime

    def call(
        self,
        runtime_id: str,
        action: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            runtime = self.instances.get(runtime_id)
            call_lock = self._instance_locks.get(runtime_id)
        if runtime is None or call_lock is None:
            raise KeyError(f"runtime not started: {runtime_id}")
        if not isinstance(action, str) or not action:
            raise ValueError("action must be a non-empty string")
        if params is None:
            params = {}
        if not isinstance(params, dict):
            raise TypeError("params must be an object")

        with call_lock:
            result = runtime.call(action, params)
        if not isinstance(result, dict):
            raise TypeError("runtime call result must be an object")
        return result

    def health(self, runtime_id: str) -> dict:
        with self._lock:
            runtime = self.instances.get(runtime_id)
            call_lock = self._instance_locks.get(runtime_id)
        if runtime is None or call_lock is None:
            raise KeyError(f"runtime not started: {runtime_id}")
        with call_lock:
            result = runtime.health()
        if not isinstance(result, dict):
            raise TypeError("runtime health result must be an object")
        return result

    def stop_runtime(self, runtime_id: str) -> None:
        with self._lock:
            runtime = self.instances.pop(runtime_id, None)
            call_lock = self._instance_locks.pop(runtime_id, None)
        if runtime is None or call_lock is None:
            raise KeyError(f"runtime not started: {runtime_id}")
        with call_lock:
            runtime.stop()

    def stop_all(self) -> None:
        with self._lock:
            runtime_ids = list(self.instances)
        errors = []
        for runtime_id in reversed(runtime_ids):
            try:
                self.stop_runtime(runtime_id)
            except Exception as exc:  # continue stopping the remaining runtimes
                errors.append((runtime_id, exc))
        if errors:
            details = ", ".join(f"{runtime_id}: {exc}" for runtime_id, exc in errors)
            raise RuntimeError(f"failed to stop runtimes: {details}")


class RuntimeService:
    """Small localhost HTTP bridge from workflow workers to RuntimeManager."""

    MAX_REQUEST_BYTES = 1024 * 1024

    def __init__(
        self,
        manager: RuntimeManager,
        host: str = "127.0.0.1",
        port: int = 48765,
        auth_token: str = "",
        shutdown_callback: Optional[Callable[[], None]] = None,
        health_metadata: Optional[dict] = None,
    ) -> None:
        if host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("the first runtime service version only supports localhost")
        self.manager = manager
        self.host = host
        self.port = port
        self.auth_token = auth_token
        self.shutdown_callback = shutdown_callback
        self.health_metadata = dict(health_metadata or {})
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    @property
    def address(self) -> Tuple[str, int]:
        if self._server is None:
            return self.host, self.port
        bound_host, bound_port = self._server.server_address[:2]
        return str(bound_host), int(bound_port)

    @property
    def base_url(self) -> str:
        host, port = self.address
        return f"http://{host}:{port}"

    def start(self) -> None:
        if self._server is not None:
            return

        manager = self.manager
        max_request_bytes = self.MAX_REQUEST_BYTES
        auth_token = self.auth_token
        shutdown_callback = self.shutdown_callback
        health_metadata = self.health_metadata

        class Handler(BaseHTTPRequestHandler):
            def _write_json(self, status: int, payload: dict) -> None:
                data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _runtime_id(self, suffix: str) -> Optional[str]:
                parts = [unquote(part) for part in urlsplit(self.path).path.split("/") if part]
                if len(parts) == 3 and parts[0] == "runtime" and parts[2] == suffix:
                    return parts[1]
                return None

            def _authorized(self) -> bool:
                supplied = self.headers.get("Authorization", "")
                expected = f"Bearer {auth_token}"
                return bool(auth_token) and hmac.compare_digest(supplied, expected)

            def _require_authorization(self) -> bool:
                if self._authorized():
                    return True
                self._write_json(401, {"error": "unauthorized"})
                return False

            def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
                if not self._require_authorization():
                    return
                if urlsplit(self.path).path == "/shutdown":
                    if shutdown_callback is None:
                        self._write_json(404, {"error": "not found"})
                        return
                    self._write_json(202, {"status": "stopping"})
                    threading.Thread(target=shutdown_callback, daemon=True).start()
                    return
                runtime_id = self._runtime_id("call")
                if runtime_id is None:
                    self._write_json(404, {"error": "not found"})
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if length <= 0 or length > max_request_bytes:
                        raise ValueError("invalid request size")
                    body = json.loads(self.rfile.read(length).decode("utf-8"))
                    if not isinstance(body, dict):
                        raise ValueError("request body must be an object")
                    result = manager.call(
                        runtime_id,
                        body.get("action", ""),
                        body.get("params", {}),
                    )
                    self._write_json(200, result)
                except KeyError as exc:
                    self._write_json(404, {"error": str(exc)})
                except (TypeError, ValueError, json.JSONDecodeError) as exc:
                    self._write_json(400, {"error": str(exc)})
                except Exception as exc:
                    self._write_json(500, {"error": str(exc)})

            def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
                if not self._require_authorization():
                    return
                if urlsplit(self.path).path == "/health":
                    self._write_json(
                        200,
                        {
                            "status": "ok",
                            "service": "runtime",
                            **health_metadata,
                        },
                    )
                    return
                runtime_id = self._runtime_id("health")
                if runtime_id is None:
                    self._write_json(404, {"error": "not found"})
                    return
                try:
                    self._write_json(200, manager.health(runtime_id))
                except KeyError as exc:
                    self._write_json(404, {"error": str(exc)})
                except Exception as exc:
                    self._write_json(500, {"error": str(exc)})

            def log_message(self, format: str, *args: object) -> None:
                return

        self._server = ThreadingHTTPServer((self.host, self.port), Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="mozikit-runtime-service",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        server, thread = self._server, self._thread
        self._server = None
        self._thread = None
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5)

    def __enter__(self) -> "RuntimeService":
        self.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.stop()
