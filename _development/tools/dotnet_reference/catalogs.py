"""Fixed-source resource precedence and evidence gates, using synthetic files."""
from pathlib import Path
from types import ModuleType
import argparse
import base64
import copy
import hashlib
import gzip
import importlib.util
import json
import random
import struct
import sys
import tempfile
import zipfile

root = Path(__file__).resolve().parents[3]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--reference', type=Path, required=True, help='Fixed Python source snapshot')
parser.add_argument('--manifest', type=Path, required=True, help='Source SHA-256 manifest for that snapshot')
parser.add_argument('--output', type=Path)
parser.add_argument('--bundled', action='store_true', help='Compare the fixed runtime data bundle; requires an explicit output')
args = parser.parse_args()
if args.bundled and args.output is None:
    parser.error('--bundled requires --output in a local verification directory')
metadata = json.loads(args.manifest.read_text(encoding='utf8'))
reference = args.reference.resolve()
dependencies = {}
for name in ('parser_core', 'parser_core.catalog', 'parser_core.ingestion'):
    package = ModuleType(name)
    package.__path__ = []
    sys.modules[name] = package

def module(name, relative):
    path = reference/relative
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if metadata['files'][relative]['sha256'] != digest:
        raise ValueError('Catalog reference changed: '+relative)
    dependencies[relative] = digest
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value

prefix = '_internal/packages/parser_core/parser_core/'
fields = module('parser_core.ingestion.fields', prefix+'ingestion/fields.py')
module('parser_core.ingestion.identity', prefix+'ingestion/identity.py')
resources = module('parser_core.catalog.resources', prefix+'catalog/resources.py')
resources._repo_root = lambda: active_root
names = module('parser_core.catalog.names', prefix+'catalog/names.py')
display = module('parser_core.catalog.display', prefix+'catalog/display.py')
packet = module('parser_core.catalog.packet_semantics', prefix+'catalog/packet_semantics.py')
buffs = module('parser_core.catalog.buff_templates', prefix+'catalog/buff_templates.py')
skills = module('parser_core.catalog.skill_damage', prefix+'catalog/skill_damage.py')
identity = module('parser_core.ingestion.skill_identity', prefix+'ingestion/skill_identity.py')

def encode(value):
    if type(value) is int: return {'int': str(value)}
    if type(value) is float: return {'f64': struct.pack('>d', value).hex()}
    if isinstance(value, (list, tuple)): return [encode(item) for item in value]
    if isinstance(value, dict): return {str(key): encode(item) for key,item in value.items()}
    return value

