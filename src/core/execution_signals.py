"""Translate terminal interruption into the executor's normal stop request."""
from contextlib import contextmanager
import signal
import threading


@contextmanager
def stop_on_interrupt(executor, enabled=False):
    if not enabled or threading.current_thread() is not threading.main_thread():
        yield
        return
    signals = [signal.SIGINT]
    if hasattr(signal, 'SIGBREAK'):
        signals.append(signal.SIGBREAK)
    previous = {sig: signal.getsignal(sig) for sig in signals}
    def stop(signum, frame):
        executor.request_stop()
    for sig in signals:
        signal.signal(sig, stop)
    try:
        yield
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
