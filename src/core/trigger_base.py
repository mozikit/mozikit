"""Minimal contract for daemon-owned workflow triggers."""

from abc import ABC, abstractmethod
from typing import Any, Callable

TriggerEmit = Callable[[dict[str, Any]], None]


class TriggerBase(ABC):
    def __init__(self, trigger_id: str, config: dict | None = None):
        self.trigger_id = trigger_id
        self.config = config or {}

    @abstractmethod
    def start(self, emit: TriggerEmit) -> None:
        pass

    @abstractmethod
    def stop(self) -> None:
        pass