cases = []
def add(kind, files=None, ids=None, directories=None, queries=None, binary_files=None):
    global active_root
    files = {name: value if isinstance(value, str) else json.dumps(value, ensure_ascii=False) for name,value in (files or {}).items()}
    with tempfile.TemporaryDirectory(prefix='endfield-catalog-ref-') as temporary:
        directory = Path(temporary)
        active_root = directory/'_internal'
        active_root.mkdir()
        for name, contents in files.items():
            path = directory/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(contents, encoding='utf8', newline='')
        for name in directories or []: (directory/name).mkdir(parents=True, exist_ok=True)
        for name, contents in (binary_files or {}).items():
            path = directory/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(contents)
        for function in (names._load_num_id_str_skill_map, packet._load_num_id_str_buff_map,
                         skills._load_official_skill_damage_catalog, buffs._load_current_buff_roots,
                         skills._load_skill_item_metadata, resources._load_weapon_catalog,
                         resources._load_suit_catalog, resources._load_equip_item_catalog,
                         names._load_character_names, names._load_skill_name_prefixes,
                         names._load_skill_exact_names, names._load_canonical_skill_display_names,
                         names._load_packet_numeric_skill_map, display._load_enemy_names,
                         skills._load_character_profiles, skills._load_skill_profiles):
            function.cache_clear()
        if kind == 'dungeons':
            dungeons = module('parser_core.catalog.dungeons', prefix+'catalog/dungeons.py')
            expected = dict(entries=dungeons._load_dungeon_by_id(), resolved=[dungeons._resolve_dungeon_context(value) for value in ids])
        elif kind == 'numbers':
            expected = dict(skills=names._load_num_id_str_skill_map(), buffs=packet._load_num_id_str_buff_map())
        elif kind == 'profiles':
            expected = skills._load_official_skill_damage_catalog()
        elif kind == 'skill_metadata':
            expected = [skills._load_skill_item_metadata(key) for key in ids]
        elif kind in ('weapons','suits','equipment'):
            try:
                expected = {'weapons':resources._load_weapon_catalog,'suits':resources._load_suit_catalog,
                            'equipment':resources._load_equip_item_catalog}[kind]()
            except (AttributeError,TypeError,UnicodeDecodeError) as error:
                expected = dict(catalog_error=type(error).__name__)
        elif kind == 'buff_roots':
            expected_roots = buffs._load_current_buff_roots()
            expected = dict(roots=expected_roots,
                action_types={key:sorted(value) for key,value in (buffs._BUFF_ACTION_TYPES_INDEX or ({},{}))[1].items()})
        elif kind == 'identities':
            expected = []
            for query in queries:
                skill, owner = query.get('skill'), query.get('owner')
                action, unit = query.get('action'), query.get('unit')
                action = int(action) if action is not None else None
                unit = int(unit) if unit is not None else None
                expected.append(dict(skill=identity._canonical_num_table_skill_id(skill,owner),
                    hit=identity._canonical_hit_skill_id(skill,owner),
                    buff=identity._canonical_runtime_buff_skill_id(skill,owner,action_id=action,damage_unit_index=unit),
                    template=identity._canonical_hit_skill_id_from_cast_context(skill,owner,100,
                        target_enemy_key=None,recent_skill_casts_by_char={},recent_numeric_buffs_by_source={},
                        action_id=action,damage_unit_index=unit,template_type=query.get('template'))))
        elif kind == 'contracts':
            dungeons = module('parser_core.catalog.dungeons', prefix+'catalog/dungeons.py')
            expected = dict(entries=dungeons._load_contract_tag_catalog(), payloads=[dungeons._contract_tag_payload(int(value)) for value in ids])
        elif kind in ('display_names', 'skill_profiles', 'character_profiles'):
            try:
                if kind == 'display_names':
                    expected = dict(characters=names._load_character_names(),
                        enemies=display._load_enemy_names(), prefixes=names._load_skill_name_prefixes(),
                        exact=names._load_skill_exact_names(), canonical=names._load_canonical_skill_display_names(),
                        resolved=[[names._resolve_character_name(key), display._resolve_enemy_name(key), names._resolve_skill_name(key)] for key in ids])
                elif kind == 'skill_profiles':
                    expected = dict(profiles=skills._load_skill_profiles(), resolved=[skills._resolve_skill_profile(key) for key in ids])
                else:
                    expected = skills._load_character_profiles()
            except (AttributeError, TypeError, UnicodeDecodeError, json.JSONDecodeError, OverflowError) as error:
                expected = dict(catalog_error=type(error).__name__)
        else: raise ValueError(kind)
        cases.append(dict(name=f'{kind}/{len(cases)}', kind=kind, files=files, ids=ids or [],
                          directories=directories or [], queries=queries or [],
                          binary_files={key:base64.b64encode(value).decode('ascii') for key,value in (binary_files or {}).items()},
                          expected=encode(copy.deepcopy(expected))))

ids = [None, '', 'unknown', 'indie_contract001', 'indie_hard016_s', 'series', 'child', 'indie_hard999', 'unnamed', 'named']
add('dungeons', ids=ids)
alias = '_internal/data/local_tables/dungeon_catalog.json'
for value in ({}, {'parser': {'dungeon_context_aliases': {'child': ['group', '合成关卡'],
        'indie_contract001': ['override', '别名覆盖'], 'invalid': ['a'], 'ignored': 'bad'}}},
        '{broken', '\ufeff{}'):
    add('dungeons', {alias: value}, ids=ids)
for source in ('akedata', 'local_tables'):
    manifest = f'_internal/data/{source}/dungeon/manifest.json'
    item = f'_internal/data/{source}/dungeon/items/synthetic.json'
    base = {'templateId': 'template', 'contentFile': 'folder/synthetic.json'}
    for shape in ([], {}, {'entries': [None, 4, base]}, [base]):
        for data in ({'dungeonSeriesId': 'series', 'dungeonSeriesname': '合成系列',
                        'dungeons': {'child': {'name': '子关卡'}, 'indie_hard999': {'name': '高难合成'}},
                        'includeDungeonIds': ['child', 'indie_hard999', 'unnamed', '', None]},
                     {'childDungeons': {'named': {'name': '独立活动'}, 'unnamed': {}}}, {}):
            add('dungeons', {manifest: shape, item: data}, ids=ids)
    for definition in (None, [], '{invalid', '\ufeff{}'):
        add('dungeons', {manifest: [base], item: definition}, ids=ids)
    add('dungeons', {manifest: [base]}, ids=ids)
    add('dungeons', {manifest: [base]}, ids=ids, directories=[item.rsplit('/', 1)[0]])
    for content, detail in (('synthetic.json', 'data/custom.json'), ('missing.json', 'data/custom.json'),
                            ('', 'missing/synthetic.json'), ('', ''), ('synthetic.json', 'missing/path.json')):
        add('dungeons', {manifest: [dict(templateId='series', contentFile=content, detailPath=detail)],
                        item: {'dungeonSeriesname': '后备'}, '_internal/data/custom.json': {'dungeonSeriesname': '优先'}}, ids=ids)
