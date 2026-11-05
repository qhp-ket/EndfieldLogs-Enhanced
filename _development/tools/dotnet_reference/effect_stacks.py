"""Compare native stack grouping, limits and observed counterfactual selection."""
import argparse
import copy
import gzip
import hashlib
import importlib
import itertools
import json
from pathlib import Path
import struct
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--bundled', action='store_true')
    args = parser.parse_args()
    if args.bundled and args.output is None:
        parser.error('--bundled requires an explicit local output')
    target = args.output or Path(__file__).resolve().parents[3] / '_internal/dotnet/Specs/Fixtures/effect-stacks.json'
    metadata = json.loads(args.manifest.read_text(encoding='utf8'))
    prefix = '_internal/packages/parser_core/parser_core/'
    dependencies = {}
    for relative, expected in metadata['files'].items():
        if relative.startswith(prefix) and relative.endswith('.py'):
            digest = hashlib.sha256((args.reference / relative).read_bytes()).hexdigest()
            if digest != expected['sha256']: raise ValueError('Fixed stack reference changed: ' + relative)
            dependencies[relative] = digest
    package = ModuleType('parser_core')
    package.__path__ = [str(args.reference / prefix)]
    sys.modules['parser_core'] = package
    rules = importlib.import_module('parser_core.effects.stacking_rules')
    identity = importlib.import_module('parser_core.effects.window_identity')
    windows = importlib.import_module('parser_core.effects.windows')
    selection = importlib.import_module('parser_core.allocation.stack_selection')
    templates = importlib.import_module('parser_core.catalog.buff_templates')
    current = {}
    for module in (rules, identity, windows, selection):
        module._load_current_buff_roots = lambda: current.get('roots', {})
    rules._load_local_buff_semantic_entries = lambda: current.get('semantics', {})
    rules._load_weapon_buff_stack_limits = lambda: current.get('weapon_limits', {})
    cases = []

    def encode(value):
        if type(value) is int: return {'int':str(value)}
        if type(value) is float: return {'f64':struct.pack('>d', value).hex()}
        if isinstance(value, (list,tuple)): return [encode(item) for item in value]
        if isinstance(value, dict): return {str(key):encode(item) for key,item in value.items()}
        return value

    def add(kind, config, files=None):
        current.clear()
        current.update(copy.deepcopy(config))
        untouched = encode(current)
        try:
            if kind == 'load':
                with tempfile.TemporaryDirectory() as folder:
                    root = Path(folder) / '_internal'
                    root.mkdir()
                    for name, data in (files or {}).items():
                        path = Path(folder) / name
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_text(data, encoding='utf8')
                    templates._repo_root = lambda: root
                    templates._load_local_buff_semantic_entries.cache_clear()
                    templates._load_weapon_buff_stack_limits.cache_clear()
                    current['semantics'] = templates._load_local_buff_semantic_entries()
                    current['weapon_limits'] = templates._load_weapon_buff_stack_limits()
                    result = [dict(key=q['key'], limit=rules._buff_stack_limit(q['key'],q.get('bb_values')),
                        unique=rules._is_nonstacking_refresh_event(q['key'])) for q in config['queries']]
            elif kind == 'limit': result = rules._buff_stack_limit(config.get('key'),config.get('bb_values'))
            elif kind == 'unique': result = rules._is_nonstacking_refresh_event(config.get('key'))
            elif kind == 'food': result = rules._is_food_potion_buff(config.get('key'))
            elif kind == 'group': result = identity._buff_window_stack_group_key(config['window'])
            elif kind == 'ordered': result = windows._merge_buff_windows(config['windows'])
            elif kind == 'dedupe': result = windows._dedupe_mirrored_buff_windows(config['windows'])
            elif kind == 'apply': result = windows._apply_buff_stack_limits(config['windows'])
            elif kind == 'select':
                hit, rows = copy.deepcopy(config['hit']),copy.deepcopy(config['windows'])
                state = SimpleNamespace(hit=hit, buff_windows=rows, include_debug=config.get('debug',False), ignored_effects=[],
                    window_indices=config.get('indices',list(range(len(rows)))), hit_ts_ms=hit['ts_ms'],hit_line_no=hit.get('line_no'),
                    attacker_key=hit['character_key'],target_enemy_key=hit.get('target_enemy_key'),
                    damage_element=hit.get('damage_element'), damage_school=hit.get('damage_school'))
                selection.select_stack_effects(state)
                result = dict(hit=hit,windows=rows,effects=state.effects_at_hit,zones=sorted(state.unresolved_stack_zones),ignored=state.ignored_effects)
            else: raise ValueError(kind)
        except (TypeError,ValueError,OverflowError,AttributeError) as error:
            result = dict(error=type(error).__name__)
        if kind != 'load' and encode(current) != untouched: raise AssertionError('Reference mutated input config')
        case = dict(name=f'{kind}/{len(cases)}',kind=kind,config_json=json.dumps(config,ensure_ascii=True),expected=encode(result))
        if files is not None: case['files']=files
        cases.append(case)

    key = 'buff_test'
    def config(settings=None, **changes):
        data=dict(key=key, roots={key:dict(stackingSettings=settings)} if settings is not None else {})
        data.update(changes)
        return data
    values = [None,False,True,-1,0,1,2,1.00009,1.0002,'3','bad',float('nan'),float('inf'),10**400]
    for kind, use, count in itertools.product(['Unique','HighPriority','HighPriorityWithMaxStack','Unlimited','Other',None], [None,False,True], values):
        settings=dict(stackingType=kind,useMaxStackCntKey=use,maxStackCnt=count,maxStackCntKey='limit')
        add('limit',config(settings,bb_values={'limit':2}))
    for value in values:
        add('limit',config(dict(stackingType='Unique',useMaxStackCntKey=True,maxStackCnt=4,maxStackCntKey='limit'),bb_values={'limit':value}))
        add('limit',config(semantics={key:dict(stacking=dict(maxStackCnt=value))},weapon_limits={key:7}))
    add('limit',config(weapon_limits={'other':3}))
    add('limit',dict(key='',roots={key:dict(stackingSettings=dict(maxStackCnt=9))}))
    for kind in ['Unique','HighPriority','Unlimited','unique',None]:
        add('unique',config(dict(stackingType=kind)))
    for name in ['buff_common_food_potion','BUFF_COMMON_FOOD_POTION_2','buff_common_food_potion_more','buff_food_potion','buff_common_potion','']:
        add('food',dict(key=name))
    for setting, actor, owner in itertools.product([None,dict(identifierType='StackingKey',stackingKey='shared'),
            dict(identifierType='StackingKey'),dict(identifierType='EventKey',stackingKey='ignored')], [None,'','0','12',12], [None,'a','b']):
        add('group',config(setting,window=dict(event_key=key,target_actor_id=actor,target_character_key=owner,source_character_key='irrelevant')))
    first = dict(uid='1',event_key=key,source_character_key='support',target_character_key='attacker',target_actor_id='11',
        start_ts_ms=1000,end_ts_ms=2000,start_line_no=10,end_line_no=40,line_no=10,zone_effects=[dict(zone='amp',element='all',rate=.2)],
        dynamic_effects=[],stack_limit=1,bb_values={})
    for changes in [dict(start_ts_ms=900,line_no=30),dict(start_ts_ms=1000,line_no=9),dict(start_ts_ms=1000,line_no=11),
            dict(end_ts_ms=999),dict(end_ts_ms=1000),dict(event_key='😀'),dict(event_key='\ue000')]:
        add('ordered',config(windows=[first,dict(first,**changes),first]))
        add('apply',config(windows=[first,dict(first,**changes),first]))
    for field, value in dict(uid='2',uid_aliases=['old'],source_character_key='other',target_character_key='enemy',event_key='other',
            target_actor_id='12',source_actor_id='13',start_ts_ms=1001,end_ts_ms=1999,zone_effects=[dict(zone='amp',rate=.3)],
            dynamic_effects=[dict(zone='amp',base_rate=.3)],effect_segments=[],start_line_no=11,end_line_no=41,
            snapshot_end_ts_ms=1999,snapshot_end_line_no=39,enable_observations=[],snapshot_update=True,event_name='display',stack_limit=2).items():
        add('dedupe',config(windows=[first,dict(first,**{field:value}),copy.deepcopy(first)]))
    for uid in (None,'',0):
        add('dedupe',config(windows=[dict(first,uid=uid),dict(first,uid=uid)]))
    for kind in ['Unlimited','HighPriority','Unique','Other']:
        add('apply',config(dict(stackingType=kind,useMaxStackCntKey=True,maxStackCntKey='limit'),windows=[first,dict(first,bb_values=dict(limit=2))]))
    hit=dict(character_key='attacker',target_enemy_key='enemy',source_actor_id='11',target_actor_id='22',ts_ms=1500,line_no=30,
        damage_element='fire',damage_school='spell',packet_seq_id=10,packet_session_id='s')

    def select(rows, roots=None, **changes):
        for debug in (False,True):
            add('select',dict(roots=roots or {},windows=rows,hit=changes.get('hit',hit),debug=debug,**{k:v for k,v in changes.items() if k!='hit'}))
    for kind, limit, identifier in itertools.product(['Unlimited','Unique','HighPriority','HighPriorityWithMaxStack',None], [None,1,2,3], ['EventKey','StackingKey']):
        settings=dict(stackingType=kind,useMaxStackCntKey=False,maxStackCnt=limit,identifierType=identifier,stackingKey='shared')
        roots={key:dict(stackingSettings=settings),'buff_other':dict(stackingSettings=copy.deepcopy(settings))}
        select([first,dict(first,uid='2')],roots)
        select([first,dict(first,uid='2',event_key='buff_other')],roots)
        select([first,dict(first,uid='2',source_character_key='attacker')],roots)
    for owner, actor, source, uid in itertools.product(['attacker','enemy','foreign',None], ['11','22','33',None], ['attacker','support'], ['1','2','',None]):
        select([first,dict(first,target_character_key=owner,target_actor_id=actor,source_character_key=source,uid=uid)])
    disabled = dict(first,uid='self',source_character_key='attacker',enable_observations=[dict(ts_ms=1100,line_no=20,operationSeq=7,enabled=False)])
    for kind, same_group, applies in itertools.product(['HighPriority','HighPriorityWithMaxStack','Unique','Unlimited'], [True,False], [True,False]):
        roots={key:dict(stackingSettings=dict(stackingType=kind,maxStackCnt=1))}
        external=dict(first,uid='external',zone_effects=[dict(zone='amp',element='fire' if applies else 'physical',rate=.2)])
        select([disabled,external if same_group else dict(external,target_actor_id='33')],roots)
    for changes in [dict(requires_enable_observation=True),dict(snapshot_update=True,start_ts_ms=1500),dict(rdps_conflicting_enable_state=True),
            dict(zone_effects=[dict(zone='atk',element='physical',rate=.2)],requires_enable_observation=True),
            dict(dynamic_effects=[dict(zone='res',element='fire',parameter_snapshots=[],parameter_keys=['r'])])]:
        select([dict(first,**changes),dict(first,uid='2')])
    for selected in [[],[0],[1],[1,0],[0,0],[0,1,0]]:
        select([first,dict(first,uid='2')],indices=selected)
    for changes in [dict(packet_seq_id=None),dict(packet_session_id=None),dict(damage_element='physical',damage_school='physical'),dict(source_actor_id=None)]:
        select([disabled,dict(first,uid='2')],hit=dict(hit,**changes))
    # Real loader precedence: skill hints bind only exact created weapon buffs.
    skill_manifest = dict(entries=[dict(id='sk_wpn_sword_1',binaryProbe=dict(blackboardDoubleHints=[dict(key='max_stack',value='3')],createdBuffIds=['buff_wpn_sword_1_test','buff_other'])),
        dict(id='sk_wpn_sword_2',binaryProbe=dict(blackboardDoubleHints=[dict(key='other',value=9),dict(key='max_stack',value=0),dict(key='max_stack',value=4)],highConfidenceCreatedBuffIds=['buff_wpn_sword_1_test']))])
    paths = dict(semantic='_internal/data/local_semantics/buff/details.json',skill='_internal/data/local_static/skill/manifest.json')
    for semantic in [None,{},dict(entries={key:dict(stacking=dict(maxStackCnt=2))}),dict(entries=[]),dict(entries={key:False})]:
        files={paths['skill']:json.dumps(skill_manifest)}
        if semantic is not None: files[paths['semantic']]=json.dumps(semantic)
        add('load',dict(queries=[dict(key=key),dict(key='buff_wpn_sword_1_test'),dict(key='buff_other'),dict(key='missing')]),files)
    for payload in [[],{},dict(entries=[]),skill_manifest,dict(entries=[None,dict(id='other'),dict(id='sk_wpn_x',binaryProbe=dict(blackboardDoubleHints=[],createdBuffIds=['buff_wpn_x']))])]:
        add('load',dict(queries=[dict(key='buff_wpn_sword_1_test')]),{paths['skill']:json.dumps(payload)})
    if args.bundled:
        cases.clear()
        relative='_internal/data/runtime-data.zip'
        archive=args.reference/relative
        digest=hashlib.sha256(archive.read_bytes()).hexdigest()
        if digest!=metadata['files'][relative]['sha256']: raise ValueError('Reference runtime bundle changed')
        dependencies[relative]=digest
        with zipfile.ZipFile(archive) as bundle:
            data=json.loads(gzip.decompress(bundle.read('data/local_static/buff/typed_roots.json.gz')))
            files={'_internal/'+name:bundle.read(name).decode('utf8') for name in ['data/local_static/skill/manifest.json','data/local_semantics/buff/details.json'] if name in bundle.namelist()}
        queries=[]
        for name,entry in data['entries'].items():
            root=entry.get('root')
            if not isinstance(root,dict) or not isinstance(root.get('stackingSettings'),dict): continue
            settings=root['stackingSettings']
            reduced={name:dict(stackingSettings=settings)}
            for bb in ({},{str(settings.get('maxStackCntKey') or ''):2}):
                add('limit',dict(roots=reduced,key=name,bb_values=bb))
            select([dict(first,event_key=name),dict(first,event_key=name,uid='2')],reduced)
            queries.append(dict(key=name))
        add('load',dict(queries=queries),files)
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(cases,ensure_ascii=True,separators=(',',':')),encoding='utf8')
    target.with_suffix('.reference.json').write_text(json.dumps(dict(source_head=metadata['head'],cases=len(cases),dependencies=dependencies),indent=2),encoding='utf8')
    print('Effect stack fixtures:',len(cases))


if __name__=='__main__': main()
