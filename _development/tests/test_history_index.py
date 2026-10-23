"""History lists index in the background; removal never deletes source logs."""
import json
import threading

import pytest

from endfield_pcap import gui_config, gui_main, history_index
from endfield_pcap.history_analysis import load_record_snapshot
from endfield_pcap.history_index import HistoryIndex, record_key
from test_history_overlay import raw_scene, raw_hit
from test_trace_import import two_battles, wait_for
from test_overlay_controls import main_window


def test_unchanged_trace_index_survives_restart_without_read_or_analysis(tmp_path, monkeypatch):
    source = tmp_path / 'trace_20261022-100000.log'
    source.write_text(two_battles(), encoding='utf-8-sig')
    index = HistoryIndex(tmp_path / 'index')
    first = index.records(source, trace=True)
    def forbidden(*args, **kwargs):
        pytest.fail('unchanged source was reindexed')
    monkeypatch.setattr(history_index, 'load_trace_records', forbidden)
    again = HistoryIndex(index.directory).records(source, trace=True)
    assert [record_key(r) for r in first] == [record_key(r) for r in again]
    assert all(not r.snapshot for r in again)
    assert load_record_snapshot(again[1])['battle']['total_damage'] == 860
    payload = json.loads(next(index.directory.glob('*.json')).read_text(encoding='utf-8'))
    assert 'snapshot' not in payload['records'][0]
    assert 'content' not in payload['records'][0]


def test_changed_trace_invalidates_disk_index(tmp_path, monkeypatch):
    source = tmp_path / 'trace_20261022-100000.log'
    source.write_text(two_battles(), encoding='utf-8')
    index = HistoryIndex(tmp_path / 'index')
    old = index.records(source, trace=True)
    source.write_text(two_battles().replace('hit=200 ', 'hit=300 '), encoding='utf-8')
    new = index.records(source, trace=True)
    assert new[0].source_signature != old[0].source_signature
    assert load_record_snapshot(new[1])['battle']['total_damage'] == 960
    with pytest.raises(ValueError, match='已变化'):
        load_record_snapshot(old[0])


def test_ndjson_cache_skips_reparsing_and_recovers_from_corruption(tmp_path, monkeypatch):
    source = tmp_path / 'session_test.ndjson'
    source.write_text('\n'.join(json.dumps(e) for e in [raw_scene(), raw_hit(1001000, 123)]), encoding='utf-8')
    index = HistoryIndex(tmp_path / 'index')
    assert index.records(source)[0].total_damage == 123
    original = history_index._parse_log_file
    calls = []
    def parse(path):
        calls.append(path)
        return original(path)
    monkeypatch.setattr(history_index, '_parse_log_file', parse)
    assert index.records(source)[0].total_damage == 123
    assert not calls
    next(index.directory.glob('*.json')).write_text('bad cache', encoding='utf8')
    assert index.records(source)[0].total_damage == 123
    assert calls == [source]


def test_gui_indexes_off_thread_and_removes_only_one_battle_persistently(main_window, app, tmp_path, monkeypatch):
    window = main_window
    wait_for(lambda: not window._records_pending, app)
    source = tmp_path / 'trace_20261022-100000.log'
    source.write_text(two_battles(), encoding='utf-8')
    original_bytes = source.read_bytes()
    original = window._history_index.records
    threads = []
    def indexed(*args, **kwargs):
        threads.append(threading.current_thread())
        return original(*args, **kwargs)
    monkeypatch.setattr(window._history_index, 'records', indexed)
    window._queue_trace_import([source])
    wait_for(lambda: not window._trace_import_pending, app)
    assert len(window.records) == 2
    assert all(t is not threading.main_thread() for t in threads)
    assert all(not r.snapshot for r in window.records)
    assert window.records_page.summary_total.text() == '待加载'
    assert '不会删除原始日志文件' in window.records_page.remove_record_hint.text()
    removed = window._selected_record
    key = record_key(removed)
    window.records_page.remove_record_btn.click()
    assert len(window.records) == 1
    assert key in gui_config.load_app_config(window.config_path).hidden_history_records
    assert source.read_bytes() == original_bytes
    window._load_records()
    wait_for(lambda: not window._records_pending and not window._trace_import_pending, app)
    assert len(window.records) == 1
    # Simulate a restart: forget all in-memory trace records/signatures.
    window._trace_records.clear()
    window._trace_signatures.clear()
    window._load_records()
    wait_for(lambda: not window._records_pending and not window._trace_import_pending, app)
    assert len(window.records) == 1
    assert record_key(window.records[0]) != key
    # Explicit import restores the hidden battle; background refresh never does.
    window._queue_trace_import([source])
    wait_for(lambda: not window._trace_import_pending, app)
    assert len(window.records) == 2
    assert key not in window.app_config.hidden_history_records
    assert source.read_bytes() == original_bytes


def test_removal_during_analysis_and_reimport_cannot_resurrect_record(main_window, app, tmp_path, monkeypatch):
    window = main_window
    source = tmp_path / 'trace_20261022-100000.log'
    source.write_text(two_battles(), encoding='utf8')
    window._queue_trace_import([source])
    wait_for(lambda: not window._trace_import_pending, app)
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    def analyze(record):
        entered.set()
        release.wait(5)
        finished.set()
        return {'battle': {'total_damage': 999999}}
    monkeypatch.setattr('endfield_pcap.gui_history.load_record_snapshot', analyze)
    window._load_selected_history()
    wait_for(entered.is_set, app)
    # Queue a reimport first, then remove before its result is delivered.
    window._queue_trace_import([source])
    window._remove_selected_history()
    release.set()
    wait_for(lambda: finished.is_set() and not window._trace_import_pending, app)
    window._drain_queue()
    assert len(window.records) == 1
    assert not window.overlay_manager._history_mode
    assert len(window.app_config.hidden_history_records) == 1


def test_ndjson_scan_does_not_block_gui_and_removed_row_stays_hidden(main_window, app, tmp_path, monkeypatch):
    window = main_window
    wait_for(lambda: not window._records_pending, app)
    source = tmp_path / 'session_test.ndjson'
    source.write_text('\n'.join(json.dumps(e) for e in [raw_scene(), raw_hit(1001000, 123)]), encoding='utf8')
    original_bytes = source.read_bytes()
    entered, release = threading.Event(), threading.Event()
    original = window._history_index.records
    def slow_index(*args, **kwargs):
        assert threading.current_thread() is not threading.main_thread()
        entered.set()
        release.wait(5)
        return original(*args, **kwargs)
    monkeypatch.setattr(window._history_index, 'records', slow_index)
    window._load_records()
    wait_for(entered.is_set, app)
    assert window._records_pending
    # The UI event loop remains available while the source is being indexed.
    window.records_page.return_live_btn.click()
    assert window.records_page.overlay_source_status.text() == '悬浮窗：实时日志'
    release.set()
    wait_for(lambda: not window._records_pending, app)
    assert len(window.records) == 1
    window.records_page.remove_record_btn.click()
    assert not window.records
    window._load_records()
    wait_for(lambda: not window._records_pending, app)
    assert not window.records and not window.records_page.remove_record_btn.isEnabled()
    assert source.read_bytes() == original_bytes
    assert len(gui_config.load_app_config(window.config_path).hidden_history_records) == 1
