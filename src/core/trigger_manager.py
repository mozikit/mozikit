"""Desired-state reconciliation for daemon-owned workflow triggers."""

from __future__ import annotations

import hashlib
import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ._file_utils import atomic_write_json_sync
from .log_manager import get_logger
from .trigger_base import TriggerBase
from .trigger_registry import TriggerRegistry, trigger_registry
from .workflow_executor import write_workflow_file
from .workflow_run_dispatcher import WorkflowRunDispatcher

logger = get_logger("trigger_manager")


@dataclass(frozen=True)
class TriggerDefinition:
    key: str
    workflow_id: str
    workflow_name: str
    workflow_path: str
    trigger_id: str
    trigger_type: str
    config: dict
    fingerprint: str


@dataclass
class _ActualTrigger:
    definition: TriggerDefinition
    instance: TriggerBase


class TriggerManager:
    def __init__(
        self,
        workflows_dir: str | Path,
        *,
        registry: Optional[TriggerRegistry] = None,
        dispatcher: Optional[WorkflowRunDispatcher] = None,
        state_path: Optional[str | Path] = None,
        reconcile_interval: float = 1.0,
    ) -> None:
        self.workflows_dir = Path(workflows_dir).expanduser().resolve()
        self.registry = registry or trigger_registry
        self.dispatcher = dispatcher or WorkflowRunDispatcher()
        self.state_path = Path(state_path) if state_path else None
        self.reconcile_interval = max(reconcile_interval, 0.05)
        self._actual: dict[str, _ActualTrigger] = {}
        self._errors: dict[str, str] = {}
        self._seen = self._load_seen()
        self._lock = threading.RLock()
        self._reconcile_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread = None
        self._runs = ThreadPoolExecutor(max_workers=4, thread_name_prefix="trigger-run")

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        if self._runs is None:
            self._runs = ThreadPoolExecutor(
                max_workers=4, thread_name_prefix="trigger-run"
            )
        self._stop_event.clear()
        self.reconcile()
        self._thread = threading.Thread(
            target=self._reconcile_loop, name="trigger-reconcile", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        thread, self._thread = self._thread, None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2)
        with self._reconcile_lock:
            for key in list(self._actual):
                self._stop_trigger(key)
        runs, self._runs = self._runs, None
        if runs is not None:
            runs.shutdown(wait=True, cancel_futures=True)

    def reconcile(self) -> dict:
        with self._reconcile_lock:
            return self._reconcile()

    def _reconcile(self) -> dict:
        desired = self._load_desired()
        for key, actual in list(self._actual.items()):
            expected = desired.get(key)
            running = getattr(actual.instance, "is_running", True)
            if expected is None or expected.fingerprint != actual.definition.fingerprint or not running:
                self._stop_trigger(key)
        for key, definition in desired.items():
            if key not in self._actual:
                self._start_trigger(definition)
        for key in list(self._errors):
            if key not in desired:
                self._errors.pop(key, None)
        return self.status(desired)

    def activate_workflow(self, workflow_path: str) -> dict:
        self._set_active(workflow_path, True)
        return self.reconcile()

    def deactivate_workflow(self, workflow_id: str) -> dict:
        for path, document in self._workflow_documents():
            identity = document.get("workflow_id") or str(path.resolve())
            if identity == workflow_id:
                self._set_active(str(path), False)
        return self.reconcile()

    def status(self, desired: Optional[dict[str, TriggerDefinition]] = None) -> dict:
        desired = desired if desired is not None else self._load_desired()
        with self._lock:
            return {
                "desired": sorted(desired),
                "actual": {
                    key: {
                        "status": "running"
                        if getattr(actual.instance, "is_running", True)
                        else "stopped",
                        "workflow_id": actual.definition.workflow_id,
                        "trigger_type": actual.definition.trigger_type,
                    }
                    for key, actual in self._actual.items()
                },
                "errors": dict(self._errors),
            }

    def _reconcile_loop(self) -> None:
        while not self._stop_event.wait(self.reconcile_interval):
            try:
                self.reconcile()
            except Exception:
                logger.exception("Trigger reconciliation failed")

    def _workflow_documents(self):
        if not self.workflows_dir.is_dir():
            return
        for path in sorted(self.workflows_dir.rglob("workflow.json")):
            try:
                document = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(document, dict):
                    yield path, document
            except (OSError, json.JSONDecodeError):
                logger.warning("Ignoring invalid workflow during trigger reconciliation: %s", path)

    def _load_desired(self) -> dict[str, TriggerDefinition]:
        desired = {}
        for path, document in self._workflow_documents() or []:
            if document.get("active") is not True:
                continue
            workflow_id = document.get("workflow_id") or str(path.resolve())
            workflow_name = document.get("workflow_name") or path.parent.name
            triggers = document.get("triggers", [])
            if not isinstance(triggers, list):
                continue
            for index, item in enumerate(triggers):
                if not isinstance(item, dict) or item.get("enabled", True) is not True:
                    continue
                trigger_id = item.get("trigger_id") or f"trigger-{index + 1}"
                trigger_type = item.get("trigger_type")
                config = item.get("config", {})
                if not isinstance(trigger_type, str) or not isinstance(config, dict):
                    continue
                key = f"{workflow_id}/{trigger_id}"
                fingerprint = hashlib.sha256(
                    json.dumps(
                        [str(path.resolve()), trigger_type, config],
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest()
                desired[key] = TriggerDefinition(
                    key, workflow_id, workflow_name, str(path), trigger_id,
                    trigger_type, config, fingerprint
                )
        return desired

    def _start_trigger(self, definition: TriggerDefinition) -> None:
        trigger_class = self.registry.get(definition.trigger_type)
        if trigger_class is None:
            self._errors[definition.key] = f"unknown trigger type: {definition.trigger_type}"
            return
        try:
            instance = trigger_class(definition.trigger_id, definition.config)
            instance.start(lambda payload: self._emit(definition, payload))
            with self._lock:
                self._actual[definition.key] = _ActualTrigger(definition, instance)
                self._errors.pop(definition.key, None)
        except Exception as exc:
            self._errors[definition.key] = str(exc)
            logger.exception("Could not start trigger %s", definition.key)

    def _stop_trigger(self, key: str) -> None:
        with self._lock:
            actual = self._actual.pop(key, None)
        if actual is not None:
            try:
                actual.instance.stop()
            except Exception as exc:
                self._errors[key] = str(exc)
                logger.exception("Could not stop trigger %s", key)

    def _emit(self, definition: TriggerDefinition, payload: dict) -> None:
        if not isinstance(payload, dict):
            logger.error("Trigger %s emitted a non-object payload", definition.key)
            return
        event_id = payload.get("event_id") or payload.get("message_id")
        if event_id is not None:
            dedupe_key = f"{definition.key}:{event_id}"
            with self._lock:
                if dedupe_key in self._seen:
                    return
                self._seen.append(dedupe_key)
                self._seen = self._seen[-1000:]
                self._save_seen()
        runs = self._runs
        if runs is not None:
            runs.submit(self._run_workflow, definition, dict(payload))

    def _run_workflow(self, definition: TriggerDefinition, payload: dict) -> None:
        try:
            self.dispatcher.run(
                definition.workflow_path,
                trigger_type="trigger",
                initial_data=payload,
                workflow_name=definition.workflow_name,
            )
        except Exception:
            logger.exception("Trigger workflow run failed: %s", definition.key)

    def _load_seen(self) -> list[str]:
        if self.state_path is None or not self.state_path.is_file():
            return []
        try:
            document = json.loads(self.state_path.read_text(encoding="utf-8"))
            return list(document.get("seen_events", []))[-1000:]
        except Exception:
            return []

    def _save_seen(self) -> None:
        if self.state_path is not None:
            atomic_write_json_sync(self.state_path, {"seen_events": self._seen})

    def _set_active(self, workflow_path: str, active: bool) -> None:
        path = Path(workflow_path).expanduser().resolve()
        if not path.is_relative_to(self.workflows_dir):
            raise ValueError("workflow must be inside the configured workspace")
        document = json.loads(path.read_text(encoding="utf-8"))
        document.setdefault("workflow_id", str(uuid.uuid4()))
        document["active"] = active
        write_workflow_file(str(path), document)
