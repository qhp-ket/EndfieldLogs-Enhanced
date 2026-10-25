"""Battle-specific binding, independent display, portable paths and battle-only extent."""
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
import json
import pytest
from PySide6.QtCore import QTimer
from app_test_support.ui.window import main_window
from app_test_support.scenarios.compact import sample
from app_test_support.scenarios.trace import wait_for
from endfield_pcap.gui.battle.detail import BattleDetailDialog
from endfield_pcap.gui.config import load_app_config
from endfield_pcap.history.index import record_key
from endfield_pcap.inputlog.bindings import read_binding,write_binding,relocate_bindings
from endfield_pcap.inputlog.history import load_evidence,battle_start_wall_ms


def input_file(path,origin):
    rows=[dict(type='session',schema_version=1,wall_ns=round((origin-5000)*1e6))]
    for i,(ms,phase) in enumerate([(-4000,'down'),(-3900,'up'),(-50,'down'),(100,'up'),
                                  (300,'down'),(350,'up'),(950,'down'),(1500,'up'),(4000,'down'),(4100,'up')],1):
        rows.append(dict(type='input',seq=i,device='fixture',code='K:49',phase=phase,value=int(phase=='down'),
                         wall_ns=round((origin+ms)*1e6),mono_ns=round((5000+ms)*1e6)))
    rows.append(dict(type='end',wall_ns=round((origin+10000)*1e6)))
    path.write_text('\n'.join(json.dumps(row) for row in rows),encoding='utf8')


def test_system_time_projection_selects_only_battle_overlap_regardless_of_log_duration(tmp_path):
    trace=tmp_path/'trace_20261025.log';trace.write_text('',encoding='utf8')
    path=tmp_path/'long.input.jsonl'
    start=datetime.fromisoformat('2026-10-25T12:00:00').timestamp()*1000
    input_file(path,start)
    result=load_evidence([path],trace,dict(battle_start_at='2026-10-25T12:00:00',duration_ms=1000),
                         {'show_other':True},verify=False)
    assert [r['start_ms'] for r in result['actions']]==pytest.approx([-50,300,950],abs=.001)
    assert [r['end_ms'] for r in result['actions']]==pytest.approx([100,350,1500],abs=.001)
    assert all(0<=r['time_ms']<=1000 for r in result['raw'])
    assert result['start_wall_ms']==start
    assert result['input_counts']=={'other':4}
    assert result['recording_counts']=={'other':10}


def test_binding_is_relative_to_trace_and_survives_trace_sidecar_rename(tmp_path):
    old=tmp_path/'trace.log';new=tmp_path/'trace -- renamed.log'
    record=SimpleNamespace(file_path=old,record_index=2,started_at_ms=123)
    value=write_binding(old,old.with_suffix('.input.jsonl'),visible=True,offset_ms=2.,manual_slots={1:'char'})
    assert value['path']=='trace.input.jsonl'
    moved=relocate_bindings({record_key(record):value},old,new)
    record.file_path=new
    restored=read_binding(moved[record_key(record)],new)
    assert restored['path']==new.with_suffix('.input.jsonl')
    assert restored['visible'] and restored['manual_slots']=={1:'char'}
    relocated=read_binding(value,tmp_path/'moved'/'trace.log')
    assert relocated['path']==tmp_path/'moved'/'trace.input.jsonl'


