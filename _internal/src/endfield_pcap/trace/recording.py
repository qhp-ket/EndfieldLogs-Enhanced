"""Persistent JSONL recording; live consumers receive complete event batches."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime
import hashlib
from pathlib import Path
from threading import RLock
from uuid import uuid4

from parser_core.trace_jsonl import TraceHeader, TraceJsonlWriter, serialize
from endfield_pcap.trace.bridge import TraceBridge


def make_recording_header(*, now=None):
    from endfield_pcap._version import __version__
    from endfield_pcap.runtime.paths import bundle_root
    now = now or datetime.now().astimezone()
    if now.tzinfo is None:
        now = now.astimezone()
    resources = {}
    for name in ('resource-manifest.json', 'runtime-data.zip'):
        path = bundle_root() / 'data' / name
        if path.is_file():
            with path.open('rb') as stream:
                resources[name] = hashlib.file_digest(stream, 'sha256').hexdigest()
    return TraceHeader(str(uuid4()), 1, None, 'python', __version__, now.tzname() or 'local',
                       int(now.utcoffset().total_seconds() // 60), resources)


class TraceRecording:
    def __init__(self, event_sink, header, *, log_directory=None, archive_time=None, on_changed=None, trace_file=None):
        if header.volume != 1 or header.previous_volume is not None:
            raise ValueError('A new recording must start at volume 1')
        self._header = deepcopy(header)
        serialize(self._header)
        self._sink, self._on_changed = event_sink, on_changed
        self._directory = Path(log_directory).resolve() if log_directory is not None else None
        self._initial_file = Path(trace_file).resolve() if trace_file is not None else None
        if self._initial_file is not None and self._initial_file.suffix.lower() != '.jsonl':
            raise ValueError('Structured recordings require a .jsonl filename')
        self._lock = RLock()
        self._pending = []
        self._stream = self._writer = None
        self.trace_file = None
        self.events_written = 0
        self._file_sequence = 0
        self._closed = self._failed = False
        self._bridge = TraceBridge(write_enabled=False, event_sink=self._pending.append,
                                   line_sink=self._unexpected_text)
        if self._directory is not None or self._initial_file is not None:
            self.trace_file, self._stream, self._writer = self._open_volume(self._header, archive_time)

    @staticmethod
    def _unexpected_text(line):
        raise RuntimeError('Structured recording emitted legacy text')

    @property
    def header(self):
        with self._lock:
            return deepcopy(self._header)

    def _open_volume(self, header, time):
        time = time or datetime.now()
        folder = (self.trace_file.parent if self.trace_file is not None else self._initial_file.parent
                  if self._initial_file is not None else self._directory / time.strftime('%Y%m%d'))
        folder.mkdir(parents=True, exist_ok=True)
        stem = 'trace_' + time.strftime('%Y%m%d-%H%M%S')
        if self.trace_file is None and self._initial_file is not None:
            stem = self._initial_file.stem
        index = 0
        while True:
            path = folder / (stem + (f'_{index:02d}' if index else '') + '.jsonl')
            try:
                stream = path.open('xb')
                break
            except FileExistsError:
                index += 1
        try:
            writer = TraceJsonlWriter(stream, header)
            writer.flush()
            return path, stream, writer
        except BaseException:
            stream.close()
            raise

    def _check(self):
        if self._closed:
            raise RuntimeError('The recording is closed')
        if self._failed:
            raise RuntimeError('The recording failed and cannot continue')

    def _execute(self, produce):
        with self._lock:
            self._check()
            try:
                result = produce()
                if self._pending:
                    if self._writer is not None:
                        self.append_events(self._pending)
                    batch = tuple(self._pending)
                    self._pending.clear()
                    self._sink(batch)
                    self.events_written += len(batch)
                    if self._on_changed is not None:
                        self._on_changed()
                return result
            except BaseException:
                self._failed = True
                self._pending.clear()
                raise

    def handle_event(self, event):
        return self._execute(lambda: self._bridge.handle_event(event))

    def begin_capture_session(self, *, timestamp_ms=None):
        return self._execute(lambda: self._bridge.begin_capture_session(timestamp_ms=timestamp_ms))

    def end_capture_session(self, *, timestamp_ms=None):
        return self._execute(lambda: self._bridge.end_capture_session(timestamp_ms=timestamp_ms))

    def flush_pending(self):
        return self._execute(self._bridge.flush_pending)

    def append_events(self, events):
        """Copy the producer's completed group to this file, without recalculation."""
        with self._lock:
            self._check()
            if self._writer is not None:
                for event in events:
                    self._file_sequence += 1
                    self._writer.write(replace(event, sequence=self._file_sequence))
                self._writer.flush()

    def rotate_volume(self, *, archive_time=None):
        with self._lock:
            self._check()
            if self.trace_file is None:
                raise RuntimeError('Continuous volumes require a file recording')
            header = replace(self._header, volume=self._header.volume + 1,
                             previous_volume={'volume': self._header.volume, 'file': self.trace_file.name})
            self._writer.flush()
            path, stream, writer = self._open_volume(header, archive_time)
            previous = self._stream
            self.trace_file, self._stream, self._writer, self._header = path, stream, writer, header
            previous.close()
            if self._on_changed is not None:
                self._on_changed()
            return path

    def close(self, *, finish_session=True):
        with self._lock:
            if self._closed:
                return
            try:
                if not self._failed:
                    self.end_capture_session() if finish_session else self.flush_pending()
            finally:
                self._closed = True
                if self._stream is not None:
                    self._stream.close()

    def __enter__(self):
        return self

    def __exit__(self, *exception):
        self.close()
