from app_test_support.scenarios.trace import two_battles, wait_for
from PySide6.QtWidgets import QFileDialog

"""Trace files share canonical history presentation and never change live state."""

import json
import pytest
from PySide6.QtCore import QEventLoop, QTimer
import endfield_pcap.settings as gui_config
from endfield_pcap.history.analysis import load_record_snapshot
from endfield_pcap.history.importer import load_trace_records
from app_test_support.ui.window import main_window
from app_test_support.ui.qt import EVIDENCE, snapshot_message

def wait_for_damage(overlay, expected):
    wait_for(lambda: str(int(overlay.canvas.modules[0].snapshot.get('battle',{}).get('total_damage',0))) == expected, __import__('PySide6.QtWidgets',fromlist=['QApplication']).QApplication.instance())

def test_trace_import_indexes_then_loads_selected_snapshot_and_keeps_quality(tmp_path, monkeypatch):
    from parser_core import unified
    original_parse = unified.parse_overlay_battle_snapshot_text
    calls = []
    def parse(*args, **kwargs):
        calls.append(args[0])
        return original_parse(*args, **kwargs)
    monkeypatch.setattr(unified, 'parse_overlay_battle_snapshot_text', parse)
    path = tmp_path/'trace_20261022-100000.log'
    path.write_text(two_battles(), encoding='utf-8-sig')
    original = path.read_bytes()
    records = load_trace_records(path)
    assert path.read_bytes() == original
    assert [r.record_index for r in records] == [1, 2]
    assert not calls
    assert all(not r.snapshot and not r.analysis_loaded for r in records)
    assert all('2026-10-22' in r.label for r in records)
    snapshots = [load_record_snapshot(records[0])]
    assert len(calls) == 1 and not records[1].snapshot
    snapshots.append(load_record_snapshot(records[1]))
    assert [s['battle']['total_damage'] for s in snapshots] == [760, 860]
    assert all('snapshot_quality' in s for s in snapshots)
    assert snapshots[0]['participants'][0]['total_rd'] == pytest.approx(640)
    snapshots[0]['battle']['total_damage'] = 0
    assert load_record_snapshot(records[0])['battle']['total_damage'] == 760
    assert len(calls) == 2  # Repeat loading reuses the selected snapshot only.
    path.write_text('replaced after import', encoding='utf8')
    with pytest.raises(ValueError, match='已变化'):
        load_record_snapshot(records[0])
    assert records[0].source_end_line <= records[1].source_start_line

@pytest.mark.parametrize('value', [None, 'bad', 42, {}])
def test_invalid_trace_config_is_ignored(tmp_path, value):
    path = tmp_path/'settings.json'
    path.write_text(json.dumps({'imported_trace_files':value}), encoding='utf8')
    assert gui_config.load_app_config(path).imported_trace_files == []

def test_no_battle_is_an_import_error_without_modifying_source(tmp_path):
    path = tmp_path/'empty.log'
    path.write_text('[10:00:00.000] GAME_CLOCK_TICK tickMs=1', encoding='utf8')
    with pytest.raises(ValueError):
        load_trace_records(path)
    assert path.read_text(encoding='utf8').endswith('tickMs=1')

def test_gui_import_repeat_failure_history_and_return_live(main_window, app, monkeypatch, tmp_path):
    window = main_window
    path = tmp_path/'trace_20261022-100000.log'
    path.write_text(two_battles(), encoding='utf8')
    monkeypatch.setattr(QFileDialog, 'getOpenFileNames', lambda *a: ([str(path),str(path)], ''))
    window.switchTo(window.records_page)
    window.overlay_manager.apply_analysis_snapshot(snapshot_message())
    window.records_page.import_trace_btn.click()
    wait_for(lambda: not window.history_controller.import_pending, app)
    assert len(window.history_controller.records) == 2
    assert window.app_config.imported_trace_files == [path]
    assert gui_config.load_app_config(window.config_path).imported_trace_files == [path]
    assert not window.overlay_manager._history_mode  # import alone never switches sources
    window.records_page.import_trace_btn.click()
    wait_for(lambda: not window.history_controller.import_pending, app)
    assert len(window.history_controller.records) == 2
    window.records_page.load_overlay_btn.click()
    wait_for(lambda: window.overlay_manager._history_mode, app)
    selected = window.history_controller.selected_records[-1]
    assert window.overlay_manager._analysis_snapshot['snapshot']['battle']['total_damage'] == selected.total_damage
    platform=app.platformName()
    loop=QEventLoop(); QTimer.singleShot(200,loop.quit); loop.exec()
    assert window.grab().save(str(EVIDENCE/f'gui-trace-imported-{platform}.png'))
    overlay = window.overlay_manager._windows['controls']
    wait_for_damage(overlay,'860')
    assert len(overlay.canvas.modules[0].snapshot['participants']) == 2
    loop=QEventLoop(); QTimer.singleShot(250,loop.quit); loop.exec()
    assert overlay.grab().save(str(EVIDENCE/f'overlay-trace-imported-{platform}.png'))
    window.overlay_manager.apply_analysis_snapshot(snapshot_message(2))
    assert window.overlay_manager._history_mode
    window.records_page.return_live_btn.click()
    assert not window.overlay_manager._history_mode
    assert window.overlay_manager._analysis_snapshot['source']['mode'] == 'live'
    wait_for_damage(overlay,'760')
    assert overlay.canvas.modules[0].snapshot['battle']['total_damage']==760
    before = window.overlay_manager._analysis_snapshot
    monkeypatch.setattr(QFileDialog, 'getOpenFileNames', lambda *a: ([str(tmp_path/'missing.log')], ''))
    window.records_page.import_trace_btn.click()
    wait_for(lambda: not window.history_controller.import_pending, app)
    assert len(window.history_controller.records) == 2 and window.overlay_manager._analysis_snapshot == before
    assert window.records_page.import_trace_status.toolTip()
    monkeypatch.setattr(QFileDialog, 'getOpenFileNames', lambda *a: ([], ''))
    window.records_page.import_trace_btn.click()
    assert not window.history_controller.import_pending
    # Refresh reuses unchanged cached imports.
    window.history_presenter.refresh()
    assert not window.history_controller.import_pending
