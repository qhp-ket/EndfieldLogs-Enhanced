"""Recorder privilege dispatch and real authenticated pipe/file lifecycle, without UAC."""
import io
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid
from types import SimpleNamespace
import pytest
from endfield_pcap.inputlog import elevation,worker


def ordinary_test_launch(executable,arguments):
    args=list(arguments)
    at=args.index('-c')+1
    # The transport runs in actual child processes, but no desktop consent is
    # requested. This fixture does not claim to test Windows elevated input.
    args[at]=args[at].replace(elevation.ENTRY,
        'from endfield_pcap.inputlog import elevation; '
        'elevation.is_admin=lambda:True; elevation.elevated_main()')
    process=subprocess.Popen([executable,*args],stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    return SimpleNamespace(poll=process.poll,close=lambda:None,terminate=process.terminate)


@pytest.mark.parametrize('already_admin',[False,True])
def test_worker_dispatches_only_requested_recorder_to_admin_broker(monkeypatch,already_admin):
    calls=[]
    config=dict(game_exe='game.exe',log_dir='logs',trace=None,elevated=True)
    monkeypatch.setattr(sys,'argv',['worker',json.dumps(config)])
    monkeypatch.setattr(elevation,'is_admin',lambda:already_admin)
    monkeypatch.setattr(elevation,'relay',lambda cfg:calls.append(('relay',cfg)))
    monkeypatch.setattr(worker,'run',lambda cfg:calls.append(('record',cfg)))
    worker.main()
    assert calls==[('record' if already_admin else 'relay',
                    dict(game_exe='game.exe',log_dir='logs',trace=None))]


def test_cancelled_consent_is_visible_and_never_starts_ordinary_recorder(monkeypatch,capsys):
    monkeypatch.setattr(sys,'argv',['worker',json.dumps(dict(elevated=True))])
    monkeypatch.setattr(elevation,'is_admin',lambda:False)
    def cancelled(config): raise OSError('已取消输入记录的管理员授权')
    monkeypatch.setattr(elevation,'relay',cancelled)
    monkeypatch.setattr(worker,'run',lambda cfg:pytest.fail('Must not pretend capture started after cancellation'))
    with pytest.raises(SystemExit) as error:worker.main()
    assert error.value.code==1
    status=json.loads(capsys.readouterr().out)
    assert status['status']=='error' and '取消' in status['error']


def test_shell_launch_uses_runas_and_quoted_argument_list_without_a_shell(monkeypatch):
    seen={}
    class Call:
        def __call__(self,pointer):
            info=pointer._obj
            seen.update(verb=info.verb,file=info.file,args=info.parameters,show=info.show)
            info.process=123
            return True
    monkeypatch.setattr(elevation.ctypes,'WinDLL',lambda *args,**kwargs:SimpleNamespace(ShellExecuteExW=Call()))
    monkeypatch.setattr(elevation,'AdminProcess',lambda handle:dict(handle=handle))
    args=['-c','print("text with spaces")',r'D:\中文 路径\file.json']
    result=elevation.launch_admin(r'C:\Python With Spaces\pythonw.exe',args)
    assert result=={'handle':123}
    assert seen==dict(verb='runas',file=r'C:\Python With Spaces\pythonw.exe',
                     args=subprocess.list2cmdline(args),show=0)


@pytest.mark.parametrize('rotate',[False,True])
def test_real_pipe_recorder_status_stop_and_trace_rotation_write_readable_jsonl(tmp_path,monkeypatch,rotate):
    folder=tmp_path/'输入 日志'
    trace=tmp_path/'关联 trace.log';trace.write_text('synthetic trace\n',encoding='utf8')
    commands=[dict(command='trace',path=str(trace))] if rotate else []
    commands.append(dict(command='stop'))
    output=io.StringIO()
    monkeypatch.setattr(sys,'stdin',io.StringIO(''.join(json.dumps(c)+'\n' for c in commands)))
    monkeypatch.setattr(sys,'stdout',output)
    monkeypatch.setattr(elevation,'launch_admin',ordinary_test_launch)
    elevation.relay(dict(game_exe=str(tmp_path/'not-a-running-game.exe'),log_dir=str(folder),trace=None))
    statuses=[json.loads(line) for line in output.getvalue().splitlines()]
    assert statuses[0]['status']=='starting'
    assert any(s['status']=='waiting_game' for s in statuses)
    paths=list(folder.rglob('*.input.jsonl'))
    if rotate:paths.append(trace.with_suffix('.input.jsonl'))
    assert len(paths)==(2 if rotate else 1)
    for path in paths:
        rows=[json.loads(line) for line in path.read_text(encoding='utf8').splitlines()]
        assert rows[0]['type']=='session'
        assert any(r['type']=='end' for r in rows)
        assert any(r.get('reason')=='input_process_privilege' for r in rows)
        assert not any(r['type']=='input' for r in rows),'Background inputs must remain excluded'
        assert not any(r.get('fatal') for r in rows)
    if rotate:
        assert rows[-1]['type']=='trace_digest'


def test_cancelled_broker_closes_listener_and_keeps_log_folder_readable(tmp_path,monkeypatch):
    def cancelled(*args):raise OSError('cancelled')
    monkeypatch.setattr(elevation,'launch_admin',cancelled)
    with pytest.raises(OSError,match='cancelled'):
        elevation.relay(dict(game_exe='game.exe',log_dir=str(tmp_path),trace=None))
    from datetime import datetime
    assert (tmp_path/datetime.now().strftime('%Y%m%d')).is_dir()


def test_disconnected_control_pipe_ends_recorder_and_closes_jsonl(tmp_path):
    from endfield_pcap.inputlog.controller import worker_bootstrap
    address=rf'\\.\pipe\EndfieldLogs-Input-Test-{uuid.uuid4().hex}'
    key=b'synthetic test authentication'
    listener=elevation.Listener(address,family='AF_PIPE',authkey=key)
    child=ordinary_test_launch(sys.executable,['-u','-B','-c',worker_bootstrap(elevation.ENTRY),address,key.hex()])
    connection=None
    try:
        connection=listener.accept()
        elevation.send(connection,dict(game_exe=str(tmp_path/'not-a-game.exe'),log_dir=str(tmp_path),trace=None))
        text=''
        deadline=time.monotonic()+10
        while 'waiting_game' not in text and time.monotonic()<deadline:
            assert connection.poll(5),'Recorder failed to publish startup status'
            text+=elevation.receive(connection)['text']
        assert 'waiting_game' in text
        connection.close();connection=None
        deadline=time.monotonic()+5
        while child.poll() is None and time.monotonic()<deadline:time.sleep(.02)
        assert child.poll() is not None,'Recorder must not outlive its controlling pipe'
        path=next(tmp_path.rglob('*.input.jsonl'))
        rows=[json.loads(line) for line in path.read_text(encoding='utf8').splitlines()]
        assert any(row['type']=='end' for row in rows)
        assert not any(row['type']=='input' for row in rows)
    finally:
        if connection:connection.close()
        listener.close()
        if child.poll() is None:child.terminate()
