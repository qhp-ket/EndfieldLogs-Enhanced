"""Fallback transitions remain honest, bounded and subordinate to delivered events."""
from endfield_pcap.inputlog.backends.windows_state import WindowsStateFallback
import endfield_pcap.inputlog.backends.windows_state as module


def setup(monkeypatch):
    clock=[1_000_000_000]
    monkeypatch.setattr(module.time,'perf_counter_ns',lambda:clock[0])
    monkeypatch.setattr(module.time,'time_ns',lambda:clock[0]+10_000_000_000)
    held=set();active=[True];events=[]
    backend=WindowsStateFallback(lambda record_type,**fields:events.append(dict(type=record_type,**fields)),
                                 lambda:active[0],lambda vk:0x8000 if vk in held else 0)
    def pump(delta,keys):
        clock[0]+=int(delta*1e6);held.clear();held.update(keys);backend.pump()
    return backend,pump,active,events,clock


def test_suppressed_windows_events_still_record_down_up_with_source_and_precision(monkeypatch):
    backend,pump,_,events,_=setup(monkeypatch)
    pump(0,[]);pump(8,[49]);pump(40,[]);pump(90,[])
    rows=[r for r in events if r['type']=='input']
    assert [(r['code'],r['phase']) for r in rows]==[('K:49','down'),('K:49','up')]
    assert all(r['backend']=='windows_state' and r['timing_uncertainty_ms']==8 for r in rows)
    assert rows[1]['mono_ns']-rows[0]['mono_ns']==40_000_000
    assert len([r for r in events if r.get('reason')=='input_state_sampling_fallback'])==1


def test_hook_and_raw_transitions_win_no_duplicate_sampled_keys(monkeypatch):
    backend,pump,_,events,clock=setup(monkeypatch)
    pump(0,[]);pump(8,[69])
    backend.note_event(dict(code='K:69',phase='down',mono_ns=clock[0]))
    pump(40,[])
    backend.note_event(dict(code='K:69',phase='up',mono_ns=clock[0]))
    pump(90,[])
    assert not events


def test_foreground_baseline_and_focus_loss_never_invent_a_press(monkeypatch):
    backend,pump,active,events,_=setup(monkeypatch)
    pump(0,[49]);pump(8,[]);pump(90,[])
    assert [r['phase'] for r in events if r['type']=='input']==['up']
    events.clear();pump(8,[69]);active[0]=False;pump(100,[])
    active[0]=True;pump(10,[50]);pump(100,[50])
    assert not events


def test_generic_modifier_is_not_duplicated_as_left_and_right_keys(monkeypatch):
    _,pump,_,events,_=setup(monkeypatch)
    pump(0,[]);pump(8,[18,164]);pump(90,[18,164]);pump(8,[]);pump(90,[])
    assert [r['code'] for r in events if r['type']=='input']==['K:ALT','K:ALT']


def test_high_rate_mouse_messages_do_not_increase_keyboard_sampling_rate(monkeypatch):
    backend,pump,_,_,_=setup(monkeypatch)
    reads=[]
    backend.read_state=lambda key:reads.append(key) or 0
    pump(0,[])
    for _ in range(7):pump(1,[])
    assert len(reads)==255
    pump(1,[])
    assert len(reads)==510
