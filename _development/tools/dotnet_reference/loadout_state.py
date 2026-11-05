"""Fixed-reference loadout merging and ordered group/state transitions."""
from pathlib import Path
from types import ModuleType
from datetime import date
import argparse
import copy
import hashlib
import importlib
import json
import random
import struct
import sys


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference',type=Path,required=True)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[3]
    args.output=args.output or root/'_internal/dotnet/Specs/Fixtures/loadout-state.json'
    metadata=json.loads(args.manifest.read_text(encoding='utf8'))
    prefix='_internal/packages/parser_core/parser_core/'
    dependencies={}
    for relative,expected in metadata['files'].items():
        if relative.startswith(prefix) and relative.endswith('.py'):
            digest=hashlib.sha256((args.reference/relative).read_bytes()).hexdigest()
            if digest != expected['sha256']: raise ValueError('Fixed reference changed: '+relative)
            dependencies[relative]=digest
    package=ModuleType('parser_core');package.__path__=[str(args.reference/prefix)];sys.modules['parser_core']=package
    loadout=importlib.import_module('parser_core.ingestion.loadout')
    state_module=importlib.import_module('parser_core.ingestion.state')
    resources=importlib.import_module('parser_core.catalog.resources')
    names=importlib.import_module('parser_core.catalog.names')
    config=json.loads(json.loads((root/'_internal/dotnet/Specs/Fixtures/loadout-snapshots.json').read_text(encoding='utf8'))[0]['config_json'])
    loadout._load_weapon_catalog=lambda:config['weapons']
    loadout._load_equip_item_catalog=lambda:config['equipment']
    loadout._load_weapon_refine_catalog=lambda:config['refinement']
    loadout._resolve_character_name=lambda key:config['names'].get(key)
    resources._load_suit_catalog=lambda:config['suits']
    names._load_num_id_str_skill_map=lambda:config['skills']
    cases=[]
    def encode(value):
        if type(value) is int:return {'int':str(value)}
        if type(value) is float:return {'f64':struct.pack('>d',value).hex()}
        if isinstance(value,(list,tuple)):return [encode(item) for item in value]
        if isinstance(value,dict):return {key:encode(item) for key,item in value.items()}
        return value
    def snapshot(state):
        return dict(loadouts=state.loadout_by_char,groups=state.loadout_groups,
                    current_group=state.current_loadout_group['index'] if state.current_loadout_group is not None else None,
                    active_weapons=state.active_weapons_by_char,active_suits={key:sorted(value) for key,value in state.active_suits_by_char.items()},
                    skills=state.char_skill_levels)
    def run_stream(data):
        state=state_module.IngestionState(reference_date=date(2026,10,25),first_hit_hint_ms=None,last_hit_hint_ms=None,
            context_enemy_hint=None,trace_identity_inference_seen=False,loadout_override_by_char=data.get('overrides'),critical_attributes_override_by_actor=None)
        state.squad_actor_keys.update(data.get('squad',{}));steps=[]
        for index,operation in enumerate(data['operations']):
            if 'squad' in operation:state.squad_actor_keys=dict(operation['squad'])
            line=operation.get('text','');time=operation.get('time',100);number=operation.get('line',index+1)
            consumed=None;error=None
            try:
                consumed=(loadout.consume_loadout_group(state,line,number,time)
                    or loadout.consume_loadout_snapshot(state,line,number,time)
                    or loadout.consume_character_skills(state,line,number,time))
            except (ValueError,TypeError,OverflowError,AttributeError) as exc:error=type(exc).__name__
            steps.append(copy.deepcopy(dict(consumed=consumed,state=snapshot(state),error=error)))
        return steps
    def add(name,kind,data):
        original=copy.deepcopy(data)
        try:
            if kind=='merge':value=loadout._merge_loadout_snapshot(data['base'],data['update'])
            elif kind=='equips':value=loadout._merge_loadout_equips_by_slot(data['base'],data['update'])
            elif kind=='tracked':value=loadout._merge_tracked_loadout_state(data['base'],data['update'])
            elif kind=='weapon':value=loadout._loadout_with_weapon_state(data['base'],data['update'])
            elif kind=='source_ids':value=list(loadout._loadout_weapon_source_skill_ids(data))
            elif kind=='integer_set':
                result=set()
                for item in data:result.add(int(item))
                value=list(result)
            elif kind=='stream':value=run_stream(data)
            else:raise AssertionError(kind)
            expected=dict(value=encode(value),error=None)
        except (ValueError,TypeError,OverflowError,AttributeError) as error:expected=dict(value=None,error=type(error).__name__)
        if original!=data:raise AssertionError('Reference mutated input: '+name)
        cases.append(dict(name=name,kind=kind,input_json=json.dumps(data),config_json=json.dumps(config),expected=expected))
    previous=dict(character_key='chr_0001_alpha',potential=2,weapon_inst_id='11',weapon_template='wpn_test',
                  weapon_refine=4,weapon_refine_source='source_skill',gem_template='old',gem_terms={'rate':.5},
                  weapon_source_skills=[dict(skill_id='101',level=2,bb={'rate':.2})],skill_int_ids=['5','101','7'],
                  equips=[dict(slot=0,item_id='equip_test',stats=[1]),dict(slot=1,item_id='old',stats=[2])],
                  suit_effects=[dict(suit_id='suit_test',piece_count=3)])
    for value in (None,'',[],{},0,False,True,1,'value',[0],{'x':0}):
        for field in ('weapon_refine','weapon_refine_source','equips','suit_effects','extra'):
            add('merge/empty/'+str(len(cases)),'merge',dict(base=previous,update={field:value}))
    for complete in (False,True,0,1,'true'):
        for value in (None,[],{},''):
            add('merge/complete/'+str(len(cases)),'merge',dict(base=previous,update=dict(equipment_snapshot_complete=complete,
                equips=value,suit_effects=value,equip_suit_raw=value,unresolved_equip_inst_ids=value)))
    for source in ('source_skill','loadout',None,''):
        for refine in (0,2,5,None):
            add('merge/refine/'+str(len(cases)),'merge',dict(base=previous,update=dict(weapon_refine=refine,weapon_refine_source=source)))
    for value in ('11','12',None,0,False,'',11):
        for kind in ('tracked','weapon'):
            add('weapon/identity/'+str(len(cases)),kind,dict(base=previous,update=dict(weapon_inst_id=value,weapon_template='new')))
    for sources in ([],[dict(skill_id='102')],[dict(skill_id='101'),dict(skill_id='5'),dict(skill_id='105')],
                    [dict(skill_id='bad'),None,dict(skill_id=False)],{},'abc'):
        add('weapon/sources/'+str(len(cases)),'weapon',dict(base=previous,update=dict(weapon_source_skills=sources)))
        add('source_ids/'+str(len(cases)),'source_ids',dict(weapon_source_skills=sources,weapon_refine_stats=[dict(skill_id='33')]))
    for value in (None,False,0,'0',2.9,'2.0','2_000','bad',[],{},True):
        add('weapon/potential/'+str(len(cases)),'weapon',dict(base=dict(previous,potential=value),update={}))
    equip_cases=[dict(slot=0,item_id='equip_test',level=3),dict(slot=0,item_id='changed'),dict(slot=2,item_id='added'),
                 dict(item_id='unplaced'),dict(slot='-1',item_id='negative'),dict(slot='bad'),dict(slot=True),dict(slot=0.9),
                 dict(slot='01'),dict(slot='1.0'),dict(slot='--2'),None,'bad']
    for row in equip_cases:
        add('equips/single/'+str(len(cases)),'equips',dict(base=previous['equips'],update=[row]))
    add('equips/duplicate','equips',dict(base=previous['equips']+[dict(slot=0,item_id='duplicate')],update=equip_cases))
    for suits in ([dict(suit_id='x',piece_count='bad')],[dict(suit_id='',piece_count='bad')],1):
        add('merge/suit-count/'+str(len(cases)),'merge',dict(base=previous,update=dict(equips=[dict(slot=0)],suit_effects=suits)))
    rng=random.Random(63415)
    for index in range(100):
        values=[rng.choice([rng.randrange(-20000,20000),rng.randrange(-100,100)*8,2**61+rng.randrange(100)]) for _ in range(rng.randrange(1,200))]
        add('set/random/'+str(index),'integer_set',values)
    for values in ([0,-1,-2,1,8,16],list(range(150)),list(reversed(range(150))),[i*32 for i in range(150)],
                   [-(2**61-1)*i for i in range(1,25)],[2**100+i*(2**61-1) for i in range(25)]):
        add('set/collision/'+str(len(cases)),'integer_set',values)
    slot=' LOADOUT slot=0 char=chr_0001_alpha potential=2 weaponInstId=11 weaponTemplate=wpn_test weaponLv=2 refine=0 equipSuit={[suit_test]=3} skillIntIds=[5 101] equips={[0]=equip_test}'
    stats=' LOADOUT_STATS char=chr_0001_alpha weaponTemplate=wpn_test weaponLv=2 weaponInstId=11 weaponSourceSkills={101:level=2} gemInstId=33 gemWeaponId=11 gemTerms={202:rate@cost1}'
    chars=' CHAR_SKILLS owner=chr_0001_alpha ownerId=55 skills=[101:2]'
    def stream(name,lines,**data):
        add(name,'stream',dict(operations=[dict(text=line,time=time) for line,time in lines],**data))
    stream('stream/basic',[(slot,100),(stats,100),(slot+' equipsComplete=1',200),('unknown',200)])
    stream('stream/group-boundaries',[(' LOADOUT reason=SC_SELF_SCENE_INFO',100),(slot,100),(stats,100),(stats,101),(' LOADOUT reason=empty',101),(slot,101)])
    stream('stream/weapon-replacement',[(slot,100),(stats,100),(slot.replace('weaponInstId=11','weaponInstId=12').replace('wpn_test','unknown'),200),(stats.replace('weaponInstId=11','weaponInstId=12'),200)])
    stream('stream/skill-inference',[(slot.replace('refine=0','refine=bad'),100),(chars,110),(chars,120)],squad={'55':'chr_0001_alpha'})
    for reason in ('SC_SELF_SCENE_INFO','SC_SYNC_CHAR_BAG_INFO','unknown',''):
        stream('stream/gem/'+reason,[(' LOADOUT reason='+reason,100),(stats.replace('weaponSourceSkills={101:level=2}','weaponSourceSkills={}'),100),(stats,101)])
    for overrides in ({},{'chr_0001_alpha':previous}):
        stream('stream/override/'+str(len(cases)),[(slot,100),(stats,100),(chars,110),(slot.replace('weaponInstId=11','weaponInstId=12'),200)],overrides=overrides,squad={'55':'chr_0001_alpha'})
    for index in range(80):
        lines=[];time=100
        for _ in range(rng.randrange(3,15)):
            time+=rng.choice([0,0,1,-1])
            line=rng.choice([slot,stats,chars,' LOADOUT reason=SC_SELF_SCENE_INFO',' LOADOUT slot=bad char=foreign',
                             slot+' equipsComplete=1',slot.replace('weaponInstId=11','weaponInstId=12')])
            lines.append((line,time))
        stream('stream/random/'+str(index),lines,squad={'55':'chr_0001_alpha'})
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(cases,ensure_ascii=True,separators=(',',':')),encoding='utf8')
    args.output.with_suffix('.reference.json').write_text(json.dumps(dict(cases=len(cases),source_head=metadata['head'],dependencies=dependencies),indent=2),encoding='utf8')
    print('Loadout state fixtures:',len(cases))


if __name__=='__main__':main()
