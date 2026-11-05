"""Compare complete ordinary/combo window assembly with the immutable Python reference."""
import argparse
import ast
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
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference',type=Path,required=True)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--bundled',action='store_true')
    args=parser.parse_args()
    if args.bundled and args.output is None: parser.error('--bundled requires an explicit local output')
    output=args.output or Path(__file__).resolve().parents[3]/'_internal/dotnet/Specs/Fixtures/report-effect-windows.json'
    metadata=json.loads(args.manifest.read_text(encoding='utf8'))
    dependencies={}
    def pinned(relative):
        data=(args.reference/relative).read_bytes()
        digest=hashlib.sha256(data).hexdigest()
        if digest!=metadata['files'][relative]['sha256']: raise ValueError('Fixed report window reference changed: '+relative)
        dependencies[relative]=digest
        return data
    prefix='_internal/packages/parser_core/parser_core/'
    for relative in metadata['files']:
        if relative.startswith(prefix) and relative.endswith('.py'): pinned(relative)
    package=ModuleType('parser_core'); package.__path__=[str(args.reference/prefix)]; sys.modules['parser_core']=package
    report=importlib.import_module('parser_core.reporting.effect_windows')
    templates=importlib.import_module('parser_core.catalog.buff_templates')
    mapping=importlib.import_module('parser_core.effects.packet_mapping')
    packet=importlib.import_module('parser_core.catalog.packet_semantics')
    approval=importlib.import_module('parser_core.effects.approval')
    semantic=importlib.import_module('parser_core.effects.semantic_conditions')
    conditions=importlib.import_module('parser_core.effects.conditions')
    specifications=importlib.import_module('parser_core.effects.specifications')
    classification=importlib.import_module('parser_core.effects.classification')
    enhanced=importlib.import_module('parser_core.effects.typed_actions')
    stacking=importlib.import_module('parser_core.effects.stacking_rules')
    lifecycle=importlib.import_module('parser_core.effects.lifecycle')
    windows=importlib.import_module('parser_core.effects.windows')
    imbue=importlib.import_module('parser_core.effects.imbue')
    registry_rules=importlib.import_module('parser_core.effects.registry')
    current={}
    for module in [report,templates,approval,semantic,conditions,specifications,stacking,lifecycle,windows,imbue,registry_rules]:
        module._load_current_buff_roots=lambda:current['roots']
    for module in [templates,classification,enhanced,stacking,windows]:
        module._load_local_buff_semantic_entries=lambda:current['semantics']
    for module in [templates,classification,windows]:
        module._buff_classifier_hint=lambda key:current['classifier'].get(key)
    classification._load_equip_suit_allowed_buffs=lambda:{key:set(value) for key,value in current['suit_buffs'].items()}
    stacking._load_weapon_buff_stack_limits=lambda:current['weapon_limits']
    semantic._load_damage_zone_config=lambda:current['zones']
    approval._load_rdps_semantics_registry=lambda:current['registry']
    approval._load_num_id_str_buff_map=lambda:current['numbers']
    approval._load_num_id_str_skill_map=lambda:current['skills']
    imbue._load_num_id_str_buff_map=approval._load_num_id_str_buff_map
    mapping._load_num_id_str_buff_map=approval._load_num_id_str_buff_map
    mapping._load_packet_numeric_buff_map=lambda:current['mappings']
    mapping._load_mechanism_registry_by_buff_id=lambda:current['mechanisms']
    def canonical():
        groups={}
        for row in current['mappings'].values():
            if row.get('canonical_buff_id'): groups.setdefault(str(row['canonical_buff_id']),[]).append(row)
        return {key:packet._merge_packet_buff_mapping_rows(rows) for key,rows in groups.items()}
    mapping._load_packet_canonical_buff_map=canonical
    archive='_internal/data/runtime-data.zip'; pinned(archive)
    with zipfile.ZipFile(args.reference/archive) as bundle:
        typed=json.loads(gzip.decompress(bundle.read('data/local_static/buff/typed_roots.json.gz')))['entries']
    trigger='buff_common_affixes_combo_trigger'; middle='buff_common_affixes_skillimbue'; modifier='buff_common_affixes_skillimbue_atk'
    combo_roots={key:typed[key]['root'] for key in [trigger,middle,modifier]}
    registry=json.loads(pinned('_internal/data/packet_semantics/rdps_semantics_registry.json'))
    relative='_internal/packages/parser_core/tests/mechanics/test_rdps_combo_packet_chain.py'
    tree=ast.parse(pinned(relative).decode('utf8'))
    helpers=ast.Module(body=[node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name in {'combo_chain','combo_hit'}],type_ignores=[])
    scope=dict(TRIGGER=trigger,IMBUE=middle,MODIFIER=modifier,SESSION='synthetic-combo-session')
    exec(compile(helpers,relative,'exec'),scope)
    empty_condition=dict(onlyExecuteWhenSourceIsMainChar=False,onlyExecuteWhenSourceIsGuard=False,actionData=[])
    processor={'$type':'Beyond.Gameplay.Core.DamageScaleProcessor','side':'Attacker','zoneName':'NormalCalcZone',
        'addition':dict(useBlackboardKey=True,blackboardKey='rate')}
    root=dict(lifeType='Infinity',stackingSettings=dict(stackingType='Unlimited'),damageModifier=[dict(enableSide='Attacker',
        condition=empty_condition,damageProcessors=[processor])],attributeModifier=dict(isConvertedAttribute=False,attributeModifiers=[]))
    base_roots={key:copy.deepcopy(root) for key in ['buff','buff_other','buff_equipsuit_a','buff_wpn_sword_0012_valid']}
    base_roots.update(combo_roots)
    base_roots['buff_dynamic']=dict(lifeType='Infinity',damageModifier=[])
    shared=dict(roots=base_roots,zones=dict(NormalCalcZone={},ProdCalcZone={}),registry=copy.deepcopy(registry),numbers={},skills={},
        mappings={},mechanisms={},semantics={},classifier={},details={},suit_buffs=dict(suit_a=['buff_equipsuit_a']),weapon_limits={})
    shared['registry']['verified_effects'].update(buff=dict(effects=[dict(zone='dmg_inc',element='all',bb_key='rate')]),
        buff_dynamic=dict(dynamic=True,dynamic_effects=[dict(zone='amp',element='all',base_bb_key='base')]))
    def record(**changes):
        row=dict(uid='7',ts_ms=1000,line_no=10,event_key='buff',raw_event_key='buff',source_character_key='chr_source',
            source_character_name='提供者',target_character_key='chr_target',target_character_name='接收者',target_enemy_key=None,target_enemy_name=None,
            source_actor_id='11',target_actor_id='22',owner_raw='chr_target',raw_source='chr_source',
            lifetime_mode='Infinity',lifetime_source='typed_current_BuffData',bb_values=dict(rate=.2),bb_keys=['rate'],attr_mods=[],
            enable_observations=[])
        row.update(changes); return row
    def complete(row):
        return record(**row)
    cases=[]
    def encode(value):
        if type(value) is int:return {'int':str(value)}
        if type(value) is float:return {'f64':struct.pack('>d',value).hex()}
        if isinstance(value,(list,tuple)):return [encode(item) for item in value]
        if isinstance(value,dict):return {str(key):encode(item) for key,item in value.items()}
        return value
    with tempfile.TemporaryDirectory() as folder:
        resource_root=Path(folder)
        templates._repo_root=lambda:resource_root
        def add(label,records=None,hits=None,last=2000,arts=None,suits=None,weapons=None,**resources):
            config=dict(records=[record()] if records is None else records,hits=[] if hits is None else hits,last_hit_ms=last,
                arts={} if arts is None else arts,active_suits={} if suits is None else suits,active_weapons={} if weapons is None else weapons,**resources)
            current.clear(); current.update(shared); current.update(resources)
            before=encode(config)
            packet._RDPS_VERIFIED_INDEX=None
            conditions._decoded_damage_modifier_condition_rows.cache_clear()
            enhanced._enhanced_action_child_effect_specs.cache_clear()
            isolated=SimpleNamespace(buff_starts=copy.deepcopy(config['records']),hits=copy.deepcopy(config['hits']),
                active_suits_by_char={key:set(value) for key,value in config['active_suits'].items()},
                active_weapons_by_char=config['active_weapons'],buff_root_action_indices={})
            try:
                result=report.prepare_effect_windows(isolated,config['arts'],last)
                expected=dict(records=isolated.buff_starts,hits=isolated.hits,windows=result)
            except (TypeError,ValueError,OverflowError,AttributeError,KeyError) as error:
                expected=dict(error=type(error).__name__)
            if encode(config)!=before:raise AssertionError('Reference window assembly mutated fixture configuration')
            cases.append(dict(name=f'{label}/{len(cases)}',config_json=json.dumps(config,ensure_ascii=True),expected=encode(expected)))
        if args.bundled:
            with zipfile.ZipFile(args.reference/archive) as bundle:
                def resource(path):
                    direct='_internal/'+path
                    return json.loads(pinned(direct)) if direct in metadata['files'] else json.loads(bundle.read(path))
                shared['semantics']=resource('data/local_semantics/buff/details.json')['entries']
                shared['classifier']=resource('data/local_semantics/classifier_hints.json')['buffHints']
                shared['mappings']=resource('data/packet_semantics/buff_numeric_map.json')['mappings']
                shared['mechanisms']=resource('data/packet_semantics/mechanism_registry.json')['by_buff_id']
                for name in bundle.namelist():
                    if name.startswith('data/akedata/buff/items/') and name.endswith('.json'):
                        content=bundle.read(name)
                        shared['details'][Path(name).stem]=json.loads(content)
                        path=resource_root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(content)
                zone_path=resource_root/'data/local_static/damage_zone_config.json';zone_path.parent.mkdir(parents=True)
                zone_path.write_bytes(bundle.read('data/local_static/damage_zone_config.json'))
                templates._load_damage_zone_config.cache_clear();shared['zones']=templates._load_damage_zone_config()
            for key,item in typed.items():
                observed=set()
                def walk(node):
                    if isinstance(node,dict):
                        if node.get('useBlackboardKey') is True and isinstance(node.get('blackboardKey'),str):observed.add(node['blackboardKey'])
                        for value in node.values():walk(value)
                    elif isinstance(node,list):
                        for value in node:walk(value)
                walk(item['root'])
                for enemy in [False,True]:
                    add('bundled',records=[record(event_key=key,raw_event_key=key,bb_keys=sorted(observed),bb_values={key:.2 for key in observed},
                        target_character_key=None if enemy else 'chr_target',target_enemy_key='enemy' if enemy else None,
                        target_character_name=None if enemy else '接收者',target_enemy_name='敌人' if enemy else None)],roots={key:item['root']})
        else:
            add('ordinary');add('empty',records=[])
            for end,raw,boundary,last in itertools.product([None,900,1000,1500,3000],[None,-1,0,200,3000],[None,900,1000,1200,1800],[900,1000,2000]):
                add('lifetime',records=[record(end_ts_ms=end,end_line_no=30,raw_duration_ms=raw,snapshot_end_ts_ms=boundary,snapshot_end_line_no=20)],last=last)
            for life,mode in itertools.product(['Infinity','Duration',None],['Infinity','Duration',None]):
                changed=copy.deepcopy(root);changed['lifeType']=life
                add('lifetime-source',records=[record(lifetime_mode=mode)],roots={'buff':changed})
            for setting in [None,{},dict(stackingType='Unlimited'),dict(stackingType='HighPriority'),
                dict(stackingType='HighPriorityWithMaxStack',maxStackCnt=2),dict(stackingType='Unique',useMaxStackCntKey=False,maxStackCnt=0),
                dict(stackingType='Unique',useMaxStackCntKey=True,maxStackCntKey='layers'),dict(stackingType='Unlimited',maxStackCnt=2)]:
                for layers in [None,0,1,3]:
                    changed=copy.deepcopy(root);changed['stackingSettings']=setting
                    add('native-stacking',records=[record(bb_values=dict(rate=.2,layers=layers,max_stack=7),packet_mapping=dict(stack_limit=8))],roots={'buff':changed})
            for rate,key,target in itertools.product([None,False,-1,0,.2,'0.2',float('inf')],['buff','missing'],['player','enemy']):
                add('effect-evidence',records=[record(event_key=key,bb_values=dict(rate=rate),target_character_key='chr_target' if target=='player' else None,
                    target_character_name='接收者' if target=='player' else None,target_enemy_key='enemy' if target=='enemy' else None,target_enemy_name='敌人' if target=='enemy' else None)])
            for field,value in [('uid_observation_only',True),('rdps_live_identity_conflict',True),('rdps_conflicting_enable_state',True),
                ('rdps_unresolved_semantic_condition',['old']),('rdps_unresolved_dynamic_effect',True),('snapshot_update',True)]:
                add('quality-'+field,records=[record(**{field:value})])
            for observations in [[],[dict(ts_ms=1000,line_no=10,is_enable=False)],
                [dict(ts_ms=1000,line_no=10,is_enable=False),dict(ts_ms=1200,line_no=15,is_enable=True)]]:
                add('enable-timeline',records=[record(enable_observations=observations)])
            for other in [record(),record(uid='8'),record(line_no=11),record(end_ts_ms=1700),record(uid=''),record(event_key='buff_other'),
                record(enable_observations=[dict(ts_ms=1000,line_no=10,is_enable=True)])]:
                add('deduplicate',records=[record(),other])
            add('order',records=[record(ts_ms=1200,event_key='buff_other'),record(event_key='buff_other'),record(),record(ts_ms=900)])
            for key,active in itertools.product(['buff_equipsuit_a','buff_wpn_sword_0012_valid'],[{},dict(chr_source=[]),dict(chr_source=['suit_a']),dict(other=['suit_a'])]):
                for weapons in [{},dict(chr_source='wpn_sword_0012'),dict(chr_source='wpn_sword_0013')]:
                    add('loadout-filter',records=[record(event_key=key)],suits=active,weapons=weapons)
            for value in [0.,20.,100.5]:add('static-arts',arts=dict(chr_source=value))
            for bb in [{},dict(base=.3),dict(base=0),dict(base=-1),dict(base=.3,tick=.02)]:
                add('dynamic-only',records=[record(event_key='buff_dynamic',bb_values=bb)])
                add('dynamic-matching-identity',records=[record(event_key='buff_dynamic',raw_event_key='buff_dynamic',bb_keys=list(bb),bb_values=bb)])
            for mask,rate in itertools.product([0x100,0x200,0x300,0,None],[.1,.2,.5]):
                chain=[complete(row) for row in scope['combo_chain'](rate=rate)]
                add('combined-combo',records=[record(),*chain],hits=[scope['combo_hit'](mask=mask)])
            add('combo-neighbour',records=[complete(row) for row in scope['combo_chain']()],hits=[scope['combo_hit'](),dict(scope['combo_hit'](),line_no=201)])
            add('combo-missing-origin',records=[record(),*[complete(row) for row in scope['combo_chain']()][1:]],hits=[scope['combo_hit']()])
            add('missing-required',records=[dict(event_key='buff',ts_ms=1000,bb_values=dict(rate=.2))])
            short_circuit=record();del short_circuit['target_enemy_name']
            add('target-name-short-circuit',records=[short_circuit])
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(dict(resources_json=json.dumps(shared,ensure_ascii=True),cases=cases),ensure_ascii=True,separators=(',',':')),encoding='utf8')
        output.with_suffix('.reference.json').write_text(json.dumps(dict(source_head=metadata['head'],cases=len(cases),dependencies=dependencies),indent=2),encoding='utf8')
        print('Report effect window fixtures:',len(cases))


if __name__=='__main__':main()
