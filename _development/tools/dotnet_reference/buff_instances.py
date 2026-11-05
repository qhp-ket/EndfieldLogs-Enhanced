"""Compare ordered BUFF lifetimes and packet anchors against a fixed Python source."""
from collections import defaultdict
from pathlib import Path
from types import ModuleType, SimpleNamespace
import argparse
import copy
import hashlib
import importlib
import json
import random
import struct
import sys
import gzip
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--dynamic', action='store_true', help='Generate dynamic parameter scenarios')
    parser.add_argument('--keyword', action='store_true', help='Generate keyword-rate ingestion with explicit upstream approval evidence')
    parser.add_argument('--bundled', action='store_true', help='Compare actual bundled dynamic roots; requires --dynamic and an explicit local output')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.keyword and (args.dynamic or args.bundled):
        parser.error('--keyword is separate from --dynamic and --bundled')
    if args.bundled and (not args.dynamic or args.output is None):
        parser.error('--bundled requires --dynamic and --output')
    if args.output is None:
        args.output=Path(__file__).resolve().parents[3]/'_internal/dotnet/Specs/Fixtures/buff-instances.json'
    metadata = json.loads(args.manifest.read_text(encoding='utf8'))
    prefix = '_internal/packages/parser_core/parser_core/'
    dependencies = {}
    for relative, expected in metadata['files'].items():
        if relative.startswith(prefix) and relative.endswith('.py'):
            digest = hashlib.sha256((args.reference/relative).read_bytes()).hexdigest()
            if digest != expected['sha256']:
                raise ValueError('Fixed BUFF reference changed: '+relative)
            dependencies[relative] = digest
    package = ModuleType('parser_core')
    package.__path__ = [str(args.reference/prefix)]
    sys.modules['parser_core'] = package
    hits = importlib.import_module('parser_core.ingestion.hits')
    observations = importlib.import_module('parser_core.ingestion.buff_observations')
    mapping = importlib.import_module('parser_core.effects.packet_mapping')
    status = importlib.import_module('parser_core.effects.enemy_status')
    skill_ids = importlib.import_module('parser_core.ingestion.skill_identity')
    lifecycle = importlib.import_module('parser_core.effects.lifecycle')
    dynamic = importlib.import_module('parser_core.ingestion.dynamic_evidence')
    effect_approval = importlib.import_module('parser_core.effects.approval')
    packet_catalog = importlib.import_module('parser_core.catalog.packet_semantics')
    current = {}
    roots = lambda: current.get('roots', {})
    numbers = lambda: current.get('numbers', {})
    hits._load_current_buff_roots = roots
    observations._load_current_buff_roots = roots
    observations._load_num_id_str_buff_map = numbers
    observations._rdps_registry_matching_effect_entry = lambda *args, **kwargs: (
        effect_approval._rdps_registry_matching_effect_entry(*args, **kwargs) if current.get('use_approval') else current.get('approval'))
    effect_approval._load_rdps_semantics_registry = lambda: current.get('registry', {})
    effect_approval._load_current_buff_roots = roots
    effect_approval._load_num_id_str_buff_map = numbers
    effect_approval._load_num_id_str_skill_map = lambda: current.get('skills', {})
    status._load_current_buff_roots = roots
    lifecycle._load_current_buff_roots = roots
    dynamic._load_current_buff_roots = roots
    dynamic._load_num_id_str_buff_map = numbers
    dynamic._load_skill_item_metadata = lambda key: dict(dynamic_action_keys={int(k):v for k,v in current.get('skill_metadata',{}).get(key,{}).items()})
    skill_ids._load_num_id_str_buff_map = numbers
    hits._resolve_character_name = lambda key: current.get('names', {}).get(key)
    hits._resolve_enemy_name = lambda key: current.get('names', {}).get(key)
    mapping._load_packet_numeric_buff_map = lambda: current.get('numeric', {})
    mapping._load_num_id_str_buff_map = numbers
    mapping._load_mechanism_registry_by_buff_id = lambda: current.get('mechanisms', {})

    def canonical_map():
        rows = defaultdict(list)
        for row in current.get('numeric', {}).values():
            if row.get('canonical_buff_id'):
                rows[str(row['canonical_buff_id'])].append(row)
        return {key: packet_catalog._merge_packet_buff_mapping_rows(value) for key, value in rows.items()}
    mapping._load_packet_canonical_buff_map = canonical_map

    def encode(value):
        if type(value) is int: return {'int': str(value)}
        if type(value) is float: return {'f64': struct.pack('>d', value).hex()}
        if isinstance(value, (list, tuple)): return [encode(item) for item in value]
        if isinstance(value, dict): return {str(key): encode(item) for key, item in value.items()}
        if isinstance(value, set): return [encode(item) for item in sorted(value)]
        return value

    def snapshot(state):
        def index(record):
            return next((i for i, row in enumerate(state.buff_starts) if row is record), None)
        rows = []
        for record in state.buff_starts:
            public = {key: value for key, value in record.items() if not key.startswith('_')}
            pending = copy.deepcopy(record.get('_dynamic_pending_state'))
            if pending is not None:
                pending['operations'] = {key:(signature[0],signature[1],signature[2],
                    float.fromhex(signature[3]) if signature[3] is not None else None,json.loads(signature[4]))
                    for key,signature in pending['operations'].items()}
            rows.append(dict(fields=public, observed=record.get('_observed_bb_values', {}),
                             invalid=sorted(record.get('_dynamic_unresolved_keys') or []),
                             dynamic=pending, legacy=record.get('_resistance_parameter_state'),
                             previous=index(record.get('_previous_snapshot_record')),
                             ends=[lifecycle._buff_record_end_ts_ms(record, end) for end in (-1, 100, 1000, 10000)]))
            if record.get('_keyword_seen_updates') is not None:
                rows[-1]['keyword_updates'] = {key: [value[0], value[1], json.loads(value[2])]
                    for key, value in record['_keyword_seen_updates'].items()}
        history = []
        for key, entry in state.buff_creation_operation_history.items():
            history.append(dict(key=key, record=index(entry['record']), observation=entry['observation'],
                                instance=entry['instance_start_line_no']))
        return dict(records=rows, active={uid:index(record) for uid, record in state.active_buff_starts_by_uid.items()},
                    pending=index(state.pending_buff_record), roster=state.roster_order,
                    numeric={key:[index(record) for record in rows] for key,rows in state.recent_numeric_buffs_by_source.items()},
                    unresolved=state.unresolved_buff_actions, history=history,
                    dynamic_events=state.dynamic_bb_events, refresh_events=state.buff_attribute_refresh_events,
                    pending_modifiers=dict(state.pending_attr_mods),
                    shared_enable=[[left['enable_observations'] is right['enable_observations']
                                    for right in state.buff_starts] for left in state.buff_starts],
                    shared_refresh=[[left['attribute_refresh_snapshots'] is right['attribute_refresh_snapshots']
                                     for right in state.buff_starts] for left in state.buff_starts])

    cases = []
    def add(name, lines, **config):
        nonlocal current
        current = copy.deepcopy(config)
        state = SimpleNamespace(buff_starts=[], active_buff_starts_by_uid={}, pending_buff_record=None,
            roster_seen=set(), roster_order=[], participant_totals=defaultdict(dict), pending_attr_mods=defaultdict(list),
            recent_numeric_buffs_by_source=defaultdict(list), recent_skill_casts_by_char={},
            active_suits_by_char=current.get('suits', {}), active_weapons_by_char=current.get('weapons', {}),
            unresolved_buff_actions=[], buff_creation_operation_history={}, context_enemy_hint=None,
            dynamic_bb_events=[],buff_attribute_refresh_events=[],buff_root_action_indices={})
        expected = []
        events = []
        for index, event in enumerate(lines):
            event = dict(text=event) if isinstance(event, str) else event
            event = dict({'line':index+1, 'ts':(index+1)*100}, **event)
            events.append(event)
            error = None
            try:
                if 'seed' in event:
                    seed = copy.deepcopy(event['seed'])
                    record = state.active_buff_starts_by_uid[seed.pop('uid')]
                    for key, value in seed.items():
                        if key == '_dynamic_pending_state':
                            value['context'] = tuple(value['context'])
                            value['invalid_keys'] = set(value['invalid_keys'])
                            value['operations'] = {int(k):v for k,v in value['operations'].items()}
                        elif key == '_dynamic_unresolved_keys':
                            value = set(value)
                        record[key] = value
                elif not observations.consume_buff_observation(state, event['text'], event['line'], event['ts']):
                    if not dynamic.consume_dynamic_observation(state,event['text'],event['line'],event['ts']) and not observations.consume_buff_blackboard(state, event['text'], event['line'], event['ts']):
                        hits.consume_hit_and_buff_lifecycle(state, event['text'], event['line'], event['ts'])
            except (ValueError, TypeError, OverflowError, AttributeError) as exc:
                error = type(exc).__name__
            expected.append(encode(copy.deepcopy(dict(error=error, state=snapshot(state)))))
        cases.append(dict(name=name, config=config, events=events, expected=expected))

    actor, enemy = 'chr_0001_alpha', 'eny_0001_enemy'
    def start(uid='31', template='buff_test', **fields):
        values = dict(uid=uid, id=template, owner=enemy, ownerId='22', src=actor, srcId='11', **fields)
        return ' BUFF_START '+' '.join(f'{key}={value}' for key,value in values.items())
    def creation(**changes):
        payload = dict(schemaVersion=1, buffUid='31', buffTemplate='buff_test', buffId='buff_test',
            sourceEvent='BattleOpTriggerAction', sessionId='session', operationSeq=1,
            generationScope='operation_owner', operationOwnerId='11', operationGeneration=0,
            sourceActorId='11', targetActorId='22')
        payload.update(changes)
        return ' BUFF_CREATE_OBSERVED '+json.dumps(payload, ensure_ascii=True)
    def enable(**changes):
        payload = dict(schemaVersion=1, buffUid='31', ownerId='22', enabled=True, operationSeq=3)
        payload.update(changes)
        return ' BUFF_ENABLE '+json.dumps(payload)
    def origin(**changes):
        payload = dict(schemaVersion=1, buffUid='31', buffTemplate='buff_test', sourceActorId='11', targetActorId='22',
                       environmentInstId='99', actionId=1, operationSeq=2, triggerType=0)
        payload.update(changes)
        return ' BUFF_ORIGIN '+json.dumps(payload)
    limited = dict(lifeType='Limited', duration=dict(useBlackboardKey=False, value=2))
    infinity = dict(lifeType='Infinity')
    add('lifetime/explicit', [start(dur=1), ' BUFF_END uid=31', ' BB[ duration=9 ]', 'ordinary'], roots={'buff_test':limited})
    add('lifetime/packet-pause', [start(dur=0.05), {'text':' BUFF_END uid=31', 'ts':3000}], roots={'buff_test':limited})
    for duration in (limited, infinity, dict(lifeType='Limited',duration=dict(useBlackboardKey=True,blackboardKey='duration')),
                     dict(lifeType='Limited',duration=dict(useBlackboardKey=0,value=5)),
                     dict(lifeType='Limited',duration=dict(useBlackboardKey=False,value=True)), {}):
        add(f'lifetime/root/{len(cases)}', [start(), ' BB[ duration=1.5 resist=-0.2 bad=NaN ]', start(), ' BUFF_END uid=31'], roots={'buff_test':duration})
    for uid in ('0','4294967295','','31','-1','0001'):
        add('identity/uid/'+uid, [start(uid=uid), enable(buffUid=uid), start(uid=uid), ' BUFF_END uid='+uid])
    for key, value in dict(ownerId='44',srcId='55',owner=actor,src='chr_0002_beta',id='buff_other').items():
        fields = dict(uid='31',id='buff_test',owner=enemy,ownerId='22',src=actor,srcId='11')
        fields[key] = value
        changed = ' BUFF_START '+' '.join(f'{k}={v}' for k,v in fields.items())
        add('identity/conflict/'+key,[start(),enable(),origin(),changed,enable(),start()],roots={'buff_test':infinity,'buff_other':limited})
    add('identity/missing', [start(), ' BUFF_START uid=31 id=buff_test owner='+enemy, enable(), ' BUFF_END uid=31'])
    add('modifiers/consume', [' ATTR_MOD buff=7 bbKey=x attrType=4 val=0.25', ' DMG_MOD buff=7 bbKey=y val=-1',
        start(template='7'), ' BB[ x=-1 y=0 ]', ' BUFF_START uid=41 id=7 owner=unknown src=unknown', start(template='7')], numbers={'7':'buff_test'})
    for mode, func in [('enable',enable),('origin',origin),('creation',creation)]:
        base = json.loads(func().split(' ',2)[2])
        for key, value in list(base.items()):
            for replacement in (None,True,False,0,1,-1,1.0,'',[],{}):
                if replacement == value and type(replacement) is type(value): continue
                add(f'{mode}/field/{key}/{len(cases)}',[start(),func(**{key:replacement}), ' BUFF_END uid=31'])
        for blob in ('{}','[]','null','{',' {"schemaVersion":1}', '{"schemaVersion":1,"schemaVersion":1}',
                     func().split(' ',2)[2][:-1]+',"operationSeq":3}'):
            add(f'{mode}/json/{len(cases)}',[start(),' BUFF_'+dict(enable='ENABLE',origin='ORIGIN',creation='CREATE_OBSERVED')[mode]+' '+blob])
    assignments = [dict(target_key='resist',use_direct_value=True,numeric_value=-0.2)]
    add('creation/duplicate-snapshot',[start(),creation(assignedItems=assignments),start(),creation(assignedItems=assignments),enable()])
    add('creation/conflict',[start(),creation(assignedItems=assignments),start(),creation(assignedItems=[dict(assignments[0],numeric_value=-0.4)])])
    add('creation/closed-instance-replay',[start(),creation(), ' BUFF_END uid=31', start(),creation()])
    add('creation/stale',[start(),creation(operationSeq=10),start(),creation(operationSeq=9)])
    add('creation/session-conflict',[start(),creation(),creation(sessionId='other',operationSeq=2)])
    for context in (['session','11',0],['session','11',1],['session','44',1]):
        for seq in (0,1,10):
            seed = dict(uid='31',_dynamic_pending_state=dict(context=context,values={'old':-1.0},
                value_sources={},last_seq=seq,operations={},invalid_keys=['old']),
                _dynamic_unresolved_keys=['old'],attribute_refresh_snapshots=[{'operation_seq':0,'status':'observed'},
                                                                             {'operation_seq':10,'status':'observed'}])
            add(f'creation/pending/{len(cases)}',[start(),{'seed':seed},creation(assignedItems=[
                dict(target_key='old',use_direct_value=True,numeric_value=-0.2)]),start(),creation(assignedItems=[
                dict(target_key='old',use_direct_value=True,numeric_value=-0.4)])])
    for items in (None,[],[{}],[[]],[['x',1]],[True],assignments,assignments*2,
                  assignments+[dict(assignments[0],numeric_value=0.0)],
                  [dict(assignments[0],numeric_value=0.0),dict(assignments[0],numeric_value=-0.0)],
                  [dict(assignments[0],use_direct_value=False)],[dict(assignments[0],numeric_value=True)],
                  [dict(assignments[0],numeric_value=float('inf'))]):
        add(f'creation/assignments/{len(cases)}',[start(),' BB[ resist=-0.3 ]',creation(assignedItems=items)])
    add('creation/nested-duplicate',[start(),creation()[:-1]+',"buffTemplateId":{"type":1,"str_id":"buff_test","str_id":"buff_test"}}'])
    add('creation/assigned-duplicate',[start(),creation()[:-1]+',"assignedItems":[{"target_key":"x","target_key":"y","use_direct_value":true,"numeric_value":1}]}'])
    for template in ({'type':1,'int_id':7},{'type':'Buff','str_id':'buff_test'},{'type':True,'str_id':'buff_test'},
                     {'type':1,'str_id':'buff_test','int_id':7},[],{},[['type',1]],{'type':1.0,'int_id':7}):
        add(f'creation/template/{len(cases)}',[start(),creation(buffTemplateId=template)],numbers={'7':'buff_test'})
    for generation in (0,True,1.0,None,'0',[],{}):
        add(f'creation/generation/{len(cases)}',[start(),creation(operationGeneration=generation),start(),creation(operationGeneration=generation)])
    for first, second in ((0,False),(0,0.0),(True,1),(1.0,1),(None,0),('1',1)):
        add(f'creation/equal-context/{len(cases)}',[start(),creation(operationGeneration=first),start(),creation(operationGeneration=second)])
    add('observations/nested-pairs',[start(),enable(extra={'a':1,'nested':{'b':2}}),start(),origin(extra={'x':[{'y':3}]}),creation(extra={'z':4})])
    add('observations/names',[start(),start(uid='41',template='buff_wpn_test_0123_one')],names={actor:'合成角色',enemy:'合成敌人'})
    for numeric in ({'7':{'canonical_buff_id':'buff_test','character_id':actor}},
                    {'7':{'canonical_buff_id':'buff_test','suit_id':'suit_A'}},
                    {'7':{'canonical_buff_id':'buff_test','weapon_id':'wpn_A'}},
                    {'7':{'canonical_buff_id':'buff_test','effects':[{'zone':'amp','rate':1}], 'reason':''},
                     '8':{'canonical_buff_id':'buff_test','effects':[{'rate':1,'zone':'amp'},{'rate':1.0,'zone':'amp'}],'reason':'合成'}}):
        for suits in ({},{actor:[]},{actor:['suit_A']}):
            for weapons in ({},{actor:'wpn_B'},{actor:'wpn_A'}):
                add(f'mapping/guards/{len(cases)}',[start(template='7'),start(template='buff_test')],numeric=numeric,suits=suits,weapons=weapons)
    for rows in ([],[{}],[{'source_kind':'weapon','source_id':'wpn_A'}],[{},{}]):
        add(f'mapping/mechanism/{len(cases)}',[start(template='7')],numbers={'7':'buff_test'},mechanisms={'buff_test':rows})
    add('mapping/internal-trigger',[start(template='7'),' BB[ phy_dmg_up=1 final_phy_dmg_up=2 shatter_dmg=3 consumed_layer=1 ]'],numbers={'7':'buff_test'})
    add('unresolved/end',[start(),' BUFF_ACTION_UNRESOLVED uid=31 seq=2 triggerType=4 actionId=9 ownerId=22 srcId=11',' BUFF_END uid=31'])
    rng = random.Random(730163)
    for index in range(32):
        lines = [start()]
        for step in range(8):
            lines.append(rng.choice([start(),creation(operationSeq=rng.randrange(4)),enable(enabled=bool(rng.randrange(2))),
                                    origin(), ' BUFF_END uid=31',' BB[ duration=0.2 resist=-0.1 ]','ordinary']))
        add(f'ordered/{index}',lines,roots={'buff_test':limited})
    if args.keyword:
        cases.clear()
        approval = {'_rdps_whitelist_keys':['buff_chr_0023_antal_normal_fragile'], '_keyword_origin':[{'actionId':1}]}
        marker = 'buff_marker'
        root = {'$type':'Beyond.Gameplay.Core.VulnerableAction.Data', 'serverActionIndex':1,
            'enhancingList':[{'operationType':'Add', 'value':{'useBlackboardKey':True,'blackboardKey':'potential_5_rate'},
                              'buffIds':[marker]}]}
        def keyword(unresolved=False, **changes):
            payload = dict(schemaVersion=1, buffUid='31', ownerId='22', sessionId='session',
                operationSeq=2, generation=0, addedBuffNumId=7, operationPayloadCase='trigger_keyword_op_data',
                modify=[dict(configIndex=0, rateAfter=0.3)])
            payload.update(changes)
            return (' BUFF_KEYWORD_UPDATE_UNRESOLVED ' if unresolved else ' BUFF_KEYWORD_UPDATE ') + json.dumps(payload)
        def kwadd(name, lines, **changes):
            config = dict(approval=approval, roots={'buff_chr_0023_antal_tageffect':root}, numbers={'7':marker})
            config.update(changes)
            add(name, lines, **config)
        prefix = [start(), creation()]
        kwadd('keyword/observed', prefix+[keyword(),keyword(),keyword(operationSeq=3,modify=[dict(configIndex=0,rateAfter=0.5)])])
        kwadd('keyword/conflict', prefix+[keyword(),keyword(modify=[dict(configIndex=0,rateAfter=0.4)]),keyword()])
        kwadd('keyword/value-type-signature', prefix+[keyword(modify=[dict(configIndex=0,rateAfter=0)]),
            keyword(modify=[dict(configIndex=0,rateAfter=0.0)]),keyword(modify=[dict(configIndex=0,rateAfter=-0.0)])])
        kwadd('keyword/generation-signature',prefix+[keyword(),keyword(generation=1),keyword(addedBuffNumId=8)])
        kwadd('keyword/out-of-order',prefix+[keyword(operationSeq=4),keyword(operationSeq=3),keyword(operationSeq=2)])
        kwadd('keyword/no-creation',[start(),keyword()])
        kwadd('keyword/wrong-creation-session',[start(),creation(sessionId='other'),keyword()])
        kwadd('keyword/before-creation',prefix+[keyword(operationSeq=1),keyword(operationSeq=0)])
        kwadd('keyword/end',prefix+[' BUFF_END uid=31',keyword()])
        kwadd('keyword/new-snapshot',prefix+[keyword(),start(),keyword(),creation(operationSeq=3),keyword(operationSeq=4)])
        kwadd('keyword/unresolved-tag',prefix+[keyword(unresolved=True),keyword(operationSeq=3,validationErrors=['unknown'])])
        for field in ('schemaVersion','buffUid','ownerId','sessionId','operationSeq','generation','addedBuffNumId','operationPayloadCase'):
            for value in (None,True,False,0,1,-1,1.0,'','31','22','session',[],{},2**32,2**64):
                kwadd(f'keyword/field/{field}/{len(cases)}',prefix+[keyword(**{field:value})])
        for rate in (None,True,False,-1,0,0.0,-0.0,1,1.5,'0.3',float('nan'),float('inf'),-float('inf')):
            kwadd(f'keyword/rate/{len(cases)}',prefix+[keyword(modify=[dict(configIndex=0,rateAfter=rate)]),keyword()])
        for rows in (None,{},[],[None],[[]],[{}],[dict(configIndex=True,rateAfter=0.3)],
                     [dict(configIndex=0,rateAfter=0.3)]*2,[[['configIndex',0],['rateAfter',0.3]]],
                     {'x':dict(configIndex=0,rateAfter=0.3)},[dict(configIndex=0,rateAfter=0.3,extra={'x':1,'y':2})]):
            kwadd(f'keyword/rows/{len(cases)}',prefix+[keyword(modify=rows),keyword(modify=rows)])
        for value in (None,[],{},False,True,'error',['error']):
            kwadd(f'keyword/errors/{len(cases)}',prefix+[keyword(validationErrors=value),keyword()])
        for value in (None,{},dict(approval,_rdps_whitelist_keys=[]),dict(approval,_keyword_origin=[]),
                      dict(approval,_rdps_whitelist_keys=['other']),dict(approval,_rdps_whitelist_keys=['buff_chr_0023_antal_normal_fragile','other'])):
            kwadd(f'keyword/approval/{len(cases)}',prefix+[keyword()],approval=value)
        for changed in ({},{'serverActionIndex':2},dict(root,enhancingList=[]),dict(root,enhancingList=root['enhancingList']*2),
                        dict(root,enhancingList=[dict(root['enhancingList'][0],operationType='Multiply')]),
                        dict(root,enhancingList=[dict(root['enhancingList'][0],buffIds=['other'])]),
                        dict(root,enhancingList=[dict(root['enhancingList'][0],value={'useBlackboardKey':False,'value':0.1})])):
            kwadd(f'keyword/root/{len(cases)}',prefix+[keyword(),keyword(operationSeq=3)],roots={'buff_chr_0023_antal_tageffect':changed})
        kwadd('keyword/root-duplicate',prefix+[keyword()],roots={'buff_chr_0023_antal_tageffect':dict(a=root,b=root)})
        for blob in ('', '{','[]','null',' {}','{"schemaVersion":1,"schemaVersion":1}',
                     keyword().split(' ',2)[2].replace('"rateAfter": 0.3','"rateAfter":0.3,"rateAfter":0.4'),
                     keyword().split(' ',2)[2].replace('"configIndex": 0','"configIndex":0,"configIndex":0'),
                     keyword().split(' ',2)[2]+',', '[1,]', '{"x":1,}'):
            kwadd(f'keyword/json/{len(cases)}',prefix+[' BUFF_KEYWORD_UPDATE '+blob,keyword()])
        kwadd('keyword/nested-order-signature',prefix+[keyword(modify=[dict(configIndex=0,rateAfter=0.3,extra={'x':1,'y':2})]),
            keyword(modify=[dict(rateAfter=0.3,configIndex=0,extra={'y':2,'x':1})])])
        parent='buff_chr_0023_antal_tageffect'
        main='buff_common_affixes_vulnerable_fire'
        real_root=dict(root, isEnable=True, subType='Fire', rate=dict(useBlackboardKey=True,blackboardKey='rate'))
        approved_entry=dict(aliases=[parent], guard=dict(source_character_key=actor), effects=[dict(zone='fragile',element='fire',bb_key='rate')])
        real_registry=dict(verified_effects={'buff_chr_0023_antal_normal_fragile':approved_entry},
                           _keyword_buff_map=dict(Vulnerable=dict(Fire=main)))
        real_prefix=[start(template=main),creation(buffTemplate=main,buffId=main),
                     origin(buffTemplate=main,environmentType='Buff',ownerType='1',templateStrId=parent,templateIntId=None)]
        def connected(name,lines,**changes):
            config=dict(use_approval=True,registry=real_registry,roots={parent:real_root},numbers={'7':marker})
            config.update(changes)
            add('keyword/connected/'+name,lines,**config)
        connected('updates',real_prefix+[keyword(),keyword(operationSeq=3,modify=[dict(configIndex=0,rateAfter=0.5)])])
        connected('conflict',real_prefix+[keyword(),keyword(modify=[dict(configIndex=0,rateAfter=0.9)])])
        connected('missing-origin',real_prefix[:2]+[keyword()])
        connected('wrong-origin',real_prefix[:2]+[origin(buffTemplate=main,environmentType='Buff',ownerType='1',templateStrId='wrong'),keyword()])
        connected('disabled',real_prefix+[keyword()],roots={parent:dict(real_root,isEnable=False)})
        connected('missing-rate-key',real_prefix+[keyword()],roots={parent:dict(real_root,rate=dict(useBlackboardKey=True,blackboardKey='wrong'))})
        connected('wrong-source-guard',real_prefix+[keyword()],registry=dict(real_registry,verified_effects={
            'buff_chr_0023_antal_normal_fragile':dict(approved_entry,guard=dict(source_character_key='foreign'))}))
        connected('no-registry',real_prefix+[keyword()],registry={})
        connected('end-and-reopen',real_prefix+[keyword(),' BUFF_END uid=31',*real_prefix,keyword()])
        connected('new-snapshot',real_prefix+[keyword(),start(template=main),keyword(),creation(buffTemplate=main,buffId=main,operationSeq=4),keyword(operationSeq=5)])
        if args.output.name == 'buff-instances.json': args.output=args.output.with_name('buff-keywords.json')
    if args.dynamic:
        cases.clear()
        modify_type = 'Beyond.Gameplay.Core.ModifyDynamicBlackboard.Data'
        refresh_type = 'Beyond.Gameplay.Core.RefreshBuffAttrModifierValue.Data'
        root = dict(lifeType='Infinity',actions=[
            dict(serverActionIndex=1,isEnable=True,**{'$type':modify_type},key='resist',operation='Add',value={'value':1}),
            dict(serverActionIndex=2,isEnable=True,**{'$type':refresh_type})],
            attributeModifier={'attributeModifiers':[
                dict(attributeType=4,formulaItem='Add',param={'useBlackboardKey':True,'blackboardKey':'resist'}),
                dict(attributeType=5,formulaItem='Add',param={'useBlackboardKey':False,'value':0.2})]})

        def identity(refresh=False,**changes):
            data = dict(schemaVersion=1,actionType=31 if refresh else 7,
                actionRuntimeCase='refresh_buff_attr_modifier_value_action' if refresh else 'modify_dynamic_blackboard_action',
                operationPayloadCase='trigger_action_op_data',ownerType=1,templateType='Buff',triggerType=0,
                sessionId='session',operationSeq=3 if refresh else 2,generation=0,actionId=2 if refresh else 1,
                environmentInstId='31',ownerId='22',operationOwnerId='22',templateIdCase='str_id',templateStrId='buff_test',templateIntId=None)
            if refresh: data['buffUid']='31'
            data.update(changes)
            return data

        def modify(value=-0.2, envelope=None, **fields):
            envelope = identity() if envelope is None else envelope
            values = dict(seq=envelope.get('operationSeq',2),tick=777,inst='31',ownerId='22',owner=enemy,
                skill=envelope.get('templateStrId') or 'buff_test',actionId=envelope.get('actionId',1),value=value)
            values.update(fields)
            return ' BB_MODIFY_DYNAMIC '+' '.join(f'{key}={value}' for key,value in values.items())+' identity='+json.dumps(envelope)

        def refresh(envelope=None,**changes):
            return ' BUFF_ATTR_REFRESH '+json.dumps(identity(True,**changes) if envelope is None else envelope)

        def dynadd(name,lines,**config):
            config = dict({'roots':{'buff_test':root}},**config)
            add('dynamic/'+name,lines,**config)

        dynadd('assignment',[start(),creation(),modify(),refresh(),modify(),refresh()])
        dynadd('creation-seed',[start(),creation(assignedItems=[dict(target_key='resist',use_direct_value=True,numeric_value=-0.3)]),refresh()])
        dynadd('missing-parameters',[start(),creation(),refresh()])
        dynadd('late-conflict',[start(),creation(),modify(),refresh(),modify(-0.4)])
        dynadd('snapshot',[start(),creation(),modify(),refresh(),start(),modify(-0.3,envelope=identity(operationSeq=4)),refresh(operationSeq=5)])
        dynadd('contexts',[start(),creation(),modify(),modify(-0.3,envelope=identity(generation=1,operationSeq=4)),refresh(generation=1,operationSeq=5),modify(-0.4,envelope=identity(generation=0,operationSeq=6))])
        for initial,repeat in ((0.0,-0.0),(-0.2,-0.2),(-0.2,-0.3)):
            dynadd(f'duplicate/{len(cases)}',[start(),creation(),modify(initial),refresh(),modify(repeat)])
        for key, value in identity().items():
            for replacement in (None,False,0,-1,1.0,'',[],{}):
                if replacement == value and type(replacement) is type(value): continue
                dynadd(f'identity/{key}/{len(cases)}',[start(),creation(),modify(envelope=identity(**{key:replacement})),refresh()])
        for key, value in dict(inst='41',ownerId='11',skill='buff_other',actionId=2,seq=10,value='NaN').items():
            dynadd('text/'+key,[start(),creation(),modify(**{key:value}),refresh()])
        for broken in (' BB_MODIFY_DYNAMIC skill=buff_test ownerId=22 inst=31 actionId=1 value=-0.4',
                       modify()[:-1]+',"actionId":1}',modify().split(' identity=')[0]+' identity=null'):
            dynadd(f'identity/encoding/{len(cases)}',[start(),creation(),broken,refresh()])
        for key in ('schemaVersion','buffUid','environmentInstId','ownerId','actionType','triggerType','templateIdCase','generation'):
            dynadd('refresh/invalid/'+key,[start(),creation(),modify(),refresh(**{key:None})])
        for mode in ('disabled','duplicate','missing','missing_key','wrong_type','inherited_disabled','plus_type'):
            variant = copy.deepcopy(root)
            if mode == 'disabled': variant['actions'][0]['isEnable']=False
            elif mode == 'duplicate': variant['actions'].append(copy.deepcopy(variant['actions'][0]))
            elif mode == 'missing': variant['actions']=variant['actions'][1:]
            elif mode == 'missing_key': variant['actions'][0]['key']=''
            elif mode == 'wrong_type': variant['actions'][0]['$type']=refresh_type
            elif mode == 'plus_type': variant['actions'][0]['$type']=modify_type.replace('.Data','+Data')
            else: variant={'serverActionIndex':9,'isEnable':False,'child':variant}
            dynadd('root/'+mode,[start(),creation(),modify(),refresh()],roots={'buff_test':variant})
        for literal in (None,True,'-0.2',-0.2,float('inf'),float('-inf'),float('nan')):
            variant = copy.deepcopy(root)
            variant['attributeModifier']['attributeModifiers'][1]['param']['value']=literal
            dynadd(f'parameter/literal/{len(cases)}',[start(),creation(),modify(),refresh()],roots={'buff_test':variant})
        for extra in ({'nested':{'a':1,'b':2}},{'nested':{'b':2,'a':1}},{'nested':[1,2]}):
            dynadd(f'signature/nested/{len(cases)}',[start(),creation(),modify(envelope=identity(extra={'nested':{'a':1,'b':2}})),modify(envelope=identity(extra=extra))])
        dynadd('metadata/fallback',[start(),modify().split(' identity=')[0],refresh()],roots={},skill_metadata={'buff_test':{'1':'resist'}})
        dynadd('template/numeric',[start(),creation(),modify(envelope=identity(templateIdCase='int_id',templateIntId=7,templateStrId=None)),refresh(templateIdCase='int_id',templateIntId=7,templateStrId=None)],numbers={'7':'buff_test'})

        corrosion = 'buff_common_natural_natural_corrupt_do'
        parent = 'buff_parent'
        corrosion_root = copy.deepcopy(root)
        corrosion_root['stackingSettings']={'stackingType':'Stack'}
        corrosion_root['actions'][0]['key']='def_decrease'
        corrosion_root['actions'].append(dict(serverActionIndex=3,isEnable=True,**{'$type':modify_type},key='additional_def_decrease'))
        corrosion_root['attributeModifier']['attributeModifiers']=[dict(attributeType=4,formulaItem='Add',param={'useBlackboardKey':True,'blackboardKey':key})
                                                                 for key in ('def_decrease','additional_def_decrease')]
        parent_root = dict(actions=[dict(serverActionIndex=9,isEnable=True,**{'$type':'Beyond.Gameplay.Core.CreateBuffAction.Data'})])
        assigned = [dict(target_key=key,use_direct_value=True,numeric_value=value) for key,value in (('def_decrease',-0.2),('additional_def_decrease',-0.1))]
        anchor = creation(buffTemplate=corrosion,buffId=corrosion,creationActionType='BattleActionCreateBuff',
                          creationActionRuntimeCase='create_buff_action',assignedItems=assigned)
        provenance = origin(buffTemplate=corrosion,operationSeq=1,actionId=9,environmentType='Buff',ownerType=1,templateStrId=parent,templateIntId=None)
        for provenance_lines in ([],[provenance],[provenance,provenance],[provenance,origin(buffTemplate=corrosion,operationSeq=1,actionId=9,environmentType='Buff',ownerType=1,templateStrId=parent,environmentInstId='98')]):
            dynadd(f'creation/proof/{len(cases)}',[start(template=corrosion),anchor,*provenance_lines,
                refresh(templateStrId=corrosion)],roots={corrosion:corrosion_root,parent:parent_root})

        def legacy_payload(refresh=False,**changes):
            data = dict(schemaVersion=1,actionId=2 if refresh else 1,actionType=31 if refresh else 7,
                sessionId='session',operationSeq=4 if refresh else 2,eventContext=dict(owner_type=1,template_type='Buff',
                    inst_id='31',owner_id='22',seq_id=4 if refresh else 2,template_str_id=corrosion,template_int_id=None))
            data.update(changes)
            return data
        legacy_modify = modify(envelope=legacy_payload(),skill=corrosion)
        legacy_second = modify(-0.1,envelope=legacy_payload(actionId=3,operationSeq=3,eventContext=dict(legacy_payload()['eventContext'],seq_id=3)),skill=corrosion)
        legacy_refresh = refresh(envelope=legacy_payload(True))
        dynadd('legacy/observations',[start(template=corrosion),anchor,legacy_modify,legacy_second,legacy_refresh,legacy_modify,legacy_refresh],roots={corrosion:corrosion_root})
        dynadd('legacy/conflict',[start(template=corrosion),anchor,legacy_modify,legacy_second,legacy_refresh,
            modify(-0.4,envelope=legacy_payload(),skill=corrosion),legacy_refresh],roots={corrosion:corrosion_root})
        for key,value in dict(operationOwnerId='22',generation=0,ownerId='22',environmentInstId='31',operationPayloadCase='trigger_action_op_data').items():
            dynadd('legacy/no-modern-fallback/'+key,[start(template=corrosion),anchor,
                modify(envelope=legacy_payload(**{key:value}),skill=corrosion),legacy_refresh],roots={corrosion:corrosion_root})
        for parameter in ({'useBlackboardKey':True,'blackboardKey':''},{'useBlackboardKey':True,'blackboardKey':'missing'},
                          {'useBlackboardKey':1,'value':1},{'value':None}):
            variant = copy.deepcopy(root)
            variant['attributeModifier']['attributeModifiers'][0]['param']=parameter
            dynadd(f'parameter/binding/{len(cases)}',[start(),creation(),modify(),refresh()],roots={'buff_test':variant})
        dynadd('refresh/missing-definitions',[start(),creation(),modify(),refresh(),refresh()],roots={'buff_test':dict(root,attributeModifier={})})
        for index in range(32):
            lines = [start(),creation()]
            for step in range(10):
                seq = rng.randrange(2,8)
                lines.append(rng.choice([start(),creation(operationSeq=seq),modify(rng.choice([-0.2,-0.1,0.0]),envelope=identity(operationSeq=seq,generation=rng.randrange(2))),
                                        refresh(operationSeq=seq,generation=rng.randrange(2)),' BB[ resist=-0.3 ]',' BUFF_END uid=31']))
            dynadd(f'ordered/{index}',lines)
        if args.bundled:
            relative = '_internal/data/runtime-data.zip'
            archive_path = args.reference/relative
            digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
            if metadata['files'][relative]['sha256'] != digest:
                raise ValueError('Fixed runtime bundle changed')
            dependencies[relative]=digest
            with zipfile.ZipFile(archive_path) as archive:
                document=json.loads(gzip.decompress(archive.read('data/local_static/buff/typed_roots.json.gz')))
            cases.clear()
            for template,entry in sorted(document['entries'].items()):
                actual_root=entry['root']
                index=dynamic.indexed_root_actions(actual_root,{})[1]
                modifies=[action for action,rows in sorted(index.items()) if any(node.get('$type')==modify_type for node,_ in rows)]
                refreshes=[action for action,rows in sorted(index.items()) if any(node.get('$type')==refresh_type for node,_ in rows)]
                if not modifies and not refreshes: continue
                lines=[start(template=template),creation(buffTemplate=template,buffId=template)]
                if modifies: lines.append(modify(envelope=identity(templateStrId=template,actionId=modifies[0])))
                if refreshes: lines.append(refresh(templateStrId=template,actionId=refreshes[0]))
                dynadd(f'bundled/{len(cases)}',lines,roots={template:actual_root})
            for case in cases:
                case['config_json']=json.dumps(case.pop('config'),ensure_ascii=True)
        if args.output.name == 'buff-instances.json': args.output=args.output.with_name('buff-dynamics.json')
    # Stable parsed JSON is the fixture input, including its named nonfinite constants.
    for case in cases:
        if 'config' in case:
            try: json.dumps(case['config'],allow_nan=False)
            except ValueError: case['config_json']=json.dumps(case.pop('config'),ensure_ascii=True)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(cases,ensure_ascii=True,separators=(',',':'),allow_nan=False),encoding='utf8')
    args.output.with_suffix('.reference.json').write_text(json.dumps(dict(cases=len(cases),
        events=sum(len(case['events']) for case in cases),source_head=metadata['head'],dependencies=dependencies),indent=2),encoding='utf8')
    print('BUFF instance fixtures:',len(cases), 'events:',sum(len(case['events']) for case in cases))


if __name__ == '__main__':
    main()
