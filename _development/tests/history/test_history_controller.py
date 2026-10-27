"""Owner-thread history state and request ordering, without a widget host."""
import threading
import time

import pytest

from endfield_pcap.application.capture_state import CaptureWritingState, WritingKind
from endfield_pcap.application.history import HistoryController, HistoryBatch
from endfield_pcap.application.settings import SettingsStore
from endfield_pcap.history.importer import TraceCombatRecord
from endfield_pcap.history.index import record_key
from endfield_pcap.settings import load_app_config


def drain_until(controller, condition):
    deadline = time.monotonic()+3
    while not condition():
        controller.drain()
        if time.monotonic() >= deadline:
            pytest.fail('history task did not reach its expected state')
        time.sleep(.002)


class GatedAnalysis:
    def __init__(self):
        self.entered = {index: threading.Event() for index in (1, 2)}
        self.release = {index: threading.Event() for index in (1, 2)}
        self.threads = {}
        self.snapshots = {index: dict(battle=dict(total_damage=index*100, duration_ms=1000)) for index in (1, 2)}

    def __call__(self, record):
        index = record.record_index
        self.threads[index] = threading.current_thread()
        self.entered[index].set()
        assert self.release[index].wait(5)
        # The trace adapter is allowed to cache only on its disposable request.
        record.snapshot = self.snapshots[index]
        return record.snapshot

    def finish(self, index):
        assert self.entered[index].wait(2)
        self.release[index].set()
        self.threads[index].join(2)
        assert not self.threads[index].is_alive()

    def cleanup(self):
        for event in self.release.values():
            event.set()
        for thread in self.threads.values():
            thread.join(2)


def history(tmp_path, loader):
    path = tmp_path/'settings.json'
    source = tmp_path/'trace_20261028.log'
    source.write_text('synthetic index source', encoding='utf8')
    rows = [TraceCombatRecord(source, index, index*1000, f'fixture {index}', analysis_loaded=False)
            for index in (1, 2)]

    class Index:
        def records(self, path, *, trace):
            assert path == source and trace
            return rows

    settings = SettingsStore(load_app_config(path), path)
    controller = HistoryController(settings, lambda: CaptureWritingState(WritingKind.IDLE), index=Index(), loader=loader)
    controller.import_files([source])
    drain_until(controller, lambda: not controller.import_pending)
    return controller, rows, source


def test_new_request_keeps_its_record_snapshot_and_cache_after_old_worker_finishes(tmp_path):
    loader = GatedAnalysis()
    controller, rows, _ = history(tmp_path, loader)
    first, second = map(record_key, rows)
    try:
        controller.select([first], first)
        controller.load([first])
        assert loader.entered[1].wait(2)
        controller.select([second], second)
        controller.load([second], open_details=True)
        loader.finish(2)
        assert not rows[1].analysis_loaded and not rows[1].snapshot
        accepted = controller.drain()
        assert len(accepted) == 1 and isinstance(accepted[0], HistoryBatch)
        assert accepted[0].open_details
        assert controller.record is rows[1] and controller.displayed_key == second
        snapshot = controller.cached_snapshot(rows[1])
        assert snapshot is loader.snapshots[2]
        assert rows[1].total_damage == 200
        loader.finish(1)
        assert controller.drain() == []
        assert controller.record is rows[1] and controller.displayed_key == second
        assert controller.cached_snapshot(rows[1]) is snapshot
        assert not rows[0].snapshot and not rows[0].analysis_loaded
        # A window may retain the same report after the disposable cache drops.
        controller.release_cache()
        assert controller.detail_snapshot is None and snapshot['battle']['total_damage'] == 200
    finally:
        controller.close()
        loader.cleanup()


@pytest.mark.parametrize('action', ['live', 'remove', 'selection', 'close'])
@pytest.mark.parametrize('completed', [False, True])
def test_invalidated_history_never_restores_a_record_or_report(tmp_path, action, completed):
    loader = GatedAnalysis()
    controller, rows, source = history(tmp_path, loader)
    key = record_key(rows[0])
    original = source.read_bytes()
    try:
        controller.select([key], key)
        controller.load([key], open_details=True)
        assert loader.entered[1].wait(2)
        if completed:
            loader.finish(1)
        if action == 'live':
            controller.return_live()
        elif action == 'remove':
            controller.remove([key])
        elif action == 'selection':
            controller.select([record_key(rows[1])], record_key(rows[1]))
        else:
            controller.close()
        loader.finish(1)
        assert controller.drain() == []
        assert controller.displayed_key is None and controller.detail_snapshot is None
        assert not controller.pending_keys and not rows[0].analysis_loaded and not rows[0].snapshot
        if action == 'remove':
            assert key not in {record_key(record) for record in controller.records}
            assert key in load_app_config(controller.settings.path).hidden_history_records
        assert source.read_bytes() == original
    finally:
        controller.close()
        loader.cleanup()


def test_batch_keeps_requested_order_and_last_failure_without_success_fallback(tmp_path):
    calls, threads = [], []
    entered = threading.Event()

    def load(record):
        calls.append(record.record_index)
        threads.append(threading.current_thread())
        if record.record_index == 1:
            entered.set()
            raise ValueError('final selected item failed')
        return dict(battle=dict(total_damage=200))

    controller, rows, _ = history(tmp_path, load)
    keys = [record_key(rows[1]), record_key(rows[0])]
    try:
        controller.select(keys, keys[-1])
        controller.load(keys)
        assert entered.wait(2)
        threads[-1].join(2)
        results = controller.drain()
        assert calls == [2, 1]
        assert results[0].results[-1].error == 'final selected item failed'
        assert controller.record is rows[0]
        assert controller.displayed_key is None and controller.detail_snapshot is None
        assert rows[1].total_damage == 200 and not rows[0].analysis_loaded
    finally:
        controller.close()


@pytest.mark.parametrize('kind,active,allowed', [
    (WritingKind.IDLE, False, True), (WritingKind.ACTIVE, True, False),
    (WritingKind.ACTIVE, False, True), (WritingKind.UNCERTAIN, False, False),
])
def test_public_writing_state_distinguishes_idle_known_path_and_uncertain(tmp_path, kind, active, allowed):
    source = tmp_path/'source.log'
    status = CaptureWritingState(kind, (source.resolve(),) if active else (tmp_path/'different.log',))
    assert status.permits_rename(source) is allowed
