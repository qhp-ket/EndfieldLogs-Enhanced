"""Fixed application history boundaries, lightweight summaries and rename references."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import sys
import tempfile
from dataclasses import asdict, replace
from datetime import datetime, timezone, timedelta


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference',type=Path,required=True)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--dependency-root',type=Path)
    args=parser.parse_args(); reference=args.reference.resolve()
    manifest=json.loads(args.manifest.read_text(encoding='utf8')); dependencies={}
    for relative, info in manifest['files'].items():
        if relative.endswith('.py') and (relative.startswith('_internal/src/endfield_pcap/') or relative.startswith('_internal/packages/parser_core/parser_core/')):
            digest=hashlib.sha256((reference/relative).read_bytes()).hexdigest()
            if digest!=info['sha256']: raise ValueError('Fixed reference changed: '+relative)
            dependencies[relative]=digest
    sys.path[:0]=[str(reference/'_internal/src'),str(reference/'_internal/packages/parser_core'),str(reference/'_internal/packages/uploader_core')]
    if args.dependency_root: sys.path.append(str(args.dependency_root.resolve()))
    from parser_core.battle_splitter import split_trace_battles
    import endfield_pcap.history.records as records
    import endfield_pcap.history.importer as importer
    from endfield_pcap.history.index import record_key
    from endfield_pcap.history.files import renamed_path, relocate_key
    from endfield_pcap.inputlog.bindings import relocate_bindings
    class FixedDateTime(datetime):
        @classmethod
        def fromtimestamp(cls,stamp,tz=None):
            return datetime.fromtimestamp(stamp,timezone(timedelta(hours=8)))
    records.datetime=importer.datetime=FixedDateTime
    importer.bundle_root=lambda:reference/'_internal'
    cases=[]
    def add(kind,name,config,callback):
        try: expected=callback()
        except (ValueError,TypeError,KeyError,OverflowError) as error: expected=dict(error=str(error))
        cases.append(dict(kind=kind,name=name,config_json=json.dumps(config,ensure_ascii=True),expected=expected))
    hit=lambda time,n=1:f'[{time}] HP_V2 #{n} src=chr_0001_test atk=chr_0001_test tgt=eny_0001_test skill=chr_0001_test_normal_skill hit=100'
    samples=[[],[hit('00:00:01.000')],[hit('23:59:59.900'),hit('00:00:00.100',2)],[hit('00:00:01.000'),hit('00:00:31.000',2),hit('00:01:01.001',3)]]
    official=['[00:00:00.000] OFFICIAL_TIMER_START gameId=g challengeStartTs=123',hit('00:00:01.000'),
        '[00:00:02.000] GAME_TIMER_START source=CS_BATTLE_OP startMs=0',hit('00:00:03.000',2),
        '[00:00:04.000] OFFICIAL_TIMER_END gameId=g passTime=4000','[00:00:05.000] BATTLE_RESULT passed=1']
    samples += [official,official[:3]+[official[0]]+official[3:]]
    for end in ['GAME_TIMER_END elapsedMs=4000 sane=1','GAME_TIMER_END elapsedMs=0 sane=1','OFFICIAL_TIMER_END passTime=4000','GAME_INST_LEAVE gameId=g','GAME_TIMER_RESET source=manual']:
        samples.append(['[00:00:00.000] LOADOUT slot=0 actor=chr_0001_test','\n','[00:00:00.500] DUNGEON_CONTEXT id=test',hit('00:00:01.000'),'[00:00:04.000] '+end,'[00:00:05.000] BATTLE_RESULT passed=1'])
    rng=random.Random(20261030)
    for _ in range(60):
        rows=[]
        for index in range(18):
            stamp=f'00:00:{rng.randrange(60):02d}.{rng.randrange(1000):03d}'
            token=rng.choice(['hit','hit','GAME_TIMER_START source=packet startMs=10','GAME_TIMER_END elapsedMs=2500 sane=1',
                'OFFICIAL_TIMER_START gameId=g challengeStartTs=123','OFFICIAL_TIMER_START gameId=h challengeStartTs=456',
                'OFFICIAL_TIMER_END gameId=g passTime=5000','GAME_INST_LEAVE gameId=g','DUNGEON_CONTEXT id=a','LOADOUT slot=0 actor=chr_0001_test','noise'])
            rows.append(hit(stamp,index+1) if token=='hit' else f'[{stamp}] {token}')
        samples.append(rows)
    with tempfile.TemporaryDirectory() as directory:
        root=Path(directory)
        def projection(row,path):
            data=asdict(row); data.pop('snapshot',None); data['file_path']=str(path)
            if 'source_signature' in data:data['source_signature']=list(data['source_signature'])
            data['key']=record_key(replace(row,file_path=path))
            return data
        for rows in samples:
            for separator in ['\n','\r\n','\u2028']:
                text=separator.join(rows)+separator
                add('split','boundaries',dict(text=text),lambda text=text:split_trace_battles(text))
                path=root/'trace_20261028.log'; raw=text.encode('utf8'); path.write_bytes(raw);os.utime(path,ns=(1793188800000000000,1793188800000000000))
                signature=[path.stat().st_mtime_ns,path.stat().st_size]
                add('trace','trace-index',dict(data=raw.hex(),file_name=path.name,signature=signature),lambda path=path:[projection(row,Path(r'C:\history')/path.name) for row in importer.load_trace_records(path)])
        base=[dict(type='SC_SELF_SCENE_INFO',timestamp_ms=1793188800000,char_list=[dict(battle_inst_id=11,templateid='chr_0001_test',display_name='角色一'),dict(battle_inst_id=22,templateid='chr_0002_test',display_name='角色二')])]
        def damage(owner=11,value=-100,stamp=1793188801000,crit=False):
            return dict(type='BattleOpTriggerAction',timestamp_ms=stamp,action=dict(action_type='BattleActionDamage',damage_action=dict(attacker_id=owner,details=[dict(value=value,is_crit=crit)])))
        for count in [1,2,8]:
            for outsider in [False,True]:
                for starts in [False,True]:
                    events=list(base)
                    for index in range(count):
                        if starts: events.append(dict(type='BattleOpModifyBattleState',timestamp_ms=1793188800000+index*1000,is_in_battle=True))
                        events.append(damage(owner=999 if outsider else 11 if index%2==0 else 22,value=-index-0.5,stamp=1793188801000+index*1000,crit=index%2==0))
                    text='\n'.join(json.dumps(item,ensure_ascii=False) for item in events)+'\n{invalid\n'
                    path=root/'session_test.ndjson';path.write_text(text,encoding='utf8');signature=[path.stat().st_mtime_ns,path.stat().st_size]
                    add('events','ndjson-summary',dict(text=text,file_name=path.name,signature=signature),lambda path=path:[projection(row,Path(r'C:\history')/path.name) for row in records._parse_log_file(path)])
        for label in ['新名称','  空格  ','','bad/name','name.','a'*241,'😀'*200]:
            source=Path(r'C:\history\trace_20261028 -- previous.log')
            add('name','rename-name',dict(path=str(source),label=label),lambda:str(renamed_path(source,label)))
        old=Path(r'C:\history\trace_20261028.log');new=renamed_path(old,'新名称');key=json.dumps([os.path.normcase(str(old)),2,1793188800000],ensure_ascii=False)
        for source in ['trace_20261028.input.jsonl','trace_20261028.part-0001.input.jsonl','external.input.jsonl',None]:
            bindings={key:dict(path=source,visible=True,offset_ms=30,manual_slots={'0':'chr_0001_test','5':'bad'},manual=True)}
            add('bindings','rename-bindings',dict(old=str(old),new=str(new),bindings=bindings),lambda bindings=bindings:relocate_bindings(bindings,old,new))
    out=Path(__file__).resolve().parents[3]/'_internal/dotnet/Specs/Fixtures/history-index.json'
    out.write_text(json.dumps(cases,ensure_ascii=True,separators=(',',':')),encoding='utf8')
    out.with_suffix('.reference.json').write_text(json.dumps(dict(source_head=manifest['head'],cases=len(cases),offset_minutes=480,dependencies=dependencies),indent=2),encoding='utf8')
    print('History fixtures:',len(cases))


if __name__=='__main__':main()
