"""Windows capture owns a fast message thread, isolated from SDL and disk I/O."""
from __future__ import annotations
import ctypes
import queue
import threading
import time
from endfield_pcap.runtime.game_window import GameWindows
from endfield_pcap.inputlog.backends.raw_input import RawInput
from endfield_pcap.inputlog.backends.windows_fallback import WindowsInputFallback
from endfield_pcap.inputlog.backends.windows_state import WindowsStateFallback


class WindowsInput:
    def __init__(self, emit, executable):
        self.emit, self.executable = emit, executable
        self.events = queue.Queue(maxsize=32768)
        self.stopped = threading.Event()
        self.ready = threading.Event()
        self.error = None
        self.received = {'keyboard':0, 'mouse':0, 'hid':0}
        self.announced = set()
        self.missing = 0
        self.missing_start = None
        self.missing_end = None
        self._queue_lock = threading.Lock()
        self.sampler = None
        self.message_pumps = 0
        self.accepted = {'key':0,'button':0,'motion':0,'wheel':0}
        self.filtered = 0
        self.thread = threading.Thread(target=self._run, name='windows-input', daemon=True)
        self.thread.start()
        if not self.ready.wait(5):
            self.close()
            raise RuntimeError('Windows 输入线程启动超时')
        if self.error:
            self.close()
            raise RuntimeError(self.error)
        # Keep asynchronous state polling outside the thread that dispatches
        # low-level keyboard hooks. It must continue even if that message
        # queue is busy, and must not query state from inside a hook dispatch.
        target = GameWindows(self.executable)
        user = ctypes.WinDLL('user32')
        user.GetAsyncKeyState.argtypes = [ctypes.c_int]
        user.GetAsyncKeyState.restype = ctypes.c_short
        self.sampler = WindowsStateFallback(lambda record_type,**fields:self._enqueue(record_type,fields),
                                          target.foreground,user.GetAsyncKeyState)

    def _run(self):
        backends = []
        fallback = None
        try:
            target = GameWindows(self.executable)
            hwnd = None
            def foreground():
                # Hook callbacks only make one native call; process discovery,
                # JSON, writer locks and SDL never execute in the callback.
                return bool(hwnd and target.user.GetForegroundWindow()==hwnd)
            def emit(record_type, **fields):
                if record_type=='input':
                    fields.setdefault('mono_ns', time.perf_counter_ns())
                    fields.setdefault('wall_ns', time.time_ns())
                    if not foreground():
                        self.filtered += 1
                        return
                    kind=fields.get('kind')
                    if kind in self.accepted:self.accepted[kind]+=1
                    if fallback and fields.get('backend')=='raw_input':
                        fallback.note_raw(fields)
                    if self.sampler:
                        self.sampler.note_event(fields)
                self._enqueue(record_type, fields)
            raw = RawInput(emit)
            backends.append(raw)
            self.received = raw.received
            try:
                def note_hook(fields):
                    # A hook event waits before publication so Raw Input can
                    # take precedence. State sampling must know it at receipt,
                    # rather than treating that wait as a missing keyboard.
                    if self.sampler:self.sampler.note_event(fields)
                fallback = WindowsInputFallback(emit, foreground, note_hook)
                backends.append(fallback)
            except Exception as exc:
                emit('error', message=f'键鼠事件兼容采集不可用：{exc}')
            self.ready.set()
            while not self.stopped.is_set():
                hwnd = target.foreground()
                for backend in backends:
                    backend.pump()
                self.message_pumps+=1
                self.announced = (fallback.announced if fallback else set())
                raw.wait(50)
        except Exception as exc:
            self.error = f'{type(exc).__name__}: {exc}'
        finally:
            for backend in reversed(backends):
                backend.close()
            self.ready.set()

    def _enqueue(self, kind, fields):
        with self._queue_lock:
            self._enqueue_locked(kind,fields)

    def _enqueue_locked(self, kind, fields):
        if self.missing:
            try:
                self.events.put_nowait(('gap', dict(reason='windows_input_overflow', count=1,
                    missing_events=self.missing,start_mono_ns=self.missing_start,end_mono_ns=self.missing_end)))
                self.missing = 0
                self.missing_start = self.missing_end = None
            except queue.Full:
                self.missing += 1
                self.missing_end=time.perf_counter_ns()
                return
        try:
            self.events.put_nowait((kind, fields))
        except queue.Full:
            self.missing += 1
            self.missing_start=self.missing_start or time.perf_counter_ns()
            self.missing_end=time.perf_counter_ns()

    def pump(self, *, raise_error=True):
        if self.sampler:
            self.sampler.pump()
            self.announced=self.announced | self.sampler.announced
        self._drain(raise_error=raise_error)

    def health(self):
        return dict(version=2,message_thread_alive=self.thread.is_alive(),message_pumps=self.message_pumps,
                    state_samples=getattr(self.sampler,'samples',0),raw_received=dict(self.received),
                    foreground_received=dict(self.accepted),foreground_filtered=self.filtered)

    def _drain(self, *, raise_error=True):
        for _ in range(32768):
            try:
                kind, fields = self.events.get_nowait()
            except queue.Empty:
                break
            self.emit(kind, **fields)
        if self.error and raise_error:
            raise RuntimeError(self.error)

    def wait(self, milliseconds):
        self.stopped.wait(milliseconds/1000)

    def close(self):
        self.stopped.set()
        self.thread.join(3)
        if self.sampler:self.sampler.close()
        self._drain(raise_error=False)
        if self.missing:
            self.emit('gap', reason='windows_input_overflow', count=1, missing_events=self.missing,
                      start_mono_ns=self.missing_start,end_mono_ns=self.missing_end)
            self.missing = 0
