"""History state owner: independent workers, generations, selection and cache."""
from __future__ import annotations

from dataclasses import dataclass, replace
import logging
from pathlib import Path
import queue
import threading

from endfield_pcap.application.settings import SettingsStore
from endfield_pcap.history import analysis
from endfield_pcap.history.files import rename_log, relocate_key, relocate_record
from endfield_pcap.history.importer import TraceCombatRecord, apply_snapshot_summary
from endfield_pcap.history.index import HistoryIndex, record_key, _resolve_log_dir
from endfield_pcap.inputlog.bindings import relocate_bindings

LOGGER = logging.getLogger(__name__)


def signature(record):
    try:
        stat = record.file_path.stat()
        return stat.st_mtime_ns, stat.st_size
    except OSError:
        return None


@dataclass(frozen=True, slots=True)
class RecordAnalysis:
    key: str
    snapshot: dict | None
    error: str | None


@dataclass(frozen=True, slots=True)
class HistoryBatch:
    generation: int
    results: tuple[RecordAnalysis, ...]
    open_details: bool


@dataclass(frozen=True, slots=True)
class HistoryListing:
    generation: int
    records: tuple
    errors: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TraceImport:
    generation: int
    results: tuple
    errors: tuple[str, ...]
    restore_keys: frozenset[str]


