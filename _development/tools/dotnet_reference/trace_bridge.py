"""Freeze canonical trace lines after each event using the fixed Python application source."""
import argparse
import copy
import hashlib
import json
import random
import struct
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path


def uncanonical(value):
    if isinstance(value, list):
        return [uncanonical(item) for item in value]
    if isinstance(value, dict):
        if set(value) == {'int'}:
            return int(value['int'])
        if set(value) == {'f64'}:
            return struct.unpack('>d', bytes.fromhex(value['f64']))[0]
        return {key: uncanonical(item) for key, item in value.items()}
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', required=True, type=Path)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--resource-root', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    metadata = json.loads(args.manifest.read_text(encoding='utf8'))
    dependencies = {}
    for relative, info in metadata['files'].items():
        if relative.startswith('_internal/src/endfield_pcap/') and relative.endswith('.py'):
            digest = hashlib.sha256((args.reference / relative).read_bytes()).hexdigest()
            if digest != info['sha256']:
                raise ValueError('Fixed application reference changed: ' + relative)
            dependencies[relative] = digest
    sys.path.insert(0, str(args.reference / '_internal/src'))
    import endfield_pcap.capture.resolver as resolver
    import endfield_pcap.trace.formatting as formatting
    import endfield_pcap.trace.bridge as bridge_module
    from endfield_pcap.trace.bridge import TraceBridge
    class ReferenceDateTime(datetime):
        @classmethod
        def fromtimestamp(cls, timestamp, tz=None):
            return datetime.fromtimestamp(timestamp, timezone(timedelta(hours=8)))
    bridge_module.datetime = ReferenceDateTime
    fixtures = Path(__file__).resolve().parents[3] / '_internal/dotnet/Specs/Fixtures'
    cases = []
    source_hashes = {}
    table = {'skill_id': {'dic': {'42': 'chr_0001_test_skill', '0': 'chr_0001_test_zero'}},
             'buff_id': {'dic': {'55': 'buff_explicit', '0': 'buff_zero'}}}

    with tempfile.TemporaryDirectory() as folder:
        root = args.resource_root or Path(folder)
        if not args.resource_root:
            (root / 'data/local_tables').mkdir(parents=True)
            (root / 'data/local_tables/NumIdStrTable.json').write_text(json.dumps(table), encoding='utf8')
        resolver.bundle_root = formatting.bundle_root = lambda: root

        def add(label, events, begin=False, end=True):
            lines = []
            bridge = TraceBridge(write_enabled=False, line_sink=lines.append)
            steps = []
            expected = []
            if begin:
                bridge.begin_capture_session(timestamp_ms=0)
                steps.append({'begin': 0})
                expected.append(list(lines))
            for event in events:
                if isinstance(event, tuple):
                    bridge.begin_capture_session(timestamp_ms=event[1])
                    steps.append({'begin': event[1]})
                else:
                    bridge.handle_event(copy.deepcopy(event))
                    steps.append({'event_json': json.dumps(event, ensure_ascii=True, separators=(',', ':'))})
                expected.append(list(lines))
            if end:
                bridge.end_capture_session()
                steps.append({'end': True})
                expected.append(list(lines))
            config = {'steps': steps, 'table': table if not args.resource_root else None,
                      'resource_root': str(root.resolve()) if args.resource_root else None}
            cases.append({'name': f'{len(cases):04d}-{label}', 'config_json': json.dumps(config, separators=(',', ':')), 'expected': expected})

        for suite in ['session-business', 'session-scene', 'session-inventory']:
            source = fixtures / (suite + '.json')
            source_hashes[source.name] = hashlib.sha256(source.read_bytes()).hexdigest()
            for sample in json.loads(source.read_text(encoding='utf8')):
                events = uncanonical(sample['expected'][-1]['events'])
                # The source business cases already prove event order/presence through the typed protobuf path.
                add(suite + '-' + sample['name'], events, begin=True)

        def ev(kind, timestamp=1000, **fields):
            return dict(type=kind, session_id='合成-session', timestamp_ms=timestamp, **fields)

        scene = ev('SC_SELF_SCENE_INFO', char_list=[dict(id=101, battle_inst_id=11, templateid='chr_0001_test', level=90, hp=100.0, attrs=[]),
            dict(id=202, battle_inst_id=22, templateid='chr_0002_other', attrs=[dict(attr_type=3, value=0.0000001)])])
        enemy = ev('SC_OBJECT_ENTER_VIEW', objects=[dict(obj_id=33, battle_inst_id=333, templateid='eny_0001_test', hp=1234.5)])
        def trigger(action, timestamp=1010, **fields):
            return ev('BattleOpTriggerAction', timestamp, owner_id=11, inst_id=777, owner_type='1',
                template_type='Buff', template_int_id=55, seq_id=12, client_tick_tms=900,
                action=action, **fields)
        def create(uid=888, phase=0, timestamp=1010, **detail):
            return trigger(dict(action_type='BattleActionCreateBuff', action_id=0, create_buff_action=dict(details=[
                dict(buff_inst_id=uid, source_id=11, target_id=22, **detail)])), timestamp, trigger_type=phase)
        def damage(value=-123.5, timestamp=1020, **detail):
            return trigger(dict(action_type='BattleActionDamage', action_id=4, damage_action=dict(attacker_id=11, details=[
                dict(value=value, target_id=333, **detail)])), timestamp)
        add('buff-execute-end-order', [scene, create(buff_num_id=55, assigned_items=[dict(target_key='rate', numeric_value=.2)]), create(phase=2)])
        add('buff-same-timestamp-refresh', [scene, create(buff_num_id=55, assigned_items=[dict(target_key='rate', numeric_value=.2)]),
            create(buff_num_id=55, assigned_items=[dict(target_key='rate', numeric_value=.3)]), create(buff_num_id=55, assigned_items=[dict(target_key='rate', numeric_value=.3)]), damage()])
        for phase in [None, True, 1, 3, 4, -1]:
            add('unresolved-create-phase', [scene, create(phase=phase, buff_num_id=55)])
        for key in ['target_key', 'input_value_key', 'targetKey', 'inputValueKey']:
            add('assigned-key-'+key, [ev('BattleOpAddBuff', buff_inst_id=888, src_inst_id=11, target_inst_id=22, int_id=55,
                assigned_items=[{key: 'rate', 'numeric_value': 0}]), damage()])
        add('buff-observation-identity-priority', [create(buff_num_id=987), create(buff_id={'str_id': 'buff_verified'}),
            create(buff_num_id=55), create(assigned_items=[]), create(phase=2), create(buff_num_id=55)])
        add('add-buff-then-unknown-create', [scene, ev('BattleOpAddBuff', buff_inst_id=888, src_inst_id=11, target_inst_id=22, str_id='buff_explicit'), create()])
        add('clock-does-not-flush-add', [ev('BattleOpAddBuff', buff_inst_id=888, int_id=55), ev('GAME_CLOCK_TICK', source='CS_BATTLE_OP', tick_ms=42, seq_id=0), damage()])
        add('new-flow-isolates', [scene, enemy, create(buff_num_id=55), damage(), ('begin', 5000), damage(timestamp=5001)])
        add('session-end-keeps-last-packet-clock', [ev('BattleOpModifyBattleState', timestamp=4000, is_in_battle=True), ev('SC_PING', timestamp=9999, client_ts=42)])
        for game in ['normal', 'indie_battletower_x']:
            start = ev('DUNGEON_CONTEXT', dungeon_id=game)
            battle = ev('BattleOpModifyBattleState', is_in_battle=True, client_tick_tms=0)
            stop = ev('BattleOpModifyBattleState', timestamp=2000, is_in_battle=False, client_tick_tms=900)
            official_start = ev('SC_GAME_MECHANICS_SYNC_CHALLENGE_START', game_id=game, challenge_start_ts=1000)
            for boundary in ['SC_GAME_MECHANICS_SYNC_LEAVE_GAME_INST', 'SC_GAME_MECHANICS_SYNC_RESTART_GAME_INST', 'CS_ENTER_DUNGEON', 'CS_SCENE_LOAD_FINISH']:
                add('boundary-'+game+'-'+boundary, [start, battle, official_start, ev(boundary, timestamp=3000)])
            add('official-scene-await-'+game, [start, battle, official_start, ev('SC_SCENE_SET_BATTLE', timestamp=1800, in_battle=False), stop,
                ev('SC_SYNC_WEEK_RAID_SETTLEMENT', timestamp=3000, game_id=game, total_playtime=1234),
                ev('SC_GAME_MECHANICS_SYNC_CHALLENGE_COMPLETE', timestamp=3100, game_id=game, is_pass=True, pass_time=1300)])
            add('multi-phase-'+game, [start, battle, stop, battle, stop])
        calc_fields = ['client_calc_result_value', 'client_final_damage_scale', 'client_attack_value', 'client_crit_add_scale', 'client_def_attr_defender_def',
            'client_def_resistance', 'client_dmg_type_resistance', 'client_defender_poise_factor', 'client_ignite_damage_scalar', 'client_final_value',
            'client_weak_damage_scalar', 'client_shelter_damage_scalar', 'client_physical_infliction_damage_scalar']
        for value in [0, -.49, -.5, -1.5, -2.5, -1e-7, -1e20, -1.2345678901234567, -1.234567e6]:
            add('damage-number-'+str(value), [scene, enemy, damage(value, cur_hp=-0.0, is_crit=True, calculate_damage_check_args=dict.fromkeys(calc_fields, value))])
        evidence = damage(modifier_args=dict(attacker_modifiers=[dict(buff_inst_id=888, processor_index=0)], defender_modifiers=[dict(buff_inst_id=999)]),
            battle_report_info=dict(attacker_attr_modify_info=[dict(attr_type=3, attrs=[0, 1.5, '2'])], defender_attr_modify_info=[dict(attr_type=5, attrs=[0.0])]))
        evidence['damage_detail_presence'] = [dict(has_battle_report_info=False, has_calculation_check_args=True, processor_debug_args_count=2,
            has_attacker_attr_modifier_debug_data=True, attacker_modifier_debug_handle_count=1, defender_modifier_debug_arg_entry_count=3)]
        evidence.update(operation_owner_id=str(2**64-1), generation=2**32-1)
        add('damage-evidence-order', [scene, enemy, evidence])
        keyword = ev('BattleOpTriggerKeyword', owner_id='22', buff_inst_id='888', generation=0, seq_id=1, add_buff_num_id=55,
            client_tick_tms='0', operation_payload_case='trigger_keyword_op_data', modify=[dict(config_index=0, modify_value=.4)])
        add('keyword-ordered-conflict-cache', [scene, create(buff_num_id=55, assigned_items=[dict(target_key='rate', numeric_value=.2)]), keyword,
            {**keyword, 'modify': [dict(config_index=0, modify_value=.5)]}, {**keyword, 'seq_id': 0}, create(buff_num_id=55, assigned_items=[dict(target_key='rate', numeric_value=.5)])])
        for bad in [dict(owner_id=True), dict(buff_inst_id='00'), dict(generation=True), dict(seq_id=None), dict(modify='bad'),
                    dict(modify=[dict(config_index=-1, modify_value=1)]), dict(modify=[dict(config_index=0, modify_value=float('inf'))])]:
            add('keyword-invalid', [{**keyword, **bad}])
        for action_type, runtime_field, payload in [('BattleActionModifyDynamicBlackboard', 'modify_dynamic_blackboard_action', dict(client_value=1.25)),
                ('BattleActionRefreshBuffAttrModifierValue', 'refresh_buff_attr_modifier_value_action', {}),
                ('BattleActionReadSkillActionToBb', 'read_skill_setting_to_bb_action', dict(runtime_details=[]))]:
            action = dict(action_type=action_type, action_id=7, **{runtime_field: payload})
            full = trigger(action, operation_owner_id=22, trigger_owner_id=22, trigger_inst_id=888, generation=0,
                template_id={'type': 'Buff', 'int_id': 55}, template_id_case='int_id', operation_payload_case='trigger_action_op_data', action_runtime_case=runtime_field, trigger_type=0)
            add('blackboard-full-envelope-'+action_type, [full, damage(), damage()])
            add('blackboard-legacy-envelope-'+action_type, [trigger(action), damage()])
            for key, bad in [('generation', True), ('template_id_case', 'str_id'), ('operation_owner_id', '-1'), ('client_tick_tms', str(2**63))]:
                add('blackboard-invalid-'+action_type+'-'+key, [{**full, key: bad}])
        dynamic = [trigger(dict(action_type='BattleActionModifyDynamicBlackboard', action_id=n, modify_dynamic_blackboard_action=dict(client_value=n+.25))) for n in range(12)]
        calc = [trigger(dict(action_type='BattleActionSimpleCalcBb', action_id=n, simple_calc_bb_action=dict(client_target_key='x', client_final_value=n+.5))) for n in range(16)]
        add('blackboard-tail-and-consumption', [*dynamic, *calc, damage(), damage()])
        add('other-blackboard-actions', [trigger(dict(action_type='BattleActionMultiModifyBb', action_id=0, multi_modify_bb_action=dict(key='x', value=1.25))),
            trigger(dict(action_type='BattleActionSetBlackboardFromPreset', set_blackboard_from_preset_action=dict(modified_value='引号"与\\')))])
        add('scene-skill-zero-and-level-dedup', [scene,
            ev('SC_SELF_SCENE_INFO_SKILLS', owner_templateid='chr_0001_test', owner_inst_id=11, skills=[dict(skill_inst_id=701, template_int_id=42, level=3, skill_source='Character'), dict(skill_inst_id=702, template_int_id=0, level=0)]),
            ev('SC_SELF_SCENE_INFO_SKILLS', owner_templateid='chr_0001_test', owner_inst_id=11, skills=[dict(skill_inst_id=701, template_int_id=42, level=3, skill_source='Changed'), dict(skill_inst_id=702, template_int_id=0, level=0)]),
            ev('BattleOpSkillStartCast', owner_id=11, skill_inst_id=701, client_tick_tms=0),
            ev('BattleOpSkillEndCast', owner_id='11', skill_inst_id=701), ev('BattleOpSkillDetach', skill_inst_id=701),
            ev('BattleOpSkillStartCast', owner_id=11, skill_inst_id=701)])
        add('attach-explicit-actor-and-detach', [ev('BattleOpSkillAttach', src_inst_id=11, skill_inst_id=701,
            template_str_id='chr_0001_test_skill', skill_source='Character'),
            ev('BattleOpSkillStartCast', owner_id=11, skill_inst_id=701), ev('BattleOpSkillDetach', skill_inst_id=701),
            ev('BattleOpSkillStartCast', owner_id=11, skill_inst_id=701)])
        launch = trigger(dict(action_type='BattleActionLaunchProjectile', action_id=14,
            launch_projectile_action=dict(source_id=11, details=[dict(client_projectile_id=901), dict(projectile_id=902)])))
        launch.update(template_str_id='buff_chr_0036_jsspsi_xianjing_inkhurteffect')
        add('projectile-explicit-owner-ink-release', [ev('SC_SELF_SCENE_INFO', char_list=[dict(id=101, battle_inst_id=11, templateid='chr_0036_jsspsi')]), launch,
            {**launch, 'timestamp_ms': 1020}])
        add('unknown-projectile-has-no-inferred-actor', [launch])
        add('ability-entity-coordinates', [scene, trigger(dict(action_type='BattleActionSpawnAbilityEntity', action_id=2,
            spawn_ability_entity_action=dict(details=[dict(client_ability_entity_id=123, source_id=11, init_pos=dict(x=0, y=1.5), rotation=dict(y=-1.5))])))])
        add('buff-enable-strings-and-wide-identity', [ev('BattleOpSetBuffEnableState', owner_id=2**64-1,
            states={'汉字': False, str(2**64-2): True}, seq_id=0, generation=0, client_tick_tms=-1)])
        if args.resource_root:
            actual_table = json.loads((root / 'data/local_tables/NumIdStrTable.json').read_text(encoding='utf8'))
            for raw_id, canonical_id in list(actual_table['skill_id']['dic'].items())[:96]:
                add('bundled-skill-'+str(raw_id), [scene, ev('BattleOpSkillAttach', src_inst_id=11, skill_inst_id=701, template_int_id=int(raw_id)),
                    ev('BattleOpSkillStartCast', owner_id=11, skill_inst_id=701), ev('BattleOpSkillEndCast', owner_id=11, skill_inst_id=701)])
            for raw_id, canonical_id in list(actual_table['buff_id']['dic'].items())[:96]:
                add('bundled-buff-'+str(raw_id), [scene, ev('BattleOpAddBuff', buff_inst_id=888, int_id=int(raw_id), src_inst_id=11, target_inst_id=22),
                    create(buff_num_id=int(raw_id), assigned_items=[dict(target_key='rate', numeric_value=.2)]), create(phase=2)])
        rng = random.Random(20261029)
        for index in range(24):
            rows = [scene, enemy]
            for _ in range(20):
                choice = rng.randrange(6)
                if choice < 2:
                    rows.append(create(uid=rng.choice([888, 889]), phase=rng.choice([0, 2]), timestamp=1000+index, buff_num_id=rng.choice([0, 55, 987]), assigned_items=[dict(target_key='rate', numeric_value=rng.choice([0, .2, .3]))]))
                elif choice < 4:
                    rows.append(damage(rng.uniform(-1e7, -.5), timestamp=1200+index))
                elif choice == 4:
                    rows.append(ev('BattleOpFinishBuff', timestamp=1100+index, buff_inst_id=rng.choice([888, 889])))
                else:
                    rows.append(ev('SC_PING', timestamp=1300+index, client_ts=0))
            add('mixed-event-order', rows)

    output = args.output or fixtures / 'trace-bridge.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(cases, ensure_ascii=True, separators=(',', ':')), encoding='utf8')
    resource_hashes = {}
    if args.resource_root:
        for relative in ['data/local_tables/NumIdStrTable.json', 'data/packet_semantics/packet_resolver_bundle.json']:
            resource_hashes[relative] = hashlib.sha256((args.resource_root / relative).read_bytes()).hexdigest()
    output.with_suffix('.reference.json').write_text(json.dumps(dict(source_head=metadata['head'], cases=len(cases),
        dependencies=dependencies, source_fixtures=source_hashes, resource_hashes=resource_hashes,
        timezone_offset_minutes=480), indent=2), encoding='utf8')
    print('Trace bridge fixtures:', len(cases))


if __name__ == '__main__':
    main()
