"""Versioned JSONL, bounded asynchronous writes, explicit loss intervals."""
from __future__ import annotations
import hashlib
from copy import deepcopy
import json
import queue
import threading
import time
import uuid
from pathlib import Path

SCHEMA_VERSION = 1


def companion(trace):
    return Path(trace).with_suffix('.input.jsonl')


def clock():
    return {'wall_ns': time.time_ns(), 'mono_ns': time.perf_counter_ns()}


class InputWriter:
    def __init__(self, path, *, trace=None, capacity=32768, session=None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # An existing recording is never silently appended to a different session.
        self.file = self.path.open('x', encoding='utf-8', buffering=256*1024)
        self.queue = queue.Queue(maxsize=capacity)
        self.seq = self.count = self.lost = 0
        self.error = None
        self._lock = threading.Lock()
        self._gap = None
        self.trace = Path(trace) if trace else None
        self._write(dict(type='session', schema_version=SCHEMA_VERSION,
            session_id=session or uuid.uuid4().hex, trace_name=self.trace.name if self.trace else None,
            clock='unix_ns + perf_counter_ns', **clock()))
        self.thread = threading.Thread(target=self._run, name='input-jsonl', daemon=True)
        self.thread.start()

    def _write(self, item):
        self.file.write(json.dumps(item, ensure_ascii=False, separators=(',', ':'), allow_nan=False)+'\n')

    def put(self, record_type, **fields):
        with self._lock:
            self.seq += 1
            item = dict(type=record_type, seq=self.seq, **clock())
            item.update(deepcopy(fields))
            if self._gap:
                try:
                    self.queue.put_nowait(self._gap)
                    self._gap = None
                except queue.Full:
                    pass
            try:
                if self._gap:
                    raise queue.Full
                self.queue.put_nowait(item)
                self.count += 1
                return item
            except queue.Full:
                self.lost += 1
                if self._gap is None:
                    self._gap = dict(type='gap', seq=self.seq, start_wall_ns=item['wall_ns'],
                                     start_mono_ns=item['mono_ns'], count=0)
                self._gap.update(end_wall_ns=item['wall_ns'], end_mono_ns=item['mono_ns'])
                self._gap['count'] += 1
                return None

    def _run(self):
        flushed_at=time.monotonic()
        try:
            while True:
                try:
                    item = self.queue.get(timeout=.25)
                except queue.Empty:
                    self.file.flush()
                    flushed_at=time.monotonic()
                    continue
                if item is None:
                    break
                self._write(item)
                # A busy mouse/joystick queue may never become empty. Keep
                # the live file readable instead of waiting for buffer size.
                if time.monotonic()-flushed_at>=.25:
                    self.file.flush()
                    flushed_at=time.monotonic()
        except Exception as exc:
            self.error = str(exc)

    def close(self, reason='stopped'):
        # Only called by the input process's control loop, never a capture callback.
        if self.thread.is_alive():
            if self._gap:
                self._enqueue_final(self._gap)
                self._gap = None
            self._enqueue_final(dict(type='end', reason=reason, **clock()))
            self._enqueue_final(None)
            self.thread.join(5)
        if self.thread.is_alive():
            raise OSError('输入日志写入未能结束')
        if self.trace and self.trace.is_file() and not self.error:
            # The trace may still grow. Mark the exact prefix covered by this recording.
            size = self.trace.stat().st_size
            digest = hashlib.sha256()
            with self.trace.open('rb') as source:
                remaining = size
                while remaining:
                    block = source.read(min(1024*1024, remaining))
                    if not block:
                        break
                    digest.update(block)
                    remaining -= len(block)
            self._write(dict(type='trace_digest', name=self.trace.name, bytes=size-remaining,
                             sha256=digest.hexdigest(), scope='prefix'))
        self.file.close()
        if self.error:
            raise OSError(self.error)

    def _enqueue_final(self, item):
        while self.thread.is_alive():
            try:
                self.queue.put(item, timeout=.1)
                return
            except queue.Full:
                continue
