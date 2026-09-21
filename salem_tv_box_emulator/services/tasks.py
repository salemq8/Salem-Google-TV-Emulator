"""Ordered engine work and independent read-only/background work, delivered on Qt's thread."""
from __future__ import annotations

import logging
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable

from PySide6.QtCore import QObject, Signal


class TaskRunner(QObject):
    completed = Signal(str, object, object)

    def __init__(self, parent: QObject) -> None:
        super().__init__(parent)
        self.engine = ThreadPoolExecutor(max_workers=1, thread_name_prefix="salem-engine")
        self.background = ThreadPoolExecutor(max_workers=2, thread_name_prefix="salem-service")
        self.callbacks: dict[str, tuple[Callable, Callable]] = {}
        self.closed = False
        self.completed.connect(self._deliver)

    def submit(self, key: str, work: Callable, success: Callable, failure: Callable, *, engine: bool = True) -> bool:
        if self.closed or key in self.callbacks:
            return False
        self.callbacks[key] = success, failure
        future = (self.engine if engine else self.background).submit(work)
        future.add_done_callback(lambda done: self._finish(key, done))
        return True

    def pending_count(self, prefix: str) -> int:
        """Count accepted tasks until their results have been delivered on the UI thread."""
        return sum(key.startswith(prefix) for key in self.callbacks)

    def _finish(self, key: str, future: Future) -> None:
        if self.closed:
            return
        try:
            result, error = future.result(), None
        except Exception as exc:
            logging.getLogger(__name__).exception("Task %s failed", key)
            result, error = None, exc
        if not self.closed:
            self.completed.emit(key, result, error)

    def _deliver(self, key: str, result: object, error: Exception | None) -> None:
        callbacks = self.callbacks.pop(key, None)
        if self.closed or not callbacks:
            return
        success, failure = callbacks
        try:
            failure(error) if error else success(result)
        except Exception as exc:
            logging.getLogger(__name__).exception("UI callback %s failed", key)
            failure(exc)

    def close(self) -> None:
        self.closed = True
        self.callbacks.clear()
        self.engine.shutdown(wait=False, cancel_futures=True)
        self.background.shutdown(wait=False, cancel_futures=True)
