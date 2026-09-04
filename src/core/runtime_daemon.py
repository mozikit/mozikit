"""Single-owner process for persistent Mozikit runtimes."""

from __future__ import annotations

import json
import os
import secrets
import signal
import sys
import threading
import uuid
from pathlib import Path
from typing import Optional

from ._file_utils import atomic_write, atomic_write_json_sync
from .runtime_host import RuntimeHost
from .runtime_paths import get_runtime_dir


class RuntimeDaemonAlreadyRunning(RuntimeError):
    pass


class RuntimeDaemonLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._stream = None

    @property
    def acquired(self) -> bool:
        return self._stream is not None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stream = self.path.open("a+b")
        if stream.seek(0, os.SEEK_END) == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, IOError) as exc:
            stream.close()
            raise RuntimeDaemonAlreadyRunning("Runtime Daemon is already running") from exc
        self._stream = stream

    def release(self) -> None:
        stream, self._stream = self._stream, None
        if stream is None:
            return
        try:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        finally:
            stream.close()


class RuntimeDaemon:
    def __init__(
        self,
        runtime_dir: Optional[Path] = None,
        port: Optional[int] = None,
        shutdown_callback=None,
    ):
        self.runtime_dir = runtime_dir or get_runtime_dir()
        self.connection_path = self.runtime_dir / "connection.json"
        self.token_path = self.runtime_dir / "auth.token"
        self.lock = RuntimeDaemonLock(self.runtime_dir / "daemon.lock")
        self.port = (
            int(os.environ.get("MOZIKIT_RUNTIME_PORT", "0"))
            if port is None
            else port
        )
        self.host: Optional[RuntimeHost] = None
        self.shutdown_callback = shutdown_callback

    def start(self) -> None:
        self.lock.acquire()
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        token = secrets.token_urlsafe(32)
        try:
            atomic_write(self.token_path, token)
            try:
                os.chmod(self.token_path, 0o600)
            except OSError:
                pass
            self.host = RuntimeHost(
                config_path=str(self.runtime_dir / "runtimes.json"),
                plugin_root=str(self.runtime_dir / "plugins"),
                port=self.port,
                auth_token=token,
                shutdown_callback=self.shutdown_callback,
            )
            self.host.start()
            atomic_write_json_sync(
                self.connection_path,
                {
                    "url": self.host.base_url,
                    "pid": os.getpid(),
                    "instance_id": uuid.uuid4().hex,
                },
            )
        except Exception:
            self.stop()
            raise

    def stop(self) -> None:
        if not self.lock.acquired:
            return
        try:
            if self.host is not None:
                self.host.stop()
                self.host = None
        finally:
            for path in (self.connection_path, self.token_path):
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
            self.lock.release()


def main() -> None:
    stopped = threading.Event()
    daemon = RuntimeDaemon(shutdown_callback=stopped.set)

    def request_stop(signum, frame):
        stopped.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    try:
        daemon.start()
        stopped.wait()
    except RuntimeDaemonAlreadyRunning as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)
    finally:
        daemon.stop()


if __name__ == "__main__":
    main()
