"""Deterministic interval trigger used to validate persistent event runs."""

import threading
import uuid

from .trigger_base import TriggerBase, TriggerEmit


class TestTrigger(TriggerBase):
    __test__ = False

    def __init__(self, trigger_id: str, config: dict | None = None):
        super().__init__(trigger_id, config)
        self._stop_event = threading.Event()
        self._thread = None
        self._sequence = 0
        self._generation = uuid.uuid4().hex

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, emit: TriggerEmit) -> None:
        if self.is_running:
            return
        interval = max(float(self.config.get("interval", 1)), 0.01)
        self._stop_event.clear()

        def run() -> None:
            while not self._stop_event.wait(interval):
                self._sequence += 1
                emit(
                    {
                        "event_id": (
                            f"{self.trigger_id}:{self._generation}:{self._sequence}"
                        ),
                        "sequence": self._sequence,
                    }
                )

        self._thread = threading.Thread(
            target=run,
            name=f"trigger-{self.trigger_id}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        thread, self._thread = self._thread, None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2)
