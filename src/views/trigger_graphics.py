"""Visual-only representation of daemon-owned workflow triggers."""

from __future__ import annotations

from PySide6.QtWidgets import QGraphicsItem

from src.core.trigger_definition_registry import get_trigger_definition
from .node_graphics import NodeGraphicsItem


class TriggerGraphicsItem(NodeGraphicsItem):
    """Render a trigger on the canvas without making it an executable Node."""

    is_trigger_visual = True

    def __init__(self, trigger: dict, parent=None):
        trigger_id = str(trigger.get("trigger_id") or "trigger")
        trigger_type = str(trigger.get("trigger_type") or "unknown")
        definition = get_trigger_definition(trigger_type)
        title = definition.display_name if definition else f"Trigger: {trigger_type}"
        super().__init__(
            f"trigger:{trigger_id}",
            f"trigger.{trigger_type}",
            f"⚡ {title}",
            {},
            {"output": {"type": "object", "description": "Trigger event payload"}},
            parent,
        )
        self.trigger_id = trigger_id
        self.trigger_type = trigger_type
        self.trigger_definition = trigger
        self.config = dict(trigger.get("config") or {})
        self.runtime_status = {}
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
        self.run_btn.hide()
        self.del_btn.hide()
        self.setToolTip(self._build_trigger_tooltip())

    def refresh_from_definition(self, trigger: dict) -> None:
        """Refresh the visual cache after the Workflow Model is updated."""
        self.trigger_definition = trigger
        self.config = dict(trigger.get("config") or {})
        self.setToolTip(self._build_trigger_tooltip())

    def set_runtime_status(self, status: dict | None) -> None:
        """Show daemon runtime information in the visual item's tooltip."""
        self.runtime_status = dict(status or {})
        self.setToolTip(self._build_trigger_tooltip())

    def _build_trigger_tooltip(self) -> str:
        lines = [self.title, f"Trigger ID: {self.trigger_id}", f"类型: {self.trigger_type}"]
        runtime_status = self.runtime_status.get("status")
        if runtime_status:
            lines.append(f"Runtime: {runtime_status}")
        event = self.runtime_status.get("last_event") or {}
        if event:
            lines.append(f"最近事件: {event.get('event_type', 'unknown')}")
            if event.get("event_type") == "moved":
                lines.append(f"源: {event.get('src_path', '-')}")
                lines.append(f"目标: {event.get('dest_path', '-')}")
            else:
                lines.append(f"路径: {event.get('path', '-')}")
        lines.extend(f"{key}: {value}" for key, value in self.config.items())
        return "\n".join(lines)

    def execute_node(self):
        """Triggers are started by Runtime Daemon, never manually as Nodes."""

    def configure_node(self):
        """Trigger configuration is persisted in ``triggers[]``."""

    def delete_node(self):
        """Prevent accidental deletion without updating ``triggers[]``."""

    def itemChange(self, change, value):
        result = super().itemChange(change, value)
        if hasattr(self, "run_btn"):
            self.run_btn.hide()
        if hasattr(self, "del_btn"):
            self.del_btn.hide()
        return result
