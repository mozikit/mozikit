"""Client discovery and startup for the user-scoped Runtime Daemon."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Optional, Tuple
from urllib.request import Request, urlopen

from .runtime_paths import get_runtime_dir
from .runtime_protocol import expected_identity


class RuntimeClient:
    def __init__(self, runtime_dir: Optional[Path] = None) -> None:
        self.runtime_dir = runtime_dir or get_runtime_dir()
        self.connection_path = self.runtime_dir / "connection.json"
        self.token_path = self.runtime_dir / "auth.token"
        self.startup_error_path = self.runtime_dir / "startup-error.json"

    def is_configured(self) -> bool:
        if os.path.isfile(self.runtime_dir / "runtimes.json"):
            return True
        plugin_root = self.runtime_dir / "plugins"
        if plugin_root.is_dir() and next(plugin_root.rglob("runtime.json"), None) is not None:
            return True
        from src.core import resolve_workspace

        workspace = resolve_workspace()
        if workspace.is_dir():
            for path in workspace.rglob("workflow.json"):
                try:
                    document = json.loads(path.read_text(encoding="utf-8"))
                    if document.get("active") is True and document.get("triggers"):
                        return True
                except (OSError, json.JSONDecodeError, AttributeError):
                    continue
        return False

    def connection_document(self) -> dict:
        with self.connection_path.open("r", encoding="utf-8") as stream:
            document = json.load(stream)
        if not isinstance(document, dict):
            raise RuntimeError("Runtime Daemon connection metadata is invalid")
        return document

    def connection(self) -> Tuple[str, str]:
        document = self.connection_document()
        url = document.get("url", "")
        token = self.token_path.read_text(encoding="utf-8").strip()
        if not url or not token:
            raise RuntimeError("Runtime Daemon connection metadata is incomplete")
        return url.rstrip("/"), token

    def _health(self) -> Optional[dict]:
        try:
            url, token = self.connection()
            request = Request(
                f"{url}/health",
                headers={"Authorization": f"Bearer {token}"},
            )
            with urlopen(request, timeout=1) as response:
                if response.status != 200:
                    return None
                document = json.loads(response.read().decode("utf-8"))
                return document if isinstance(document, dict) else None
        except Exception:
            return None

    def is_alive(self) -> bool:
        return self._health() is not None

    def is_running(self) -> bool:
        health = self._health()
        if health is None:
            return False
        try:
            connection = self.connection_document()
        except Exception:
            return False
        expected = expected_identity(self.runtime_dir)
        return (
            all(health.get(key) == value for key, value in expected.items())
            and all(connection.get(key) == value for key, value in expected.items())
            and health.get("instance_id") == connection.get("instance_id")
        )

    def _daemon_command(self):
        if getattr(sys, "frozen", False):
            return [sys.executable, "runtime", "daemon"]
        return [sys.executable, "-m", "src.core.runtime_daemon"]

    def _startup_error(self) -> str:
        try:
            document = json.loads(self.startup_error_path.read_text(encoding="utf-8"))
            return document.get("message") or document.get("error_type") or "unknown error"
        except Exception:
            return "unknown error"

    def ensure_running(self, required: bool = False, timeout: float = 10.0) -> bool:
        if self.is_running():
            return True
        if not required and not self.is_configured():
            return False

        if self.is_alive():
            self.stop_daemon()
            stop_deadline = time.monotonic() + min(timeout, 5.0)
            while self.is_alive() and time.monotonic() < stop_deadline:
                time.sleep(0.05)
            if self.is_alive():
                raise RuntimeError("Incompatible Runtime Daemon did not stop")

        kwargs = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
        from src.core import resolve_workspace

        daemon_env = os.environ.copy()
        daemon_env["MOZIKIT_WORKSPACE"] = str(resolve_workspace().resolve())
        kwargs["env"] = daemon_env
        if os.name == "nt":
            kwargs["creationflags"] = 0x08000000 | 0x00000008
        else:
            kwargs["start_new_session"] = True
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.startup_error_path.unlink(missing_ok=True)
        log_stream = (self.runtime_dir / "daemon.log").open("ab")
        kwargs["stdout"] = log_stream
        kwargs["stderr"] = subprocess.STDOUT
        try:
            process = subprocess.Popen(
                self._daemon_command(),
                cwd=str(Path(__file__).resolve().parents[2]),
                **kwargs,
            )
        except Exception as exc:
            raise RuntimeError(f"Could not start Runtime Daemon: {exc}") from exc
        finally:
            log_stream.close()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.is_running():
                return True
            return_code = process.poll()
            if return_code is not None and return_code != 2:
                raise RuntimeError(
                    f"Runtime Daemon startup failed: {self._startup_error()}"
                )
            time.sleep(0.05)
        raise RuntimeError("Runtime Daemon did not become ready")

    def stop_daemon(self) -> bool:
        if not self.is_alive():
            return False
        url, token = self.connection()
        request = Request(
            f"{url}/shutdown",
            data=b"{}",
            headers={"Authorization": f"Bearer {token}"},
            method="POST",
        )
        with urlopen(request, timeout=2) as response:
            return response.status == 202

    def worker_env(self) -> Dict[str, str]:
        if not self.is_running():
            return {}
        url, token = self.connection()
        return {
            "MOZIKIT_RUNTIME_URL": url,
            "MOZIKIT_RUNTIME_TOKEN": token,
        }

    def trigger_status(self) -> dict:
        url, token = self.connection()
        request = Request(
            f"{url}/triggers/status",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urlopen(request, timeout=2) as response:
            return json.loads(response.read().decode("utf-8"))