add('dungeons', {'_internal/data/akedata/dungeon/manifest.json': [dict(templateId='series', contentFile='a.json')],
    '_internal/data/akedata/dungeon/items/a.json': dict(dungeonSeriesname='来源一', dungeons={'child': {}}),
    '_internal/data/local_tables/dungeon/manifest.json': [dict(templateId='series', contentFile='b.json')],
    '_internal/data/local_tables/dungeon/items/b.json': dict(dungeonSeriesname='来源二', dungeons={'child': {}})}, ids=ids)

local_number = '_internal/data/local_tables/NumIdStrTable.json'
outer_number = 'endfield_tables/Data/TableCfg/NumIdStrTable.json'
numbers = {'skill_id': {'dic': {'1': 'chr_0001_test_skill', '2': '', '3': None, '4': 10, '5': True}},
           'buff_id': {'dic': {'1': 'buff_synthetic', '6': False}}}
for outer in (None, '{bad', [], {}, {'skill_id': {'dic': {}}}, {'buff_id': {'dic': {}}}, numbers):
    for inner in (None, '{bad', {}, numbers):
        add('numbers', {name: value for name,value in ((outer_number, outer), (local_number, inner)) if value is not None})

binding = dict(kind='typed_root_deserialization', **names._CURRENT_TYPED_RESOURCE_BINDING)
profile = dict(proof=dict(actionBoundaries='typed_root_deserialization', sourceBytes=64, consumedBytes=64),
               actions={'7': [dict(source='typed_memorypack_full_object', index=0, damageAttribute='hp', element='fire',
                                   expression=dict(key='atk_scale', value=1.5))]}, retained='完整证据')
document = dict(schemaVersion=2, source='official_local_skilldata_memorypack', decoder=binding,
                summary=dict(inputResourceCount=1, completeRootCount=1), decodeErrors=[], skills={'synthetic_buff': profile})
profile_path = '_internal/data/local_static/skill/damage_element_catalog.json'
add('profiles')
add('profiles', {profile_path: document})
for key, values in {'schemaVersion': [None, 1, 2.0, True, '2'], 'source': ['', 'other'],
                    'decodeErrors': [None, {}, ['error']], 'skills': [None, [], {}]}.items():
    for value in values:
        altered = copy.deepcopy(document); altered[key] = value
        add('profiles', {profile_path: altered})
for key in binding:
    altered = copy.deepcopy(document); altered['decoder'][key] = 'incorrect'
    add('profiles', {profile_path: altered})
for key, values in {'inputResourceCount': [None, 0, -1, 1.0, True, 2],
                    'completeRootCount': [None, 0, 2, 1.0, True]}.items():
    for value in values:
        altered = copy.deepcopy(document); altered['summary'][key] = value
        add('profiles', {profile_path: altered})
for key, values in {'actionBoundaries': ['', None], 'sourceBytes': [0, -1, 64.0, True, None],
                    'consumedBytes': [0, 63, 64.0, None]}.items():
    for value in values:
        altered = copy.deepcopy(document); altered['skills']['synthetic_buff']['proof'][key] = value
        add('profiles', {profile_path: altered})
for value in (None, [], {}, {'7': []}, {'7': None}, {'7': [None]}, {'7': [{}]},
              {'7': [dict(source='typed_memorypack_full_object')]}, {'7': [dict(source='incorrect')]}):
    altered = copy.deepcopy(document); altered['skills']['synthetic_buff']['actions'] = value
    add('profiles', {profile_path: altered})
for value in ('derived', True, False, '', [], {}):
    altered = copy.deepcopy(document); altered['skills']['synthetic_buff']['derivedFrom'] = value
    add('profiles', {profile_path: altered})

queries = [dict(skill=skill,owner=owner,action=action,unit=unit,template=template)
    for skill in ('skill_1','skill_8','skill_99','unmapped')
    for owner in (None,'chr_0001_test','eny_0001_test')
    for action,unit in (('7','0'),('7','1'),('8','0'),(None,None))
    for template in (None,'skill','buff')]
mapping = {'skill_id':{'dic':{'1':'chr_0001_test_skill'}},'buff_id':{'dic':{'1':'synthetic_buff','8':'synthetic_buff'}}}
for value in (None, [], [dict(source='typed_memorypack_full_object', index=0,damageAttribute='hp',element='fire')],
              [dict(source='typed_memorypack_full_object', index=True,damageAttribute='hp',element='fire')],
              [dict(source='typed_memorypack_full_object', index=0.0,damageAttribute='hp',element='fire')],
              [dict(source='typed_memorypack_full_object', index=0,damageAttribute='poise',element='fire')],
              [dict(source='typed_memorypack_full_object', index=0,damageAttribute='hp',element='')],
              [dict(source='typed_memorypack_full_object', index=0,damageAttribute='hp',element='fire')]*2):
    altered = copy.deepcopy(document); altered['skills']['synthetic_buff']['actions']['7'] = value
    add('identities', {profile_path:altered, local_number:mapping}, queries=queries)

