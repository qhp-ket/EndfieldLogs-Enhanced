"""Lazy sidecar discovery/indexing. Results are presentation evidence only."""
from __future__ import annotations
from bisect import bisect_right
from collections import Counter,OrderedDict
from datetime import datetime,timedelta
import hashlib
import json
from pathlib import Path
import re
import threading
from endfield_pcap.inputlog.storage import companion,SCHEMA_VERSION
from endfield_pcap.inputlog.interpret import Interpreter,normalize_settings,project,tooltip

_cache=OrderedDict()
_lock=threading.Lock()


def _source_paths(trace):
    trace = Path(trace).resolve()
    if trace.suffix.lower() == '.jsonl' and trace.is_file():
        from parser_core.trace_volumes import resolve_volumes
        chain = resolve_volumes(trace)
        if not chain.complete:
            raise ValueError('；'.join(chain.issues))
        return [item.path for item in chain.volumes]
    if trace.suffix.lower() == '.ndjson' and trace.is_file():
        from endfield_pcap.history.session_volumes import resolve_sessions, associated_trace
        chain = resolve_sessions(trace)
        if not chain.complete:
            raise ValueError('；'.join(chain.issues))
        linked = associated_trace(chain)
        if linked is not None and not linked.complete:
            raise ValueError('；'.join(linked.issues))
        trace_volumes = {item.header['trace_volume'] for item in chain.volumes if item.header}
        return [item.path for item in chain.volumes] + ([item.path for item in linked.volumes
            if item.header.volume in trace_volumes] if linked else [])
    return [trace]


def _companions(trace):
    trace=Path(trace)
    base=companion(trace)
    parts=sorted(trace.parent.glob(base.name.removesuffix('.input.jsonl')+'.part-*.input.jsonl'))
    return ([base] if base.is_file() else [])+parts


def discover(trace):
    try:
        sources = _source_paths(trace)
    except (OSError, ValueError):
        sources = [Path(trace)]  # A worker reports incomplete history without breaking selection.
    return list(dict.fromkeys(path for source in sources for path in _companions(source)))


def _input_sources(trace):
    return {path.resolve(): source for source in _source_paths(trace) for path in _companions(source)}


