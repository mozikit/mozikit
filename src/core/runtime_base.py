"""Base contract for long-lived Mozikit runtime extensions."""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class RuntimeBase(ABC):
    """A process-scoped service that can be called by workflow nodes."""

    def __init__(self, runtime_id: str, config: Optional[dict] = None):
        self.runtime_id = runtime_id
        self.config = config or {}

    @abstractmethod
    def start(self) -> None:
        """Start resources owned by this runtime."""

    @abstractmethod
    def stop(self) -> None:
        """Stop resources owned by this runtime."""

    @abstractmethod
    def call(self, action: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Perform one synchronous runtime action."""

    def health(self) -> dict:
        return {"status": "running"}
