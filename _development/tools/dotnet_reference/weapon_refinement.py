"""Compare refinement proofs from observed skill levels against fixed Python."""
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
import zipfile


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference',type=Path,required=True)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--bundled',action='store_true')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if args.bundled and args.output is None: parser.error('--bundled requires --output')
    args.output=args.output or Path(__file__).resolve().parents[3]/'_internal/dotnet/Specs/Fixtures/weapon-refinement.json'
    metadata=json.loads(args.manifest.read_text(encoding='utf8'))
    prefix='_internal/packages/parser_core/parser_core/'
    dependencies={}
    for relative,expected in metadata['files'].items():
        if relative.startswith(prefix) and relative.endswith('.py'):
            digest=hashlib.sha256((args.reference/relative).read_bytes()).hexdigest()
            if digest != expected['sha256']: raise ValueError('Fixed refinement reference changed: '+relative)
            dependencies[relative]=digest
    package=ModuleType('parser_core'); package.__path__=[str(args.reference/prefix)]
    sys.modules['parser_core']=package
    loadout=importlib.import_module('parser_core.ingestion.loadout')
    current={}
    loadout._load_weapon_refine_catalog=lambda:current
    cases=[]
    def encode(value):
        if type(value) is int: return {'int':str(value)}
        if type(value) is float: return {'f64':struct.pack('>d',value).hex()}
        return value
    def add(name,entry,skills,gem=None,weapon='wpn_test'):
        current.clear(); current[weapon]=entry
        original=copy.deepcopy((entry,skills,gem))
        try: expected=dict(value=encode(loadout._infer_verified_weapon_refine_from_levels(weapon,skills,gem_terms=gem)),error=None)
        except (ValueError,TypeError,OverflowError) as error: expected=dict(value=None,error=type(error).__name__)
        if (entry,skills,gem) != original: raise AssertionError('Reference mutated input: '+name)
        cases.append(dict(name=name,entry_json=json.dumps(entry),skills_json=json.dumps(skills),gem_json=json.dumps(gem),weapon=weapon,expected=expected))
    entry=dict(mainSkillId='skill_main',mainSkillNumId=101,mainSkillGemTermNumId=202,
        skillLevelToRefine={'1':0,'2':1,'3':2,'4':3,'5':4,'6':5},supportedSkillLevels=list(range(1,13)),
        mainSkillBounds=[dict(lowerBound=1,upperBound=3)],refineBonusBounds={str(index):dict(lowerBound=index,upperBound=index+2) for index in range(6)})
    def skill(**changes): return dict(dict(skill_id='skill_main',level=3),**changes)
    for level in (None,True,False,0,-1,1,2,3,4,5,6,7,12,13,1.0,1.5,'1','01','1.0','1e0','+1','-1',' 1 ','\u00b2','\uff11',[],{},float('nan'),float('inf')):
        add('level/'+str(len(cases)),entry,[skill(level=level)])
    for skills in (None,[],{},'other',0,False,True,1,[None,1,{},[]],[skill()],
                   [skill(skill_id='101')],[skill(skill_id=101)], [skill(skill_id='other')],
                   [skill(),skill(level=4)],[skill(),skill()], [skill(skill_id='skill_main',skill_int_id=101)],
                   [skill(skill_id='skill_main',skill_int_id=999)],[skill(skill_id='other'),skill()]):
        add('sources/'+str(len(cases)),entry,skills)
    for field in ('skill_id','skillKey','skill_str_id','skill_int_id'):
        for identity in (None,'','skill_main',101,'101',0,False,True,1.0,[],{},'other'):
            add('identity/'+field+'/'+str(len(cases)),entry,[dict(level=3,**{field:identity})])
    for gem in (None,[],{},True,[None],[{}], [dict(term_num_id=202,cost=0)], [dict(term_num_id=203,cost=1)],
                [dict(term_num_id=202,cost=0)]*2):
        for level in (1,2,3,4,5,6,12,13): add('gem/'+str(len(cases)),entry,[skill(level=level)],gem)
    for term in (None,True,False,0,-1,202,202.0,'202',2**64):
        for cost in (None,True,False,-1,0,1,5,6,7,1.0,'1'):
            add('gem-fields/'+str(len(cases)),entry,[skill()], [dict(term_num_id=term,cost=cost)])
    for field,values in dict(mainSkillId=[None,'other'],mainSkillNumId=[None,0],mainSkillGemTermNumId=[None,True,'202'],
        mainSkillBounds=[None,[],[dict(lowerBound=1.0,upperBound=3.0)],[dict(lowerBound='1',upperBound='3')]],
        refineBonusBounds=[None,{}, {'0':dict(lowerBound=0,upperBound=0),'1':dict(lowerBound=0,upperBound=0)}],
        supportedSkillLevels=[[],[True]],skillLevelToRefine=[{}, {'3':1.5},{'3':False},{'3':'2'},{'3':[]},{'3':float('inf')}]).items():
        for value in values:
            changed=dict(entry,**{field:value})
            for gem in (None,[dict(term_num_id=202,cost=1)]): add('catalog/'+field+'/'+str(len(cases)),changed,[skill()],gem)
    rng=random.Random(15691)
    for index in range(100):
        skills=[skill(level=rng.randrange(14),skill_id=rng.choice(['skill_main','101','other'])) for _ in range(rng.randrange(4))]
        gem=[dict(term_num_id=202,cost=rng.randrange(7))] if rng.randrange(2) else None
        add('random/'+str(index),entry,skills,gem)
    if args.bundled:
        relative='_internal/data/runtime-data.zip'
        digest=hashlib.sha256((args.reference/relative).read_bytes()).hexdigest()
        if metadata['files'][relative]['sha256'] != digest: raise ValueError('Fixed resource changed')
        dependencies[relative]=digest
        with zipfile.ZipFile(args.reference/relative) as archive:
            entries=json.loads(archive.read('data/local_tables/weapon/refine_catalog.json'))['entries']
        for weapon,definition in entries.items():
            levels=set(int(key) for key in definition.get('skillLevelToRefine',{})) | set(definition.get('supportedSkillLevels',[]))
            for level in sorted(levels|{0,-1,max(levels,default=0)+1}):
                source=[dict(skill_id=definition['mainSkillId'],level=level)]
                add('bundled/'+weapon+'/'+str(level),definition,source,weapon=weapon)
                if type(definition.get('mainSkillGemTermNumId')) is int:
                    for cost in range(7): add('bundled-gem/'+weapon+'/'+str(level)+'/'+str(cost),definition,source,
                        [dict(term_num_id=definition['mainSkillGemTermNumId'],cost=cost)],weapon)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(cases,ensure_ascii=True,separators=(',',':'),allow_nan=False),encoding='utf8')
    args.output.with_suffix('.reference.json').write_text(json.dumps(dict(cases=len(cases),source_head=metadata['head'],dependencies=dependencies),indent=2),encoding='utf8')
    print('Weapon refinement fixtures:',len(cases))


if __name__ == '__main__': main()
