"""Ordered HP, entity and packet evidence against the fixed Python implementation."""
from datetime import date
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[3]
                        / '_internal/dotnet/Specs/Fixtures/hit-observations.json')
    args = parser.parse_args()
    metadata = json.loads(args.manifest.read_text(encoding='utf8'))
    prefix = '_internal/packages/parser_core/parser_core/'
    dependencies = {}
    for relative, expected in metadata['files'].items():
        if relative.startswith(prefix) and relative.endswith('.py'):
            digest = hashlib.sha256((args.reference / relative).read_bytes()).hexdigest()
            if digest != expected['sha256']:
                raise ValueError('Fixed hit reference changed: ' + relative)
            dependencies[relative] = digest
    package = ModuleType('parser_core')
    package.__path__ = [str(args.reference / prefix)]
    sys.modules['parser_core'] = package
    hits = importlib.import_module('parser_core.ingestion.hits')
    entities = importlib.import_module('parser_core.ingestion.entities')
    packets = importlib.import_module('parser_core.ingestion.packet_evidence')
    buff_observations = importlib.import_module('parser_core.ingestion.buff_observations')
    mapping = importlib.import_module('parser_core.effects.packet_mapping')
    packet_catalog = importlib.import_module('parser_core.catalog.packet_semantics')
    enemy_status = importlib.import_module('parser_core.effects.enemy_status')
    names = importlib.import_module('parser_core.catalog.names')
    skill_ids = importlib.import_module('parser_core.ingestion.skill_identity')
    elements = importlib.import_module('parser_core.effects.damage_types')
    state_module = importlib.import_module('parser_core.ingestion.state')
    current = {}
    names._load_num_id_str_skill_map = lambda: current.get('skills', {})
    skill_ids._load_num_id_str_buff_map = lambda: current.get('buffs', {})
    skill_ids._load_official_skill_damage_catalog = lambda: current.get('identity_profiles', {})
    units_for = lambda key: {int(k): v for k, v in current.get('units', {}).get(names._canonical_packet_skill_id(key), {}).items()}
    hits._load_skill_action_damage_units = units_for
    elements._load_skill_action_damage_units = units_for
    hits._resolve_character_name = lambda key: current.get('names', {}).get(key)
    hits._resolve_enemy_name = lambda key: current.get('names', {}).get(key)
    hits._resolve_skill_name = lambda key: current.get('names', {}).get(key)
    hits._resolve_skill_profile = lambda key: current.get('profiles', {}).get(names._canonical_packet_skill_id(key))
    hits._load_current_buff_roots = lambda: current.get('roots', {})
    enemy_status._load_current_buff_roots = lambda: current.get('roots', {})
    buff_observations._load_current_buff_roots = lambda: current.get('roots', {})
    buff_observations._load_num_id_str_buff_map = lambda: current.get('buffs', {})
    mapping._load_packet_numeric_buff_map = lambda: current.get('numeric', {})
    mapping._load_num_id_str_buff_map = lambda: current.get('buffs', {})
    mapping._load_mechanism_registry_by_buff_id = lambda: current.get('mechanisms', {})
    def canonical_mapping():
        groups = {}
        for row in current.get('numeric', {}).values():
            if row.get('canonical_buff_id'):
                groups.setdefault(str(row['canonical_buff_id']), []).append(row)
        return {key: packet_catalog._merge_packet_buff_mapping_rows(rows) for key, rows in groups.items()}
    mapping._load_packet_canonical_buff_map = canonical_mapping

    def encode(value):
        if type(value) is int:
            return {'int': str(value)}
        if type(value) is float:
            return {'f64': struct.pack('>d', value).hex()}
        if isinstance(value, (list, tuple)):
            return [encode(item) for item in value]
        if isinstance(value, dict):
            return {str(key): encode(item) for key, item in value.items()}
        if isinstance(value, set):
            return [encode(item) for item in sorted(value)]
        return value

    def snapshot(state):
        result = dict(hits=state.hits, unresolved=state.unresolved_hits,
            indices={str(key): next(index for index, hit in enumerate(state.hits) if hit is value)
                     for key, value in state.hits_by_seq.items()},
            enemies=dict(state.enemy_counter), hp=state.last_enemy_hp_by_target, roster=state.roster_order,
            participants=dict(state.participant_totals), skills=list(state.skill_totals.values()),
            baselines=state.baseline_by_character, modifier_last_seen=state.packet_modifier_last_seen_by_uid,
            loadouts=state.loadout_by_char, suits=state.active_suits_by_char, weapons=state.active_weapons_by_char)
        if current.get('mixed'):
            def index(record):
                return next((index for index, row in enumerate(state.buff_starts) if row is record), None)
            result['buffs'] = dict(records=[{key: value for key, value in row.items() if not key.startswith('_')}
                                           for row in state.buff_starts],
                active={key:index(value) for key,value in state.active_buff_starts_by_uid.items()},
                pending=index(state.pending_buff_record), pending_modifiers=dict(state.pending_attr_mods),
                unresolved=state.unresolved_buff_actions)
        return result

    cases = []

    def add(name, operations, **config):
        current.clear()
        current.update(config)
        state = state_module.IngestionState(reference_date=date(2026, 10, 27), first_hit_hint_ms=None,
            last_hit_hint_ms=None, context_enemy_hint=None, trace_identity_inference_seen=False,
            loadout_override_by_char=None, critical_attributes_override_by_actor=None)
        state.loadout_by_char = copy.deepcopy(config.get('loadouts', {}))
        state.active_suits_by_char = {key: set(value) for key, value in config.get('suits', {}).items()}
        state.active_weapons_by_char = dict(config.get('weapons', {}))
        steps = []
        normalized = []
        for index, operation in enumerate(operations):
            operation = dict(line=operation) if isinstance(operation, str) else dict(operation)
            operation.setdefault('number', index + 1)
            operation.setdefault('time', (index + 1) * 100)
            normalized.append(operation)
            line, number, timestamp = operation['line'], operation['number'], operation['time']
            handled = (entities.consume_entity_observation(state, line, number, timestamp)
                       or config.get('mixed') and buff_observations.consume_buff_observation(state, line, number, timestamp)
                       or config.get('mixed') and buff_observations.consume_buff_blackboard(state, line, number, timestamp)
                       or packets.consume_packet_evidence(state, line, number, timestamp)
                       or hits.consume_hit_and_buff_lifecycle(state, line, number, timestamp))
            steps.append(encode(dict(handled=handled, state=snapshot(state))))
        cases.append(dict(name=name, config=config, operations=normalized, expected=steps))

    actor = 'chr_0001_alpha'
    other = 'chr_0002_beta'
    enemy = 'eny_0001_test'

    def hit(seq=1, **changes):
        fields = dict(src=actor, atk=actor, tgt=enemy, atkId='11', tgtId='22', skill='skill_test',
                      hit=100, eHP=1000, critFlag=0, hits=1, actionId=1, damageUnitIndex=0,
                      packetSeq=9, packetSessionId='session')
        fields.update(changes)
        return (' HP_V2 ' + (f'#{seq} ' if seq is not None else '')
                + ' '.join(f'{key}={value}' for key, value in fields.items() if value is not None))

    add('basic/all-fields', [hit(skillLv=3, templateIntId=4, origTemplateIntId=5, eventInstId='111',
        eventOwnerId='112', packetOwnerId=str(2**64 - 1), packetGeneration=0, clientTick=123,
        partInstId=4, raw='123.5', packetFinalValue='122.5', dynBB='1:-0.0;2:3', calcBB='1:x=4;1:y=value'),
        hit(2, hit=200, eHP=700, critFlag=1)], names={actor:'合成角色', enemy:'合成敌人', 'skill_test':'合成技能'})
    for field in ('src', 'atk', 'tgt'):
        for value in (None, 'unknown', enemy, actor, other, 'id_11', actor + '_12', 'eny_0001_test_extra'):
            add(f'actor/{field}/{value}', [hit(**{field: value})])
    for value in (None, '', '0', '00', '-1', '1', '01', '1.0', '1e0', str(2**80), '١'):
        add('ids/' + str(value), [hit(atkId=value, tgtId=value, eventInstId=value, eventOwnerId=value,
                                    packetOwnerId=value, packetGeneration=value, packetSeq=value,
                                    clientTick=value, actionId=value, damageUnitIndex=value)])
    for value in (None, '', 'bad', '0', '-1', '1', '1.0', '2e2', '3.5', str(2**100), 'NaN', 'Infinity'):
        add('values/' + str(value), [hit(hit=value, raw=value, packetFinalValue=value, eHP=value,
            critFlag=value, hits=value, skillLv=value, templateIntId=value, origTemplateIntId=value, partInstId=value)])
    add('overkill/dead', [hit(eHP=50), hit(2, eHP=-50), hit(3, eHP=0), hit(4, hit=-2, eHP=-2), hit(5, eHP=500)])
    add('overkill/two-actors', [hit(eHP=50), hit(2, tgtId='23', eHP=40), hit(3, eHP=0), hit(4, tgtId='23', eHP=0)])
    add('overkill/missing-hp', [hit(eHP=20), hit(2, eHP=None), hit(3, eHP=0)])
    add('overkill/template-fallback', [hit(eHP=20, tgtId=None), hit(2, eHP=0, tgtId='0'), hit(3, eHP=0, tgtId=None)])
    add('sequence/duplicate', [hit(), ' BASELINE #1 1=5 2=6', hit(hit=200), ' BASELINE #1 1=7', hit(None)])
    add('baseline/ignored-before-hit', [' BASELINE #1 1=5', hit(), hit(2)])
    add('packets/shared-hit', [hit(), ' BASELINE #1 1=5', hit(2),
        ' PKT_MOD #1 atk=[31 32] def=[41]', ' PKT_ATTR #1 atk=[9:0.5] def=[]',
        ' PKT_ATTR_INFO #1 {"reportPresent":true,"packetSeq":9,"packetSessionId":"session"}',
        ' PKT_MOD_DETAIL #1 {"attacker":[{"index":0,"buff_inst_id":31}],"defender":[],"packetSeq":9}',
        ' PKT_ATTR_INFO #1 {"reportPresent":false}',
        ' DPD_RAW #1 calc=95 atkScale=1 blocked=0 damageType=0x1 decorateMask=0x0 collider="x" atkZones=[] defZones=[]'])
    add('packets/session-mismatch', [hit(), ' PKT_ATTR_INFO #1 {"reportPresent":true,"packetSessionId":"other"}',
        ' PKT_MOD_DETAIL #1 {"attacker":[],"defender":[],"packetSeq":10}'])
    for value in (None, '', '1:2', '1:2,1:3;2:-0.0', '1e0:3;bad:4;2:NaN;3:Infinity', '1:2:3', '-1:-2'):
        add('blackboard/' + str(value), [hit(dynBB=value, calcBB=value)])
    add('blackboard/calculation', [hit(calcBB='1:a=3;1:b=-0.0;1:a=5;2:=bad;bad:x=4;2:x=NaN;3:y=a=b')])
    stats = f' ENTITY_STATS id=11 template={actor} kind=character level=30 attrs=[1:200/150 9:0.2 10:0.5]'
    target_stats = f' ENTITY_STATS id=22 template={enemy} kind=enemy level=40 attrs=[3:100 4:1 5:0.8 94:10 98:20]'
    add('entities/full-partial-copy', [stats, target_stats, hit(),
        f' ENTITY_ATTR_UPDATE id=11 template={actor} kind=character attrs=[9:0.4]', hit(2),
        f' ENTITY_ATTR_UPDATE id=11 template={actor} kind=character attrs=[9:bad]', hit(3)])
    add('entities/wrong-binding', [stats.replace(actor, other), target_stats.replace(enemy, 'eny_0002_other'), hit()])
    add('entities/wrong-kind', [stats.replace('kind=character', 'kind=enemy'), hit()])
    add('entities/empty', [stats[:stats.index('attrs=')] + 'attrs=[]', target_stats[:target_stats.index('attrs=')] + 'attrs=[]', hit()])
    add('entities/invalid-attributes', [stats.replace('1:200/150', '1:200/150 1:300'),
        target_stats.replace('3:100', '3:100 3:200'), hit()])
    add('entities/time-order', [dict(line=stats, time=500), dict(line=target_stats, time=400),
        dict(line=hit(), time=300), dict(line=stats.replace('1:200', '1:300'), time=200),
        dict(line=hit(2), time=450), dict(line=hit(3), time=600)])
    unit = dict(index=0, element='fire', damage_attribute_type='hp', damage_decorate_mask=0x4000,
                damage_decorate_mask_source='current_typed_skill_or_buff_exact_unit_generation_only',
                damage_calculation=dict(source='synthetic', damageProcessors=[]))
    add('units/exact', [hit(), hit(2, actionId=None), hit(3, damageUnitIndex=None)], units={'skill_test':{'1':[unit]}},
        profiles={'skill_test':dict(group_type=3, family_skill_key='skill_family')})
    add('units/ambiguous', [hit()], units={'skill_test':{'1':[unit, unit]}})
    add('units/mixed-attribute', [hit()], units={'skill_test':{'1':[unit, dict(unit, damage_attribute_type='poise')]}})
    add('units/weapon-alias', [hit(skill='sk_wpn_lance_0010')])
    for skills, buffs in (({'7':'skill_test'}, {}), ({}, {'7':'buff_test'}), ({'7':'skill_test'}, {'7':'buff_test'})):
        for template in (None, 'skill', 'buff', 'unknown'):
            add(f'numeric/{len(cases)}', [hit(skill='skill_7', templateType=template)], skills=skills, buffs=buffs,
                identity_profiles={'buff_test':dict(actions={'1':[dict(index=0, element='fire', damageAttribute='hp')]})})
    add('loadout/present', [hit(), hit(2, src=other, atk=other)], loadouts={actor:dict(weapon_template='weapon_test')},
        suits={actor:['suit_test']}, weapons={actor:'weapon_test'})
    add('loadout/absent', [hit()], suits={actor:['suit_test']}, weapons={actor:'weapon_test'})
    def buff(uid='31', **changes):
        fields = dict(uid=uid, id='buff_test', owner=enemy, ownerId='22', src=actor, srcId='11')
        fields.update(changes)
        return ' BUFF_START ' + ' '.join(f'{key}={value}' for key, value in fields.items() if value is not None)
    def mixed(name, operations, **config):
        add('mixed/' + name, operations, mixed=True, **config)
    mixed('roster', [buff(src=other),hit(),buff(uid='32',owner=actor,ownerId='11',src=other),hit(2,src=other,atk=other)])
    mixed('hp-clears-pending',[buff(),' BB[ rate=0.2 ]',hit(),' BB[ rate=0.4 ]'])
    mixed('enemy-hp-retains-pending',[buff(),hit(src=enemy,atk=enemy,tgt=actor),' BB[ rate=0.4 ]'])
    mixed('unknown-hp-retains-pending',[buff(),hit(src='unknown',atk=None),' BB[ rate=0.4 ]'])
    mixed('conflicting-hp-retains-pending',[buff(),hit(src=other),' BB[ rate=0.4 ]'])
    mixed('packet-retains-pending',[hit(),buff(),' BASELINE #1 1=5',' BB[ rate=0.4 ]'])
    mixed('ordinary-clears-pending',[buff(),'ordinary',' BB[ rate=0.4 ]'])
    mixed('attr-mod-clears-pending',[buff(),' ATTR_MOD buff=buff_other attrType=4 bbKey=x val=0.2',' BB[ rate=0.4 ]',buff(id='buff_other')])
    mixed('hp-with-attr-mod',[buff(),hit(src='unknown',atk=None)+' ATTR_MOD buff=buff_test attrType=4 bbKey=x val=0.2',
        ' BB[ rate=0.4 ]',buff(uid='32')])
    mixed('invalid-buff-clears-pending',[buff(),buff(uid='32',src='unknown',owner='unknown'),' BB[ rate=0.4 ]'])
    mixed('buff-end-pending',[buff(),' BUFF_END uid=31',' BB[ rate=0.4 ]',hit()])
    mixed('stale-loadout-clears-buff-guards',[buff(id='7'),hit(src=other,atk=other),buff(uid='32',id='7')],
        loadouts={actor:dict(weapon_template='wpn_A')}, weapons={actor:'wpn_A'}, suits={actor:['suit_A']},
        numeric={'7':dict(canonical_buff_id='buff_test',weapon_id='wpn_A')})
    mixed('loadout-preserved',[buff(),hit(),buff(uid='32')],loadouts={actor:dict(weapon_template='wpn_A')},weapons={actor:'wpn_A'})
    mixed('source-weapon-snapshot',[buff(),hit(src=other,atk=other),buff(uid='32')],
        loadouts={actor:dict(weapon_template='wpn_A')},weapons={actor:'wpn_A'})
    mixed('duration-blackboard',[buff(), ' BB[ duration=0.5 ]',hit(),' BB[ duration=2 ]'],
        roots={'buff_test':dict(lifeType='Limited',duration=dict(useBlackboardKey=True,blackboardKey='duration'))})
    mixed('enable-retains-pending',[buff(),' BUFF_ENABLE '+json.dumps(dict(schemaVersion=1,buffUid='31',ownerId='22',enabled=True,operationSeq=2)),
        ' BB[ rate=0.4 ]',hit()])
    mixed('duplicate-uid',[buff(),' BB[ rate=0.2 ]',hit(),buff(),' BB[ rate=0.4 ]',hit(2)])
    rng = random.Random(202610271)
    for index in range(80):
        operations = [hit(rng.choice([1, 2, None]), hit=rng.choice([-2, 0, 10, 50, 100]),
            eHP=rng.choice([None, 0, -10, 10, 50]), tgtId=rng.choice(['22', '23', None]),
            src=rng.choice([actor, other]), atk=None, hits=rng.choice([None, 0, 1, 2]), critFlag=rng.choice([-1, 0, 1]))
            for _ in range(8)]
        add('random/' + str(index), operations)
    for index in range(24):
        operations = [rng.choice([buff(),buff(src=other),buff(owner=actor),hit(),hit(src='unknown',atk=None),
            ' BB[ rate=0.25 ]',' BUFF_END uid=31','ordinary',' BASELINE #1 1=5']) for _ in range(8)]
        mixed('random/' + str(index),operations)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(cases, ensure_ascii=True, separators=(',', ':')), encoding='utf8')
    args.output.with_suffix('.reference.json').write_text(json.dumps(dict(cases=len(cases), source_head=metadata['head'],
        dependencies=dependencies), indent=2), encoding='utf8')
    print('Hit observation fixtures:', len(cases), 'steps:', sum(len(test['operations']) for test in cases))


if __name__ == '__main__':
    main()
