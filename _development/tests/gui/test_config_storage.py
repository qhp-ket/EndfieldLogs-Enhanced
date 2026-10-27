"""Used portable profiles, legacy paths and interrupted settings writes."""
import json
import os
from pathlib import Path
import pytest
from endfield_pcap.settings import codec as config, storage as config_storage


def test_battle_table_widths_roundtrip_and_bounds(tmp_path):
    path = tmp_path/'settings.json'
    settings = config.load_app_config(path)
    settings.battle_table_widths = {'skills':[120,220,360], 'hits':[10,9000,'bad'], 'other':[99]}
    config.save_app_config(settings,path)
    restored = config.load_app_config(path)
    assert restored.battle_table_widths == {'skills':[120,220,360], 'hits':[40,2000,100]}


def installation(monkeypatch, root):
    monkeypatch.setattr(config, 'bundle_root', lambda: root / '_internal')
    return root / '.dev-gui/settings.json'


@pytest.mark.parametrize('legacy', [False, True])
def test_used_profile_moves_with_internal_resources_history_and_input_bindings(tmp_path, monkeypatch, legacy):
    first, second = tmp_path/'原目录', tmp_path/'移动 后'
    path = installation(monkeypatch, first)
    settings = config.load_app_config(path)
    trace = first/'.dev-gui/logs/battles/test.log'
    trace.parent.mkdir(parents=True)
    trace.write_text('synthetic', encoding='utf8')
    key = json.dumps([os.path.normcase(str(trace)), 1, 123], ensure_ascii=False)
    settings.imported_trace_files = [trace, tmp_path/'external.log']
    settings.hidden_history_records = [key]
    settings.input_log_bindings = {key: {'path':'test.input.jsonl','visible':True}}
    settings.service.dll_dir = tmp_path/'external game'
    settings.gui_font_percent = 137
    config.save_app_config(settings, path)
    if legacy:
        payload = json.loads(path.read_text(encoding='utf8'))
        payload.pop('path_base')
        for field in config_storage.SERVICE_PATHS:
            payload['service'][field] = str(getattr(settings.service, field))
        payload['imported_trace_files'] = [str(p) for p in settings.imported_trace_files]
        payload['hidden_history_records'] = [key]
        payload['input_log_bindings'] = settings.input_log_bindings
        path.write_text(json.dumps(payload), encoding='utf8')
    first.rename(second)
    moved_path = installation(monkeypatch, second)
    moved = config.load_app_config(moved_path)
    assert moved.gui_font_percent == 137
    assert moved.service.dll_dir == tmp_path/'external game'
    for field in config_storage.SERVICE_PATHS:
        assert getattr(moved.service, field) == second/getattr(settings.service, field).relative_to(first)
    assert moved.imported_trace_files == [second/trace.relative_to(first), tmp_path/'external.log']
    moved_key = json.dumps([os.path.normcase(str(second/trace.relative_to(first))), 1, 123], ensure_ascii=False)
    assert moved.hidden_history_records == [moved_key]
    assert moved.input_log_bindings[moved_key] == {'path':'test.input.jsonl','visible':True}
    assert moved.imported_trace_files[0].read_text(encoding='utf8') == 'synthetic'


def test_explicit_external_resources_are_preserved(tmp_path, monkeypatch):
    path = installation(monkeypatch, tmp_path/'app')
    settings = config.load_app_config(path)
    for field in config_storage.SERVICE_PATHS:
        setattr(settings.service, field, tmp_path/'external'/field)
    config.save_app_config(settings, path)
    for field in config_storage.SERVICE_PATHS:
        assert getattr(config.load_app_config(path).service, field) == tmp_path/'external'/field


