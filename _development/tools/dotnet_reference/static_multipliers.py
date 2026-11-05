"""Freeze full equipment/weapon/suit static multiplier derivation from the immutable reference."""
import argparse
import ast
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


def canonical(value):
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int):
        return {'int': str(value)}
    if isinstance(value, float):
        return {'f64': struct.pack('>d', value).hex()}
    if isinstance(value, dict):
        return {str(key): canonical(item) for key, item in value.items()}
    return [canonical(item) for item in value]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference',type=Path,required=True)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--bundled',action='store_true')
    args=parser.parse_args()
    if args.bundled and args.output is None: parser.error('--bundled requires an explicit local output')
    output=args.output or Path(__file__).resolve().parents[3]/'_internal/dotnet/Specs/Fixtures/static-multipliers.json'
    metadata=json.loads(args.manifest.read_text(encoding='utf8'));dependencies={}
    def pinned(relative):
        data=(args.reference/relative).read_bytes();digest=hashlib.sha256(data).hexdigest()
        if digest!=metadata['files'][relative]['sha256']: raise ValueError('Fixed multiplier reference changed: '+relative)
        dependencies[relative]=digest
        return data
    prefix='_internal/packages/parser_core/parser_core/'
    for relative in metadata['files']:
        if relative.startswith(prefix) and relative.endswith('.py'):pinned(relative)
    package=ModuleType('parser_core');package.__path__=[str(args.reference/prefix)];sys.modules['parser_core']=package
    static=importlib.import_module('parser_core.allocation.static_loadout')
    names=importlib.import_module('parser_core.catalog.names')
    resources=importlib.import_module('parser_core.catalog.resources')
    original_equipment=static._load_equip_item_catalog;original_weapons=static._load_weapon_catalog
    function=next(node for node in ast.parse(pinned(prefix+'allocation/static_loadout.py')).body if isinstance(node,ast.FunctionDef) and node.name=='_derive_static_self_multiplier_entries')
    assignments={node.targets[0].id:node.value for node in function.body if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name)}
    reviewed_suits=ast.literal_eval(assignments['suit_definitions'])
    reviewed_weapons=ast.literal_eval(assignments['basic_fields'].func.value)
    proof='a'*64
    modifier=dict(attrIndex=0,attrType=32,modifierType=5,modifyAttributeType=0,attrValues=[.1,.2])
    card=dict(skillId='sk_wpn_a',numericSkillId='101',weaponBindings=[dict(weaponId='wpn_a',skillSlot=0)],suitId='suit_a',
        requiredPieces=3,skillLevel=1,attributeIndex=0,attributeType=32,bbKey='damage',sourceBytes=100,consumedBytes=100,sourceSha256=proof,
        modifier={'$type':'Beyond.Gameplay.AttributeModifierData.AttributeModifier','attributeType':'NormalSkillDamageIncrease',
            'formulaItem':'BaseAddition','modifyAttributeType':'Specific','param':dict(useBlackboardKey=True,blackboardKey='damage')})
    catalog=dict(schemaVersion=1,source='current_official_item_skill_card_attribute',decoder=names._CURRENT_TYPED_RESOURCE_BINDING,
        weaponEntries=[copy.deepcopy(card)],suitEntries=[copy.deepcopy(card)])
    shared=dict(equipment=dict(equip_a=dict(item_name='Equipment A',attribute_modifiers=[modifier],attribute_source_sha256=proof)),
        weapons=dict(wpn_a=dict(weapon_skill_ids=['sk_wpn_a'],static_attack_fields=[],weapon_definition_sha256=proof)),
        numbers={'101':'sk_wpn_a','102':'wpn_sp_attr_atk_high'},catalog=catalog)
    cases=[];current={}
    with tempfile.TemporaryDirectory(prefix='endfield-static-multiplier-reference-') as directory:
        root=Path(directory);path=root/'data/local_static/skill/item_damage_baseline_catalog.json';path.parent.mkdir(parents=True)
        static._repo_root=lambda:root;resources._repo_root=lambda:root
        static._load_equip_item_catalog=lambda:current['equipment'];static._load_weapon_catalog=lambda:current['weapons']
        static._load_num_id_str_skill_map=lambda:current['numbers'];names._load_num_id_str_skill_map=lambda:current['numbers']
        def add(label,row=None,**changes):
            config=dict(row=copy.deepcopy(row or {}));config.update(copy.deepcopy(changes))
            current.clear();current.update(shared);current.update(changes)
            path.write_text(json.dumps(current['catalog']),encoding='utf8')
            owned=copy.deepcopy(config['row'])
            try: result=dict(row=owned,entries=static._derive_static_self_multiplier_entries(owned))
            except (TypeError,ValueError,OverflowError,AttributeError,KeyError) as exc:result=dict(error=type(exc).__name__)
            cases.append(dict(name=f'{len(cases):04d}-{label}',config_json=json.dumps(config,ensure_ascii=True),expected=canonical(result)))
        def equip(**changes):
            value=dict(item_id='equip_a',slot=0,enhance_levels=[dict(index=0,level=1)],stats=[dict(value='unknown',level='unknown')])
            value.update(changes);return value
        def equipment(modifiers=None,**changes):
            value=dict(item_name='Equipment A',attribute_modifiers=modifiers if modifiers is not None else [modifier],attribute_source_sha256=proof)
            value.update(changes);return dict(equip_a=value)
        def weapon(rate=.2,**changes):
            value=dict(weapon_template='wpn_a',weapon_source_skills=[dict(skill_id=101,bb=dict(damage=rate))]);value.update(changes);return value
        add('empty')
        add('reset-prior',dict(equipment_baseline_attributes=[dict(value=999)],rdps_unresolved_static_multiplier_sources=[dict(reason='prior')]))
        add('unresolved-slots',dict(unresolved_equip_inst_ids=['11','22']))
        for attr,stage,complete in itertools.product([2,9,10,17,28,32,33,39,40,41,42,50,51,52,53,54,55,61,65,70,87,99], [0,5,6,7], [False,True]):
            add('equipment-type-stage',dict(equips=[equip()],equipment_snapshot_complete=complete),
                equipment=equipment([dict(modifier,attrType=attr,modifierType=stage)]))
        for levels,values,complete in itertools.product([[],[dict(index=0,level=0)],[dict(index=0,level=1)],
                [dict(index=0,level=-1)],[dict(index=0,level=2)],[dict(index=0,level=0),dict(index=0,level=1)],
                [dict(index=True,level=1)],[dict(index=0,level=True)],[dict(index='0',level=1)]],
                [[],[0],[.2,.2],[.1,.2],[.2,None],[.2,True],[-1,-1],['0.2','0.3']], [False,True]):
            add('equipment-enhancement',dict(equips=[equip(enhance_levels=levels)],equipment_snapshot_complete=complete),
                equipment=equipment([dict(modifier,attrValues=values)]))
        for field,values in dict(slot=[None,True,0,1,-1,0.,'0',[]],item_id=[None,'missing'],
                stats=[[],[None],[dict(value=0)],[dict(value='unknown')]],enhance_levels=[None,[],[dict(index=0,level=1)]]).items():
            for value in values:add('equipment-'+field,dict(equips=[equip(**{field:value})]))
        for other in [equip(),equip(slot=True),equip(slot=0.),equip(slot=1),None]:
            add('equipment-duplicate-slots',dict(equips=[equip(),other]))
        for field,values in dict(attrIndex=[None,True,0,1,-1,'0',[]],attrType=[None,True,'32'],modifierType=[None,True,'5'],modifyAttributeType=[None,True,1]).items():
            for value in values:
                for complete in [False,True]:add('modifier-'+field,dict(equips=[equip()],equipment_snapshot_complete=complete),equipment=equipment([dict(modifier,**{field:value})]))
        for value in [None,'',proof.upper(),'a'*63,proof]:add('equipment-proof',dict(equips=[equip()]),equipment=equipment(attribute_source_sha256=value))
        add('invalid-modifier',dict(equips=[equip()]),equipment=equipment([None,modifier]))
        for value in [None,-1,0,.2,'0.2',True,float('inf')]:add('weapon-value',weapon(value))
        for identity,declared,stage in itertools.product([101,'101','sk_wpn_a','skill_101',102,None], [[],['sk_wpn_a'],['wpn_sp_attr_atk_high']],['BaseMultiplier','BaseFinalAddition']):
            add('weapon-basic-identity',weapon(weapon_source_skills=[dict(skill_id=identity,bb=dict(atk=.2,damage=.1))]),
                weapons=dict(wpn_a=dict(weapon_skill_ids=declared,static_attack_fields=[dict(skillId='sk_wpn_a',bbKey='atk',formulaItem=stage)],weapon_definition_sha256=proof)))
        for source in ['weapon_source_skills','weapon_refine_stats']:
            add('basic-attack',dict(weapon_template='wpn_a',**{source:[dict(skill_id=102,bb=dict(atk=.3))]}),
                weapons=dict(wpn_a=dict(weapon_skill_ids=['wpn_sp_attr_atk_high'])))
        for rate in [None,.1,.2]:
            add('basic-attack-conflict',weapon(weapon_source_skills=[dict(skill_id=102,bb=dict(atk=.2)),dict(skill_id=102,bb=dict(atk=rate))]),
                weapons=dict(wpn_a=dict(weapon_skill_ids=['wpn_sp_attr_atk_high'])))
        for category in ['weapon','suit']:
            for field,values in dict(attributeType=[None,True,17,32.,32],attributeIndex=[None,True,-1,0],sourceBytes=[None,True,0,100],consumedBytes=[99,100],
                    sourceSha256=['',proof.upper(),proof],numericSkillId=[None,102,101],requiredPieces=[None,2,3],skillLevel=[None,1,2]).items():
                for value in values:
                    changed=dict(card,**{field:value})
                    add('card-'+category+'-'+field,dict(**weapon(),suit_effects=[dict(suit_id='suit_a',active=True,value=dict(damage=.3))]),
                        catalog=dict(catalog,weaponEntries=[changed] if category=='weapon' else [],suitEntries=[changed] if category=='suit' else []))
        for formula in ['BaseAddition','Addition','BaseMultiplier',None]:
            for value in [None,-1,0,.2]:
                changed=copy.deepcopy(card);changed['modifier']['formulaItem']=formula
                add('card-stage-value',weapon(value),catalog=dict(catalog,weaponEntries=[changed],suitEntries=[]))
        for field,values in {'$type':['other',None],'attributeType':['Attack',None],'modifyAttributeType':['All',None],
                'param':[None,{},dict(useBlackboardKey=False,blackboardKey='damage'),dict(useBlackboardKey=True,blackboardKey='other')]}.items():
            for value in values:
                changed=copy.deepcopy(card);changed['modifier'][field]=value
                add('card-modifier-'+field,weapon(),catalog=dict(catalog,weaponEntries=[changed],suitEntries=[]))
        for version,decoder in itertools.product([None,0,1,True,'1',2], [None,{},catalog['decoder'],dict(catalog['decoder'],extra='allowed'),dict(catalog['decoder'],schemaSha256='b'*64)]):
            add('card-catalog-provenance',weapon(),catalog=dict(catalog,schemaVersion=version,decoder=decoder))
        for binding in [[],[dict(weaponId='wpn_a',skillSlot=0)]*2,[dict(weaponId='wpn_a',skillSlot=True)],
                [dict(weaponId='other',skillSlot=0)],[dict(weaponId='wpn_a',skillSlot=1)]]:
            add('card-binding',weapon(),catalog=dict(catalog,weaponEntries=[dict(card,weaponBindings=binding)],suitEntries=[]))
        for rates in [[.2,.2],[.2,.3],[.2,.3,.2]]:
            add('card-deduplication',weapon(weapon_source_skills=[dict(skill_id=101,bb=dict(damage=rate)) for rate in rates]))
        add('card-provenance-only-duplicate',weapon(),catalog=dict(catalog,weaponEntries=[card,dict(card,sourceSha256='b'*64)]))
        for suit_id,(base,trigger) in reviewed_suits.items():
            for values in [{},dict.fromkeys(sorted(base),.2),dict.fromkeys(sorted(base|trigger),.2),dict(unknown=.2),None]:
                for active in [False,True]:add('reviewed-suit',dict(suit_effects=[dict(suit_id=suit_id,active=active,value=values)]))
        for active,rate in itertools.product([None,False,True,1], [None,-1,0,.2]):
            add('suit-card',dict(suit_effects=[dict(suit_id='suit_a',active=active,value=dict(damage=rate))]))
        add('unknown-suits',dict(suit_effects=[dict(suit_id='unknown',active=False,value={}),dict(suit_id='another',active=True,value={})]))
        for item,skills in reviewed_weapons.items():
            for index,(skill,keys) in enumerate(skills.items()):
                number=str(5000+index)
                for bb in [dict.fromkeys(sorted(keys),.2),dict(unknown=.2),{}]:
                    for identity in [number,skill]:
                        add('reviewed-weapon',dict(weapon_template=item,weapon_source_skills=[dict(skill_id=identity,bb=bb)]),
                            weapons={item:dict(weapon_skill_ids=list(skills))},numbers={number:skill})
        for zero in [0.,.1,None]:
            add('arts-placeholder',dict(weapon_template='wpn_funnel_0008',weapon_source_skills=[dict(skill_id=101,bb=dict(physpell=20,atk=zero))]),
                weapons=dict(wpn_funnel_0008=dict(weapon_skill_ids=['wpn_sp_attr_phy_spell_high'])),numbers={'101':'wpn_sp_attr_phy_spell_high'})
        add('combined',dict(**weapon(),equips=[equip()],equipment_snapshot_complete=True,
            suit_effects=[dict(suit_id='suit_a',active=True,value=dict(damage=.3))]))
        if args.bundled:
            archive='_internal/data/runtime-data.zip';pinned(archive)
            with zipfile.ZipFile(args.reference/archive) as bundle:
                for info in bundle.infolist():
                    if info.is_dir():continue
                    target=(root/info.filename).resolve()
                    if not target.is_relative_to(root):raise ValueError('Runtime archive path outside temporary root')
                    target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(bundle.read(info))
            original_equipment.cache_clear();original_weapons.cache_clear()
            actual_equipment=original_equipment();actual_weapons=original_weapons()
            actual_catalog=json.loads(path.read_text(encoding='utf8'))
            table=json.loads((root/'data/local_tables/NumIdStrTable.json').read_text(encoding='utf8'))['skill_id']['dic']
            # Actual resources are shared by all following cases instead of repeated in each JSON row.
            for item,meta in actual_equipment.items():
                modifiers=meta.get('attribute_modifiers') or []
                for level in [None,0,1,2]:
                    row=dict(equips=[dict(item_id=item,slot=0,stats=[dict(value='unknown') for _ in modifiers],
                        enhance_levels=[] if level is None else [dict(index=i,level=level) for i in range(len(modifiers))])],equipment_snapshot_complete=level is None)
                    add('bundled-equipment',row,equipment={item:meta},weapons={},numbers=table,catalog=actual_catalog)
            reverse={value:key for key,value in table.items()}
            for item,meta in actual_weapons.items():
                declared=meta.get('weapon_skill_ids') or []
                for skill in declared:
                    fields=set()
                    if skill in {'wpn_sp_attr_atk_high','wpn_sp_attr_atk_mid','wpn_sp_attr_atk_low'}:fields.add('atk')
                    fields.update(field['bbKey'] for field in meta.get('static_attack_fields') or [] if field['skillId']==skill)
                    fields.update(definition['bbKey'] for definition in actual_catalog.get('weaponEntries') or [] if definition['skillId']==skill)
                    if not fields:continue
                    add('bundled-weapon',dict(weapon_template=item,weapon_source_skills=[dict(skill_id=reverse.get(skill,skill),bb=dict.fromkeys(sorted(fields),.2))]),
                        equipment={},weapons={item:meta},numbers=table,catalog=actual_catalog)
            for definition in actual_catalog.get('suitEntries') or []:
                add('bundled-suit',dict(suit_effects=[dict(suit_id=definition['suitId'],active=True,value={definition['bbKey']:.2})]),
                    equipment={},weapons={},numbers=table,catalog=actual_catalog)
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(dict(resources_json=json.dumps(shared,ensure_ascii=True),cases=cases),ensure_ascii=True,separators=(',',':')),encoding='utf8')
        output.with_suffix('.reference.json').write_text(json.dumps(dict(source_head=metadata['head'],cases=len(cases),dependencies=dependencies),indent=2),encoding='utf8')
        print('Static multiplier fixtures:',len(cases))


if __name__=='__main__':main()
