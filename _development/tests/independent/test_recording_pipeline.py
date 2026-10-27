"""Exercise recorder dispatch, real JSONL, failure records and real GUI start/stop."""
import ctypes
from datetime import datetime
import io
import json
import os
from pathlib import Path
import struct
import sys
import threading
import time
from types import SimpleNamespace
import pytest
from app_test_support.ui.window import main_window
from app_test_support.scenarios.trace import wait_for
from endfield_pcap.inputlog.backends.raw_input import RawInput, Header
from endfield_pcap.inputlog.worker import Recorder
from endfield_pcap.inputlog.history import InputArchive
from endfield_pcap.runtime.game_window import process_executable


def read_rows(path):
    return [json.loads(line) for line in path.read_text(encoding='utf8').splitlines()]


def test_process_identity_works_without_psutil(monkeypatch):
    monkeypatch.setitem(sys.modules, 'psutil', None)
    assert Path(process_executable(os.getpid())).resolve() == Path(sys.executable).resolve()
    assert process_executable(0) is None


def test_recorder_raw_dispatch_to_file_interrupt_reopen_and_offline_interpretation(tmp_path):
    recorder = Recorder(dict(game_exe=tmp_path/'none.exe', log_dir=tmp_path))
    active = [True]
    recorder.target = SimpleNamespace(foreground=lambda: active[0])
    recorder.rotate()
    receiver = RawInput.__new__(RawInput)
    receiver.pressed = set()
    receiver._device = lambda _: 'synthetic:keyboard'
    receiver.emit = recorder.emit
    recorder.emit('device', device='synthetic:keyboard', backend='raw_input', name='合成键盘')
    def key(vk, up=False):
        header = Header(kind=1, size=ctypes.sizeof(Header)+16, device=1, param=0)
        receiver._decode(bytes(header)+struct.pack('<HHHHII', vk, int(up), 0, vk, 0x101 if up else 0x100, 0))
    key(49);key(49);time.sleep(.01);key(49,True)
    key(69);time.sleep(.01);key(69,True)
    key(50)
    active[0] = False
    recorder.check_focus()
    key(50,True);key(51);key(51,True)
    first = recorder.writer.path
    recorder.rotate()
    active[0] = True
    recorder.check_focus()
    key(52);time.sleep(.01);key(52,True)
    second = recorder.writer.path
    recorder.writer.put('interrupt', reason='stopped')
    recorder.writer.close()
    rows = read_rows(first)
    assert rows[0]['type'] == 'session' and rows[-1]['type'] == 'end'
    assert [r['seq'] for r in rows if 'seq' in r] == list(range(1, 1+sum('seq' in r for r in rows)))
    assert [r['phase'] for r in rows if r['type']=='input' and r['code']=='K:49'] == ['down','repeat','up']
    assert not any(r.get('code') == 'K:51' for r in rows)
    archive = InputArchive(first,{})
    assert [(a['action'],a['interrupted']) for a in archive.actions] == [('skill',False),('combo',False),('skill',True)]
    assert InputArchive(second,{}).actions[0]['slot'] == 3
    assert read_rows(second)[-1]['reason'] == 'stopped'


def test_backend_start_failure_is_visible_in_inputlog(monkeypatch,tmp_path):
    import endfield_pcap.inputlog.backends.windows as backend
    monkeypatch.setattr(sys,'stdin',io.StringIO(''))
    def broken(_): raise OSError('synthetic Raw Input registration failure')
    monkeypatch.setattr(backend,'RawInput',broken)
    recorder = Recorder(dict(game_exe=tmp_path/'none.exe',log_dir=tmp_path))
    with pytest.raises(RuntimeError,match='registration failure'):recorder.run()
    rows = read_rows(recorder.writer.path)
    assert rows[-1]['type']=='end' and rows[-1]['reason']=='error'
    assert any(r['type']=='error' and r.get('fatal') and 'registration failure' in r['message'] for r in rows)


def test_runtime_windows_failure_still_closes_input_file(monkeypatch,tmp_path):
    import endfield_pcap.inputlog.backends.windows as backend
    failed=threading.Event()
    class Raw:
        received={}
        def __init__(self,emit): pass
        def pump(self):
            if failed.is_set(): raise OSError('synthetic message loop failure')
        def wait(self,ms): failed.wait(ms/1000)
        def close(self): pass
    class Auxiliary:
        announced=set()
        def __init__(self,*args): pass
        def pump(self): pass
        def close(self): pass
    monkeypatch.setattr(backend,'RawInput',Raw)
    monkeypatch.setattr(backend,'WindowsInputFallback',Auxiliary)
    monkeypatch.setattr(backend,'WindowsStateFallback',type('Sampler',(Auxiliary,),{'interval_ms':8}))
    recorder=Recorder(dict(game_exe=tmp_path/'none.exe',log_dir=tmp_path))
    recorder.rotate()
    capture=backend.WindowsInput(recorder.emit,tmp_path/'none.exe')
    failed.set()
    capture.thread.join(2)
    assert not capture.thread.is_alive()
    with pytest.raises(RuntimeError,match='message loop failure'): capture.pump()
    capture.close()  # Cleanup must not rethrow and prevent the JSONL end record.
    recorder.writer.put('error',fatal=True,message=capture.error)
    recorder.writer.close('error')
    assert read_rows(recorder.writer.path)[-1]['reason']=='error'