def test_atomic_replacement_failure_keeps_previous_settings_and_removes_temporary_file(tmp_path, monkeypatch):
    path = tmp_path/'settings.json'
    settings = config.load_app_config(path)
    settings.gui_font_percent = 130
    config.save_app_config(settings, path)
    before = path.read_bytes()
    replace = config_storage.os.replace
    def fail(source, destination):
        if destination == path:
            raise OSError('synthetic replace failure')
        return replace(source, destination)
    monkeypatch.setattr(config_storage.os, 'replace', fail)
    settings.gui_font_percent = 150
    with pytest.raises(OSError, match='replace failure'):
        config.save_app_config(settings, path)
    assert path.read_bytes() == before
    assert not list(tmp_path.glob('*.tmp'))
    assert config.load_app_config(path).gui_font_percent == 130


def test_transient_windows_sharing_failure_retries_atomic_replacement(tmp_path, monkeypatch):
    path = tmp_path/'settings.json'
    config.save_app_config(config.load_app_config(path), path)
    replace = config_storage.os.replace
    attempts = []
    def transient(source, destination):
        if destination == path:
            attempts.append(destination)
            if len(attempts) < 3:
                raise PermissionError('synthetic sharing violation')
        return replace(source, destination)
    monkeypatch.setattr(config_storage.os, 'replace', transient)
    changed = config.load_app_config(path)
    changed.gui_font_percent = 135
    config.save_app_config(changed, path)
    assert len(attempts) == 3
    assert config.load_app_config(path).gui_font_percent == 135


@pytest.mark.parametrize('broken', ['{', '[]', '\ufffd'])
def test_corrupt_configuration_uses_backup_and_preserves_bad_file(tmp_path, broken):
    path = tmp_path/'settings.json'
    settings = config.load_app_config(path)
    settings.gui_font_percent = 140
    config.save_app_config(settings, path)
    settings.gui_font_percent = 150
    config.save_app_config(settings, path)
    path.write_text(broken, encoding='utf8')
    recovered = config.load_app_config(path)
    assert recovered.gui_font_percent == 140
    assert next(tmp_path.glob('*.corrupt-*')).read_text(encoding='utf8') == broken
    config.save_app_config(recovered, path)
    assert config.load_app_config(path).gui_font_percent == 140


def test_corrupt_configuration_still_recovers_backup_when_preservation_is_locked(tmp_path, monkeypatch, caplog):
    path = tmp_path/'settings.json'
    backup = path.with_suffix('.json.bak')
    backup.write_text('{"gui_font_percent": 140}', encoding='utf8')
    path.write_text('{broken', encoding='utf8')
    rename = Path.rename

    def locked(source, destination):
        if source == path:
            raise PermissionError('synthetic sharing violation')
        return rename(source, destination)

    monkeypatch.setattr(Path, 'rename', locked)
    recovered = config.load_app_config(path)
    assert recovered.gui_font_percent == 140
    assert path.read_text(encoding='utf8') == '{broken'
    assert '无法保留损坏配置原文件' in caplog.text
    config.save_app_config(recovered, path)
    assert config.load_app_config(path).gui_font_percent == 140
    assert json.loads(backup.read_text(encoding='utf8')) == {'gui_font_percent': 140}


@pytest.mark.parametrize('service,overlays', [(None, {}), ([], None),
    ({'ws_port':'invalid', 'log_dir':[], 'dll_dir':None},
     [None, {'source_type':'invalid'}, {'source_value':'damage','opacity':'invalid',
       'scale':float('inf'),'font_scale':None,'geometry':{'x':'bad','width':None}}])])
def test_invalid_fields_fall_back_without_discarding_valid_settings(tmp_path, service, overlays):
    path = tmp_path/'settings.json'
    path.write_text(json.dumps(dict(service=service, overlays=overlays,
        gui_font_percent=140, imported_trace_files=['\0', None, 12])), encoding='utf8')
    loaded = config.load_app_config(path)
    assert loaded.gui_font_percent == 140 and loaded.service.ws_port == 29325
    assert not loaded.imported_trace_files
    assert [e.source_value for e in loaded.overlays] == ['damage','combo_skill','uid_mask']
    assert loaded.overlays[0].opacity == loaded.overlays[0].scale == 1.