class InputArchive:
    def __init__(self,path,settings):
        self.path=Path(path)
        self.header={}
        self.warnings=[]
        self.index=[]
        self.devices={}
        self.input_counts=Counter()
        self.digest=None
        interpreter=Interpreter(settings)
        ended=False
        last_second=None
        previous_seq=None
        self.wall_ordered=True
        previous_stamp=0
        with self.path.open('rb') as stream:
            while True:
                offset=stream.tell();raw=stream.readline()
                if not raw: break
                try:
                    event=json.loads(raw)
                    if not isinstance(event,dict): raise ValueError('JSON record is not an object')
                except ValueError:
                    self.warnings.append(f'偏移 {offset}：记录不完整 / 损坏')
                    interpreter.interrupt(interpreter.last or dict(wall_ns=0),'malformed_record')
                    continue
                if not self.header:
                    if event.get('type')!='session' or event.get('schema_version')!=SCHEMA_VERSION:
                        raise ValueError('不支持的输入日志版本')
                    self.header=event
                seq=event.get('seq')
                if seq is not None:
                    if previous_seq is not None and seq<=previous_seq:
                        raise ValueError('输入日志序号未递增')
                    if previous_seq is not None and seq>previous_seq+1:
                        if len(self.warnings)<100:
                            self.warnings.append(f'序号 {previous_seq+1}–{seq-1} 缺失')
                        interpreter.interrupt(event,'sequence_gap')
                    previous_seq=seq+(max(1,int(event.get('count',1)))-1 if event.get('type')=='gap' else 0)
                stamp=event.get('wall_ns',event.get('start_wall_ns',0))
                if stamp and stamp<previous_stamp:
                    self.wall_ordered=False
                if stamp: previous_stamp=stamp
                second=stamp//1_000_000_000
                if stamp and second!=last_second:
                    self.index.append((stamp,offset));last_second=second
                if event.get('type')=='gap': self.warnings.append(f'记录缺失 {event.get("missing_events",event.get("count",0))} 条')
                if event.get('type')=='diagnostic' and event.get('reason')=='input_state_sampling_fallback':
                    self.warnings.append(f'输入使用状态采样（{event.get("sample_interval_ms",8)}ms），不含完整原始设备事件')
                if event.get('type')=='device': self.devices[event['device']]=event
                if event.get('type')=='input': self.input_counts[event.get('kind','other')]+=1
                if event.get('type')=='trace_digest': self.digest=event
                if event.get('type')=='end': ended=True
                interpreter.feed(event)
        self.actions=interpreter.close()
        if not ended: self.warnings.append('录制尚未结束或未正常结束，末尾按住区间按中断处理')
        if len(self.warnings)>100:
            self.warnings=self.warnings[:100]+['更多诊断已省略']

    def verify_trace(self,trace):
        if not self.digest:
            return '未附 trace 摘要（录制可能仍在运行）'
        size=self.digest['bytes']
        source=Path(trace)
        if source.stat().st_size<size:
            raise ValueError('trace 长度与输入日志关联摘要不匹配')
        digest=hashlib.sha256()
        with source.open('rb') as stream:
            remaining=size
            while remaining:
                block=stream.read(min(remaining,1024*1024))
                if not block: raise ValueError('trace 在校验期间发生变化')
                digest.update(block);remaining-=len(block)
        if digest.hexdigest()!=self.digest['sha256']:
            raise ValueError('trace 与输入日志关联摘要不匹配；请手动核对来源')
        return '已校验 trace 关联'

    def raw_range(self,start_ns,end_ns,settings,counts=None):
        # Only selected battle values are retained. Repaints reuse this result.
        indexes=sorted(self.index)
        at=max(0,bisect_right([v[0] for v in indexes],start_ns)-1)
        result=[]
        with self.path.open('rb') as stream:
            if indexes and self.wall_ordered: stream.seek(indexes[at][1])
            for raw in stream:
                try: event=json.loads(raw)
                except ValueError: continue
                stamp=event.get('wall_ns',0)
                if stamp>end_ns:
                    if self.wall_ordered: break
                    continue
                if stamp<start_ns or event.get('type')!='input': continue
                kind=event.get('kind')
                if counts is not None: counts[kind or 'other']+=1
                if kind=='motion' and not settings['show_motion']: continue
                if kind in ('axis','hat','sensor','touch','other') and not settings['show_axes']: continue
                if kind not in ('motion','axis','hat','sensor','touch','other') and not settings['show_other']: continue
                result.append(event)
        return result


def clear_cache():
    """Drop disposable parsed input files once no history view is using them."""
    with _lock: _cache.clear()


def archive(path,settings):
    path=Path(path).resolve();stat=path.stat()
    key=(str(path),stat.st_size,stat.st_mtime_ns,json.dumps(normalize_settings(settings),sort_keys=True))
    with _lock:
        value=_cache.get(key)
        if value is not None:
            _cache.move_to_end(key)
            return value
    value=InputArchive(path,settings)
    with _lock:
        _cache[key]=value
        while len(_cache)>2: _cache.popitem(last=False)
    return value