buff_path = '_internal/data/local_static/buff/typed_roots.json.gz'
buff_root = {'id':'buff_synthetic','$type':'Beyond.Gameplay.Core.BuffData','$offset':0,'$end':64,
    'actions':[{'$type':'Beyond.Gameplay.Core.CreateBuffAction+Data','serverActionIndex':1,'isEnable':True},
               {'$type':'Nested+Class','children':[]}], 'lifeType':'Infinity'}
buff_document = dict(schemaVersion=1,source='official_local_buffdata_memorypack',decoder=binding,
    summary=dict(inputResourceCount=1,completeRootCount=1),entries={'buff_synthetic':dict(root=buff_root,proof=dict(sourceBytes=64,consumedBytes=64))})
def add_buff(value, damage=document):
    add('buff_roots',{profile_path:damage},binary_files={buff_path:gzip.compress(json.dumps(value,ensure_ascii=False).encode('utf8'),mtime=0)})

add('buff_roots')
add_buff(buff_document)
for key, values in {'schemaVersion':[None,0,1.0,True], 'source':['bad',None], 'decoder':[{},None],
                    'entries':[None,[],{}]}.items():
    for value in values:
        altered = copy.deepcopy(buff_document); altered[key] = value
        add_buff(altered)
for key, values in {'completeRootCount':[0,1.0,True,2], 'inputResourceCount':[0,1.0,True,2]}.items():
    for value in values:
        altered=copy.deepcopy(buff_document); altered['summary'][key]=value
        add_buff(altered)
for key, values in {'id':['other',None], '$type':['wrong',None], '$offset':[0.0,False,1], '$end':[64.0,63,None]}.items():
    for value in values:
        altered=copy.deepcopy(buff_document); altered['entries']['buff_synthetic']['root'][key]=value
        add_buff(altered)
for key, values in {'sourceBytes':[64.0,True,0,None], 'consumedBytes':[64.0,63,None]}.items():
    for value in values:
        altered=copy.deepcopy(buff_document); altered['entries']['buff_synthetic']['proof'][key]=value
        add_buff(altered)
for key in binding:
    altered=copy.deepcopy(buff_document); altered['decoder'][key]='wrong'
    add_buff(altered)
for key, value in [('schemaVersion',1),('source','wrong'),('decoder',{**binding,'extra':1})]:
    altered=copy.deepcopy(document); altered[key]=value
    add_buff(buff_document,altered)
compressed=gzip.compress(json.dumps(buff_document).encode('utf8'),mtime=0)
for value in (b'',b'not gzip',compressed[:10],compressed[:-1],compressed[:-8],compressed+b'\0\0',
              compressed+b'trailing',compressed[:-8]+b'\0'*8,
              gzip.compress(b'\xef\xbb\xbf'+json.dumps(buff_document).encode(),mtime=0)):
    add('buff_roots',{profile_path:document},binary_files={buff_path:value})
raw_buff = json.dumps(buff_document).encode('utf8')
# json.loads(bytes), used by the compressed catalog, detects UTF-8/16/32.
# Exercise this through the real resource loader rather than decoding fixtures first.
encoded_document = copy.deepcopy(buff_document)
encoded_document['entries']['buff_synthetic']['root']['label'] = '合成资源\U0001f680'
encoded_text = json.dumps(encoded_document, ensure_ascii=False)
for encoding, bom in (('utf-8', b'\xef\xbb\xbf'), ('utf-16-le', b'\xff\xfe'),
                      ('utf-16-be', b'\xfe\xff'), ('utf-32-le', b'\xff\xfe\0\0'),
                      ('utf-32-be', b'\0\0\xfe\xff')):
    payload = encoded_text.encode(encoding)
    for marker in (b'', bom):
        add('buff_roots', {profile_path: document}, binary_files={buff_path: gzip.compress(marker+payload, mtime=0)})
    for damaged in (payload[:-1], payload+b'\xff', bom+payload[:-1]):
        add('buff_roots', {profile_path: document}, binary_files={buff_path: gzip.compress(damaged, mtime=0)})
for invalid in (b'\x80', b'\xc0\x80', b'\xc2', b'\xe0\x80\x80', b'\xf0\x80\x80\x80',
                b'\xf4\x90\x80\x80', b'\xf5\x80\x80\x80', b'\xff\xfe\0',
                b'\xff\xfe\0\0\0\0\x11\0', b'\0\0\xfe\xff\0\x11\0\0'):
    add('buff_roots', {profile_path: document}, binary_files={buff_path: gzip.compress(invalid, mtime=0)})
