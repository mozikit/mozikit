"""Application-lifetime owner for runtime extensions and their HTTP service."""

from __future__ import annotations

import json
import os
from pathlib import Path
from threading import RLock
from typing import Callable, Iterable, List, Optional

from .log_manager import get_logger
from .runtime_manager import RuntimeManager, RuntimeService
from .runtime_registry import RuntimeRegistry, runtime_registry
from .runtime_paths import get_runtime_dir

logger = get_logger("runtime_host")


class RuntimeHost:
    """Own all runtime infrastructure for one Mozikit process.

    Runtime plugins and instance configuration come from the stable per-user
    Mozikit app-data runtime directory.
    Both locations can be overridden for embedding and tests.
    """

    def __init__(
        self,
        config_path: Optional[str] = None,
        plugin_root: Optional[str] = None,
        registry: Optional[RuntimeRegistry] = None,
        host: Optional[str] = None,
        port: Optional[int] = None,
        definition_paths: Optional[Iterable[str]] = None,
        auth_token: str = "",
        shutdown_callback: Optional[Callable[[], None]] = None,
    ) -> None:
        runtime_dir = get_runtime_dir()
        self.config_path = Path(
            config_path
            or os.environ.get("MOZIKIT_RUNTIME_CONFIG", str(runtime_dir / "runtimes.json"))
        )
        self.plugin_root = Path(
            plugin_root
            or os.environ.get("MOZIKIT_RUNTIME_PLUGIN_DIR", str(runtime_dir / "plugins"))
        )
        self.registry = registry or runtime_registry
        self.manager = RuntimeManager(self.registry)
        service_host = host or os.environ.get("MOZIKIT_RUNTIME_HOST", "127.0.0.1")
        service_port = port
        if service_port is None:
            service_port = int(os.environ.get("MOZIKIT_RUNTIME_PORT", "48765"))
        if not auth_token:
            raise ValueError("RuntimeHost requires an IPC authentication token")
        self.service = RuntimeService(
            self.manager,
            service_host,
            service_port,
            auth_token=auth_token,
            shutdown_callback=shutdown_callback,
        )
        self.definition_paths = [Path(path) for path in (definition_paths or [])]
        self._started = False
        self._lock = RLock()

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._started

    @property
    def base_url(self) -> str:
        return self.service.base_url

    def _discover_definition_paths(self) -> List[Path]:
        paths = list(self.definition_paths)
        if self.plugin_root.is_dir():
            paths.extend(self.plugin_root.rglob("runtime.json"))

        unique = {}
        for path in paths:
            resolved = path.resolve()
            unique[str(resolved)] = resolved
        return sorted(unique.values(), key=lambda path: str(path))

    def load_instance_config(self) -> List[dict]:
        """Load and validate enabled/disabled runtime instance definitions."""
        if not os.path.isfile(self.config_path):
            return []
        with self.config_path.open("r", encoding="utf-8") as stream:
            document = json.load(stream)

        if isinstance(document, list):
            instances = document
        elif isinstance(document, dict) and "runtimes" in document:
            instances = document["runtimes"]
        elif isinstance(document, dict) and "runtime_type" in document:
            instances = [document]
        else:
            raise ValueError(
                "runtime config must be an instance, a list, or a runtimes object"
            )

        if not isinstance(instances, list):
            raise ValueError("runtimes must be a list")

        validated = []
        for index, item in enumerate(instances):
            if not isinstance(item, dict):
                raise ValueError(f"runtime config item {index} must be an object")
            runtime_type = item.get("runtime_type")
            runtime_id = item.get("runtime_id")
            enabled = item.get("enabled", True)
            config = item.get("config", {})
            if not isinstance(runtime_type, str) or not runtime_type:
                raise ValueError(f"runtime config item {index} requires runtime_type")
            if not isinstance(runtime_id, str) or not runtime_id:
                raise ValueError(f"runtime config item {index} requires runtime_id")
            if not isinstance(enabled, bool):
                raise ValueError(f"runtime config item {index} enabled must be boolean")
            if not isinstance(config, dict):
                raise ValueError(f"runtime config item {index} config must be an object")
            validated.append(
                {
                    "runtime_type": runtime_type,
                    "runtime_id": runtime_id,
                    "enabled": enabled,
                    "config": config,
                }
            )
        return validated

    def start(self) -> None:
        """Load plugins/config, start enabled runtimes, then expose HTTP IPC."""
        with self._lock:
            if self._started:
                return
            try:
                for definition_path in self._discover_definition_paths():
                    self.registry.load_definition(str(definition_path))
                for instance in self.load_instance_config():
                    if instance["enabled"]:
                        self.manager.start_runtime(
                            instance["runtime_type"],
                            instance["runtime_id"],
                            instance["config"],
                        )
                self.service.start()
                self._started = True
                logger.info(
                    "Runtime Host started at %s with %d instance(s)",
                    self.base_url,
                    len(self.manager.instances),
                )
            except Exception:
                self.service.stop()
                self.manager.stop_all()
                raise

    def stop(self) -> None:
        """Stop accepting IPC calls, then stop every managed runtime."""
        with self._lock:
            if not self._started and not self.manager.instances:
                return
            service_error = None
            try:
                self.service.stop()
            except Exception as exc:
                service_error = exc
            finally:
                try:
                    self.manager.stop_all()
                finally:
                    self._started = False
                    logger.info("Runtime Host stopped")
            if service_error is not None:
                raise service_error

    def __enter__(self) -> "RuntimeHost":
        self.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.stop()
