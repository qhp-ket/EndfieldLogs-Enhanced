from datetime import datetime
import hashlib
import json
import struct
import time
from pathlib import Path
import pytest
from endfield_pcap.inputlog.storage import InputWriter,companion
from endfield_pcap.inputlog.history import InputArchive,load_evidence,discover,archive
from endfield_pcap.history.files import rename_log
from endfield_pcap.inputlog.backends.raw_input import RawInput,Header
from ctypes import sizeof


def event(ms,code,phase):
    return dict(type='input',kind='key',device='keyboard',code=code,phase=phase,
                wall_ns=1_800_000_000_000_000_000+int(ms*1e6),mono_ns=int(ms*1e6))


def test_writer_clock_sequence_trace_prefix_and_hash(tmp_path):
    trace=tmp_path/'trace_20261025-120000.log';trace.write_bytes(b'synthetic trace\n')
    writer=InputWriter(companion(trace),trace=trace)
    for i in range(100): writer.put('input',**{k:v for k,v in event(i,'K:49','down' if i%2==0 else 'up').items() if k!='type'})
    writer.close()
    rows=[json.loads(s) for s in writer.path.read_text(encoding='utf8').splitlines()]
    assert rows[0]['schema_version']==1 and rows[0]['mono_ns']>0
    assert [r['seq'] for r in rows if 'seq' in r]==list(range(1,101))
    assert rows[-1]['sha256']==hashlib.sha256(trace.read_bytes()).hexdigest()
    data=InputArchive(writer.path,{})
    assert len(data.actions)==50
    assert data.verify_trace(trace)=='已校验 trace 关联'
    trace.write_bytes(b'changed')
    with pytest.raises(ValueError): data.verify_trace(trace)


def test_bounded_queue_reports_every_lost_event(tmp_path):
    writer=InputWriter(tmp_path/'pressure.input.jsonl',capacity=4)
    original=writer._write
    def slow(item): time.sleep(.0001);original(item)
    writer._write=slow
    for i in range(10000): writer.put('input',device='mouse',code='M:MOVE',kind='motion',value=[i,0])
    assert writer.queue.qsize()<=4
    expected=writer.lost
    writer.close()
    rows=[json.loads(s) for s in writer.path.read_text(encoding='utf8').splitlines()]
    assert expected>0 and sum(r.get('count',0) for r in rows if r['type']=='gap')==expected
    assert len([r for r in rows if r['type']=='input'])+expected==10000


def test_sidecar_parts_rename_with_trace_and_conflicts_are_transactional(tmp_path):
    trace=tmp_path/'trace_20261025-120000.log';trace.write_bytes(b'unchanged')
    side=companion(trace);side.write_bytes(b'evidence')
    part=tmp_path/(trace.stem+'.part-123.input.jsonl');part.write_bytes(b'part')
    new=rename_log(trace,'测试')
    assert new.read_bytes()==b'unchanged'
    assert [p.read_bytes() for p in discover(new)]==[b'evidence',b'part']
    conflict=companion(new.with_name(new.stem.partition(' -- ')[0]+' -- conflict.log'))
    conflict.write_bytes(b'orphan')
    with pytest.raises(ValueError): rename_log(new,'conflict')
    assert new.exists() and companion(new).exists() and conflict.read_bytes()==b'orphan'


def test_loadout_slots_are_evidence_not_damage_order_and_cross_midnight(tmp_path):
    trace=tmp_path/'trace_20261024-235959.log'
    trace.write_text('[23:59:59.900] LOADOUT reason=SC_SELF_SCENE_INFO\n[23:59:59.900] LOADOUT slot=0 char=chr_old\n'
                     '[00:00:00.200] LOADOUT reason=changed\n[00:00:00.200] LOADOUT slot=0 char=chr_new\n',encoding='utf8')
    origin=datetime(2026,10,25).timestamp()*1e9
    rows=[]
    for ms in (-50,250):
        for delta,phase in ((0,'down'),(20,'up')):
            r=event(ms+delta,'K:49',phase);r['wall_ns']=int(origin+(ms+delta)*1e6);rows.append(r)
    side=companion(trace)
    side.write_text('\n'.join(json.dumps(r) for r in [dict(type='session',schema_version=1),*rows,dict(type='end',wall_ns=int(origin+1e9))]),encoding='utf8')
    data=load_evidence([side],trace,dict(battle_start_at='2026-10-25T00:00:00',duration_ms=1000),verify=False)
    assert [a['character_key'] for a in data['actions']]==['chr_new']  # Previous released press is outside battle.
    data=load_evidence([side],trace,dict(battle_start_at='2026-10-24T23:59:59.900',duration_ms=1100),verify=False)
    assert [a['character_key'] for a in data['actions']]==['chr_old','chr_new']
    assert archive(side,{}) is archive(side,{})


def test_raw_keyboard_repeat_mouse_wheel_preserves_device_and_values():
    events=[]
    receiver=RawInput.__new__(RawInput)
    receiver.pressed=set();receiver._device=lambda handle:'keyboard:one'
    receiver.emit=lambda record_type,**fields: events.append(dict(type=record_type,**fields))
    def keyboard(flags):
        h=Header(kind=1,size=sizeof(Header)+16,device=1,param=0)
        receiver._decode(bytes(h)+struct.pack('<HHHHII',2,flags,0,49,0x100,0))
    keyboard(0);keyboard(0);keyboard(1)
    assert [r['phase'] for r in events]==['down','repeat','up']
    h=Header(kind=0,size=sizeof(Header)+24,device=2,param=0)
    raw=bytearray(24);struct.pack_into('<HH',raw,4,0x400,65536-120);struct.pack_into('<iiI',raw,12,-5,8,0)
    receiver._decode(bytes(h)+raw)
    assert events[-2]['value']==[-5,8] and events[-1]['value']==-120