@pytest.mark.parametrize('input_offset,expected_count',[(-5000,0),(100,2)])
def test_bound_file_without_skill_inputs_reports_recording_counts_instead_of_binding_failure(main_window,app,tmp_path,input_offset,expected_count):
    trace=tmp_path/'trace_20261025.log';trace.write_text('',encoding='utf8')
    path=trace.with_suffix('.input.jsonl')
    origin=datetime.fromisoformat('2026-10-25T12:00:00').timestamp()*1e9
    rows=[dict(type='session',schema_version=1,wall_ns=int(origin-10_000_000_000))]
    rows.extend(dict(type='input',seq=i+1,kind='button',device='mouse',code='M:1',phase=phase,
                     value=int(phase=='down'),wall_ns=int(origin+(input_offset+i*50)*1e6))
                for i,phase in enumerate(('down','up')))
    path.write_text('\n'.join(json.dumps(row) for row in rows),encoding='utf8')
    snapshot=sample();snapshot['battle'].update(battle_start_at='2026-10-25T12:00:00',duration_ms=1000)
    record=SimpleNamespace(file_path=trace,record_index=1,started_at_ms=1)
    dialog=BattleDetailDialog(snapshot,'仅鼠标输入证据',main_window)
    try:
        bar=dialog.input_history;bar.set_record(record)
        wait_for(lambda:bar.status.text().startswith('已绑定'),app)
        bar.visible.setChecked(True)
        assert bar.evidence['recording_counts']=={'button':2}
        assert sum(bar.evidence['input_counts'].values())==expected_count
        assert f'本场 {expected_count} 条输入记录 / 0 条输入意图' in bar.status.text()
        assert not dialog.timeline.input_evidence['actions']
        assert ('战斗时间范围内未录到输入' in bar.status.text())==(not expected_count)
    finally:
        dialog.close();dialog.deleteLater();app.processEvents()


def test_millisecond_timer_observation_is_used_instead_of_second_precision_date_or_server_clock():
    battle=dict(battle_start_at='2026-10-25T16:10:35+08:00',timeline_zero_source='official_timer_start',
                timer_evidence={'start':{'observedMs':58235968,'challengeStartTs':'1792915824554'}})
    expected=datetime.fromisoformat('2026-10-25T16:10:35.968+08:00').timestamp()*1000
    assert battle_start_wall_ms(battle)==expected
    battle['battle_start_at']='2026-10-26T00:00:00+08:00'
    battle['timer_evidence']['start']['observedMs']=86400009
    assert battle_start_wall_ms(battle)==datetime.fromisoformat('2026-10-26T00:00:00.009+08:00').timestamp()*1000


def test_bind_and_display_are_separate_and_saved_for_each_battle(main_window,app,tmp_path,monkeypatch):
    from endfield_pcap.gui.battle import input_history
    snapshot=sample();snapshot['battle'].update(battle_start_at='2026-10-25T12:00:00',duration_ms=1000)
    trace=tmp_path/'trace_20261025.log';trace.write_text('',encoding='utf8')
    path=tmp_path/'input.input.jsonl';input_file(path,datetime.fromisoformat('2026-10-25T12:00:00').timestamp()*1000)
    first=SimpleNamespace(file_path=trace,record_index=1,started_at_ms=1)
    second=SimpleNamespace(file_path=trace,record_index=2,started_at_ms=2)
    monkeypatch.setattr(input_history.QFileDialog,'getOpenFileName',lambda *a:(str(path),''))
    dialog=BattleDetailDialog(snapshot,'绑定测试',main_window)
    try:
        bar=dialog.input_history;bar.set_record(first);bar.choose()
        wait_for(lambda:len(bar.evidence['actions'])==3,app)
        assert not bar.visible.isChecked() and not dialog.timeline.input_evidence['actions']
        assert read_binding(load_app_config(main_window.config_path).input_log_bindings[record_key(first)],trace)['path']==path
        bar.visible.setChecked(True)
        assert len(dialog.timeline.input_evidence['actions'])==3
        assert dialog.timeline._time_extent[:2]==(0.,1000.)
        bar.set_record(second)
        assert not bar.paths and not bar.visible.isChecked()
        bar.set_record(first)
        wait_for(lambda:len(bar.evidence['actions'])==3,app)
        assert bar.paths==[path] and bar.visible.isChecked()
        bar.unbind();assert not bar.paths and not dialog.timeline.input_evidence['actions']
        assert bar.visible.isChecked(), 'Unbinding must not change the independent display preference'
        bar.set_record(first);assert not bar.paths
    finally:
        dialog.close();dialog.deleteLater();app.processEvents()
