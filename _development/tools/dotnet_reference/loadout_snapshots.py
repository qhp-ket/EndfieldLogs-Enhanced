"""Generate observed loadout row projections from a fixed Python reference."""
from pathlib import Path
from types import ModuleType
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
    args.output=args.output or Path(__file__).resolve().parents[3]/'_internal/dotnet/Specs/Fixtures/loadout-snapshots.json'
    metadata=json.loads(args.manifest.read_text(encoding='utf8')); prefix='_internal/packages/parser_core/parser_core/'
    dependencies={}
    for relative,expected in metadata['files'].items():
        if relative.startswith(prefix) and relative.endswith('.py'):
            digest=hashlib.sha256((args.reference/relative).read_bytes()).hexdigest()
            if digest != expected['sha256']: raise ValueError('Fixed loadout reference changed: '+relative)
            dependencies[relative]=digest
    package=ModuleType('parser_core'); package.__path__=[str(args.reference/prefix)]; sys.modules['parser_core']=package
    loadout=importlib.import_module('parser_core.ingestion.loadout')
    resources=importlib.import_module('parser_core.catalog.resources')
    names=importlib.import_module('parser_core.catalog.names')
    current={}
    loadout._load_weapon_catalog=lambda:current.get('weapons',{})
    loadout._load_equip_item_catalog=lambda:current.get('equipment',{})
    loadout._load_weapon_refine_catalog=lambda:current.get('refinement',{})
    loadout._resolve_character_name=lambda key:current.get('names',{}).get(key)
    resources._load_suit_catalog=lambda:current.get('suits',{})
    names._load_num_id_str_skill_map=lambda:current.get('skills',{})
    cases=[]
    def encode(value):
        if type(value) is int: return {'int':str(value)}
        if type(value) is float: return {'f64':struct.pack('>d',value).hex()}
        if isinstance(value,(list,tuple)): return [encode(item) for item in value]
        if isinstance(value,dict): return {key:encode(item) for key,item in value.items()}
        return value
    config=dict(weapons=dict(wpn_test=dict(weapon_name='Test weapon',base_atk_values=[100,105.5,110],skilllist=['skill_main'])),
                equipment=dict(equip_test=dict(item_name='Test armor',suit_id='suit_test',suit_name='Test suit',part_name='Body',rarity=5,main_attr={'atk':1},sub_attrs={'hp':2})),
                suits=dict(suit_test=dict(suit_name='Test suit',required_piece_count=3,description='effect',value={'rate':0.1})),
                refinement=dict(wpn_test=dict(mainSkillId='skill_main',mainSkillNumId=101,mainSkillGemTermNumId=202,
                    skillLevelToRefine={'1':0,'2':1,'3':2},supportedSkillLevels=list(range(1,7)),
                    mainSkillBounds=[dict(lowerBound=1,upperBound=2)],refineBonusBounds={'0':dict(lowerBound=0,upperBound=0),'1':dict(lowerBound=1,upperBound=1)})),
                names={'chr_0001_alpha':'Alpha'},skills={'101':'skill_main'})
    def add(name,text,kind='slot',context=None,squad=None,allow=False,**changes):
        cfg=dict(config,**changes); current.clear(); current.update(cfg)
        original=copy.deepcopy((cfg,context,squad))
        try:
            if kind=='slot': value=loadout._parse_loadout_slot_snapshot(text)
            elif kind=='stats': value=loadout._parse_loadout_stats_snapshot(text,loadout_context=context,squad_actor_keys=squad,allow_bound_gem=allow)
            elif kind=='source': value=loadout._parse_weapon_source_skills(text)
            elif kind=='equips': value=loadout._parse_inline_equips(text)
            elif kind=='suits': value=resources._parse_suit_counts(text)
            else: raise AssertionError(kind)
            expected=dict(value=encode(value),error=None)
        except (ValueError,TypeError,OverflowError) as error: expected=dict(value=None,error=type(error).__name__)
        if (cfg,context,squad) != original: raise AssertionError('Reference mutated input')
        cases.append(dict(name=name,text=text,kind=kind,config_json=json.dumps(cfg),context_json=json.dumps(context),squad=squad,allow=allow,expected=expected))
    base=' LOADOUT slot=0 char=chr_0001_alpha charLv=80 potential=2 weaponInstId=11 weaponTemplate=wpn_test weaponLv=2 refine=0 break=1 equipSuit={[suit_test]=3} skillIntIds=[101 102] equips={[0]=equip_test|lv=0:2 1:3|stats=atk:Attack=1.5@2;hp:HP=-3}'
    add('slot/full',base)
    for text in ('',' LOADOUT slot=0',' LOADOUT char=eny_0001_enemy',' LOADOUT char=chr_unknown',' LOADOUT char="chr_0001_alpha"',base+' unplacedEquipInstIds=[1 02 x3] equipsComplete=1'):
        add('slot/boundary/'+str(len(cases)),text)
    for key,values in dict(slot=['1','-1','bad','1.0'],char=['chr_0002_beta','unknown'],charLv=['0','-1','bad','1.5'],
                          potential=['0','-1','bad'],weaponTemplate=['missing'],weaponLv=['0','-1','1','2','3','4','1.0','bad'],
                          refine=['','0','5','6','01','1.0','bad']).items():
        import re
        for value in values: add('slot/'+key+'/'+str(len(cases)),re.sub(r'\b'+key+r'=\S+',key+'='+value,base,count=1))
    for complete in ('0','1','2','true',''):
        add('slot/complete/'+complete,base+' equipsComplete='+complete)
    for text in ('','bad','skill_main:level=2','101:level=2:potentialLv=1:bb={rate=-0.2,txt=unknown}',
                 'a:bb={x={a=1,b=2},rate=0.2};b:level=3','a:level=bad:potentialLv=0',' :level=1','a:other=1','a:level=1.5'):
        add('source/'+str(len(cases)),text,'source')
    for blob in ('','[suit_test]=0','[suit_test]=2','[suit_test]=3','[missing]=4','[suit_test]=4 [suit_test]=2','[suit_test]=-1'):
        add('suits/'+str(len(cases)),blob,'suits')
    for blob in ('','[0]=equip_test','[0]=missing','[0]=equip_test|lv=0:1|stats=atk:Attack=1@2',
                 '[0]=equip_test [1]=missing|stats=x:y=bad','[0]=equip_test [0]=missing','[2]= equip_test |lv=1:3|stats=x:y=2',
                 '[0]=equip_test|stats=x=1:y','[0]=equip_test|stats=x:y=1\nignored'):
        add('equips/'+str(len(cases)),' equips={'+blob+'}','equips')
    stat=' LOADOUT_STATS char=chr_0001_alpha weaponTemplate=wpn_test weaponLv=2 weaponInstId=11 weaponSourceSkills={skill_main:level=2:potentialLv=2:bb={rate=0.2}} weaponRefineStats={101:level=1} weaponBaseAtk=0 weaponBaseAtkLv1=100 weaponBaseAtkMax=200 gemTemplate=gem_test gemInstId=33 gemWeaponId=11 gemTerms={202:rate@cost1}'
    for allow in (True,False):
        add('stats/full/'+str(allow),stat,'stats',allow=allow)
        for key,values in dict(weaponLv=['0','-1','4','1.5'],weaponBaseAtk=['0','1','-5','1.0','bad'],gemWeaponId=['11','12'],gemInstId=['0','03','33'],weaponInstId=['0','01','11']).items():
            for value in values: add('stats/'+key+'/'+str(len(cases)),re.sub(r'\b'+key+r'=\S+',key+'='+value,stat,count=1),'stats',allow=allow)
    for term in ('','202:rate@cost0','202:rate@cost6','202:rate@cost7','202:rate@cost1,202:x@cost1','202:rate@cost1,203:x@cost0','bad','202:rate@cost1,'):
        add('stats/gem/'+str(len(cases)),stat.replace('202:rate@cost1',term),'stats',allow=True)
    for text in ('',' LOADOUT_STATS char=unknown',' LOADOUT_STATS char=chr_0001_alpha',' LOADOUT_STATS char=chr_0001_alpha weaponTemplate=missing weaponLv=1'):
        add('stats/missing/'+str(len(cases)),text,'stats')
    context=dict(character_key='chr_0001_alpha',weapon_template='wpn_test',weapon_inst_id='11',weapon_refine=None,nested={'values':[1,2]})
    charline=' CHAR_SKILLS owner=chr_0001_alpha ownerId=55 skills=[101:2]'
    squad={'55':'chr_0001_alpha'}
    add('char-skills/valid',charline,'stats',context,squad)
    for key,values in dict(character_key=['wrong',None],weapon_template=['missing',None],weapon_inst_id=[None,0,'0','01','12',11],weapon_refine=[0,False,'',1]).items():
        for value in values: add('char-skills/context/'+key+'/'+str(len(cases)),charline,'stats',dict(context,**{key:value}),squad)
    for bindings in (None,{}, {'56':'chr_0001_alpha'},{'55':'chr_0001_alpha','56':'chr_0001_alpha'},{'55':'foreign'}):
        add('char-skills/squad/'+str(len(cases)),charline,'stats',context,bindings)
    for tokens in ('','101:0','101:1 101:2','101:2 skill_main:2','101:4','skill_main:1','chr_0001_alpha_skill_101:2','other:2'):
        add('char-skills/tokens/'+str(len(cases)),charline.replace('101:2',tokens),'stats',context,squad)
    rng=random.Random(19813)
    for index in range(80):
        text=f' LOADOUT slot={rng.randrange(4)} char=chr_0001_alpha weaponTemplate={rng.choice(["wpn_test","unknown"])} weaponLv={rng.randrange(-1,7)} refine={rng.randrange(-1,7)} equipSuit={{[suit_test]={rng.randrange(5)}}}'
        add('random/slot/'+str(index),text)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(cases,ensure_ascii=True,separators=(',',':')),encoding='utf8')
    args.output.with_suffix('.reference.json').write_text(json.dumps(dict(cases=len(cases),source_head=metadata['head'],dependencies=dependencies),indent=2),encoding='utf8')
    print('Loadout snapshot fixtures:',len(cases))


if __name__ == '__main__': main()
