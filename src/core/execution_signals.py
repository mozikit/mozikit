"""Translate terminal interruption into the executor's normal stop request."""
from contextlib import contextmanager
import signal
import threading


@contextmanager
def stop_on_interrupt(executor, enabled=False):
    if not enabled or threading.current_thread() is not threading.main_thread():
        yield
        return
    previous = signal.getsignal(signal.SIGINT)
    def stop(signum, frame):
        executor.request_stop()
    signal.signal(signal.SIGINT, stop)
    try:
        yield
    finally:
        signal.signal(signal.SIGINT, previous)
