"""Own one battle's input binding and generation-checked background interpretation."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
import queue
import threading

from endfield_pcap.application.settings import SettingsStore
from endfield_pcap.history.index import record_key
from endfield_pcap.history.files import relocate_key
from endfield_pcap.inputlog.bindings import read_binding, write_binding
from endfield_pcap.inputlog.history import discover, load_evidence
from endfield_pcap.inputlog.interpret import normalize_settings


def empty_evidence():
    return dict(actions=[], raw=[], warnings=[])


@dataclass(frozen=True, slots=True)
class InputEvidenceState:
    trace_path: Path | None = None
    paths: tuple[Path, ...] = ()
    visible: bool = False
    offset_ms: float = 0.
    start_override: float | None = None
    manual_slots: dict = field(default_factory=dict)
    settings: dict = field(default_factory=dict)
    pending: bool = False
    error: str | None = None
    evidence: dict = field(default_factory=empty_evidence)


@dataclass(frozen=True, slots=True)
class InputEvidenceResult:
    generation: int
    evidence: dict | None = None
    error: str | None = None


class InputEvidenceController:
    def __init__(self, battle: dict, settings: SettingsStore, *, loader=None):
        self._owner = threading.get_ident()
        # Only the small interpretation input is copied, never the full report.
        self._battle = deepcopy(battle)
        self._store = settings
        self._loader = loader or load_evidence
        self._record = None
        self._trace_path = None
        self._generation = 0
        self._closed = False
        self._cancel = threading.Event()
        self._results = queue.SimpleQueue()
        self._paths = []
        self._visible = self._manual = self._pending = False
        self._offset = 0.
        self._start_override = None
        self._slots = {}
        self._settings = normalize_settings(settings.current.input_settings)
        self._evidence = empty_evidence()
        self._error = None

    def _assert_owner(self):
        if threading.get_ident() != self._owner:
            raise RuntimeError('输入证据只能在所属线程提交')

    @property
    def state(self):
        return InputEvidenceState(self._trace_path,
            tuple(self._paths), self._visible, self._offset, self._start_override,
            dict(self._slots), deepcopy(self._settings), self._pending, self._error, self._evidence)

    def set_record(self, record):
        self._assert_owner()
        if self._closed:
            return
        self._record = record_key(record)
        self._trace_path = record.file_path
        bindings = self._store.current.input_log_bindings
        key = record_key(record)
        saved = read_binding(bindings.get(key), record.file_path)
        self._paths = ([saved['path']] if saved['path'] else []) if key in bindings else discover(record.file_path)[:1]
        self._visible, self._manual = saved['visible'], saved['manual']
        self._offset, self._start_override = saved['offset_ms'], saved['start_override']
        self._slots = saved['manual_slots']
        self.reload()

    def bind(self, path):
        self._assert_owner()
        if self._closed:
            return
        self._paths = [Path(path)]
        self._manual = True
        self._offset, self._start_override, self._slots = 0., None, {}
        self._save_binding()
        self.reload()

    def unbind(self):
        self._assert_owner()
        if self._closed:
            return
        self._paths, self._manual = [], False
        self._save_binding()
        self.reload()

    def set_visible(self, visible):
        self._assert_owner()
        if not self._closed:
            self._visible = bool(visible)
            self._save_binding()

    def set_alignment(self, *, offset_ms, start_override, manual_slots):
        self._assert_owner()
        if self._closed:
            return
        self._offset = offset_ms
        self._start_override = start_override
        self._slots, self._manual = dict(manual_slots), True
        self._save_binding()
        self.reload()

    def set_settings(self, value):
        self._assert_owner()
        if self._closed:
            return
        self._settings = normalize_settings(value)
        self._store.set_input_settings(self._settings)
        self.reload()

    def _save_binding(self):
        if self._record:
            self._store.set_input_binding(self._record, write_binding(
                self._trace_path, self._paths[0] if self._paths else None,
                visible=self._visible, offset_ms=self._offset, start_override=self._start_override,
                manual_slots=self._slots, manual=self._manual))

    def _invalidate(self):
        self._cancel.set()
        self._generation += 1
        self._pending = False
        self._evidence, self._error = empty_evidence(), None
        while True:
            try:
                self._results.get_nowait()
            except queue.Empty:
                break

    def reload(self):
        self._assert_owner()
        if self._closed:
            return
        self._invalidate()
        if not self._record or not self._paths:
            return
        self._cancel = cancel = threading.Event()
        self._pending = True
        generation, sink, loader = self._generation, self._results, self._loader
        args = (list(self._paths), self._trace_path, deepcopy(self._battle), deepcopy(self._settings))
        kwargs = dict(offset_ms=self._offset, start_override=self._start_override,
                      manual_slots=dict(self._slots), verify=not self._manual)

        def load():
            try:
                result = InputEvidenceResult(generation, loader(*args, **kwargs))
            except Exception as exc:
                result = InputEvidenceResult(generation, error=str(exc))
            if not cancel.is_set():
                sink.put(result)

        threading.Thread(target=load, name='input-history', daemon=True).start()

    def relocate(self, old, new):
        self._assert_owner()
        if self._closed or self._trace_path != old:
            return
        self._record = relocate_key(self._record, old, new)
        self._trace_path = new
        binding = read_binding(self._store.current.input_log_bindings.get(self._record), new)
        self._paths = [binding['path']] if binding['path'] else []
        self.reload()

    def drain(self):
        self._assert_owner()
        changed = False
        while True:
            try:
                result = self._results.get_nowait()
            except queue.Empty:
                break
            if self._closed or result.generation != self._generation:
                continue
            self._pending, self._error = False, result.error
            self._evidence = result.evidence if result.evidence is not None else empty_evidence()
            changed = True
        return changed

    def close(self):
        self._assert_owner()
        self._closed = True
        self._invalidate()
