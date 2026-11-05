"""Compare exact packet combo windows against the immutable Python reference."""
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
from types import ModuleType
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    output = args.output or Path(__file__).resolve().parents[3] / '_internal/dotnet/Specs/Fixtures/combo-windows.json'
    metadata = json.loads(args.manifest.read_text(encoding='utf8'))
    dependencies = {}
    prefix = '_internal/packages/parser_core/parser_core/'

    def pinned(relative):
        data = (args.reference / relative).read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest != metadata['files'][relative]['sha256']:
            raise ValueError('Fixed combo reference changed: ' + relative)
        dependencies[relative] = digest
        return data

    for relative in metadata['files']:
        if relative.startswith(prefix) and relative.endswith('.py'):
            pinned(relative)
    package = ModuleType('parser_core')
    package.__path__ = [str(args.reference / prefix)]
    sys.modules['parser_core'] = package
    imbue = importlib.import_module('parser_core.effects.imbue')
    approval = importlib.import_module('parser_core.effects.approval')
    packet = importlib.import_module('parser_core.catalog.packet_semantics')
    trigger = 'buff_common_affixes_combo_trigger'
    middle = 'buff_common_affixes_skillimbue'
    modifier = 'buff_common_affixes_skillimbue_atk'
    # Reuse the already reviewed synthetic chain builders, without importing a test module or its dependencies.
    relative = '_internal/packages/parser_core/tests/mechanics/test_rdps_combo_packet_chain.py'
    tree = ast.parse(pinned(relative).decode('utf8'))
    helpers = ast.Module(body=[node for node in tree.body if isinstance(node, ast.FunctionDef)
                              and node.name in {'combo_chain', 'combo_hit'}], type_ignores=[])
    scope = dict(TRIGGER=trigger, IMBUE=middle, MODIFIER=modifier, SESSION='synthetic-combo-session')
    exec(compile(helpers, relative, 'exec'), scope)
    chain, hit = scope['combo_chain'], scope['combo_hit']
    archive_path = '_internal/data/runtime-data.zip'
    pinned(archive_path)
    with zipfile.ZipFile(args.reference / archive_path) as bundle:
        payload = json.loads(gzip.decompress(bundle.read('data/local_static/buff/typed_roots.json.gz')))['entries']
    roots = {key:payload[key]['root'] for key in [trigger, middle, modifier]}
    registry = json.loads(pinned('_internal/data/packet_semantics/rdps_semantics_registry.json'))
    current = {}
    imbue._load_current_buff_roots = lambda: current['roots']
    imbue._load_num_id_str_buff_map = lambda: current.get('numbers', {})
    approval._load_current_buff_roots = imbue._load_current_buff_roots
    approval._load_num_id_str_buff_map = imbue._load_num_id_str_buff_map
    approval._load_num_id_str_skill_map = lambda: {}
    approval._load_rdps_semantics_registry = lambda: current['registry']

    def encode(value):
        if type(value) is int: return {'int': str(value)}
        if type(value) is float: return {'f64': struct.pack('>d', value).hex()}
        if isinstance(value, (list, tuple)): return [encode(item) for item in value]
        if isinstance(value, dict): return {str(key):encode(item) for key,item in value.items()}
        return value

    cases = []
    def add(label, hits=None, records=None, changed_roots=None, changed_registry=None, numbers=None):
        config = dict(hits=[hit()] if hits is None else hits, records=chain() if records is None else records)
        if changed_roots is not None: config['roots'] = changed_roots
        if changed_registry is not None: config['registry'] = changed_registry
        if numbers is not None: config['numbers'] = numbers
        current.clear()
        current.update(roots=copy.deepcopy(config.get('roots', roots)), registry=copy.deepcopy(config.get('registry', registry)),
                       numbers=config.get('numbers', {}))
        packet._RDPS_VERIFIED_INDEX = None
        actual_hits, actual_records = copy.deepcopy(config['hits']), copy.deepcopy(config['records'])
        try:
            windows = imbue._build_special_combo_windows(actual_hits, actual_records, battle_end_ms=2000)
            expected = dict(hits=actual_hits, windows=windows)
        except (TypeError, ValueError, OverflowError, AttributeError) as error:
            expected = dict(error=type(error).__name__)
        if encode(actual_records) != encode(config['records']):
            raise AssertionError('Reference changed BUFF records')
        cases.append(dict(name=f'{label}/{len(cases)}', config_json=json.dumps(config, ensure_ascii=True), expected=encode(expected)))

    add('valid')
    for mask, rate in itertools.product([0x100, 0x200, 0x300, 0x80, 0, -1, None, False, '256'], [.1,.2,.3,.5]):
        add('scope-rate', [hit(mask=mask)], chain(rate=rate))
    for mask, source in itertools.product([0x100,0x200,0x80,None],
            ['current_typed_skill_or_buff_exact_unit_generation_only','guessed',None]):
        row = hit(mask=None)
        row.update(static_damage_decorate_mask=mask, static_damage_decorate_mask_source=source)
        add('static-scope', [row])
    for field, values in dict(packet_session_id=[None,'','other',1], packet_seq_id=[None,-1,True,11,12,2**65],
                              ts_ms=[None,True,1199,1200,2000,2001], line_no=[None,0,True,30,31,200,201],
                              source_actor_id=['other','0200'],character_key=['other',None]).items():
        for value in values:
            row=hit(); row[field]=value
            add('hit-'+field,[row])
    for index in [None,True,False,1,-1,0.0]:
        row=hit(); row['packet_modifier_handles']['attacker'][0]['index']=index
        add('modifier-index',[row])
    for position in [0,1,2]:
        for field, values in dict(uid=['',None,1,'010001',str(2**64)],source_actor_id=['101',100,None],
                target_actor_id=['201',200,None],source_character_key=['other','',None],target_character_key=['other',None],
                ts_ms=[True,1600],line_no=[True,999],end_ts_ms=[1000,1500],end_line_no=[None,49,50,51],
                rdps_live_identity_conflict=[True],rdps_dynamic_identity_conflict=[True]).items():
            for value in values:
                records=chain(); records[position][field]=value
                add(f'record-{position}-{field}',records=records)
        records=chain(); records.append(copy.deepcopy(records[position])); add('ambiguous-instance',records=records)
    for position in [1,2]:
        for field, values in dict(_boundCreateRecord=[False,1],buffUid=['wrong'],buffTemplate=['wrong'],sourceActorId=['101'],
                targetActorId=['201'],environmentType=['Skill'],ownerType=[None,2,1],environmentInstId=['',None,'01','1'],
                templateStrId=['wrong',None],templateIntId=[True,202],actionId=[True,3],operationSeq=[None,True,99],triggerType=[None,1]).items():
            for value in values:
                records=chain(); records[position]['origin_observations'][0][field]=value
                add('origin-'+field,records=records)
        records=chain(); records[position]['origin_observations']=[]; add('missing-origin',records=records)
        records=chain(); records[position]['origin_observations'].append(copy.deepcopy(records[position]['origin_observations'][0])); add('duplicate-origin',records=records)
        for field, values in dict(sessionId=['other',None],operationSeq=[None,True,99],sourceEvent=['other'],buffUid=['wrong'],
                assignedItems=[None,[],[{}],[dict(target_key='imbue_scale',use_direct_value=False,numeric_value=.2)],
                [dict(target_key='imbue_scale',use_direct_value=True,numeric_value=-.2)],
                [dict(target_key='imbue_scale',use_direct_value=True,numeric_value=float('nan'))]],bb_conflicts=[['*'],['imbue_scale']],
                ts_ms=[None,True,1600],line_no=[None,True,999]).items():
            for value in values:
                records=chain(); records[position]['creation_observations'][0][field]=value
                add('anchor-'+field,records=records)
        records=chain(); records[position]['creation_observations']=[]; add('missing-anchor',records=records)
        records=chain(); origin=records[position]['origin_observations'][0]
        origin.update(templateStrId=None,templateIntId=202)
        add('numeric-parent',records=records,numbers={'202':trigger if position==1 else middle})
    for rate in [None,False,True,0,-1,.1,.3,'0.2',float('nan'),float('inf')]:
        records=chain(); records[2]['creation_observations'][0]['assignedItems'][0]['numeric_value']=rate
        add('forward-rate',records=records)
    for states in [[],[dict(operationSeq=19,enabled=True)],[dict(operationSeq=19,enabled=False)],
            [dict(operationSeq=19,enabled=True),dict(operationSeq=19,enabled=False)],[dict(operationSeq=21,enabled=False)],
            [dict(operationSeq=18,enabled=False),dict(operationSeq=19,enabled=True)]]:
        records=chain(); records[2]['enable_observations']=states; add('enable',records=records)
    for change in ['conflicting-rate','conflicting-boundary','conflicting-parent','disabled-conflict','duplicate-anchor']:
        records=chain(); final=records[2]
        if change=='conflicting-parent':
            row=copy.deepcopy(final['origin_observations'][0]); row['environmentInstId']='999'; final['origin_observations'].append(row)
        elif change=='disabled-conflict': final['rdps_conflicting_enable_state']=True
        else:
            row=copy.deepcopy(final['creation_observations'][0])
            if change=='conflicting-rate': row['assignedItems'][0]['numeric_value']=.3
            if change=='conflicting-boundary': row['line_no']+=1
            final['creation_observations'].append(row)
        add(change,records=records)
    for position in [0,1,2]:
        records=chain(); records[position]['snapshot_end_ts_ms']=1200; records[position]['snapshot_end_line_no']=30
        add('snapshot-cutoff',records=records)
    row=hit(); row['packet_modifier_handles']['attacker']*=2; add('duplicate-handle',[row])
    row=hit(); row['packet_modifier_handles']['attacker'].append(dict(buff_inst_id='10003',index=0,processor_debug_args={'other':1})); add('conflicting-handle',[row])
    for order in itertools.permutations(['10003','20003']):
        row=hit(); row['packet_modifier_handles']['attacker']=[dict(buff_inst_id=uid,index=0,processor_debug_args={}) for uid in order]
        add('two-providers',[row],chain()+chain(rate=.1,source='chr_0015_lifeng',source_actor='101',first_uid=20001))
    add('same-ms-hits',[hit(),hit(seq=21,line=51)])
    row=hit(seq=21,line=51); row['packet_modifier_handles']['attacker']=[]; add('no-spill',[hit(),row])
    for missing in [trigger,middle,modifier]:
        changed=copy.deepcopy(roots); changed.pop(missing); add('missing-root',changed_roots=changed)
    # Mutate the resource contract itself, including disabled outer actions and wrong forwarding operands.
    def walk(value):
        if isinstance(value,dict):
            yield value
            for child in value.values(): yield from walk(child)
        elif isinstance(value,list):
            for child in value: yield from walk(child)
    for parent,index in [(trigger,4),(middle,0)]:
        for field,value in [('isEnable',False),('buffSource','Owner'),('serverActionIndex',True)]:
            changed=copy.deepcopy(roots)
            action=next(row for row in walk(changed[parent]) if row.get('$type')=='Beyond.Gameplay.Core.CreateBuffAction.Data' and row.get('serverActionIndex')==index)
            action[field]=value; add('creation-contract-'+field,changed_roots=changed)
    for field,value in [('zoneName','Other'),('side','Defender'),('addition',dict(useBlackboardKey=False,blackboardKey='real_imbue_scale'))]:
        changed=copy.deepcopy(roots); changed[modifier]['damageModifier'][0]['damageProcessors'][0][field]=value
        add('processor-contract-'+field,changed_roots=changed)
    for index,field,value in [(0,'$type','Other'),(1,'mask',0x100),(1,'checkType','HasAll'),(2,'isEnable',False)]:
        changed=copy.deepcopy(roots); changed[modifier]['damageModifier'][0]['condition']['actionData'][index][field]=value
        add('condition-contract-'+field,changed_roots=changed)
    for branch_name,field,value in [('conditionAction','mask',0x200),('succeedActions','operation','Add'),
            ('succeedActions','key','other'),('failActions','directValue',False),('failActions','operation','Add')]:
        changed=copy.deepcopy(roots)
        changed[modifier]['damageModifier'][0]['condition']['actionData'][2][branch_name]['actionData'][0][field]=value
        add('branch-contract-'+field,changed_roots=changed)
    for value in [None,False,0,-1,.5,2,'1.5',float('nan'),float('inf')]:
        changed=copy.deepcopy(roots)
        changed[modifier]['damageModifier'][0]['condition']['actionData'][2]['succeedActions']['actionData'][0]['value2']['value']=value
        add('skill-factor-contract',changed_roots=changed)
    add('no-approval',changed_registry={})
    fixture=dict(roots_json=json.dumps(roots,ensure_ascii=True),registry_json=json.dumps(registry,ensure_ascii=True),cases=cases)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(fixture,ensure_ascii=True,separators=(',',':')),encoding='utf8')
    output.with_suffix('.reference.json').write_text(json.dumps(dict(source_head=metadata['head'],cases=len(cases),dependencies=dependencies),indent=2),encoding='utf8')
    print('Combo window fixtures:',len(cases))


if __name__=='__main__': main()
