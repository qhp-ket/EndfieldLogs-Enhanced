"""Foreground policy is independent of capture, without collecting real user inputs."""
from types import SimpleNamespace
from endfield_pcap.inputlog.worker import Recorder
import endfield_pcap.inputlog.worker as worker


def test_background_events_only_update_baseline_and_focus_loss_interrupts(monkeypatch,tmp_path):
    recorder=Recorder(dict(game_exe=str(tmp_path/'game.exe'),log_dir=str(tmp_path)))
    active=[False]
    recorder.target=SimpleNamespace(foreground=lambda:active[0])
    monkeypatch.setattr(worker,'ctypes',SimpleNamespace(windll=SimpleNamespace(
        user32=SimpleNamespace(GetAsyncKeyState=lambda key:0))))
    rows=[]
    recorder.writer=SimpleNamespace(put=lambda kind,**fields:rows.append(dict(type=kind,**fields)))
    recorder.emit('input',device='one',code='K:49',phase='down',value=1)
    assert not rows and recorder.states['one']['K:49']==1
    active[0]=True;recorder.check_focus()
    assert [r['type'] for r in rows]==['focus','baseline']
    assert rows[-1]['states']['one']['K:49']==1
    recorder.emit('input',device='one',code='K:49',phase='up',value=0)
    assert rows[-1]['type']=='input'
    active[0]=False;recorder.check_focus()
    assert rows[-1]['type']=='interrupt' and rows[-1]['reason']=='focus_lost'
    length=len(rows)
    recorder.emit('input',device='two',code='K:50',phase='down',value=1)
    assert len(rows)==length
    assert recorder.input_counts['other']==3
    assert recorder.filtered_counts['other']==2


def test_backend_change_interrupts_old_device_instead_of_leaving_a_key_held(monkeypatch,tmp_path):
    recorder=Recorder(dict(game_exe=str(tmp_path/'game.exe'),log_dir=str(tmp_path)))
    recorder.target=SimpleNamespace(foreground=lambda:True)
    recorder.focus=True
    rows=[]
    recorder.writer=SimpleNamespace(put=lambda record_type,**fields:rows.append(dict(type=record_type,**fields)))
    recorder.emit('input',device='raw:1',backend='raw_input',kind='key',code='K:49',phase='down',value=1)
    recorder.emit('input',device='windows:keyboard',backend='windows_hook',kind='key',code='K:49',phase='up',value=0)
    assert any(row.get('reason')=='input_backend_changed' and row['device']=='raw:1' for row in rows)
    assert 'raw:1' not in recorder.states