def test_windows_queue_overflow_is_visible_in_file_and_status(tmp_path):
    import queue
    from endfield_pcap.inputlog.backends.windows import WindowsInput
    recorder=Recorder(dict(game_exe=tmp_path/'none.exe',log_dir=tmp_path))
    recorder.rotate()
    capture=WindowsInput.__new__(WindowsInput)
    capture._queue_lock=threading.Lock();capture.sampler=None
    capture.emit=recorder.emit;capture.events=queue.Queue(maxsize=1)
    capture.error=None;capture.missing=0;capture.missing_start=None;capture.missing_end=None
    capture._enqueue('diagnostic',dict(message='first'))
    capture._enqueue('diagnostic',dict(message='lost'))
    capture.pump()
    capture._enqueue('diagnostic',dict(message='also lost after gap'))
    capture.pump()
    capture.stopped=threading.Event();capture.thread=SimpleNamespace(join=lambda _:None)
    capture.close()
    recorder.writer.close()
    gaps=[r for r in read_rows(recorder.writer.path) if r['type']=='gap']
    assert sum(r['missing_events'] for r in gaps)==2
    assert recorder.backend_lost==2
    assert all(r['start_mono_ns']<=r['end_mono_ns'] for r in gaps)


def test_independent_and_companion_input_files_share_trace_date_directory(tmp_path):
    recorder=Recorder(dict(game_exe=tmp_path/'none.exe',log_dir=tmp_path))
    recorder.rotate()
    assert recorder.writer.path.parent==tmp_path/datetime.now().strftime('%Y%m%d')
    first=recorder.writer.path
    trace=tmp_path/'20261024'/'trace_20261024-235959.log'
    trace.parent.mkdir();trace.write_text('',encoding='utf8')
    recorder.rotate(trace)
    assert recorder.writer.path==trace.with_suffix('.input.jsonl')
    recorder.writer.close()
    assert read_rows(first)[-1]['reason']=='rotation'


def test_state_polling_continues_while_windows_message_dispatch_is_blocked(monkeypatch,tmp_path):
    import endfield_pcap.inputlog.backends.windows as backend
    from endfield_pcap.inputlog.backends.windows_state import WindowsStateFallback
    entered=threading.Event();release=threading.Event();held=set();events=[]
    class Raw:
        received={}
        def __init__(self,emit): pass
        def pump(self):entered.set();release.wait(2)
        def wait(self,ms):release.wait(ms/1000)
        def close(self):pass
    class Hook:
        announced=set()
        def __init__(self,*args):pass
        def pump(self):pass
        def close(self):pass
    monkeypatch.setattr(backend,'RawInput',Raw)
    monkeypatch.setattr(backend,'WindowsInputFallback',Hook)
    monkeypatch.setattr(backend,'GameWindows',lambda _:SimpleNamespace(foreground=lambda:1,user=SimpleNamespace(GetForegroundWindow=lambda:1)))
    monkeypatch.setattr(backend,'WindowsStateFallback',lambda emit,foreground,read:WindowsStateFallback(emit,foreground,lambda vk:0x8000 if vk in held else 0))
    capture=backend.WindowsInput(lambda record_type,**fields:events.append(dict(type=record_type,**fields)),tmp_path/'game.exe')
    try:
        assert entered.wait(1)
        capture.pump();held.add(49);time.sleep(.012);capture.pump()
        held.clear();time.sleep(.012);capture.pump();time.sleep(.09);capture.pump()
        assert [(r['code'],r['phase']) for r in events if r['type']=='input']==[('K:49','down'),('K:49','up')]
        assert capture.health()['state_samples']>=3 and capture.health()['message_pumps']==0
    finally:
        release.set();capture.close()


def test_continuously_busy_writer_flushes_live_file_before_stop(tmp_path):
    from endfield_pcap.inputlog.storage import InputWriter
    writer=InputWriter(tmp_path/'busy.input.jsonl')
    write=writer._write
    def slower(item):
        write(item);time.sleep(.003)
    writer._write=slower
    stop=threading.Event()
    def produce():
        while not stop.is_set():
            writer.put('diagnostic',reason='busy_fixture');time.sleep(.001)
    producer=threading.Thread(target=produce);producer.start()
    try:
        time.sleep(.6)
        assert not writer.queue.empty()
        assert 'busy_fixture' in writer.path.read_text(encoding='utf8')
    finally:
        stop.set();producer.join();writer.close()


def test_real_home_button_starts_worker_stops_and_closes_jsonl(main_window,app,tmp_path,monkeypatch):
    window = main_window
    # OS consent/elevated transport are tested separately; this regression
    # exercises the actual ordinary worker without requesting desktop UAC.
    start=window.independent_controller.input.start
    monkeypatch.setattr(window.independent_controller.input,'start',lambda game,folder,**kwargs:start(game,folder,elevated=False))
    window.app_config.service.game_exe='not-a-running-game.exe'
    window.home_page.input_service_btn.click()
    try:
        wait_for(lambda: window.independent_controller.input.snapshot()['status'] not in ('starting','stopped'),app)
        state=window.independent_controller.input.snapshot()
        assert state['status']=='waiting_game',state
        path=Path(state['path'])
        wait_for(lambda:'停止记录输入' in window.home_page.input_service_btn.text(),app)
        window.home_page.input_service_btn.click()
        wait_for(lambda:not window.independent_controller.input.running,app)
        rows=read_rows(path)
        assert rows[0]['type']=='session' and rows[-1]['type']=='end'
        assert rows[-1]['reason']=='stopped'
        assert not any(r['type']=='error' and r.get('fatal') for r in rows)
        assert not any(r['type']=='input' for r in rows), 'Background input must not enter recording'
        assert not window.service_controller.is_running()
    finally:
        window.independent_controller.input.stop(wait=True)