for split in (0,1,len(raw_buff)//2,len(raw_buff)-1,len(raw_buff)):
    members = gzip.compress(raw_buff[:split],mtime=0)+b'\0\0'+gzip.compress(raw_buff[split:],mtime=0)
    add('buff_roots',{profile_path:document},binary_files={buff_path:members})

public_tags = '_internal/data/public/contract_tags.json'
local_tags = '_internal/data/local_tables/CcTagTable.json'
outer_tags = 'endfield_tables/Data/TableCfg/CcTagTable.json'
text_path = '_internal/data/local_tables/I18nTextTable_CN.json'
tag = dict(tagId=1, name={'text': '合成合约'}, desc={'id': 'desc'}, score='3', iconId='icon',
           groupId=0, conflictId=False, buffId='buff_test', retained=dict(raw=123),
           tagTerms=[dict(blackboard=[dict(key='ratio', value=0.25), dict(key='flag', value=True),
                                     dict(key='ratio', value=0.5), dict(key=None, value=1), None]), None])
texts = {'desc': '合约说明', 'name': {'text': '合约名称'}, 'alternate': {'value': '后备文本'}, 'ignored': 1}
for data in (None, '{bad', [], [tag, None, 7, {'tagId': -1}], {'tags': [tag]}, {'tags': {'one': tag}}, {}):
    add('contracts', {text_path: texts, **({public_tags: data} if data is not None else {})}, ids=['1','2','999'])
for source in (local_tags, outer_tags):
    for data in ([dict(tagId=1, name={'id': 'name'}, descTextId='alternate', score=9)],
                 {'one': dict(tagId=1, nameTextId='name', desc=None, iconUrl='example', conflictId=None)},
                 [], {}, '{bad', None):
        files = {public_tags: {'tags': [tag]}, text_path: texts}
        if data is not None: files[source] = data
        add('contracts', files, ids=['1','2'])
add('contracts', {public_tags: {'tags': [tag]}, local_tags: [dict(tagId=1, score=3)],
                 outer_tags: [], text_path: texts}, ids=['1'])
add('contracts', {public_tags: {'tags': [tag]}, local_tags: [dict(tagId=1, score=3)],
                 outer_tags: '{bad', text_path: texts}, ids=['1'])
rng = random.Random(73512)
for index in range(40):
    rows = [dict(tagId=number, score=rng.choice(['1','0','1.0','1.5','bad',False,True,None]),
                 name=rng.choice([None, {'id': 'name'}, {'text': '内联名称'}, 'name', '直接保留']),
                 description=rng.choice([None, {'text': '内联说明'}, 'desc']),
                 icon=rng.choice([None, '', 'icon']), groupId=rng.choice([0,1,None]),
                 tagTerms=rng.choice([[], None, [dict(blackboard=[dict(key='k', value=number)])]])) for number in range(1,4)]
    add('contracts', {public_tags: {'tags': rows}, text_path: texts}, ids=['1','2','3','4'])

metadata_path = '_internal/data/akedata/skill/items/synthetic.json'
for data in (None, '{bad', [], {}, {'skillSpecification':None,'castType':True,'attackRangeType':[1,2]},
             {'$type':'Beyond.Gameplay.Core.ModifyDynamicBlackboard+Data','serverActionIndex':'1.0','key':'rate'},
             {'$type':'Beyond.Gameplay.Core.SimpleCalcBBAction.Data','serverActionIndex':1.0,'key':'rate'},
             {'first':{'$type':'ModifyDynamicBlackboard.Data','serverActionIndex':1,'key':'first'},
              'second':{'$type':'ModifyDynamicBlackboard.Data','serverActionIndex':1,'key':'second'}}):
    add('skill_metadata',{} if data is None else {metadata_path:data},ids=['synthetic','missing',''])
for action in (None,True,False,-1,0,1,1.0,1.5,'2','2.0','bad'):
    add('skill_metadata',{metadata_path:{'children':[{'$type':'ModifyDynamicBlackboard.Data','serverActionIndex':action,'key':'合成键'}]}},ids=['synthetic'])

weapon_path = '_internal/data/akedata/weapon/items/weapon_test.json'
weapon_manifest = '_internal/data/local_tables/weapon/manifest.json'
definition_path = '_internal/data/local_tables/weapon/items/weapon_test.json'
attack_path = '_internal/data/packet_semantics/weapon_static_attack_catalog.json'
weapon_row = dict(weaponId='weapon_test',title='合成武器',name='后备名称',weapontype=2,rarity=6,
                  baseAtk=[10,20.5,30],skilllist=[dict(id='skill_main')])
definition = dict(raw=dict(weaponSkillList=['skill_main','skill_bonus']))
attack_field = dict(weaponId='weapon_test',skillId='skill_main',modifyAttributeType='Specific',
                    formulaItem='BaseMultiplier',bbKey='atk',sourceRootSha256='a'*64,raw=dict(value=0.1))
attack_catalog = dict(schemaVersion=1,source='current_WeaponSkill_cardAttributeModifier',
                      decoder=resources._NATIVE_DAMAGE_SEMANTICS_BINDING,entries=[attack_field])
base_weapon_files = {weapon_path:weapon_row,weapon_manifest:dict(entries=[dict(weaponId='weapon_test',name='本地名称')]),
                     definition_path:definition,attack_path:attack_catalog}
add('weapons')
for value in (weapon_row, {}, [], None, '{broken', '\ufeff{}',
              dict(weapon_row,weaponId=None,title='',name='后备'),
              dict(weapon_row,weaponId=42,baseAtk={},skilllist=None)):
    add('weapons',{weapon_path:value})
for item in (dict(weaponId='weapon_test',name=''),dict(id='weapon_new',name='新增'),
             dict(weaponId='weapon_test',weaponType=0,rarity=0),
             dict(weaponId='weapon_test',weaponType=False,rarity=True),dict(weaponId=''),{},None,7):
    add('weapons',{**base_weapon_files,weapon_manifest:dict(entries=[None,7,item])})
for value in ({}, {'entries':[]}, [], '{broken'):
    add('weapons',{**base_weapon_files,weapon_manifest:value})
for value in (None,[],{},dict(raw=None),dict(raw={}),dict(raw=dict(weaponSkillList=[])),
              dict(raw=dict(weaponSkillList=['skill_main',7])),dict(raw=dict(weaponSkillList='skill_main')),'{broken'):
    add('weapons',{**base_weapon_files,definition_path:value})
for field, values in dict(weaponId=['wrong',None],skillId=['wrong',None],modifyAttributeType=['All',None],
                         formulaItem=['BaseFinalAddition','Other',None],bbKey=[None,7,''],
                         sourceRootSha256=['A'*64,'a'*63,'a'*65,None,'a'*64+'\n']).items():
    for value in values:
        altered=copy.deepcopy(attack_catalog); altered['entries']=[dict(attack_field,**{field:value})]
        add('weapons',{**base_weapon_files,attack_path:altered})
for field, values in dict(schemaVersion=[0,1.0,True,None],source=['wrong',None],decoder=[{},None,
                        {**resources._NATIVE_DAMAGE_SEMANTICS_BINDING,'extra':1}],entries=[[],None]).items():
    for value in values:
        add('weapons',{**base_weapon_files,attack_path:dict(attack_catalog,**{field:value})})
add('weapons',base_weapon_files)
add('weapons',{**base_weapon_files,definition_path:json.dumps(definition,indent=2)+'\n'})
for encoding in ('utf8','utf-8-sig','utf-16','utf-16-be','utf-32','utf-32-be'):
    add('weapons',{key:value for key,value in base_weapon_files.items() if key != definition_path},
        binary_files={definition_path:json.dumps(definition,ensure_ascii=False).encode(encoding)})
add('weapons',{**base_weapon_files,weapon_manifest:dict(entries=[dict(weaponId='weapon_test',name='第一次'),
    dict(weaponId='weapon_test',name='第二次',rarity=1)])})

suit_path = '_internal/data/akedata/equip/items/suit_test.json'
suit_local_path = '_internal/data/local_tables/equip/items/suit_test.json'
pieces_path = '_internal/data/local_tables/equip/pieces.json'
suit_row = dict(suitID='suit_test',套组名称='合成套装',技能描述='描述',value=dict(rate=0.2),
                equip=dict(piece=dict(itemId='piece',name='护具',部位='身体',rarity=6,主词条={'atk':1},副词条={'hp':2})))
local_suit = dict(suitID='suit_test',name='本地套装',skillDescription='本地描述',requiredPieceCount=3)
piece_row = dict(itemId='new_piece',name='新护具',suitID='suit_test',partName='手部',rarity=5,
    equipAttrModifiers=[dict(attrType=2,attrValue=0.5)],displayBaseAttrModifier=dict(attrType=1,attrValue=10),
    displayAttrModifiers=[dict(attrType=2,attrValue=1,enhancedAttrValues=[2,3]),None,dict(attrValue=4)])
for kind in ('suits','equipment'):
    add(kind)
    for value in (suit_row,{},[],None,'{broken','\ufeff{}',dict(suit_row,suitID=None),
                  dict(suit_row,套组名称='',name='后备',value=None),dict(suit_row,equip=[1,2])):
        add(kind,{suit_path:value})
    for key, values in dict(name=['',None,7],displayName=['其他',None],skillDescription=['',None,{}],
                            requiredPieceCount=[None,0,3,3.0,True],value=[None,{},[],{'rate':0.3}]).items():
        for value in values:
            add(kind,{suit_path:suit_row,suit_local_path:dict(local_suit,**{key:value})})
    for value in (local_suit,dict(local_suit,suitID='suit_other'),{},None,[], '{broken'):
        add(kind,{suit_path:suit_row,suit_local_path:value})
for value in (piece_row,dict(piece_row,itemId='piece'),dict(piece_row,itemId=None,id='fallback'),{},None,7):
    add('equipment',{suit_path:suit_row,suit_local_path:local_suit,
                     pieces_path:dict(entries=[value],sourceTableSha256='f'*64)})
for field, values in dict(displayBaseAttrModifier=[None,[],{},dict(attrType=0,attrValue=0)],
        displayAttrModifiers=[None,{},[],[None,dict(attrType=2,attrValue=0,enhancedAttrValues='AB')],
                             [dict(attrType=True,enhancedAttrValues={'x':1,'y':2})]],
        suitID=[None,'',0,'unknown'],equipAttrModifiers=[None,{},[],True],rarity=[None,0,True],
        itemId=['piece','',None,5]).items():
    for value in values:
        add('equipment',{suit_path:suit_row,suit_local_path:local_suit,
            pieces_path:dict(entries=[dict(piece_row,**{field:value})],sourceTableSha256=None)})
for value in ({},dict(entries=[]),dict(entries=[piece_row,piece_row]),[],None,'{broken'):
    add('equipment',{pieces_path:value})

character_manifest = '_internal/data/akedata/character/manifest.json'
local_character_manifest = '_internal/data/local_tables/character/manifest.json'
character_item = '_internal/data/akedata/character/items/char_test.json'
enemy_manifest = '_internal/data/akedata/enemy/manifest.json'
display_catalog = '_internal/data/local_static/skill/display_name_catalog.json'
packet_skill = '_internal/data/packet_semantics/skill_numeric_map.json'
local_skill = '_internal/data/akedata/skill/items/chr_0001_test_combo_a.json'
skill_queries = [None, '', 'unknown', 'chr_0001_test', 'eny_0001_test', '12', 'skill_12',
    'chr_0001_test_skill_12', 'chr_0001_test_combo_a', 'chr_0001_test_combo_b',
    'chr_0001_test_normal', 'chr_0017_yvonne_skill_162', 'chr_0017_yvonne_skill_163']
sample_character = dict(charId='chr_0001_test', charType='fallback_type',profession='fallback_profession',
    weapontype='fallback_weapon', skills=[dict(name='战技', skillIds=['chr_0001_test_normal'], groupType=2),
        dict(name='连携', skillIds=['chr_0001_test_combo_a','chr_0001_test_combo_b'], groupType=3,
             description='<@ba.pd> <@ba.natur> <@ba.fire> <@ba.physical> <@ba.natural>')])
official_names = dict(schemaVersion=1, source='official_CharGrowth_I18n_typed_skill_display',
    decoder=names._CURRENT_TYPED_RESOURCE_BINDING,
    entries={'chr_0001_test_combo_a':dict(displayName=' 官方连携 ', proofKind='official_char_growth_skill_list')}, conflicts={})
sample_files = {character_manifest:[dict(charId='chr_0001_test', name='来源角色')],
    local_character_manifest:dict(entries=[dict(charId='chr_0001_test', name='本地角色',charTypeId='fire',
        charTypeName='火',professionName='职业',weaponTypeName='长柄')]),
    character_item:sample_character,enemy_manifest:[dict(templateId='eny_0001_test',name='合成敌人')],
    display_catalog:official_names,local_skill:dict(skillSpecification='Damage'),
    local_number:dict(skill_id=dict(dic={'12':'chr_0001_test_combo_a'})),
    packet_skill:dict(mappings={'12':dict(canonical_skill_id='chr_0001_test_combo_a', display_name='包名称')},
        canonical_display_names={'chr_0001_test_combo_a':'保留长名称'})}
for kind in ('display_names','skill_profiles','character_profiles'):
    add(kind, ids=skill_queries)
    add(kind, sample_files, ids=skill_queries)
    for path in (character_manifest,local_character_manifest,enemy_manifest,character_item,display_catalog,packet_skill,local_skill):
        for value in (None, [], {}, '{broken', '\ufeff{}'):
            add(kind, {**sample_files,path:value}, ids=skill_queries)
for shape in ([None,1,dict(charId='chr_0001_test',name='😀'),dict(charId=7,name=True)],
              dict(entries=[dict(charId='chr_0001_test',name='源角色')]), dict(entries='wrong')):
    add('display_names',{**sample_files,character_manifest:shape},ids=skill_queries)
for field, values in dict(groupType=[None,0,2,3,3.9,True,'3','３','3.0','3_0','bad',float('nan'),float('inf')],
    skillIds=[None,[],['chr_0001_test_combo_b','chr_0001_test_combo_a'],['',None,0,7,True],'AB'],
    name=['',None,False,7],description=[None,0,[],{},'<@ba.pulse> <@ba.cryst>']).items():
    for value in values:
        file = dict(sample_character,skills=[dict(sample_character['skills'][1],**{field:value})])
        for kind in ('display_names','skill_profiles'):
            add(kind,{**sample_files,character_item:file},ids=skill_queries)
for field, values in dict(schemaVersion=[None,0,1.0,True,'1'],source=[None,'wrong'],decoder=[None,{},dict(names._CURRENT_TYPED_RESOURCE_BINDING,extra=True)],
    entries=[None,[],{},{'chr_0001_test_combo_a':dict(displayName='\u001c官方😀\u001f',proofKind='typed_enabled_creation_path')},
        {'chr_0001_test_combo_a':dict(displayName=' ',proofKind='official_char_growth_skill_list')},
        {'chr_0001_test_combo_a':dict(displayName='无效',proofKind='guessed')}],
    conflicts=[None,[],{}, {'chr_0001_test_combo_a':[]},{'chr_0017_yvonne_skill_162':False}]).items():
    for value in values:
        add('display_names',{**sample_files,display_catalog:dict(official_names,**{field:value})},ids=skill_queries)
for labels in (['A','😀'],['😀','AA'],['A😀','ABC'],['\u001c中\u001f','中😀']):
    mappings = {str(i):dict(canonical_skill_id='other',display_name=label) for i,label in enumerate(labels)}
    add('display_names',{**sample_files,packet_skill:dict(mappings=mappings,canonical_display_names={'other':'X'})},ids=skill_queries+['other'])
for kind in ('display_names','skill_profiles','character_profiles'):
    for path in (local_character_manifest,character_item,enemy_manifest,display_catalog,packet_skill,local_skill):
        add(kind,{key:value for key,value in sample_files.items() if key!=path},ids=skill_queries,binary_files={path:b'\xff\xfe\x00\xd8'})

if args.bundled:
    cases.clear()
    relative = '_internal/data/runtime-data.zip'
    archive_path = reference/relative
    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    if metadata['files'][relative]['sha256'] != digest:
        raise ValueError('Reference runtime data bundle changed')
    dependencies[relative] = digest
    with zipfile.ZipFile(archive_path) as archive:
        prefixes = ('data/akedata/dungeon/', 'data/local_tables/dungeon/',
                    'data/akedata/weapon/', 'data/local_tables/weapon/',
                    'data/akedata/equip/', 'data/local_tables/equip/',
                    'data/akedata/character/', 'data/local_tables/character/', 'data/akedata/enemy/')
        filenames = {'data/local_tables/dungeon_catalog.json', 'data/local_tables/NumIdStrTable.json',
                     'data/local_static/skill/damage_element_catalog.json', 'data/public/contract_tags.json',
                     'data/packet_semantics/weapon_static_attack_catalog.json',
                     'data/packet_semantics/skill_numeric_map.json', 'data/local_static/skill/display_name_catalog.json'}
        actual_files = {'_internal/'+name: archive.read(name).decode('utf8') for name in archive.namelist()
                        if name.startswith(prefixes) or name in filenames}
        actual_buff = archive.read('data/local_static/buff/typed_roots.json.gz')
    add('dungeons', {key:value for key,value in actual_files.items() if 'dungeon' in key}, ids=ids)
    add('numbers', {key:value for key,value in actual_files.items() if 'NumIdStrTable' in key})
    add('profiles', {key:value for key,value in actual_files.items() if 'damage_element_catalog' in key})
    add('buff_roots', {key:value for key,value in actual_files.items() if 'damage_element_catalog' in key},binary_files={buff_path:actual_buff})
    tag_document = json.loads(actual_files['_internal/data/public/contract_tags.json'])
    tags = tag_document.get('tags') if isinstance(tag_document,dict) else tag_document
    tag_rows = tags.values() if isinstance(tags,dict) else tags
    tag_ids = [str(row.get('tagId') or row.get('tag_id')) for row in tag_rows if isinstance(row,dict)]
    add('contracts', {key:value for key,value in actual_files.items() if 'contract_tags' in key}, ids=tag_ids)
    for kind in ('weapons','suits','equipment'):
        add(kind,{key:value for key,value in actual_files.items() if '/weapon/' in key or '/equip/' in key or key.endswith('/weapon_static_attack_catalog.json')})
    character_files = {key:value for key,value in actual_files.items() if '/character/' in key or '/enemy/' in key or key.endswith(('/NumIdStrTable.json','/display_name_catalog.json','/skill_numeric_map.json'))}
    character_rows = json.loads(character_files[local_character_manifest])
    query_ids = [row['charId'] for row in character_rows['entries']]+skill_queries
    add('display_names',character_files,ids=query_ids)
    add('character_profiles',character_files)
    skill_files = {**character_files}
    with zipfile.ZipFile(archive_path) as archive:
        for key in archive.namelist():
            if key.startswith('data/akedata/skill/items/') and key.endswith('.json'):
                skill_files['_internal/'+key] = archive.read(key).decode('utf8')
    queries = [key.rsplit('/',1)[1][:-5] for key in skill_files if '/skill/items/' in key]+skill_queries
    add('skill_profiles',skill_files,ids=queries)
    target = args.output
else:
    target = args.output or root/'_internal/dotnet/Specs/Fixtures/catalogs.json'
target.parent.mkdir(parents=True, exist_ok=True)
record = target.with_suffix('.reference.json')
target.write_text(json.dumps(cases, ensure_ascii=False, separators=(',', ':')), encoding='utf8')
record.write_text(json.dumps(dict(cases=len(cases), source_head=metadata['head'], dependencies=dependencies), indent=2), encoding='utf8')
print('Catalog fixtures:', len(cases))
