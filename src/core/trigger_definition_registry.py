"""GUI-facing definitions for daemon-owned workflow triggers.

The runtime :mod:`trigger_registry` deliberately only knows how to construct
running trigger classes.  This registry contains the presentation and config
schema needed by editors and CLI validation without turning a trigger into a
workflow node.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock
from typing import Any, Optional


@dataclass(frozen=True)
class TriggerDefinition:
    trigger_type: str
    display_name: str
    description: str = ""
    config_schema: dict[str, dict[str, Any]] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


class TriggerDefinitionRegistry:
    def __init__(self) -> None:
        self._items: dict[str, TriggerDefinition] = {}
        self._lock = RLock()

    def register(
        self,
        trigger_type: str,
        display_name: str,
        *,
        description: str = "",
        config_schema: Optional[dict[str, dict[str, Any]]] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> TriggerDefinition:
        if not isinstance(trigger_type, str) or not trigger_type.strip():
            raise ValueError("trigger_type must be a non-empty string")
        definition = TriggerDefinition(
            trigger_type=trigger_type,
            display_name=display_name or trigger_type,
            description=description,
            config_schema=dict(config_schema or {}),
            metadata=dict(metadata or {}),
        )
        with self._lock:
            self._items[trigger_type] = definition
        return definition

    def get(self, trigger_type: str) -> Optional[TriggerDefinition]:
        with self._lock:
            return self._items.get(trigger_type)

    def list(self) -> list[TriggerDefinition]:
        with self._lock:
            return list(self._items.values())


trigger_definition_registry = TriggerDefinitionRegistry()


FOLDER_WATCH_CONFIG_SCHEMA = {
    "path": {
        "type": "path",
        "label": "Path",
        "description": "要监听的目录",
        "required": True,
        "default": "",
    },
    "recursive": {
        "type": "bool",
        "label": "Recursive",
        "default": True,
    },
    "events": {
        "type": "multi_enum",
        "label": "Events",
        "options": ["created", "modified", "deleted", "moved"],
        "default": ["created", "modified", "deleted", "moved"],
    },
    "include": {
        "type": "string_list",
        "label": "Include",
        "description": "每行一个 glob，例如 *.sav",
        "default": [],
    },
    "exclude": {
        "type": "string_list",
        "label": "Exclude",
        "description": "每行一个 glob，例如 *.tmp",
        "default": [],
    },
    "debounce_ms": {
        "type": "int",
        "label": "Debounce (ms)",
        "default": 400,
        "minimum": 0,
    },
    "settle_ms": {
        "type": "int",
        "label": "Settle (ms)",
        "default": 300,
        "minimum": 0,
    },
    "ignore_directories": {
        "type": "bool",
        "label": "Ignore directories",
        "default": True,
    },
}


trigger_definition_registry.register(
    "folder_watch",
    "Folder Changed",
    description="当监听目录中的文件发生变化时触发工作流。",
    config_schema=FOLDER_WATCH_CONFIG_SCHEMA,
)
trigger_definition_registry.register(
    "test",
    "Test Trigger",
    description="用于测试 Trigger 生命周期的周期触发器。",
    config_schema={
        "interval": {"type": "float", "label": "Interval", "default": 1.0, "minimum": 0},
    },
)


def get_trigger_definition(trigger_type: str) -> Optional[TriggerDefinition]:
    return trigger_definition_registry.get(trigger_type)


def get_trigger_definition_registry() -> TriggerDefinitionRegistry:
    """Return the process-wide GUI definition registry."""
    return trigger_definition_registry
