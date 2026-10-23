"""Trace files share canonical history presentation and never change live state."""
import json
from pathlib import Path

import pytest
from PySide6.QtTest import QTest
from PySide6.QtCore import QEventLoop, QTimer

from endfield_pcap import gui_config, gui_main
from endfield_pcap.history_analysis import load_record_snapshot
from endfield_pcap.trace_import import load_trace_records
from test_overlay_controls import main_window
from test_qt_snapshot_bridge import EVIDENCE, snapshot_message, read_dom


def two_battles():
    fixture = Path(__file__).resolve().parents[2] / '_internal/packages/parser_core/tests/fixtures/rdps_snapshot_contract.log'
    text = fixture.read_text(encoding='utf8')
    return '\n'.join([
        '[10:00:00.000] OFFICIAL_TIMER_START source=SC_GAME_MECHANICS_SYNC_CHALLENGE_START gameId=indie_hard011_s challengeStartTs=1000',
        text,
        '[10:00:03.000] OFFICIAL_TIMER_END source=SC_GAME_MECHANICS_SYNC_CHALLENGE_COMPLETE gameId=indie_hard011_s isPass=1 passTime=3000',
        '[10:00:04.000] GAME_TIMER_RESET source=SC_GAME_MECHANICS_SYNC_LEAVE_GAME_INST',
        '[10:01:00.000] OFFICIAL_TIMER_START source=SC_GAME_MECHANICS_SYNC_CHALLENGE_START gameId=indie_hard011_s challengeStartTs=61000',
        text.replace('10:00:', '10:01:').replace('hit=100 ', 'hit=200 '),
        '[10:01:03.000] OFFICIAL_TIMER_END source=SC_GAME_MECHANICS_SYNC_CHALLENGE_COMPLETE gameId=indie_hard011_s isPass=1 passTime=3000'])


def wait_for(predicate, app, timeout=45000):
    loop=QEventLoop()
    poll=QTimer()
    poll.setInterval(25)
    poll.timeout.connect(lambda: loop.quit() if predicate() else None)
    timeout_timer=QTimer()
    timeout_timer.setSingleShot(True)
    timeout_timer.timeout.connect(loop.quit)
    if not predicate():
        poll.start(); timeout_timer.start(timeout); loop.exec()
    poll.stop(); timeout_timer.stop()
    assert predicate()


def wait_for_damage(overlay, expected):
    # A newly enabled window may finish loading before the history-completion
    # queue has returned. Verify the rendered state without awaiting a past
    # loadFinished signal or reloading to manufacture another one.
    loop=QEventLoop()
    poll=QTimer(); poll.setInterval(50)
    observed=[]
    def received(value):
        observed.append(value)
        if value==expected: loop.quit()
    poll.timeout.connect(lambda: overlay.webview.page().runJavaScript(
        "document.getElementById('totalDamage')?.textContent || ''", received))
    timeout=QTimer(); timeout.setSingleShot(True); timeout.timeout.connect(loop.quit)
    poll.start(); timeout.start(15000); loop.exec(); poll.stop(); timeout.stop()
    assert expected in observed


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
    monkeypatch.setattr(gui_main.QFileDialog, 'getOpenFileNames', lambda *a: ([str(path),str(path)], ''))
    window.switchTo(window.records_page)
    window.overlay_manager.apply_analysis_snapshot(snapshot_message())
    window.records_page.import_trace_btn.click()
    wait_for(lambda: not window._trace_import_pending, app)
    assert len(window.records) == 2
    assert window.app_config.imported_trace_files == [path]
    assert gui_config.load_app_config(window.config_path).imported_trace_files == [path]
    assert not window.overlay_manager._history_mode  # import alone never switches sources
    window.records_page.import_trace_btn.click()
    wait_for(lambda: not window._trace_import_pending, app)
    assert len(window.records) == 2
    window.records_page.load_overlay_btn.click()
    wait_for(lambda: window.overlay_manager._history_mode, app)
    selected = window._selected_record
    assert window.overlay_manager._analysis_snapshot['snapshot']['battle']['total_damage'] == selected.total_damage
    platform=app.platformName()
    loop=QEventLoop(); QTimer.singleShot(200,loop.quit); loop.exec()
    assert window.grab().save(str(EVIDENCE/f'gui-trace-imported-{platform}.png'))
    overlay = window.overlay_manager._windows['controls']
    wait_for_damage(overlay,'860')
    dom=read_dom(overlay)
    assert dom['damage'] == '860' and dom['rows']==2
    loop=QEventLoop(); QTimer.singleShot(250,loop.quit); loop.exec()
    assert overlay.grab().save(str(EVIDENCE/f'overlay-trace-imported-{platform}.png'))
    window.overlay_manager.apply_analysis_snapshot(snapshot_message(2))
    assert window.overlay_manager._history_mode
    window.records_page.return_live_btn.click()
    assert not window.overlay_manager._history_mode
    assert window.overlay_manager._analysis_snapshot['source']['mode'] == 'live'
    wait_for_damage(overlay,'760')
    assert read_dom(overlay)['damage']=='760'
    before = window.overlay_manager._analysis_snapshot
    monkeypatch.setattr(gui_main.QFileDialog, 'getOpenFileNames', lambda *a: ([str(tmp_path/'missing.log')], ''))
    window.records_page.import_trace_btn.click()
    wait_for(lambda: not window._trace_import_pending, app)
    assert len(window.records) == 2 and window.overlay_manager._analysis_snapshot == before
    assert window.records_page.import_trace_status.toolTip()
    monkeypatch.setattr(gui_main.QFileDialog, 'getOpenFileNames', lambda *a: ([], ''))
    window.records_page.import_trace_btn.click()
    assert not window._trace_import_pending
    generation = window._trace_import_generation
    window._trace_import_generation += 1
    window._complete_trace_import((generation, [(path, (0,0),[])], []))
    assert len(window.records) == 2
    # Refresh reuses unchanged cached imports.
    window._load_records()
    assert not window._trace_import_pending
