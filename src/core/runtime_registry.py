"""Registry and dynamic loader for runtime extension classes."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from threading import RLock
from typing import Dict, Optional, Type

from .runtime_base import RuntimeBase


class RuntimeRegistry:
    """Maps a plugin-defined ``runtime_type`` to its implementation class."""

    def __init__(self) -> None:
        self._items: Dict[str, Type[RuntimeBase]] = {}
        self._lock = RLock()

    def register(self, runtime_type: str, runtime_class: Type[RuntimeBase]) -> None:
        if not runtime_type or not isinstance(runtime_type, str):
            raise ValueError("runtime_type must be a non-empty string")
        if not isinstance(runtime_class, type) or not issubclass(runtime_class, RuntimeBase):
            raise TypeError("runtime_class must inherit RuntimeBase")
        with self._lock:
            self._items[runtime_type] = runtime_class

    def get(self, runtime_type: str) -> Optional[Type[RuntimeBase]]:
        with self._lock:
            return self._items.get(runtime_type)

    def has(self, runtime_type: str) -> bool:
        with self._lock:
            return runtime_type in self._items

    def clear(self) -> None:
        """Clear registrations. Intended for isolated tests."""
        with self._lock:
            self._items.clear()

    def load_definition(self, definition_path: str) -> str:
        """Load a runtime class from a plugin ``runtime.json`` definition.

        Expected shape::

            {
              "runtime_type": "echo",
              "registrations": {
                "runtime": {"module": "runtime.py", "callable": "EchoRuntime"}
              }
            }
        """
        path = Path(definition_path).resolve()
        with path.open("r", encoding="utf-8") as stream:
            definition = json.load(stream)

        runtime_type = definition.get("runtime_type", "")
        registration = definition.get("registrations", {}).get("runtime", {})
        module_name = registration.get("module", "")
        callable_name = registration.get("callable", "")
        if not runtime_type or not module_name or not callable_name:
            raise ValueError(
                "runtime.json requires runtime_type and registrations.runtime "
                "module/callable"
            )

        module_path = (path.parent / module_name).resolve()
        if path.parent not in module_path.parents:
            raise ValueError("runtime module must be inside the plugin directory")
        if not module_path.is_file():
            raise FileNotFoundError(str(module_path))

        import_name = f"mozikit_runtime_{runtime_type}_{abs(hash(str(module_path)))}"
        spec = importlib.util.spec_from_file_location(import_name, str(module_path))
        if not spec or not spec.loader:
            raise ImportError(f"cannot load runtime module: {module_path}")

        module = importlib.util.module_from_spec(spec)
        sys.modules[import_name] = module
        try:
            spec.loader.exec_module(module)
            runtime_class = getattr(module, callable_name)
            self.register(runtime_type, runtime_class)
        except Exception:
            sys.modules.pop(import_name, None)
            raise
        return runtime_type


runtime_registry = RuntimeRegistry()