class HistoryController:
    def __init__(self, settings: SettingsStore, writing_state, *, index=None, loader=None):
        self.settings = settings
        self.index = index or HistoryIndex(settings.path.parent/'history-index')
        self._writing_state = writing_state
        self._loader = loader
        self._owner = threading.get_ident()
        self._results = queue.SimpleQueue()
        self._closed = False
        self._cancel = threading.Event()
        self._generation = self._index_generation = self._import_generation = 0
        self._raw_records = []
        self._trace_records = {}
        self._trace_signatures = {}
        self._log_dir = None
        self.records = []
        self.selection_order = []
        self.pending_keys = set()
        self.records_pending = self.import_pending = False
        self.record = None
        self.displayed_key = None
        self.detail_snapshot = self.detail_key = self.detail_signature = None

    def _assert_owner(self):
        if threading.get_ident() != self._owner:
            raise RuntimeError('历史记录只能在所属线程提交')

    @property
    def busy(self):
        return self.records_pending or self.import_pending or bool(self.pending_keys)

    @property
    def selected_records(self):
        records = {record_key(record): record for record in self.records}
        return [records[key] for key in self.selection_order if key in records]

    def select(self, keys, current=None):
        self._assert_owner()
        order = [key for key in self.selection_order if key in keys]
        order.extend(key for key in keys if key not in order)
        if current in order:
            order.remove(current)
            order.append(current)
        if order != self.selection_order and self.pending_keys:
            self._invalidate_analysis()
            self.record = next((record for record in self.records if record_key(record) == self.displayed_key), None)
        self.selection_order = order

    def _refresh_list(self):
        hidden = set(self.settings.current.hidden_history_records)
        records = [*self._raw_records, *(record for rows in self._trace_records.values() for record in rows)]
        self.records = sorted((record for record in records if record_key(record) not in hidden),
                              key=lambda record: record.started_at_ms, reverse=True)
        keys = {record_key(record) for record in self.records}
        self.selection_order = [key for key in self.selection_order if key in keys]

    def refresh(self):
        self._assert_owner()
        if self._closed:
            return False
        config = self.settings.current
        log_dir = _resolve_log_dir(config.service.log_dir)
        changed_directory = log_dir != config.service.log_dir
        if changed_directory:
            config.service.log_dir = log_dir
            self.settings.save()
        if self._log_dir != log_dir:
            self._index_generation += 1
            self.records_pending = False
            self._raw_records = []
            self._log_dir = log_dir
        self._refresh_list()
        if not self.records_pending:
            self.records_pending = True
            self._index_generation += 1
            generation, index, sink = self._index_generation, self.index, self._results

            def scan():
                records, errors = [], []
                try:
                    for path in sorted(log_dir.rglob('session_*.ndjson'), reverse=True):
                        try:
                            records.extend(index.records(path))
                        except Exception as exc:
                            errors.append(f'{path.name}: {exc}')
                except OSError as exc:
                    errors.append(str(exc))
                sink.put(HistoryListing(generation, tuple(records), tuple(errors)))

            threading.Thread(target=scan, name='history-index', daemon=True).start()
        changed = []
        for path in config.imported_trace_files:
            try:
                stat = path.stat()
            except OSError:
                continue
            if self._trace_signatures.get(path) != (stat.st_mtime_ns, stat.st_size):
                changed.append(path)
        self.import_files(changed, restore_removed=False)
        return changed_directory

    def import_files(self, paths, *, restore_removed=True):
        self._assert_owner()
        paths = tuple(dict.fromkeys(Path(path).resolve() for path in paths))
        if self._closed or self.import_pending or not paths:
            return False
        self.import_pending = True
        self._import_generation += 1
        generation, index, sink = self._import_generation, self.index, self._results
        restore = frozenset(self.settings.current.hidden_history_records) if restore_removed else frozenset()

        def read():
            results, errors = [], []
            for path in paths:
                try:
                    stat = path.stat()
                    records = index.records(path, trace=True)
                    results.append((path, (stat.st_mtime_ns, stat.st_size), records))
                except Exception as exc:
                    LOGGER.exception('trace import failed: %s', path)
                    errors.append(f'{path.name}: {exc}')
            sink.put(TraceImport(generation, tuple(results), tuple(errors), restore))

        threading.Thread(target=read, name='trace-import', daemon=True).start()
        return True

    def _invalidate_analysis(self):
        self._cancel.set()
        self._generation += 1
        self.pending_keys.clear()

    def load(self, keys, *, open_details=False):
        self._assert_owner()
        if self._closed:
            return False
        indexed = {record_key(record): record for record in self.records}
        records = [indexed[key] for key in dict.fromkeys(keys) if key in indexed]
        if not records:
            return False
        self._invalidate_analysis()
        self._cancel = cancel = threading.Event()
        generation, sink, loader = self._generation, self._results, self._loader or analysis.load_record_snapshot
        self.record = records[-1]
        self.pending_keys = {record_key(record) for record in records}
        # Workers get disposable row metadata. Trace parsing may cache on that
        # row, but never touches controller-owned records or full-report caches.
        requests = [(record_key(record), replace(record, snapshot={}) if isinstance(record, TraceCombatRecord)
                     else replace(record)) for record in records]

        def analyze():
            results = []
            for key, record in requests:
                if cancel.is_set():
                    return
                try:
                    results.append(RecordAnalysis(key, loader(record), None))
                except Exception as exc:
                    LOGGER.exception('history snapshot analysis failed')
                    results.append(RecordAnalysis(key, None, str(exc)))
            if not cancel.is_set():
                sink.put(HistoryBatch(generation, tuple(results), open_details))

        threading.Thread(target=analyze, name='history-analysis', daemon=True).start()
        return True

    def cached_snapshot(self, record):
        if self.detail_key == record_key(record) and self.detail_signature == signature(record):
            return self.detail_snapshot
        return None

    def drain(self):
        self._assert_owner()
        accepted = []
        while True:
            try:
                result = self._results.get_nowait()
            except queue.Empty:
                break
            if self._closed:
                continue
            if isinstance(result, HistoryBatch):
                if result.generation != self._generation:
                    continue
                self.pending_keys.clear()
                indexed = {record_key(record): record for record in self.records}
                for value in result.results:
                    if value.snapshot is not None and value.key in indexed:
                        apply_snapshot_summary(indexed[value.key], value.snapshot)
                last = result.results[-1]
                self.record = indexed.get(last.key)
                if last.snapshot is not None and self.record is not None:
                    self.displayed_key = self.detail_key = last.key
                    self.detail_snapshot = last.snapshot
                    self.detail_signature = signature(self.record)
            elif isinstance(result, HistoryListing):
                if result.generation != self._index_generation:
                    continue
                self.records_pending = False
                self._raw_records = list(result.records)
            elif isinstance(result, TraceImport):
                if result.generation != self._import_generation:
                    continue
                self.import_pending = False
                config = self.settings.current
                restored = {record_key(record) for _, _, rows in result.results for record in rows} & result.restore_keys
                config.hidden_history_records = [key for key in config.hidden_history_records if key not in restored]
                for path, value, records in result.results:
                    self._trace_records[path], self._trace_signatures[path] = records, value
                    if path not in config.imported_trace_files:
                        config.imported_trace_files.append(path)
                if result.results:
                    self.settings.save()
            self._refresh_list()
            accepted.append(result)
        return accepted

    def return_live(self):
        self._assert_owner()
        self._invalidate_analysis()
        self.record = self.displayed_key = None

    def remove(self, keys):
        self._assert_owner()
        keys = set(keys)
        reset = self.displayed_key in keys or (self.record is not None and record_key(self.record) in keys) or bool(self.pending_keys & keys)
        if reset:
            self.return_live()
        if self.detail_key in keys:
            self.release_cache()
        hidden = self.settings.current.hidden_history_records
        hidden.extend(sorted(keys-set(hidden)))
        self.settings.save()
        self._refresh_list()
        return reset

    def rename(self, path, label):
        self._assert_owner()
        if self._closed or self.busy:
            raise ValueError('请等待当前索引或分析结束后重命名')
        path = Path(path).resolve()
        if not self._writing_state().permits_rename(path):
            raise ValueError('该文件正在抓包写入或路径尚未确定，请先在首页停止服务再重命名')
        new = rename_log(path, label)
        if new == path:
            return new
        rows = [*self._raw_records, *(record for records in self._trace_records.values() for record in records),
                *self.records, self.record]
        for record in rows:
            if record is not None:
                relocate_record(record, path, new)
        if path in self._trace_records:
            self._trace_records[new] = self._trace_records.pop(path)
        if path in self._trace_signatures:
            self._trace_signatures[new] = self._trace_signatures.pop(path)
        config = self.settings.current
        config.imported_trace_files = [new if item == path else item for item in config.imported_trace_files]
        config.hidden_history_records = [relocate_key(key, path, new) for key in config.hidden_history_records]
        config.input_log_bindings = relocate_bindings(config.input_log_bindings, path, new)
        self.displayed_key = relocate_key(self.displayed_key, path, new)
        self.detail_key = relocate_key(self.detail_key, path, new)
        self.selection_order = [relocate_key(key, path, new) for key in self.selection_order]
        self.index.relocate(path, new)
        self.settings.save()
        self._refresh_list()
        return new

    def release_cache(self):
        self._assert_owner()
        self.detail_snapshot = self.detail_key = self.detail_signature = None
        for records in self._trace_records.values():
            for record in records:
                record.snapshot = {}
        from endfield_pcap.inputlog.history import clear_cache
        clear_cache()

    def close(self):
        self._assert_owner()
        self._closed = True
        self.return_live()
        self._index_generation += 1
        self._import_generation += 1
        self.records_pending = self.import_pending = False
        self.release_cache()
        self.drain()
