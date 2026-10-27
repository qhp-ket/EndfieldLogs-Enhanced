"""Request all resource owners to stop without waiting on the UI thread."""
from __future__ import annotations

from dataclasses import dataclass
import queue
import threading
import time


@dataclass(frozen=True, slots=True)
class ShutdownState:
    pending: tuple[str, ...]
    errors: tuple[str, ...]

    @property
    def complete(self):
        return not self.pending


class ShutdownController:
    def __init__(self, capture, independent):
        self.capture = capture
        self.independent = independent
        self._owner = threading.get_ident()
        self._results = queue.Queue()
        self._input_thread = None
        self._started = None
        self._warned = False
        self._errors = []

    def _assert_owner(self):
        if threading.get_ident() != self._owner:
            raise RuntimeError('退出流程只能由所属线程推进')

    def add_error(self, name, error):
        self._assert_owner()
        self._errors.append(f'{name}：{error}')

    def begin(self):
        self._assert_owner()
        if self._started is not None:
            return
        self._started = time.monotonic()
        self.independent.close()
        for name, request in (('capture', self.capture.stop), ('vision', self.independent.vision.stop)):
            try:
                request()
            except Exception as error:
                self.add_error(name, error)
        recorder = self.independent.input

        def stop_input():
            try:
                recorder.stop(wait=True)
                if recorder.running:
                    raise RuntimeError(recorder.snapshot().get('error') or '输入记录进程仍在运行')
            except Exception as error:
                self._results.put(('input', str(error)))

        self._input_thread = threading.Thread(target=stop_input, name='input-shutdown', daemon=True)
        self._input_thread.start()

    def poll(self):
        self._assert_owner()
        if self._started is None:
            raise RuntimeError('退出流程尚未开始')
        while True:
            try:
                self.add_error(*self._results.get_nowait())
            except queue.Empty:
                break
        pending = []
        if self.capture.is_running():
            pending.append('capture')
        if self._input_thread.is_alive() or self.independent.input.running:
            pending.append('input')
        if self.independent.vision.is_running():
            pending.append('vision')
        if pending and not self._warned and time.monotonic()-self._started > 15:
            self._warned = True
            self.add_error('shutdown', '资源退出超时，继续等待：' + ', '.join(pending))
        return ShutdownState(tuple(pending), tuple(self._errors))
