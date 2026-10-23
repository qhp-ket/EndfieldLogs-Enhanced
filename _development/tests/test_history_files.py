"""Renames preserve source bytes, uploader proofs and all per-file battles."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from endfield_pcap import gui_config, history_index
from endfield_pcap.history_files import rename_log, renamed_path
from endfield_pcap.history_index import record_key, HistoryIndex
from endfield_pcap.history_analysis import load_record_snapshot
from uploader_core.log_integrity import build_raw_log_proof, load_raw_log_integrity
from test_overlay_controls import main_window
from test_trace_import import two_battles, wait_for
from test_history_overlay import raw_scene, raw_hit


def test_rename_preserves_bytes_mtime_proofs_and_uploader_validation(tmp_path):
    source = tmp_path / 'trace_20261022-100000.log'
    source.write_text(two_battles(), encoding='utf8')
    data, stamp = source.read_bytes(), source.stat().st_mtime_ns
    proof = build_raw_log_proof(data, file_name=source.name)
    for suffix in ('.log.integrity.json', '.integrity.json', '.log.status.json'):
        source.with_suffix(suffix).write_text(json.dumps(proof), encoding='utf8')
    assert load_raw_log_integrity(str(source))['verified']
    index = HistoryIndex(tmp_path / 'index')
    before = index.records(source, trace=True)
    first = load_record_snapshot(before[1])
    new = rename_log(source, '打桩一')
    index.relocate(source, new)
    assert not source.exists()
    assert new.read_bytes() == data and new.stat().st_mtime_ns == stamp
    assert load_raw_log_integrity(str(new))['verified']
    assert json.loads(Path(str(new)+'.integrity.json').read_text(encoding='utf8')) == proof
    after = index.records(new, trace=True)
    second = load_record_snapshot(after[1])
    assert first['battle']['total_damage'] == second['battle']['total_damage']
    assert before[1].reference_date == after[1].reference_date
    assert new.name.startswith('trace_20261022-100000 -- ')


def test_collision_and_bad_names_change_nothing(tmp_path):
    path = tmp_path / 'session_123.ndjson'
    path.write_text('unchanged', encoding='utf8')
    target = renamed_path(path, '已有')
    target.write_text('other', encoding='utf8')
    for label in ('../escape', 'a/b', 'a\\b', '', 'a:', 'a.'):
        with pytest.raises(ValueError):
            rename_log(path, label)
    with pytest.raises(ValueError, match='已存在'):
        rename_log(path, '已有')
    assert path.read_text() == 'unchanged' and target.read_text() == 'other'
    orphan = Path(str(renamed_path(path, '旁文件重名'))+'.integrity.json')
    orphan.write_bytes(b'foreign proof')
    with pytest.raises(ValueError, match='已存在'):
        rename_log(path, '旁文件重名')
    assert path.read_text() == 'unchanged' and orphan.read_bytes() == b'foreign proof'


def test_sidecar_failure_rolls_back_log_and_never_overwrites(tmp_path, monkeypatch):
    path = tmp_path / 'trace_20261022.log'
    path.write_bytes(b'log')
    proof = Path(str(path)+'.integrity.json')
    proof.write_bytes(b'proof')
    original = Path.rename
    def fail(self, new):
        if self == proof:
            raise PermissionError('locked proof')
        return original(self, new)
    monkeypatch.setattr(Path, 'rename', fail)
    with pytest.raises(OSError):
        rename_log(path, '新名称')
    assert path.read_bytes() == b'log' and proof.read_bytes() == b'proof'
    assert not renamed_path(path, '新名称').exists()


def test_gui_rename_moves_all_battles_hidden_keys_cache_and_selection(main_window, app, tmp_path, monkeypatch):
    window = main_window
    wait_for(lambda: not window._records_pending, app)
    path = tmp_path / 'trace_20261022-100000.log'
    path.write_text(two_battles(), encoding='utf8')
    window._queue_trace_import([path])
    wait_for(lambda: not window._trace_import_pending, app)
    removed = window._selected_record
    window._remove_selected_history()
    target = window._selected_record
    window._inspect_selected_history()
    wait_for(lambda: window._history_detail_dialog is not None, app)
    assert window._rename_history_file(path, '测试重命名')
    new = renamed_path(path, '测试重命名')
    assert len(window.records) == 1 and window._selected_record is target
    assert removed.file_path == target.file_path == new
    assert record_key(removed) in window.app_config.hidden_history_records
    assert window._history_displayed_key == window._history_detail_key == record_key(target)
    assert new.name in window._history_detail_dialog.windowTitle()
    assert gui_config.load_app_config(window.config_path).imported_trace_files == [new]
    def forbidden(*args, **kwargs):
        pytest.fail('rename must relocate existing index instead of reparsing source')
    monkeypatch.setattr(history_index, 'load_trace_records', forbidden)
    assert len(HistoryIndex(window._history_index.directory).records(new, trace=True)) == 2
    window._trace_records.clear(); window._trace_signatures.clear()
    window._load_records()
    wait_for(lambda: not window._trace_import_pending and not window._records_pending, app)
    assert len(window.records) == 1 and window.records[0].file_path == new


def test_active_capture_and_pending_analysis_cannot_be_renamed(main_window, app, tmp_path, monkeypatch):
    window = main_window
    wait_for(lambda: not window._records_pending, app)
    path = tmp_path / 'trace_20261022-100000.log'
    path.write_text(two_battles(), encoding='utf8')
    monkeypatch.setattr(window.service_controller, 'is_running', lambda: True)
    window.service_controller._service = SimpleNamespace(current_log_path=path)
    assert not window._rename_history_file(path, '不可改')
    assert '停止服务' in window.records_page.import_trace_status.text()
    window.service_controller._service = None
    monkeypatch.setattr(window.service_controller, 'is_running', lambda: False)
    window._history_pending_keys = {'busy'}
    assert not window._rename_history_file(path, '不可改')
    assert path.exists()
    window._history_pending_keys.clear()


def test_open_folder_uses_argument_list_with_unicode_and_spaces(main_window, app, tmp_path, monkeypatch):
    window = main_window
    path = tmp_path / '带 空格' / 'trace_20261022-100000.log'
    path.parent.mkdir()
    path.write_text(two_battles(), encoding='utf8')
    window._queue_trace_import([path])
    wait_for(lambda: not window._trace_import_pending, app)
    calls = []
    monkeypatch.setattr('endfield_pcap.gui_history_files.QProcess.startDetached', lambda *args: calls.append(args) or (True, 1))
    window.records_page.open_folder_btn.click()
    assert calls == [('explorer.exe', ['/select,', str(path)])]


def test_renamed_ndjson_remains_discoverable_after_refresh(main_window, app, tmp_path):
    window = main_window
    wait_for(lambda: not window._records_pending, app)
    path = tmp_path / 'session_abc.ndjson'
    stamp = 1792634400000
    events = [raw_scene(stamp), {'type': 'SC_OBJECT_ENTER_VIEW', 'timestamp_ms': stamp+100,
        'objects': [{'battle_inst_id': 99, 'templateid': 'eny_0051_rodin'}]},
        {'type': 'BattleOpModifyBattleState', 'timestamp_ms': stamp+500, 'is_in_battle': True},
        raw_hit(stamp+1000, 123), raw_hit(stamp+2000, 123),
        {'type': 'BattleOpModifyBattleState', 'timestamp_ms': stamp+3000, 'is_in_battle': False}]
    path.write_text('\n'.join(json.dumps(e) for e in events), encoding='utf8')
    window._load_records()
    wait_for(lambda: not window._records_pending, app)
    assert window._rename_history_file(path, '自定义名称')
    window._load_records()
    wait_for(lambda: not window._records_pending, app)
    assert len(window.records) == 1
    assert '自定义名称' in window.records_page.record_list.item(0).text()
    assert load_record_snapshot(window.records[0])['battle']['total_damage'] == 246
