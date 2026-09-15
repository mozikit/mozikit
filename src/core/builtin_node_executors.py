"""Built-in native workflow nodes used by the GUI and Runtime Daemon.

The directory monitor is intentionally split into two pieces:

* :class:`FolderWatchTrigger` owns the long-lived watchdog observer;
* :class:`DirectoryMonitorNativeExecutor` turns the event supplied by that
  trigger into a normal workflow output.

This keeps a workflow run finite and makes the same node usable in the normal
(topologically executed) node graph.  The Debug node is native as well so it
never needs a generated script or a workflow virtual-environment dependency.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .node_extension_registries import native_executors


# ``folder_watch`` is the persisted/public name.  The aliases are accepted when
# loading older or hand-written workflow files, but only the public name is
# shown in the node browser.
DIRECTORY_WATCH_NODE_TYPES = frozenset(
    {"folder_watch", "directory_monitor", "directory_watch"}
)

DIRECTORY_WATCH_NODE_CONFIG_SCHEMA = {
    "path": {
        "type": "path",
        "label": "监听目录",
        "description": "要监听的目录",
        "required": True,
        "default": "",
    },
    "enabled": {
        "type": "bool",
        "label": "启用监视",
        "description": "工作流激活后是否启动此目录监视器",
        "default": True,
    },
    "recursive": {
        "type": "bool",
        "label": "递归子目录",
        "default": True,
    },
    "events": {
        "type": "multi_enum",
        "label": "事件类型",
        "options": ["created", "modified", "deleted", "moved"],
        "default": ["created", "modified", "deleted", "moved"],
    },
    "include": {
        "type": "string_list",
        "label": "包含规则",
        "description": "每行一个 glob，例如 *.json",
        "default": [],
    },
    "exclude": {
        "type": "string_list",
        "label": "排除规则",
        "description": "每行一个 glob，例如 *.tmp",
        "default": [],
    },
    "debounce_ms": {
        "type": "int",
        "label": "去抖 (ms)",
        "default": 400,
        "minimum": 0,
    },
    "settle_ms": {
        "type": "int",
        "label": "文件稳定等待 (ms)",
        "description": "创建或修改后等待文件写入稳定",
        "default": 300,
        "minimum": 0,
    },
    "ignore_directories": {
        "type": "bool",
        "label": "忽略目录事件",
        "default": True,
    },
}

DEBUG_NODE_CONFIG_SCHEMA = {
    "display_mode": {
        "type": "enum",
        "label": "显示格式",
        "options": ["auto", "json", "text"],
        "default": "auto",
    },
    "max_length": {
        "type": "int",
        "label": "最大显示长度",
        "description": "画布上最多显示的字符数",
        "default": 2000,
        "minimum": 100,
        "maximum": 20000,
    },
    "show_timestamp": {
        "type": "bool",
        "label": "显示时间",
        "default": True,
    },
}


def _json_safe(value: Any) -> Any:
    """Return a JSON-friendly copy without failing a workflow run."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    for method in ("model_dump", "to_dict"):
        converter = getattr(value, method, None)
        if callable(converter):
            try:
                return _json_safe(converter())
            except Exception:
                pass
    return repr(value)


class DirectoryMonitorNativeExecutor:
    """Convert the current trigger payload into graph-addressable outputs."""

    def execute(
        self,
        *,
        node,
        input_data: dict,
        context: dict,
        timeout: float | None = None,
        progress_callback=None,
        log_callback=None,
    ) -> dict:
        del timeout, progress_callback, log_callback

        incoming = _json_safe(dict(input_data or {}))
        nested_event = incoming.get("event")
        if isinstance(nested_event, dict):
            payload = dict(nested_event)
        else:
            payload = incoming

        # A manual run has no watchdog payload.  Returning a well-formed event
        # is more useful than failing, and also makes the node easy to inspect
        # before the workflow is activated.
        payload.setdefault("event_type", "manual")
        payload.setdefault("path", "")
        payload.setdefault("src_path", payload.get("path"))
        payload.setdefault("dest_path", None)
        payload.setdefault("filename", Path(payload.get("path") or "").name)
        payload.setdefault("directory", str(Path(payload.get("path") or "").parent))
        payload.setdefault("is_directory", False)
        payload.setdefault(
            "timestamp", datetime.now(timezone.utc).isoformat()
        )

        # Keep the event object for a single clean output port while also
        # exposing its common fields as ports/context keys for downstream
        # nodes that only need one value.
        output = dict(payload)
        output["event"] = dict(payload)
        return output


class DebugNativeExecutor:
    """Pass through one upstream value for display and further connections."""

    def execute(
        self,
        *,
        node,
        input_data: dict,
        context: dict,
        timeout: float | None = None,
        progress_callback=None,
        log_callback=None,
    ) -> dict:
        del context, timeout, progress_callback, log_callback
        incoming = _json_safe(dict(input_data or {}))

        if "input" in incoming:
            value = incoming["input"]
        elif "value" in incoming:
            value = incoming["value"]
        elif len(incoming) == 1:
            value = next(iter(incoming.values()))
        else:
            value = incoming

        return {"value": value}


def register_builtin_node_executors() -> None:
    """Register trusted executors once the core registry is initialized."""
    native_executors.register("directory_monitor", DirectoryMonitorNativeExecutor())
    native_executors.register("debug", DebugNativeExecutor())


__all__ = [
    "DIRECTORY_WATCH_NODE_TYPES",
    "DIRECTORY_WATCH_NODE_CONFIG_SCHEMA",
    "DEBUG_NODE_CONFIG_SCHEMA",
    "DirectoryMonitorNativeExecutor",
    "DebugNativeExecutor",
    "register_builtin_node_executors",
]
