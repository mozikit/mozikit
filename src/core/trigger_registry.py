"""Registry for persistent trigger implementations."""

from threading import RLock
from typing import Optional, Type

from .trigger_base import TriggerBase


class TriggerRegistry:
    def __init__(self) -> None:
        self._items: dict[str, Type[TriggerBase]] = {}
        self._lock = RLock()

    def register(self, trigger_type: str, trigger_class: Type[TriggerBase]) -> None:
        if not trigger_type:
            raise ValueError("trigger_type must be a non-empty string")
        if not isinstance(trigger_class, type) or not issubclass(trigger_class, TriggerBase):
            raise TypeError("trigger_class must inherit TriggerBase")
        with self._lock:
            self._items[trigger_type] = trigger_class

    def get(self, trigger_type: str) -> Optional[Type[TriggerBase]]:
        with self._lock:
            return self._items.get(trigger_type)


trigger_registry = TriggerRegistry()
