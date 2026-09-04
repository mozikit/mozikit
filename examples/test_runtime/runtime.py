"""Stateful test runtime used to validate the runtime extension boundary."""

from src.core.runtime_base import RuntimeBase


class EchoRuntime(RuntimeBase):
    def __init__(self, runtime_id, config=None):
        super().__init__(runtime_id, config)
        self.started = False
        self.count = 0

    def start(self):
        self.started = True

    def stop(self):
        self.started = False

    def call(self, action, params):
        if not self.started:
            raise RuntimeError("runtime is not running")
        if action == "echo":
            return {"text": params["text"]}
        if action == "count":
            self.count += 1
            return {"count": self.count}
        raise ValueError(f"unknown action: {action}")

    def health(self):
        return {"status": "running" if self.started else "stopped"}