def loadout_history(path,start_ms):
    """Explicit trace LOADOUT slots, including changes. Never participant/ranking order."""
    updates=[]
    path=Path(path)
    if path.suffix.lower()=='.jsonl':
        from parser_core.trace_volumes import resolve_volumes, read_events
        for event in read_events(resolve_volumes(path)):
            if event.type=='loadout_group':
                updates.append((event.captured_at_ms,None,None))
            elif event.type=='loadout_slot':
                slot=event.data.get('slot');character=event.data.get('template')
                if type(slot) is int and 0<=slot<4 and character:
                    updates.append((event.captured_at_ms,slot,character))
        return updates
    if path.suffix.lower()=='.ndjson':
        from endfield_pcap.history.session_volumes import resolve_sessions, read_lines
        for line in read_lines(resolve_sessions(path)):
            try: event=json.loads(line)
            except ValueError: continue
            if event.get('type')=='LOADOUT':
                wall=event.get('timestamp_ms',0)
                updates.append((wall,None,None))
                for row in event.get('rows',[]):
                    if type(row.get('slot')) is int and 0<=row['slot']<4 and row.get('char'):
                        updates.append((wall,row['slot'],row['char']))
        return updates
    reference=datetime.fromtimestamp(start_ms/1000)
    match=re.search(r'(20\d{6})',Path(path).name)
    day=datetime.strptime(match[1],'%Y%m%d').date() if match else reference.date()
    last_time=None
    with Path(path).open(encoding='utf-8-sig') as source:
        for line in source:
            stamp=re.search(r'(\d{2}):(\d{2}):(\d{2})\.(\d{3})',line)
            if not stamp: continue
            h,m,s,ms=map(int,stamp.groups())
            tod=((h*60+m)*60+s)*1000+ms
            if last_time is not None and tod<last_time-12*3600000: day+=timedelta(days=1)
            last_time=tod
            wall=datetime.combine(day,datetime.min.time()).timestamp()*1000+tod
            if re.search(r'\bLOADOUT reason=',line): updates.append((wall,None,None))
            row=re.search(r'\bLOADOUT slot=(\d+) char=([^\s]+)',line)
            if row:
                slot=int(row[1])
                if 0<=slot<4: updates.append((wall,slot,row[2]))
    return updates


def battle_start_wall_ms(battle):
    """Use the observed local timer anchor, never the server's challenge clock.

    Older snapshots have second precision. Their existing timer evidence
    retains the millisecond observation, including cross-midnight dates.
    """
    iso=battle.get('battle_start_at')
    if not iso: raise ValueError('战斗日期不明确，请手动指定日期和起点')
    reference=datetime.fromisoformat(iso)
    start=reference.timestamp()*1000
    if '.' in iso.split('T',1)[-1]:
        return start
    evidence=(battle.get('timer_evidence') or {}).get('start') or {}
    observed=evidence.get('observedMs')
    if battle.get('timeline_zero_source')=='official_timer_start' and type(observed) in (int,float):
        midnight=reference.replace(hour=0,minute=0,second=0,microsecond=0).timestamp()*1000
        candidate=midnight+float(observed)%86400000
        start=min((candidate-86400000,candidate,candidate+86400000),key=lambda v:abs(v-start))
    return start


def load_evidence(paths,trace,battle,settings=None,*,offset_ms=0,manual_slots=None,start_override=None,verify=True):
    settings=normalize_settings(settings)
    start=float(start_override) if start_override is not None else battle_start_wall_ms(battle)
    duration=float(battle.get('duration_ms') or 0)
    updates=loadout_history(trace,start)
    input_sources=_input_sources(trace) if verify else {}
    actions,raws,warnings=[],[],[]
    input_counts,recording_counts=Counter(),Counter()
    for path in paths:
        data=archive(path,settings)
        warnings.extend(data.warnings)
        recording_counts.update(data.input_counts)
        if verify: warnings.append(data.verify_trace(input_sources.get(Path(path).resolve(),trace)))
        projected=project(data.actions,start,duration,offset_ms=offset_ms)
        for action in projected:
            slots={}
            stamp=action['start_wall_ns']/1e6+offset_ms
            for when,slot,key in updates:
                if when>stamp: break
                if slot is None: slots.clear()
                else: slots[slot]=key
            slots.update(manual_slots or {})
            action['character_key']=slots.get(action['slot'])
            action['tooltip']=tooltip(action)
        actions.extend(projected)
        raws.extend(data.raw_range(round((start-offset_ms)*1e6),round((start+duration-offset_ms)*1e6),settings,input_counts))
    raw_projected=[dict(row,time_ms=row['wall_ns']/1e6-start+offset_ms) for row in raws]
    return dict(actions=sorted(actions,key=lambda r:r['start_ms']),raw=raw_projected,
                warnings=list(dict.fromkeys(warnings)),manual_alignment=bool(offset_ms or start_override is not None),
                start_wall_ms=start,settings=settings,paths=[str(p) for p in paths],
                input_counts=dict(input_counts),recording_counts=dict(recording_counts))
