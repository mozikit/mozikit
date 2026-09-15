"""Daemon-owned filesystem trigger implemented with watchdog."""

from __future__ import annotations

import fnmatch
import queue
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from .log_manager import get_logger
from .trigger_base import TriggerBase, TriggerEmit


logger = get_logger("folder_watch_trigger")


class FolderWatchTrigger(TriggerBase):
    """Emit one event for matching filesystem changes without blocking a run."""

    EVENT_TYPES = {"created", "modified", "deleted", "moved"}
    MAX_PENDING_EVENTS = 2048

    def __init__(self, trigger_id: str, config: dict | None = None):
        super().__init__(trigger_id, config)
        self._observer: Optional[Observer] = None
        self._worker: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._events: queue.Queue = queue.Queue(maxsize=self.MAX_PENDING_EVENTS)
        self._emit: Optional[TriggerEmit] = None
        self._last_event: dict[str, float] = {}
        self._last_queue_warning = 0.0
        self._lock = threading.RLock()
        self._path: Optional[Path] = None

    @property
    def is_running(self) -> bool:
        with self._lock:
            return bool(
                self._observer is not None
                and self._observer.is_alive()
                and self._worker is not None
                and self._worker.is_alive()
            )

    def start(self, emit: TriggerEmit) -> None:
        with self._lock:
            if self.is_running:
                return
            # A crashed observer/worker must not be leaked when the manager
            # reconciles it.  ``stop`` is idempotent and uses an RLock.
            if self._observer is not None or self._worker is not None:
                self.stop()

            path_value = self.config.get("path")
            if not isinstance(path_value, str) or not path_value.strip():
                raise ValueError("folder_watch requires a non-empty path")
            path = Path(path_value).expanduser().resolve()
            if not path.exists():
                raise FileNotFoundError(f"watch path does not exist: {path}")
            if not path.is_dir():
                raise NotADirectoryError(f"watch path is not a directory: {path}")

            events = self.config.get("events", sorted(self.EVENT_TYPES))
            if (
                not isinstance(events, list)
                or not events
                or not all(isinstance(item, str) for item in events)
                or not set(events) <= self.EVENT_TYPES
            ):
                raise ValueError(
                    "events must contain at least one of created, modified, deleted, moved"
                )
            for key in ("include", "exclude"):
                patterns = self.config.get(key, [])
                if not isinstance(patterns, list) or not all(
                    isinstance(item, str) and item.strip() for item in patterns
                ):
                    raise ValueError(f"{key} must be a list of non-empty glob strings")
            for key in ("debounce_ms", "settle_ms"):
                value = self.config.get(key, 0)
                if isinstance(value, bool):
                    raise ValueError(f"{key} must be a non-negative number")
                try:
                    if float(value) < 0:
                        raise ValueError(f"{key} must be a non-negative number")
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"{key} must be a non-negative number") from exc
            for key in ("recursive", "ignore_directories"):
                if key in self.config and not isinstance(self.config[key], bool):
                    raise ValueError(f"{key} must be a boolean")

            self._path, self._emit = path, emit
            self._last_event.clear()
            self._last_queue_warning = 0.0
            self._stop_event.clear()
            observer = Observer()
            handler = _Handler(self)
            observer_started = False
            try:
                observer.schedule(
                    handler,
                    str(path),
                    recursive=bool(self.config.get("recursive", True)),
                )
                observer.start()
                observer_started = True
                worker = threading.Thread(
                    target=self._process,
                    name=f"trigger-{self.trigger_id}",
                    daemon=True,
                )
                self._observer = observer
                self._worker = worker
                worker.start()
            except Exception:
                observer.stop()
                if observer_started:
                    observer.join(timeout=2)
                self._observer = None
                self._worker = None
                raise

    def stop(self) -> None:
        with self._lock:
            observer, worker = self._observer, self._worker
            self._observer = self._worker = None
            self._stop_event.set()
        if observer is not None:
            observer.stop()
            observer.join(timeout=2)
            if observer.is_alive():
                logger.warning("Folder watch observer did not stop in time: %s", self.trigger_id)
        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout=2)
            if worker.is_alive():
                logger.warning("Folder watch worker did not stop in time: %s", self.trigger_id)
        while True:
            try:
                self._events.get_nowait()
                self._events.task_done()
            except queue.Empty:
                break
        with self._lock:
            self._emit = None
            self._path = None
            self._last_event.clear()

    def _enqueue(self, event_type: str, src_path: str, dest_path: str | None = None, is_directory: bool = False) -> None:
        if event_type not in self.config.get("events", sorted(self.EVENT_TYPES)):
            return
        if is_directory and self.config.get("ignore_directories", True):
            return
        path = Path(dest_path or src_path)
        try:
            relative = path.relative_to(self._path).as_posix() if self._path else path.name
        except ValueError:
            relative = path.name
        include = self.config.get("include") or []
        exclude = self.config.get("exclude") or []
        if include and not any(fnmatch.fnmatch(relative, pattern) or fnmatch.fnmatch(path.name, pattern) for pattern in include):
            return
        if any(fnmatch.fnmatch(relative, pattern) or fnmatch.fnmatch(path.name, pattern) for pattern in exclude):
            return
        try:
            self._events.put_nowait(
                (
                    event_type,
                    str(Path(src_path).resolve()),
                    str(Path(dest_path).resolve()) if dest_path else None,
                    is_directory,
                )
            )
        except queue.Full:
            now = time.monotonic()
            if now - self._last_queue_warning >= 1.0:
                self._last_queue_warning = now
                logger.warning(
                    "Folder watch event queue is full; dropping events for %s",
                    self.trigger_id,
                )

    def _process(self) -> None:
        debounce = max(float(self.config.get("debounce_ms", 400)), 0) / 1000
        settle = max(float(self.config.get("settle_ms", 300)), 0) / 1000
        while not self._stop_event.is_set():
            try:
                event_type, src, dest, is_directory = self._events.get(timeout=0.05)
            except queue.Empty:
                continue
            try:
                if settle and event_type in {"created", "modified", "moved"} and self._stop_event.wait(settle):
                    continue
                key = f"{event_type}:{src}:{dest or ''}"
                now = time.monotonic()
                if now - self._last_event.get(key, 0) < debounce:
                    continue
                self._last_event[key] = now
                path = dest or src
                payload = {
                    "event_id": uuid.uuid4().hex,
                    "event_type": event_type,
                    "path": path,
                    "src_path": src,
                    "dest_path": dest,
                    "directory": str(Path(path).parent),
                    "filename": Path(path).name,
                    "is_directory": is_directory,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                if self._emit is not None:
                    try:
                        self._emit(payload)
                    except Exception:
                        # A consumer failure must not silently kill the
                        # long-lived watcher thread; reconciliation can still
                        # stop/restart it cleanly.
                        logger.exception("Folder watch event consumer failed: %s", self.trigger_id)
            finally:
                self._events.task_done()
                # This is deliberately in finally: settle/debounce ``continue``
                # paths must also periodically release old path keys.
                if len(self._last_event) > self.MAX_PENDING_EVENTS * 2:
                    cutoff = time.monotonic() - max(debounce * 4, 60.0)
                    self._last_event = {
                        key: timestamp
                        for key, timestamp in self._last_event.items()
                        if timestamp >= cutoff
                    }


class _Handler(FileSystemEventHandler):
    def __init__(self, trigger: FolderWatchTrigger):
        self.trigger = trigger

    def on_created(self, event):
        self.trigger._enqueue("created", event.src_path, is_directory=event.is_directory)

    def on_modified(self, event):
        self.trigger._enqueue("modified", event.src_path, is_directory=event.is_directory)

    def on_deleted(self, event):
        self.trigger._enqueue("deleted", event.src_path, is_directory=event.is_directory)

    def on_moved(self, event):
        self.trigger._enqueue("moved", event.src_path, event.dest_path, event.is_directory)
