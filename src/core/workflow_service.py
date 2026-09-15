"""Shared workflow and trigger management used by GUI and CLI adapters."""

from __future__ import annotations

import json
import copy
import uuid
from pathlib import Path
from typing import Any, Optional

from . import resolve_workspace
from .builtin_node_executors import DIRECTORY_WATCH_NODE_TYPES
from .trigger_definition_registry import get_trigger_definition
from .trigger_registry import trigger_registry
from .workflow_executor import write_workflow_file


class WorkflowService:
    def __init__(self, workspace: str | Path | None = None):
        self.workspace = Path(workspace or resolve_workspace()).expanduser().resolve()

    def resolve(self, workflow: str) -> Path:
        candidate = Path(workflow).expanduser()
        if not candidate.is_absolute():
            candidate = self.workspace / candidate
        if candidate.is_dir():
            candidate = candidate / "workflow.json"
        if not candidate.is_file() and not Path(workflow).suffix:
            candidate = self.workspace / workflow / "workflow.json"
        path = candidate.resolve()
        if not path.is_file():
            raise FileNotFoundError(f"workflow does not exist: {path}")
        if not path.is_relative_to(self.workspace):
            raise ValueError("workflow must be inside the configured workspace")
        return path

    def read(self, workflow: str) -> tuple[Path, dict]:
        path = self.resolve(workflow)
        document = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise ValueError("workflow document must be an object")
        return path, document

    @staticmethod
    def has_persistent_sources(document: dict) -> bool:
        """Whether a workflow has an enabled Trigger or monitor node."""
        triggers = document.get("triggers", [])
        if isinstance(triggers, list) and any(
            isinstance(trigger, dict)
            and trigger.get("enabled", True) is True
            for trigger in triggers
        ):
            return True
        nodes = document.get("nodes", [])
        return isinstance(nodes, list) and any(
            isinstance(node, dict)
            and node.get("node_type") in DIRECTORY_WATCH_NODE_TYPES
            and isinstance(node.get("config") or {}, dict)
            and (node.get("config") or {}).get("enabled", True) is True
            and isinstance((node.get("config") or {}).get("path"), str)
            and bool((node.get("config") or {}).get("path", "").strip())
            for node in nodes
        )

    def set_active(self, workflow: str, active: bool) -> dict:
        path, document = self.read(workflow)
        if active and not self.has_persistent_sources(document):
            raise ValueError("workflow has no configured triggers or directory monitor nodes")
        document.setdefault("workflow_id", str(uuid.uuid4()))
        document["active"] = active
        write_workflow_file(str(path), document)
        return document

    @staticmethod
    def _validate_trigger_id(trigger_id: str) -> str:
        if not isinstance(trigger_id, str) or not trigger_id.strip():
            raise ValueError("trigger_id must be a non-empty string")
        return trigger_id.strip()

    @staticmethod
    def _definition(trigger_type: str):
        if not isinstance(trigger_type, str) or not trigger_type.strip():
            raise ValueError("trigger_type must be a non-empty string")
        definition = get_trigger_definition(trigger_type)
        if definition is None and trigger_registry.get(trigger_type) is None:
            raise ValueError(f"unknown trigger type: {trigger_type}")
        return definition

    @classmethod
    def _validate_config(cls, trigger_type: str, config: dict) -> dict:
        if not isinstance(config, dict):
            raise ValueError("trigger config must be an object")
        definition = cls._definition(trigger_type)
        schema = definition.config_schema if definition else {}
        for key, field_schema in schema.items():
            if not isinstance(field_schema, dict) or key not in config:
                continue
            value = config[key]
            field_type = field_schema.get("type", "string")
            if field_type in {"path", "string"} and not isinstance(value, str):
                raise ValueError(f"trigger config {key} must be a string")
            if field_type == "bool" and not isinstance(value, bool):
                raise ValueError(f"trigger config {key} must be a boolean")
            if field_type == "int" and (isinstance(value, bool) or not isinstance(value, int)):
                raise ValueError(f"trigger config {key} must be an integer")
            if field_type == "float" and (
                isinstance(value, bool) or not isinstance(value, (int, float))
            ):
                raise ValueError(f"trigger config {key} must be numeric")
            if field_type in {"string_list", "multi_enum"} and (
                not isinstance(value, list) or not all(isinstance(item, str) for item in value)
            ):
                raise ValueError(f"trigger config {key} must be a string list")
            if field_type == "multi_enum" and any(
                item not in field_schema.get("options", []) for item in value
            ):
                raise ValueError(f"trigger config {key} contains an unsupported option")
            minimum = field_schema.get("minimum")
            if minimum is not None and isinstance(value, (int, float)) and value < minimum:
                raise ValueError(f"trigger config {key} must be >= {minimum}")
        path = config.get("path")
        if trigger_type == "folder_watch" and (
            not isinstance(path, str) or not path.strip()
        ):
            raise ValueError("folder_watch requires a non-empty path")
        return config

    @classmethod
    def _with_defaults(cls, trigger_type: str, config: Optional[dict]) -> dict:
        definition = cls._definition(trigger_type)
        result = {}
        if definition:
            for key, field_schema in definition.config_schema.items():
                if isinstance(field_schema, dict) and "default" in field_schema:
                    result[key] = copy.deepcopy(field_schema["default"])
        result.update(copy.deepcopy(config or {}))
        return cls._validate_config(trigger_type, result)

    @staticmethod
    def _trigger_list(document: dict) -> list[dict]:
        triggers = document.setdefault("triggers", [])
        if not isinstance(triggers, list):
            raise ValueError("workflow triggers must be a list")
        return triggers

    @classmethod
    def _find_trigger(cls, triggers: list[dict], trigger_id: str) -> dict:
        trigger_id = cls._validate_trigger_id(trigger_id)
        for item in triggers:
            if isinstance(item, dict) and item.get("trigger_id") == trigger_id:
                return item
        raise KeyError(f"trigger does not exist: {trigger_id}")

    @classmethod
    def list_trigger_model(cls, executor) -> list[dict]:
        return [copy.deepcopy(item) for item in cls._trigger_list({"triggers": executor.triggers})]

    @classmethod
    def get_trigger_model(cls, executor, trigger_id: str) -> dict:
        return cls._find_trigger(executor.triggers, trigger_id)

    @classmethod
    def update_trigger_model(
        cls,
        executor,
        trigger_id: str,
        *,
        config: Optional[dict] = None,
        enabled: Optional[bool] = None,
    ) -> dict:
        item = cls._find_trigger(executor.triggers, trigger_id)
        trigger_type = item.get("trigger_type")
        cls._definition(trigger_type)
        if enabled is not None and not isinstance(enabled, bool):
            raise ValueError("enabled must be a boolean")
        merged = dict(item.get("config") or {})
        if config is not None:
            if not isinstance(config, dict):
                raise ValueError("trigger config must be an object")
            merged.update(copy.deepcopy(config))
            cls._validate_config(trigger_type, merged)
            item["config"] = merged
        if enabled is not None:
            item["enabled"] = enabled
        return item

    def list_triggers(self, workflow: str) -> list[dict]:
        _, document = self.read(workflow)
        return [copy.deepcopy(item) for item in self._trigger_list(document)]

    def triggers(self, workflow: str) -> list[dict]:
        return self.list_triggers(workflow)

    def get_trigger(self, workflow: str, trigger_id: str) -> dict:
        _, document = self.read(workflow)
        return copy.deepcopy(self._find_trigger(self._trigger_list(document), trigger_id))

    def add_trigger(self, workflow: str, trigger_type: str, trigger_id: str, config: dict) -> dict:
        path, document = self.read(workflow)
        trigger_id = self._validate_trigger_id(trigger_id)
        triggers = self._trigger_list(document)
        if any(item.get("trigger_id") == trigger_id for item in triggers if isinstance(item, dict)):
            raise ValueError(f"duplicate trigger id: {trigger_id}")
        self._definition(trigger_type)
        item = {
            "trigger_id": trigger_id,
            "trigger_type": trigger_type,
            "enabled": True,
            "config": self._with_defaults(trigger_type, config),
        }
        triggers.append(item)
        write_workflow_file(str(path), document)
        return copy.deepcopy(item)

    def update_trigger(
        self,
        workflow: str,
        trigger_id: str,
        *,
        config: Optional[dict] = None,
        enabled: Optional[bool] = None,
        remove: bool = False,
    ) -> dict:
        path, document = self.read(workflow)
        triggers = self._trigger_list(document)
        item = self._find_trigger(triggers, trigger_id)
        if remove:
            triggers.remove(item)
        else:
            self.update_trigger_model(
                type("WorkflowModel", (), {"triggers": triggers})(),
                trigger_id,
                config=config,
                enabled=enabled,
            )
        write_workflow_file(str(path), document)
        return copy.deepcopy(item)

    def enable_trigger(self, workflow: str, trigger_id: str) -> dict:
        return self.update_trigger(workflow, trigger_id, enabled=True)

    def disable_trigger(self, workflow: str, trigger_id: str) -> dict:
        return self.update_trigger(workflow, trigger_id, enabled=False)

    def remove_trigger(self, workflow: str, trigger_id: str) -> dict:
        return self.update_trigger(workflow, trigger_id, remove=True)
