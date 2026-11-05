"""Compare reviewed effect approvals against the fixed Python implementation."""
from pathlib import Path
from types import ModuleType
import argparse
import copy
import gzip
import hashlib
import importlib
import json
import random
import re
import struct
import sys
import tempfile
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--bundled', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.bundled and args.output is None:
        parser.error('--bundled requires an explicit local output')
    args.output = args.output or Path(__file__).resolve().parents[3] / '_internal/dotnet/Specs/Fixtures/effect-approval.json'
    metadata = json.loads(args.manifest.read_text(encoding='utf8'))
    prefix = '_internal/packages/parser_core/parser_core/'
    dependencies = {}
    for relative, expected in metadata['files'].items():
        if relative.startswith(prefix) and relative.endswith('.py'):
            digest = hashlib.sha256((args.reference / relative).read_bytes()).hexdigest()
            if digest != expected['sha256']:
                raise ValueError('Fixed approval reference changed: ' + relative)
            dependencies[relative] = digest
    package = ModuleType('parser_core')
    package.__path__ = [str(args.reference / prefix)]
    sys.modules['parser_core'] = package
    approval = importlib.import_module('parser_core.effects.approval')
    packet = importlib.import_module('parser_core.catalog.packet_semantics')
    current = {}
    approval._load_rdps_semantics_registry = lambda: current.get('registry', {})
    approval._load_current_buff_roots = lambda: current.get('roots', {})
    approval._load_num_id_str_buff_map = lambda: current.get('numbers', {})
    approval._load_num_id_str_skill_map = lambda: current.get('skills', {})

    def encode(value):
        if type(value) is int: return {'int': str(value)}
        if type(value) is float: return {'f64': struct.pack('>d', value).hex()}
        if isinstance(value, (list, tuple)): return [encode(item) for item in value]
        if isinstance(value, dict): return {str(key): encode(item) for key, item in value.items()}
        return value

    cases = []

    def add(name, config, record, guard=True, kind='match'):
        current.clear()
        current.update(copy.deepcopy(config))
        packet._RDPS_VERIFIED_INDEX = None
        untouched = copy.deepcopy((current, record))
        if kind == 'registry':
            with tempfile.TemporaryDirectory() as directory:
                base=Path(directory)
                for relative, data in [('data/packet_semantics/rdps_semantics_registry.json', current.get('registry')),
                                       ('data/local_static/buff/keyword_buff_map.json', current.get('keyword'))]:
                    path=base/relative; path.parent.mkdir(parents=True,exist_ok=True)
                    path.write_text(json.dumps(data),encoding='utf8')
                packet._repo_root=lambda:base
                packet._load_rdps_semantics_registry.cache_clear()
                result=packet._load_rdps_semantics_registry()
        elif kind == 'guard': result = approval._rdps_registry_entry_matches_guard(current['entry'], record)
        elif kind == 'allowed': result = approval._rdps_registry_bb_keys_allowed(current['entry'], record)
        elif kind == 'keys': result = sorted(approval._rdps_registry_effect_bb_keys(current['entry']))
        else:
            result = approval._rdps_registry_matching_effect_entry(record, require_guard=guard, root_lookup_cache={})
            uncached = approval._rdps_registry_matching_effect_entry(record, require_guard=guard)
            if encode(result) != encode(uncached): raise AssertionError('Reference cache differs: ' + name)
        if (current, record) != untouched: raise AssertionError('Reference mutated inputs: ' + name)
        cases.append(dict(name=name, kind=kind, config_json=json.dumps(config, ensure_ascii=True),
                          record_json=json.dumps(record, ensure_ascii=True), guard=guard, expected=encode(result)))

    source = 'chr_0001_alpha'
    record = dict(uid='7', event_key='buff_test', raw_event_key='101', source_character_key=source,
                  target_character_key='chr_0002_beta', source_actor_id='11', target_actor_id='22',
                  source_skill_key='skill_test', source_skill_family_key='family_test',
                  packet_mapping=dict(weapon_id='wpn_test', suit_id='suit_test'), source_weapon_template='wpn_test',
                  bb_keys=['rate'], bb_values={'duration': 10})
    effects = [dict(zone='amp', element='all', bb_key='rate')]
    entry = dict(aliases=['buff_alias'], numeric_ids=['101'], effects=effects)
    config = dict(registry=dict(verified_effects={'buff_test': entry}), numbers={'101':'buff_test'})
    add('exact/name', config, record)
    add('exact/numeric', config, dict(record, event_key='unknown', raw_event_key='101'))
    add('exact/alias', config, dict(record, event_key='buff_alias', raw_event_key='unknown'))
    add('exact/missing', config, dict(record, event_key='other', raw_event_key='other'))
    add('exact/missing-identity', config, {})
    add('exact/same-entries', dict(config, registry=dict(verified_effects={'buff_test':entry, 'duplicate':copy.deepcopy(entry)})), record)
    conflict = copy.deepcopy(entry); conflict['effects'][0]['element']='fire'
    add('exact/conflict', dict(config, registry=dict(verified_effects={'buff_test':entry, 'duplicate':conflict})), record)
    for suffix, value in [('integer', 1), ('real', 1.0), ('negative-zero', -0.0), ('zero', 0.0)]:
        left = dict(entry, stack_limit=value)
        right = dict(entry, stack_limit=1.0)
        add('exact/signature-' + suffix, dict(config, registry=dict(verified_effects={'buff_test':left, 'duplicate':right})), record)

    guards = [None, {}, dict(requires_actor_identity=True), dict(target_kind='enemy'), dict(target_kind='character'),
              dict(recipient='self'), dict(recipient='other_character'), dict(source_character_key=source),
              dict(source_character_id=source), dict(character_id=source), dict(source_skill_key='skill_test'),
              dict(source_skill_family_key='family_test'), dict(weapon_id='wpn_test'),
              dict(weapon_id='wpn_test', requires_source_loadout=True), dict(suit_id='suit_test')]
    mutations = [({}, 'valid')]
    for key, values in dict(uid=[None, '', '0', '01', '4294967295', str(2**64-1), str(2**64), 7, True],
                            source_actor_id=[None, '', '22', 11, '11'], target_actor_id=[None, '', '11', 22],
                            source_character_key=[None, '', 'chr_other'], target_character_key=[None, '', source],
                            target_enemy_key=['eny_test'], target_player_key=['player'],
                            source_weapon_template=[None, 'wrong'], source_skill_key=[None, 'other'],
                            source_skill_family_key=[None, 'other'], packet_mapping=[None, {}, dict(weapon_id='wrong'), dict(suit_id='wrong')]).items():
        mutations.extend(({key:value}, key + '/' + str(index)) for index, value in enumerate(values))
    for index, guard in enumerate(guards):
        for changes, label in mutations:
            add(f'guard/{index}/{label}', dict(entry=dict(guard=guard)), dict(record, **changes), kind='guard')
        guarded = dict(entry, guard=guard)
        for required in (False, True):
            add(f'match-guard/{index}/{required}', dict(config, registry=dict(verified_effects={'buff_test':guarded})),
                dict(record, source_character_key='foreign'), required)

    for allowed in (None, [], ['RATE', 'duration'], ['*'], ['rate'], ['Duration'], 'rate'):
        add('allowed/' + str(len(cases)), dict(entry=dict(allowed_bb_keys=allowed)), record, kind='allowed')
    add('effect-keys', dict(entry=dict(effects=effects + [None, dict(bb_key='r', add_bb_key='a', delay_bb_key='d', max_bb_key='m', bb_keys=['r', 'extra'], required_bb_keys=['required'])])), record, kind='keys')
    prefix = dict(prefix='buff_', effects=effects, allowed_bb_keys=['rate', 'duration'])
    for declarations in ([prefix], [prefix, copy.deepcopy(prefix)], [prefix, dict(prefix, dynamic=True)], [dict(prefix, allowed_bb_keys=[])], [dict(prefix, guard=dict(recipient='self'))]):
        add('prefix/' + str(len(cases)), dict(registry=dict(verified_prefixes=declarations)), record)

    empty_root = dict(attributeModifier=dict(attributeModifiers=[]), damageModifier=[], globalModifier=[])
    for actual, approved in [('buff_test', 'buff_test'), ('buff_chr_0023_antal_tageffect', 'buff_chr_0023_antal_normal_fragile'),
                             ('buff_common_natural_natural_corrupt_triggered', 'buff_chr_0025_ardelia_dynamic_def_decrease')]:
        for root in (empty_root, dict(empty_root, globalModifier=[1]), {}):
            approved_entry = dict(entry, aliases=[actual], lifecycle_only=True, dynamic=True, ignored_bb_keys=['already'])
            add('lifecycle/' + str(len(cases)), dict(registry=dict(verified_effects={approved:approved_entry}), roots={actual:root}),
                dict(record, event_key=actual, raw_event_key=actual))
    corrosion='buff_common_natural_natural_corrupt_do'; ardelia='buff_chr_0025_ardelia_dynamic_def_decrease'
    add('corrosion/deduplicate', dict(registry=dict(verified_effects={corrosion:dict(effects=effects), ardelia:dict(effects=effects, aliases=[corrosion])})), dict(record, event_key=corrosion, raw_event_key=corrosion))

    origin = dict(_boundCreateRecord=True, buffUid='7', buffTemplate='buff_test', sourceActorId='11', targetActorId='22',
                  environmentType='Buff', ownerType='1', environmentInstId='77', templateStrId='buff_parent',
                  templateIntId=None, actionId=3, triggerType=0)
    binding = dict(template='buff_test', decoder=copy.deepcopy(approval._NATIVE_DAMAGE_SEMANTICS_BINDING),
                   sourceRootSha256='a'*64, parent_kind='Buff', parent_template='buff_parent', create_actions=[3],
                   recipient='other_character', bb_key_remap={'rate':'actual_rate'})
    bound_config=dict(registry=dict(verified_effects={'approved_parent':dict(effects=effects, runtime_bindings=[binding])}),
                      numbers={'202':'buff_parent'})
    bound_record=dict(record, raw_event_key='buff_test', origin_observations=[origin])
    add('runtime/valid', bound_config, bound_record)
    numeric_origin=dict(origin, templateStrId=None, templateIntId=202)
    add('runtime/numeric-parent', bound_config, dict(bound_record, origin_observations=[numeric_origin]))
    for field, values in dict(_boundCreateRecord=[None, False, 1], buffUid=['8', 7], sourceActorId=['22', '01'],
                              targetActorId=['11', str(2**64)], buffTemplate=['wrong'], environmentType=['Skill'],
                              templateStrId=['wrong'], templateIntId=[True, 1.0], actionId=[3.0, True, 4], triggerType=[1, None]).items():
        for value in values:
            add('runtime/' + field + '/' + str(value), bound_config, dict(bound_record, origin_observations=[dict(origin, **{field:value})]))
    for field, values in dict(decoder=[{}, dict(binding['decoder'], extra=1)], sourceRootSha256=['', 'A'*64, 'a'*63],
                              parent_kind=['Skill'], create_actions=[[]], recipient=['self']).items():
        for value in values:
            changed=copy.deepcopy(bound_config); changed['registry']['verified_effects']['approved_parent']['runtime_bindings'][0][field]=value
            add('runtime/binding/' + field + '/' + str(len(cases)), changed, bound_record)

    def keyword_case(visual=False, antal=False):
        parent='buff_chr_0023_antal_tageffect' if antal else 'buff_parent'
        approved='buff_chr_0023_antal_normal_fragile' if antal else ('buff_visual' if visual else 'approved_parent')
        action=dict(serverActionIndex=3, isEnable=True, **{'$type':'Beyond.Gameplay.Core.VulnerableAction.Data'},
                    subType='Fire', rate=dict(useBlackboardKey=True, blackboardKey='rate'), overrideChildBuffId=False)
        parent_root=dict(empty_root, actions=[action])
        main_root=dict(blackboard=[dict(key='child_buff_id', isDynamic=False, valueStr='buff_visual')],
            actions=[dict(serverActionIndex=4, isEnable=True, **{'$type':'Beyond.Gameplay.Core.CreateBuffAction.Data'},
                          buffs=[dict(readIdFromBlackboard=True, buffIdKey='child_buff_id', assignBlackboard=True,
                                      assignItems=[dict(targetKey=k, useDirectValue=False, inputValueKey=k) for k in ('rate','duration')])])])
        spec=dict(zone='fragile', element='fire', bb_key='rate')
        approved_entry=dict(effects=[spec], guard=dict(source_character_key=source), aliases=[] if visual else [parent])
        cfg=dict(registry=dict(verified_effects={approved:approved_entry}, _keyword_buff_map=dict(Vulnerable=dict(Fire='buff_test'))),
                 roots={parent:parent_root, 'buff_test':main_root, 'buff_visual':copy.deepcopy(empty_root)}, numbers={'202':parent})
        rec=dict(bound_record, origin_observations=[dict(origin, templateStrId=parent)])
        return cfg, rec, approved, parent

    for visual, antal in ((False, False), (True, False), (False, True)):
        cfg, rec, approved, parent=keyword_case(visual, antal)
        label=f'keyword/{visual}/{antal}'
        add(label+'/valid', cfg, rec)
        add(label+'/updated', cfg, dict(rec, keyword_rate_snapshots=[dict(status='observed')]))
        add(label+'/numeric-parent', cfg, dict(rec, origin_observations=[dict(rec['origin_observations'][0], templateStrId=None, templateIntId=202)]))
        for field, values in dict(_boundCreateRecord=[None, False, 1], buffUid=['0', 7], sourceActorId=['22'], targetActorId=['11'],
                                  environmentType=['Skill'], ownerType=['2', True], environmentInstId=['4294967295', '0', str(2**64)],
                                  templateStrId=['wrong'], templateIntId=[True, -1], actionId=[3.0, True, -1], buffTemplate=['wrong']).items():
            for value in values:
                add(label+'/'+field+'/'+str(value), cfg, dict(rec, origin_observations=[dict(rec['origin_observations'][0], **{field:value})]))
        for field, value in [('isEnable', False), ('isEnable', 1), ('serverActionIndex', 3.0), ('subType','Other'), ('rate',dict(useBlackboardKey=False, value=0.2)), ('rate',dict(useBlackboardKey=True, blackboardKey='other'))]:
            changed=copy.deepcopy(cfg); changed['roots'][parent]['actions'][0][field]=value
            add(label+'/action/'+field+'/'+str(len(cases)), changed, rec)
        changed=copy.deepcopy(cfg); changed['roots'][parent]['actions'].append(copy.deepcopy(changed['roots'][parent]['actions'][0]))
        add(label+'/duplicate-action', changed, rec)
        changed=copy.deepcopy(cfg); changed['roots'][parent]=dict(serverActionIndex=5, isEnable=False, child=changed['roots'][parent])
        add(label+'/disabled-ancestor', changed, rec)
        changed=copy.deepcopy(cfg); changed['registry']['verified_effects'][approved]['guard']['source_character_key']='foreign'
        for guarded in (True, False): add(label+'/guard/'+str(guarded), changed, rec, guarded)
        if visual:
            for path, value in [(['blackboard',0,'isDynamic'],True), (['actions',0,'isEnable'],False),
                                (['actions',0,'buffs',0,'assignBlackboard'],False),
                                (['actions',0,'buffs',0,'assignItems',0,'inputValueKey'],'wrong')]:
                changed=copy.deepcopy(cfg); target=changed['roots']['buff_test']
                for key in path[:-1]: target=target[key]
                target[path[-1]]=value
                add(label+'/forward/'+str(len(cases)), changed, rec)

    rng=random.Random(8126)
    for index in range(80):
        guard=rng.choice(guards)
        changes={}
        for _ in range(rng.randrange(1, 5)): changes.update(rng.choice(mutations)[0])
        add('random/'+str(index), dict(config, registry=dict(verified_effects={'buff_test':dict(entry, guard=guard)})), dict(record, **changes), rng.choice([True,False]))

    mapping={kind:{subtype:'buff_'+kind+'_'+subtype for subtype in ('All','Spell','Physical','Natural','Fire','Crystal','Pulse')}
             for kind in ('Vulnerable','Enhanced')}
    keyword=dict(schemaVersion=1,source='current_native_keyword_switch_and_metadata_literals',decoder=packet._CURRENT_KEYWORD_BINDING,mapping=mapping)
    add('registry/valid',dict(registry=config['registry'],keyword=keyword),{},kind='registry')
    for field, values in dict(schemaVersion=[True, 1.0, None, 2],source=['other',None],
                              decoder=[None,{},dict(keyword['decoder'],extra=1)], mapping=[None,{},dict(mapping,Other={}),dict(mapping,Vulnerable={'Fire':'buff_test'})]).items():
        for value in values:
            add('registry/'+field+'/'+str(len(cases)),dict(registry=config['registry'],keyword=dict(keyword,**{field:value})),{},kind='registry')
    for value in (None, {}, [], 0, ''):
        add('registry/root/'+str(len(cases)),dict(registry=value,keyword=keyword),{},kind='registry')

    if args.bundled:
        for relative in ('_internal/data/runtime-data.zip','_internal/data/packet_semantics/rdps_semantics_registry.json'):
            digest=hashlib.sha256((args.reference/relative).read_bytes()).hexdigest()
            if metadata['files'][relative]['sha256'] != digest: raise ValueError('Fixed resource changed: '+relative)
            dependencies[relative]=digest
        registry=json.loads((args.reference/'_internal/data/packet_semantics/rdps_semantics_registry.json').read_text(encoding='utf8'))
        with zipfile.ZipFile(args.reference / '_internal/data/runtime-data.zip') as archive:
            roots_payload=json.loads(gzip.decompress(archive.read('data/local_static/buff/typed_roots.json.gz')))
            keyword=json.loads(archive.read('data/local_static/buff/keyword_buff_map.json'))
        add('bundled/registry',dict(registry=registry,keyword=keyword),{},kind='registry')
        registry['_keyword_buff_map']=keyword['mapping']
        bundled_roots={key:row['root'] for key,row in roots_payload['entries'].items()}
        # Each actual approval is tested in isolation; unrelated main aliases cannot conceal a missing projection.
        for key, value in registry['verified_effects'].items():
            if not isinstance(value,dict): continue
            isolated=dict(registry, verified_effects={key:value}, verified_prefixes=[])
            identities=[key, *(value.get('aliases') or []), *(str(item) for item in value.get('numeric_ids') or [])]
            for identity in identities:
                for guarded in (False,True):
                    add('bundled/'+key+'/'+identity+'/'+str(guarded), dict(registry=isolated, roots={k:v for k,v in bundled_roots.items() if k in identities}),
                        dict(record,event_key=identity,raw_event_key=identity),guarded)
        for parent, parent_root in bundled_roots.items():
            for action_id, nodes in approval.indexed_root_actions(parent_root,{})[1].items():
                for action, enabled in nodes:
                    kind={'Beyond.Gameplay.Core.VulnerableAction.Data':'Vulnerable','Beyond.Gameplay.Core.EnhancedAction.Data':'Enhanced'}.get(action.get('$type'))
                    if kind is None: continue
                    main=registry['_keyword_buff_map'].get(kind,{}).get(action.get('subType'))
                    if not main: continue
                    main_root=bundled_roots.get(main,{})
                    if action.get('overrideChildBuffId') is True:
                        visual=(action.get('childBuffId') or {}).get('value')
                    else:
                        visual=next((row.get('valueStr') for row in main_root.get('blackboard',[]) if row.get('key')=='child_buff_id'),None)
                    keys=[key for key,entry in registry['verified_effects'].items() if isinstance(entry,dict)
                          and (key in (parent,visual) or parent in (entry.get('aliases') or []))]
                    for key in keys:
                        entry=registry['verified_effects'][key]
                        guard=entry.get('guard') or {}
                        matched=re.search(r'chr_\d+_[a-z]+',parent)
                        source=guard.get('source_character_key') or guard.get('source_character_id') or guard.get('character_id') or (matched.group() if matched else actor)
                        rec=dict(record,event_key=main,raw_event_key=main,source_character_key=source,
                                 target_character_key=source if guard.get('recipient')=='self' else 'chr_0002_beta',
                                 source_skill_key=guard.get('source_skill_key','skill_test'),
                                 source_skill_family_key=guard.get('source_skill_family_key','family_test'))
                        if guard.get('target_kind')=='enemy': rec.update(target_character_key=None,target_enemy_key='eny_0001_test')
                        if guard.get('recipient')=='self': rec['target_actor_id']=rec['source_actor_id']
                        if guard.get('weapon_id'): rec.update(source_weapon_template=guard['weapon_id'],packet_mapping=dict(weapon_id=guard['weapon_id']))
                        if guard.get('suit_id'): rec['packet_mapping']=dict(suit_id=guard['suit_id'])
                        rec['origin_observations']=[dict(origin,buffTemplate=main,sourceActorId=rec['source_actor_id'],
                            targetActorId=rec['target_actor_id'],templateStrId=parent,actionId=action_id)]
                        cfg=dict(registry=dict(registry,verified_effects={key:entry},verified_prefixes=[]),
                                 roots={name:bundled_roots[name] for name in (parent,main,visual) if name in bundled_roots})
                        label=f'bundled-keyword/{parent}/{action_id}/{key}'
                        for guarded in (False,True): add(label+'/'+str(guarded),cfg,rec,guarded)
                        add(label+'/foreign-source',cfg,dict(rec,source_character_key='foreign'))

    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(cases,ensure_ascii=True,separators=(',',':')),encoding='utf8')
    args.output.with_suffix('.reference.json').write_text(json.dumps(dict(cases=len(cases),source_head=metadata['head'],dependencies=dependencies),indent=2),encoding='utf8')
    print('Effect approval fixtures:',len(cases))


if __name__ == '__main__': main()
