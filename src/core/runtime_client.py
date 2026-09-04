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


class RuntimeClient:
    def __init__(self, runtime_dir: Optional[Path] = None) -> None:
        self.runtime_dir = runtime_dir or get_runtime_dir()
        self.connection_path = self.runtime_dir / "connection.json"
        self.token_path = self.runtime_dir / "auth.token"

    def is_configured(self) -> bool:
        if os.path.isfile(self.runtime_dir / "runtimes.json"):
            return True
        plugin_root = self.runtime_dir / "plugins"
        return plugin_root.is_dir() and next(plugin_root.rglob("runtime.json"), None) is not None

    def connection(self) -> Tuple[str, str]:
        with self.connection_path.open("r", encoding="utf-8") as stream:
            document = json.load(stream)
        url = document.get("url", "")
        token = self.token_path.read_text(encoding="utf-8").strip()
        if not url or not token:
            raise RuntimeError("Runtime Daemon connection metadata is incomplete")
        return url.rstrip("/"), token

    def is_running(self) -> bool:
        try:
            url, token = self.connection()
            request = Request(
                f"{url}/health",
                headers={"Authorization": f"Bearer {token}"},
            )
            with urlopen(request, timeout=1) as response:
                return response.status == 200
        except Exception:
            return False

    def ensure_running(self, required: bool = False, timeout: float = 10.0) -> bool:
        if self.is_running():
            return True
        if not required and not self.is_configured():
            return False

        kwargs = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
        if os.name == "nt":
            kwargs["creationflags"] = 0x08000000 | 0x00000008
        else:
            kwargs["start_new_session"] = True
        subprocess.Popen(
            [sys.executable, "-m", "src.core.runtime_daemon"],
            cwd=str(Path(__file__).resolve().parents[2]),
            **kwargs,
        )
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.is_running():
                return True
            time.sleep(0.05)
        raise RuntimeError("Runtime Daemon did not become ready")

    def stop_daemon(self) -> bool:
        if not self.is_running():
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
