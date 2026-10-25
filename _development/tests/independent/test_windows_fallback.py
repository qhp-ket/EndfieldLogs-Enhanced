"""Fallback selection does not duplicate raw reports or record background keys."""
from collections import deque
import time
from endfield_pcap.inputlog.backends.windows_fallback import WindowsInputFallback


def fixture():
    events=[]
    backend=WindowsInputFallback.__new__(WindowsInputFallback)
    backend.emit=lambda record_type,**fields:events.append(dict(type=record_type,**fields))
    backend.foreground=lambda:True
    backend.pending=deque();backend.raw_times={};backend.announced=set();backend.error=None
    return backend,events


def test_raw_reports_win_and_missing_raw_preserves_original_clock_and_source():
    backend,events=fixture()
    then=time.perf_counter_ns()-int(.08e9)
    backend.pending.extend([dict(kind='key',code='K:49',phase='down',value=1,mono_ns=then,wall_ns=123),
                            dict(kind='key',code='K:69',phase='down',value=1,mono_ns=then,wall_ns=124)])
    backend.raw_times[('key','K:49','down')]=then+1000
    backend.pump()
    inputs=[r for r in events if r['type']=='input']
    assert len(inputs)==1 and inputs[0]['code']=='K:69'
    assert inputs[0]['mono_ns']==then and inputs[0]['wall_ns']==124
    assert inputs[0]['backend']=='windows_hook' and not inputs[0]['device_identity_available']
    assert any(r.get('reason')=='raw_input_delivery_fallback' for r in events)


def test_background_input_is_not_queued_or_written():
    backend,events=fixture()
    backend.foreground=lambda:False
    backend._queue(kind='key',code='K:49',phase='down')
    assert not backend.pending and not events


def test_overflow_is_explicit_and_queue_remains_bounded():
    backend,events=fixture()
    backend.pending.extend([{}]*8192)
    backend._queue(kind='motion',code='M:MOVE',value=[1,2])
    assert len(backend.pending)==1
    assert events[0]['type']=='gap'
    assert events[0]['count']==1 and events[0]['missing_events']==8192


def test_hook_capture_is_known_before_delayed_publication_for_sampler_deduplication():
    backend,events=fixture()
    seen=[];backend.on_event=lambda event:seen.append(dict(event))
    backend._queue(kind='key',code='K:49',phase='down',value=1)
    assert not events  # Raw Input still has priority during the publication delay.
    assert len(seen)==1 and seen[0]['code']=='K:49' and seen[0]['phase']=='down'
