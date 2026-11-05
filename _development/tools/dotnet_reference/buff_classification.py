"""Verify BUFF display classification and loadout filters against the fixed Python source."""
import argparse
import copy
import hashlib
import importlib
import itertools
import json
from pathlib import Path
import struct
import sys
import tempfile
from types import ModuleType
import zipfile


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference',type=Path,required=True)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--bundled',action='store_true')
    args=parser.parse_args()
    if args.bundled and args.output is None: parser.error('--bundled requires an explicit local output')
    output=args.output or Path(__file__).resolve().parents[3]/'_internal/dotnet/Specs/Fixtures/buff-classification.json'
    metadata=json.loads(args.manifest.read_text(encoding='utf8'))
    dependencies={}
    def pinned(relative):
        data=(args.reference/relative).read_bytes()
        digest=hashlib.sha256(data).hexdigest()
        if digest!=metadata['files'][relative]['sha256']: raise ValueError('Fixed classification reference changed: '+relative)
        dependencies[relative]=digest
        return data
    prefix='_internal/packages/parser_core/parser_core/'
    for relative in metadata['files']:
        if relative.startswith(prefix) and relative.endswith('.py'): pinned(relative)
    package=ModuleType('parser_core'); package.__path__=[str(args.reference/prefix)]; sys.modules['parser_core']=package
    classification=importlib.import_module('parser_core.effects.classification')
    mapping=importlib.import_module('parser_core.effects.packet_mapping')
    packet=importlib.import_module('parser_core.catalog.packet_semantics')
    templates=importlib.import_module('parser_core.catalog.buff_templates')
    shared=dict(mappings={},mechanisms={},numbers={},semantics={},classifier={},skills={},suits={})
    current={}
    mapping._load_packet_numeric_buff_map=lambda: current['mappings']
    mapping._load_num_id_str_buff_map=lambda: current['numbers']
    mapping._load_mechanism_registry_by_buff_id=lambda: current['mechanisms']
    def canonical():
        groups={}
        for row in current['mappings'].values():
            if row.get('canonical_buff_id'): groups.setdefault(str(row['canonical_buff_id']),[]).append(row)
        return {key:packet._merge_packet_buff_mapping_rows(rows) for key,rows in groups.items()}
    mapping._load_packet_canonical_buff_map=canonical
    classification._load_local_buff_semantic_entries=lambda: current['semantics']
    classification._buff_classifier_hint=lambda key: current['classifier'].get(key)
    templates._load_local_buff_semantic_entries=classification._load_local_buff_semantic_entries
    templates._load_local_skill_semantic_entries=lambda: current['skills']
    cases=[]
    def encode(value):
        if type(value) is int: return {'int':str(value)}
        if type(value) is float: return {'f64':struct.pack('>d',value).hex()}
        if isinstance(value,(list,tuple)): return [encode(item) for item in value]
        if isinstance(value,dict): return {str(key):encode(item) for key,item in value.items()}
        return value
    with tempfile.TemporaryDirectory() as folder:
        root=Path(folder)
        suit_roots={}
        def add(label,record=None,active_suits=None,active_weapons=None,**resources):
            config=dict(record=record or {},active_suits=active_suits,active_weapons=active_weapons,**resources)
            current.clear(); current.update(shared); current.update(resources)
            name=str(len(cases)) if 'suits' in resources else 'shared'
            if name not in suit_roots:
                path=root/name/'data/local_tables/equip/items'; path.mkdir(parents=True)
                for key,payload in current['suits'].items():
                    (path/key).write_text(json.dumps(payload),encoding='utf8')
                suit_roots[name]=root/name
            templates._repo_root=lambda:suit_roots[name]
            templates._buff_child_family_ids.cache_clear(); templates._load_equip_suit_allowed_buffs.cache_clear()
            record=copy.deepcopy(config['record']); before=encode(config)
            key=str(record.get('event_key') or '')
            source=record.get('source_character_key')
            operations=dict(noise=lambda:classification._is_noise_buff(key),
                ignore_rate=lambda:classification._should_ignore_rate_buff(key),
                ignore_record=lambda:classification._should_ignore_record_rate_effects(record),
                packet_wrapper=lambda:classification._is_packet_effectless_wrapper(record),
                internal=lambda:classification._is_internal_trigger_damage_record(record),
                wrapper=lambda:classification._is_effectless_wrapper_record(record),
                suit=lambda:classification._equip_buff_matches_active_suits(key,source,active_suits),
                weapon=lambda:classification._weapon_buff_matches_active_weapon(key,source,active_weapons),
                allowed=lambda:{key:sorted(value) for key,value in templates._load_equip_suit_allowed_buffs().items()})
            result={}
            for field,operation in operations.items():
                try: result[field]=operation()
                except (TypeError,ValueError,OverflowError,AttributeError) as error: result[field]=dict(error=type(error).__name__)
            if encode(config)!=before or encode(record)!=encode(config['record']): raise AssertionError('Classification changed source evidence')
            cases.append(dict(name=f'{label}/{len(cases)}',config_json=json.dumps(config,ensure_ascii=True),expected=encode(result)))

        if args.bundled:
            archive='_internal/data/runtime-data.zip'; pinned(archive)
            with zipfile.ZipFile(args.reference/archive) as bundle:
                def resource(relative):
                    direct='_internal/'+relative
                    return json.loads(pinned(direct)) if direct in metadata['files'] else json.loads(bundle.read(relative))
                shared['mappings']=resource('data/packet_semantics/buff_numeric_map.json')['mappings']
                shared['mechanisms']=resource('data/packet_semantics/mechanism_registry.json')['by_buff_id']
                shared['semantics']=resource('data/local_semantics/buff/details.json')['entries']
                shared['skills']=resource('data/local_semantics/skill/details.json')['entries']
                shared['classifier']=resource('data/local_semantics/classifier_hints.json')['buffHints']
                for name in bundle.namelist():
                    if name.startswith('data/local_tables/equip/items/suit_') and name.endswith('.json'):
                        shared['suits'][Path(name).name]=json.loads(bundle.read(name))
            for key in sorted(shared['semantics'].keys() | shared['classifier'].keys() | shared['mappings'].keys()):
                add('bundled',dict(event_key=key,source_character_key='chr_test'))
            for suit in shared['suits'].values():
                for key in ['buff_equipsuit_atk_02','buff_equipsuit_usp_02_AddAttack','buff_equipsuit_missing']:
                    add('bundled-suit',dict(event_key=key,source_character_key='chr_test'),active_suits={'chr_test':[suit['suitID']]})
        else:
            for key in ['buff_common_vfx_test','buff_common_dash','buff_common_normal_skill_fx_a','buff_common_combo_attack_fx_a',
                'buff_common_full_immune_weak_a','buff_chr_0011_seraph_mainchr_heal','buff_chr_0023_antal_ultimate_icon',
                'buff_chr_0023_antal_ultimate_icon_2','buff_common_obtain_ultimate_sp','buff_common_dash_behit_listener',
                'buff_common_poise_break_damage_taken_scale','buff_equipsuit_atk_02_aruadetect','buff_equipsuit_usp_02',
                'BUFF_EQUIPSUIT_COMBO_CD01','prefix_buff_common_affixes_slow_suffix','buff_chr_0023_antal_utimate_skill',
                'buff_common_affixes_shelter_default_child','buff_common_affixes_vulnerable_spell','buff_common_try_fire_triggered_wrapper',
                'buff_common_fire_pulse_corrupt_triggered','buff_common_try_cryst_fire_triggered','buff_common_natural_fire_triggered_wrapper','buff']:
                add('name-classification',dict(event_key=key))
            for role,effects,dynamic,attrs in itertools.product(['effect','Effect','wrapper','MARKER','utility','unknown',''],[None,[],[{}]],[None,[],[{}]],[None,[],[{}]]):
                add('packet-role',dict(event_key='buff',packet_mapping=dict(role=role,effects=effects,dynamic_effects=dynamic),attr_mods=attrs))
            for key,owner,source,omitted in itertools.product(['123','１２３','abc'],['eny_test','chr_test',None],['chr_test','eny_test',None],[None,'consumed_layer']):
                bb=dict(phy_dmg_up=.2,final_phy_dmg_up=.3,shatter_dmg=2,consumed_layer=1)
                if omitted: bb.pop(omitted)
                add('trigger-helper',dict(event_key='buff',raw_event_key=key,owner_raw=owner,raw_source=source,bb_values=bb,attr_mods=[{}]))
            for classification_name,flags,children in itertools.product(['wrapper','marker_or_utility','effect',''],[None,{},dict(hasDynamicBlackboard=True)],
                    [[],['buff_other'],['buff_common_vfx_test'],['buff_common_vfx_test','buff_other']]):
                hint=dict(classification=classification_name,semanticFlags=flags,createdBuffIds=children)
                for action in [[],['VulnerableAction'],['OnSpellAbnormalStartFinish']]:
                    add('classifier-hint',dict(event_key='buff'),classifier={'buff':hint},semantics={'buff':dict(actionTypes=action,referencedBuffIds=children)})
            for value in [None,False,True,-1,0,1,1.9,'2','bad',[],{},float('nan'),float('inf'),10**400]:
                add('resolved-count',dict(event_key='buff'),classifier={'buff':dict(classification='wrapper',resolvedEffectCount=value,createdBuffIds=['buff_other'])})
            skills={'passive':dict(createdBuffIds=['buff_equipsuit_root','buff_unrelated'],binaryReferencedBuffIds=['buff_equipsuit_binary'])}
            buffs={'buff_equipsuit_root':dict(referencedBuffIds=['buff_equipsuit_child']),
                'buff_equipsuit_child':dict(binaryCreatedBuffIds=['buff_equipsuit_root','buff_nonsuit_child'])}
            suits={'suit_a.json':dict(suitID='suit_a',passiveSkillId='passive'),'suit_empty.json':dict(suitID='suit_empty',passiveSkillId='missing')}
            for key,source,active in itertools.product(['buff_equipsuit_root','buff_equipsuit_child','buff_equipsuit_binary','buff_equipsuit_unknown','buff_nonsuit_child'],
                    ['chr_test','chr_other',None],[None,{},dict(chr_test=[]),dict(chr_test=['suit_a']),dict(chr_test=['suit_empty']),dict(chr_test=['suit_a','suit_empty'])]):
                add('suit-loadout',dict(event_key=key,source_character_key=source),active_suits=active,skills=skills,semantics=buffs,suits=suits)
            for key,source,active in itertools.product(['buff_wpn_sword_0012_atkup','buff_wpn_sword_0013_team','buff_other','BUFF_WPN_SWORD_0012_ATKUP'],
                    ['chr_test','chr_other',None],[None,{},dict(chr_test=''),dict(chr_test='wpn_sword_0012'),dict(chr_test='wpn_sword_0013')]):
                add('weapon-loadout',dict(event_key=key,source_character_key=source),active_weapons=active)
            add('weapon-explicit',dict(event_key='buff_wpn_sword_0012_atkup',source_character_key='chr_test'),
                active_weapons=dict(chr_test='wpn_other'),mappings={'buff_wpn_sword_0012_atkup':dict(weapon_id='wpn_other')})
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(dict(resources_json=json.dumps(shared,ensure_ascii=True),cases=cases),ensure_ascii=True,separators=(',',':')),encoding='utf8')
        output.with_suffix('.reference.json').write_text(json.dumps(dict(source_head=metadata['head'],cases=len(cases),dependencies=dependencies),indent=2),encoding='utf8')
        print('BUFF classification fixtures:',len(cases))


if __name__=='__main__': main()
