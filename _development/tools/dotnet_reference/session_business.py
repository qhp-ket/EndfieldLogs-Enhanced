"""Freeze typed session operation events and skill state from the fixed Python application reference."""
import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import random
import sys
import tempfile

from report_projection import canonical


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--dependency-path', type=Path)
    parser.add_argument('--scene', action='store_true', help='Generate separate scene/entity/context fixtures')
    parser.add_argument('--inventory', action='store_true', help='Generate separate inventory/loadout fixtures')
    parser.add_argument('--resource-root', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    metadata = json.loads(args.manifest.read_text(encoding='utf8'))
    prefix = '_internal/src/endfield_pcap/'
    dependencies = {}
    for relative, info in metadata['files'].items():
        if relative.startswith(prefix) and relative.endswith('.py'):
            digest = hashlib.sha256((args.reference / relative).read_bytes()).hexdigest()
            if digest != info['sha256']:
                raise ValueError('Fixed application reference changed: ' + relative)
            dependencies[relative] = digest
    if args.dependency_path:
        sys.path.insert(0, str(args.dependency_path))
    sys.path.insert(0, str(args.reference / '_internal/src'))
    from google.protobuf import json_format, message_factory, __version__ as protobuf_version
    from endfield_pcap.capture.registry import DecodedMessage
    from endfield_pcap.models import Endpoint, FlowKey, RuntimeMetrics, SquadMember
    from endfield_pcap.service.session.pipeline import SessionPipeline
    from endfield_pcap.proto_generated.CS_BATTLE_OP_pb2 import CS_BATTLE_OP
    from endfield_pcap.proto_generated.SC_SELF_SCENE_INFO_pb2 import SC_SELF_SCENE_INFO
    from endfield_pcap.data import loadout
    if args.inventory:
        loadout.bundle_root = lambda: args.resource_root or Path(__file__).parent / '__empty_resources'
    descriptor = CS_BATTLE_OP.DESCRIPTOR.fields_by_name['client_data'].message_type.fields_by_name['op_list'].message_type
    op_class = message_factory.GetMessageClass(descriptor)
    scene_battle = SC_SELF_SCENE_INFO.DESCRIPTOR.fields_by_name['detail'].message_type.fields_by_name['char_list'].message_type.fields_by_name['battle_info'].message_type
    cases = []
    rng = random.Random(20261029)

    def populate(message, depth=3):
        if depth < 0:
            return message
        selected = set()
        for field in message.DESCRIPTOR.fields:
            if field.containing_oneof:
                if field.containing_oneof.name in selected:
                    continue
                selected.add(field.containing_oneof.name)
            if field.message_type is not None and field.message_type.GetOptions().map_entry:
                key = 'sample' if field.message_type.fields_by_name['key'].type == field.TYPE_STRING else 77
                if field.message_type.fields_by_name['value'].type == field.TYPE_BOOL:
                    getattr(message, field.name)[key] = False
                continue
            if field.is_repeated:
                if field.type == field.TYPE_MESSAGE:
                    populate(getattr(message, field.name).add(), depth-1)
                elif field.type == field.TYPE_STRING:
                    getattr(message, field.name).append('sample')
                else:
                    getattr(message, field.name).append(1)
            elif field.type == field.TYPE_MESSAGE:
                populate(getattr(message, field.name), depth-1)
                getattr(message, field.name).SetInParent()
            elif field.type == field.TYPE_ENUM:
                setattr(message, field.name, field.enum_type.values[-1].number)
            elif field.type in (field.TYPE_FLOAT, field.TYPE_DOUBLE):
                setattr(message, field.name, 1.25)
            elif field.type == field.TYPE_BOOL:
                setattr(message, field.name, True)
            elif field.type == field.TYPE_STRING:
                setattr(message, field.name, 'sample')
            elif field.type == field.TYPE_BYTES:
                setattr(message, field.name, b'\x00\xff')
            else:
                setattr(message, field.name, 77)
        return message

    def message(name, payload=None):
        cls = getattr(importlib.import_module('endfield_pcap.proto_generated.' + name + '_pb2'), name)
        return json_format.ParseDict(payload or {}, cls())

    def operation(kind, body=None, field=None, **values):
        result = op_class(op_type=kind, **values)
        if field:
            json_format.ParseDict(body or {}, getattr(result, field))
            getattr(result, field).SetInParent()
        return result

    def batch(operations):
        result = CS_BATTLE_OP()
        result.client_data.op_list.extend(operations)
        return result

    def add(label, messages, owners=(), merge=False, tracked=(), names=None, dungeons=None):
        with tempfile.TemporaryDirectory() as folder:
            os.environ['ENDFIELD_LOGS_DATA_ROOT'] = folder
            events = []
            session = SessionPipeline(FlowKey(Endpoint('192.0.2.1', 1000), Endpoint('203.0.113.1', 30000)),
                'synthetic', None, None, None, {}, {}, merge, events.append, None, None, RuntimeMetrics())
            session.name_index.update(names or {})
            session.multi_phase_dungeon_map.update(dungeons or {})
            seeds = []
            for identity, battle in owners:
                session.squad_index[identity] = SquadMember(identity, identity+1000, 'chr_test', '测试角色', False, 0)
                session._cache_scene_skill_levels(identity, battle)
                session._replace_server_skill_rows(identity, [session._server_skill_row(identity, skill) for skill in battle.skill_list])
                seeds.append(dict(owner=str(identity), battle_type=battle.DESCRIPTOR.full_name, battle_hex=battle.SerializeToString().hex()))
            session.tracked_enemy_templateid = 'enemy' if merge else None
            session.tracked_enemy_inst_ids.update(tracked)
            steps = []
            expected = []
            for index, source in enumerate(messages):
                timestamp = 1000+index*10
                name = source.DESCRIPTOR.full_name
                direction = 'cs' if name.startswith('CS_') else 'sc'
                data = source.SerializeToString()
                decoded = DecodedMessage(direction, name, index+1, {}, source, data)
                session._handle_message(decoded, timestamp)
                steps.append(dict(name=name, bytes=data.hex(), timestamp_ms=timestamp, direction=direction, message_id=index+1))
                state = dict(events=canonical([event.as_dict() for event in events]),
                    skills=canonical({str(owner): list(rows.values()) for owner, rows in session.server_skill_state_by_owner_inst.items()}),
                    merged=session.merged_battle_active, tracked=sorted(session.tracked_enemy_inst_ids))
                if args.scene or args.inventory:
                    state.update(scene_team=canonical(session.scene_team_char_ids),
                        dungeon_team=canonical(session.dungeon_team_char_ids), tracked_dungeon=session.tracked_dungeon_id)
                if args.inventory:
                    state['loadout'] = canonical(session._loadout_rows())
                expected.append(state)
            cases.append(dict(name=f'{len(cases):04d}-{label}', config_json=json.dumps(dict(steps=steps, owners=seeds,
                merge=merge, tracked=list(tracked), names=names, dungeons=dungeons, scene_state=args.scene or args.inventory,
                inventory_state=args.inventory, resource_root=str(args.resource_root.resolve()) if args.resource_root else None)), expected=expected))

    handlers = {'BattleOpAddBuff': 'add_buff_op_data', 'BattleOpFinishBuff': 'finish_buff_op_data',
        'BattleOpSkillAttach': 'skill_attach_op_data', 'BattleOpSkillDetach': 'skill_detach_op_data',
        'BattleOpSkillStartCast': 'skill_start_cast_op_data', 'BattleOpSkillEndCast': 'skill_end_cast_op_data',
        'BattleOpTriggerAction': 'trigger_action_op_data', 'BattleOpEntityDie': 'entity_die_op_data',
        'BattleOpEntityValueModify': 'entity_value_modify_data', 'BattleOpEnablePassiveSkill': 'skill_enable_op_data',
        'BattleOpTriggerKeyword': 'trigger_keyword_op_data', 'BattleOpUpdateAtbInfo': 'update_atb_info_op_data',
        'BattleOpModifyBattleState': 'modify_battle_state_op_data', 'BattleOpModifyPoiseValue': 'modify_poise_value_op_data',
        'BattleOpSetBuffEnableState': 'set_buff_enable_state_op_data'}
    for kind in [value.name for value in descriptor.fields_by_name['op_type'].enum_type.values]:
        add(kind+'-absent-payload', [batch([operation(kind)])])
        if kind not in handlers:
            continue
        field = handlers[kind]
        add(kind+'-present-empty', [batch([operation(kind, field=field)])])
        rich = operation(kind, field=field, owner_id=2**63+7, seq_id=1, client_tick_tms=100, generation=2)
        populate(getattr(rich, field))
        add(kind+'-populated', [batch([rich])])
    action_descriptor = descriptor.fields_by_name['trigger_action_op_data'].message_type.fields_by_name['action'].message_type
    for action_field in [field for field in action_descriptor.fields if field.containing_oneof]:
        op = operation('BattleOpTriggerAction', field='trigger_action_op_data', owner_id=11, seq_id=9, client_tick_tms=400)
        populate(getattr(op.trigger_action_op_data.action, action_field.name), 4)
        getattr(op.trigger_action_op_data.action, action_field.name).SetInParent()
        op.trigger_action_op_data.template_id.type = 2
        op.trigger_action_op_data.template_id.int_id = 42
        add('action-'+action_field.name, [batch([op])])
    for reason in [value.number for value in descriptor.fields_by_name['update_atb_info_op_data'].message_type.fields_by_name['atb_data'].message_type.fields_by_name['reason'].enum_type.values]:
        add('atb-zero-speed-reason', [batch([operation('BattleOpUpdateAtbInfo', dict(atb_data=dict(reason=reason)), field='update_atb_info_op_data')])])
    add('clock-dedup-and-zero', [batch([operation('BattleOpNone', seq_id=1, client_tick_tms=100),
        operation('BattleOpNone', seq_id=2, client_tick_tms=100), operation('BattleOpNone', client_tick_tms=0),
        operation('BattleOpNone', client_tick_tms=-1), operation('BattleOpNone', client_tick_tms=101)])])
    add('multi-phase-enemy', [batch([operation('BattleOpModifyBattleState', dict(is_in_battle=True), 'modify_battle_state_op_data'),
        operation('BattleOpModifyBattleState', dict(is_in_battle=False), 'modify_battle_state_op_data'),
        operation('BattleOpEntityDie', dict(entity_inst_id=77), 'entity_die_op_data')])], merge=True, tracked=[77])
    for name in ['CS_PING', 'SC_PING', 'CS_GAME_TIME_FREEZE_START_REQ', 'CS_GAME_TIME_FREEZE_END_REQ',
                 'SC_GAME_TIME_FREEZE_START_RSP', 'SC_GAME_TIME_FREEZE_END_RSP', 'SC_GAME_MECHANICS_SYNC_CHALLENGE_START',
                 'SC_GAME_MECHANICS_SYNC_CHALLENGE_COMPLETE', 'SC_RESET_BATTLE_STATUS', 'SC_SYNC_WEEK_RAID_SETTLEMENT']:
        add(name+'-defaults', [message(name), populate(message(name))])
    for name in ['CS_CONTINGENCY_CONTRACT_SET_TAGS', 'SC_CONTINGENCY_CONTRACT_SET_TAGS',
                 'SC_CONTINGENCY_CONTRACT_TAGS_SYNC', 'SC_CONTINGENCY_CONTRACT_BATTLE_RESULT']:
        add(name+'-tags', [message(name), populate(message(name))])
    for _ in range(40):
        operations = []
        for _ in range(8):
            kind, field = rng.choice(list(handlers.items()))
            op = operation(kind, field=field, owner_id=rng.choice([0, 11, 2**64-1]), seq_id=rng.randrange(4), client_tick_tms=rng.choice([0, 100, 101]))
            if rng.choice([False, True]):
                populate(getattr(op, field), 3)
            operations.append(op)
        add('mixed-ordered-operations', [batch(operations[:4]), batch(operations[4:])])
    owner_battle = populate(message_factory.GetMessageClass(scene_battle)())
    owner_battle.skill_list[0].skill_id.type = 2
    owner_battle.skill_list[0].skill_id.int_id = 42
    for identity in [11, 2**64-1]:
        for other in [0, identity, 22]:
            op = operation('BattleOpTriggerAction', field='trigger_action_op_data', owner_id=identity)
            op.trigger_action_op_data.owner_id = other
            op.trigger_action_op_data.template_id.CopyFrom(owner_battle.skill_list[0].skill_id)
            add('owner-specific-skill-level', [batch([op])], owners=[(identity, owner_battle)])
    if args.scene:
        cases.clear()

        def character(owner=11, obj=101, template='chr_test', **extra):
            return dict(common_info=dict(id=obj, templateid=template, hp=10), level=20,
                battle_info=dict(battle_inst_id=owner, skill_list=[dict(inst_id=700+owner,
                    skill_id=dict(type='Skill', int_id=42), level=3)]), **extra)

        def scene(characters, **extra):
            return message('SC_SELF_SCENE_INFO', dict(detail=dict(char_list=characters), **extra))

        def enter(objects, field='monster_list'):
            return message('SC_OBJECT_ENTER_VIEW', dict(detail={field: objects}))

        def trigger(owner):
            return batch([operation('BattleOpTriggerAction', dict(template_id=dict(type='Skill', int_id=42)),
                'trigger_action_op_data', owner_id=owner)])

        start = batch([operation('BattleOpModifyBattleState', dict(is_in_battle=True), 'modify_battle_state_op_data')])
        for name in ['SC_SELF_SCENE_INFO', 'SC_OBJECT_ENTER_VIEW', 'SC_OBJECT_LEAVE_VIEW', 'SC_SYNC_ATTR',
                     'CS_ENTER_DUNGEON', 'CS_LEAVE_DUNGEON']:
            add(name+'-default-and-populated', [message(name), populate(message(name))])
        roster = [character(), character(22, 202, 'chr_other', attrs=[dict(attr_type=2, value=3.5)])]
        add('roster-skills-context-refresh', [scene(roster, team_info=dict(cur_leader_id=202), scene_id=7),
            trigger(11), scene([]), start, scene([character(22, 202, 'chr_other')]), trigger(11), start],
            names={'chr_test': '测试角色', 'chr_other': '支援角色'})
        add('attribute-sync-and-context', [scene(roster), message('SC_SYNC_ATTR', dict(obj_id=101,
            attr_list=[dict(attr_type=1, basic_value=0, value=100), dict(attr_type=0, value=9),
                       dict(attr_type=1, basic_value=1, value=0)])), start,
            message('SC_SYNC_ATTR', dict(obj_id=11, attr_list=[dict(attr_type=2, value=-5)])), start,
            message('SC_SYNC_ATTR', dict(obj_id=999, attr_list=[dict(attr_type=1)]))])
        add('leave-removes-owner-not-level-evidence', [scene(roster), message('SC_OBJECT_LEAVE_VIEW',
            dict(obj_list=[dict(obj_id=101), dict(obj_id=0), dict(obj_id=999)])), trigger(11), start])
        add('object-refresh-and-all-detail-types', [message('SC_OBJECT_ENTER_VIEW', dict(detail={
            'char_list': [character()], 'monster_list': [character(22, 202, 'enemy')],
            'interactive_list': [dict(common_info=dict(id=303, templateid='object'), battle_info=dict(battle_inst_id=33))],
            'npc_list': [dict(common_info=dict(id=404, templateid='npc'))],
            'summon_list': [dict(common_info=dict(id=505, templateid='summon'), battle_info=dict(battle_inst_id=55))]})),
            trigger(11), scene(roster), enter([character(11, 101, 'chr_changed')], 'char_list'), start,
            message('SC_OBJECT_LEAVE_VIEW', dict(obj_list=[dict(obj_id=101)])), start])
        for variant_field in ['buff_list', 'stacking_group_list', 'skill_nodes', 'skill_blackboard', 'none']:
            row = character(template='chr_9000_endmin')
            battle = row['battle_info']
            if variant_field == 'buff_list': battle['buff_list'] = [dict(stacking_group_id='x_chr_0003_endminf')]
            elif variant_field == 'stacking_group_list': battle['stacking_group_list'] = [dict(stacking_key='chr_0002_endminm')]
            elif variant_field == 'skill_nodes': battle['skill_list'][0]['talent_node_ids'] = ['chr_0003_endminf_node']
            elif variant_field == 'skill_blackboard': battle['skill_list'][0]['blackboard'] = dict(blackboard=dict(
                variant=dict(str_value='chr_0002_endminm')))
            add('endmin-'+variant_field, [scene([row]), start], names={'chr_0002_endminm': '管理员'})
        add('dungeon-explicit-team-and-scene-metadata', [message('CS_ENTER_DUNGEON', dict(dungeon_id=' trial ',
            char_team=[dict(obj_id=202), dict(obj_id=101), dict(obj_id=0)])), scene(roster,
            dungeon=dict(dungeon_id='trial', challenge_expire_ts=100, is_pass=False), scene_num_id=4, scene_id=7),
            start, message('CS_LEAVE_DUNGEON')])
        add('multi-phase-from-entity-to-leave', [enter([character(77, 707, 'boss')]),
            message('CS_ENTER_DUNGEON', dict(dungeon_id='trial')), start,
            enter([character(78, 708, 'boss')]), message('CS_LEAVE_DUNGEON'),
            message('CS_ENTER_DUNGEON', dict(dungeon_id='other'))], merge=True, dungeons={'trial': 'boss'})
        for index in range(35):
            rows = [character(owner=11+i, obj=101+i, template='chr_'+str(i)) for i in range(rng.randrange(1, 5))]
            rng.shuffle(rows)
            for row in rows:
                row['level'] = rng.choice([0, 1, 90])
                row['common_info']['hp'] = rng.choice([0., 1.25, 1e12])
                row['attrs'] = [dict(attr_type=rng.choice([0, 1, 3]), value=rng.choice([0., -1., 2.5])) for _ in range(3)]
            add('mixed-scene-sequence', [scene(rows), trigger(11), enter(rows, 'char_list'),
                scene(rows[1:]), start, message('SC_OBJECT_LEAVE_VIEW', dict(obj_list=[dict(obj_id=101)])),
                trigger(11), start])
    if args.inventory:
        cases.clear()
        def bag_character(identity=101, weapon=501, template='chr_test', potential=2, equips=None):
            return dict(objid=identity, templateid=template, weapon_id=weapon, level=70, potential_level=potential,
                equip_col=equips or {}, battle_mgr_info=dict(skill_list=[dict(inst_id=701+identity, source='Weapon',
                    skill_id=dict(type='Skill', int_id=42), level=3, potential_lv=potential,
                    blackboard=dict(blackboard=dict(atk=dict(float_value=0.125), note=dict(str_value='值'))))]))
        def bag(rows, team=None, **extra):
            return message('SC_SYNC_CHAR_BAG_INFO', dict(char_info=rows, team_info=[dict(char_team=team or [101, 202])], **extra))
        def grid(identity, template, kind=None, **values):
            return dict(id=template, inst=dict(inst_id=identity, **({kind: values} if kind else {})))
        def items(grids, name='SC_ITEM_BAG_SCOPE_SYNC', **extra):
            return message(name, dict(bag=dict(grids=grids), **extra))
        chars = [bag_character(equips={'0': 301, '1': 302}), bag_character(202, 502, 'chr_other', potential=5)]
        raw_items = [grid(501, 'wpn_test', 'weapon', inst_id=501, weapon_lv=10, refine_lv=2, equip_char_id=101),
            grid(502, 'wpn_other', 'weapon', inst_id=502, weapon_lv=1, equip_char_id=202),
            grid(301, 'item_equip_t1_suit_test_body', 'equip', equipid=301, equip_char_id=101, enhance={'1': 0, '2': 3}),
            grid(302, 'item_equip_t1_suit_test_hand', 'equip', equipid=302, equip_char_id=101),
            grid(601, 'gem_test', 'gem', gem_id=602, weapon_id=501, template_id=99,
                terms=[dict(term_num_id=1, cost=0), dict(term_num_id=2, cost=3)])]
        kinds = ['SC_SYNC_CHAR_BAG_INFO', 'SC_CHAR_BAG_SET_TEAM', 'SC_CHAR_BAG_SET_TEAM_LEADER',
            'SC_ITEM_BAG_SCOPE_SYNC', 'SC_ITEM_BAG_SCOPE_MODIFY', 'SC_EQUIP_PUTON', 'SC_EQUIP_PUTOFF', 'SC_EQUIP_ENHANCE',
            'SC_WEAPON_PUTON', 'SC_WEAPON_ADD_EXP', 'SC_WEAPON_BREAKTHROUGH', 'SC_WEAPON_REFINE_UPGRADE',
            'SC_WEAPON_ATTACH_GEM', 'SC_WEAPON_DETACH_GEM']
        for kind in kinds:
            add(kind+'-defaults-populated', [bag(chars), items(raw_items), message(kind), populate(message(kind))])
        add('bag-items-arrival-order-and-team-switch', [items(raw_items), bag(chars), bag(chars),
            message('SC_CHAR_BAG_SET_TEAM', dict(char_team=[202, 101])),
            message('SC_SYNC_CHAR_BAG_INFO', dict(team_info=[dict(char_team=[101])], curr_team_index=-1)),
            message('SC_CHAR_BAG_SET_TEAM', dict(char_team=[101, 999, 202]))])
        for off in [0, 101, 202, 999]:
            for destination in [101, 202, 999]:
                add('weapon-swap-source-skill-ownership', [bag(chars), items(raw_items), message('SC_WEAPON_PUTON',
                    dict(charid=destination, weaponid=502, offweaponid=501, put_off_charid=off)),
                    message('SC_CHAR_BAG_SET_TEAM', dict(char_team=[101, 202]))])
        add('equip-transfer-same-owner-slot-and-off', [bag(chars), items(raw_items),
            message('SC_EQUIP_PUTON', dict(charid=101, slotid=2, equipid=301)),
            message('SC_EQUIP_PUTON', dict(charid=202, slotid=0, equipid=301, put_off_charid=101,
                suitinfo={'new': 1}, old_owner_suitinfo={'old': 2})),
            message('SC_EQUIP_ENHANCE', dict(equip_inst_id=301, equip_data=dict(enhance={'1': 4}))),
            message('SC_EQUIP_PUTOFF', dict(charid=202, slotid=0))])
        add('gem-refresh-invalidates-observed-skill', [bag(chars), items(raw_items),
            items([grid(601, 'gem_test', 'gem', gem_id=602, weapon_id=501, terms=[dict(term_num_id=1, cost=4)])]),
            bag(chars), message('SC_WEAPON_DETACH_GEM', dict(weaponid=501, detach_gemid=602)),
            message('SC_WEAPON_ATTACH_GEM', dict(weaponid=502, gemid=602)),
            message('SC_WEAPON_ADD_EXP', dict(weaponid=502, weapon_lv=80)),
            message('SC_WEAPON_BREAKTHROUGH', dict(weaponid=502, breakthrough_lv=3)),
            message('SC_WEAPON_REFINE_UPGRADE', dict(weaponid=502, refine_lv=5))])
        add('template-only-and-missing-inventory-fields', [bag(chars), items([grid(501, 'wpn_test')]),
            message('SC_WEAPON_ADD_EXP', dict(weaponid=501, weapon_lv=10)),
            items([grid(999, 'wpn_other', 'weapon', weapon_lv=1), grid(998, 'equip', 'equip')], 'SC_ITEM_BAG_SCOPE_MODIFY'),
            message('SC_WEAPON_PUTON', dict(charid=101, weaponid=999))])
        add('scene-party-order-and-forced-context', [bag(chars), items(raw_items),
            message('CS_ENTER_DUNGEON', dict(dungeon_id='test', char_team=[dict(obj_id=202), dict(obj_id=101)])),
            message('SC_SELF_SCENE_INFO', dict(detail=dict(char_list=[dict(common_info=dict(id=101, templateid='chr_test'),
                battle_info=dict(battle_inst_id=11)), dict(common_info=dict(id=202, templateid='chr_other'), battle_info=dict(battle_inst_id=22))]))),
            batch([operation('BattleOpModifyBattleState', dict(is_in_battle=True), 'modify_battle_state_op_data')]),
            message('CS_LEAVE_DUNGEON'), message('SC_CHAR_BAG_SET_TEAM', dict(char_team=[101]))])
        for _ in range(35):
            updates = []
            for _ in range(8):
                kind = rng.choice(kinds[5:])
                sample = populate(message(kind), 2)
                for field in ['charid', 'put_off_charid']:
                    if field in sample.DESCRIPTOR.fields_by_name: setattr(sample, field, rng.choice([101, 202, 0]))
                for field in ['weaponid', 'offweaponid']:
                    if field in sample.DESCRIPTOR.fields_by_name: setattr(sample, field, rng.choice([501, 502, 0]))
                if 'equipid' in sample.DESCRIPTOR.fields_by_name: sample.equipid = rng.choice([301, 302])
                updates.append(sample)
            add('mixed-inventory-updates', [bag(chars), items(raw_items), *updates])
        if args.resource_root:
            for template, metadata_row in loadout.weapon_catalog().items():
                levels = metadata_row.get('base_atk') or []
                add('bundled-weapon-'+template, [bag([bag_character()], team=[101]),
                    items([grid(501, template, 'weapon', inst_id=501, weapon_lv=len(levels), refine_lv=2)]),
                    message('SC_WEAPON_ADD_EXP', dict(weaponid=501, weapon_lv=1)),
                    message('SC_WEAPON_REFINE_UPGRADE', dict(weaponid=501, refine_lv=0)),
                    message('SC_WEAPON_PUTON', dict(charid=101, weaponid=999)),
                    items([grid(999, template)]), bag([bag_character(weapon=999)], team=[101])])
            for template in list(loadout.equip_piece_catalog())[:35]:
                add('bundled-equipment-'+template, [bag([bag_character(equips={'0': 301})], team=[101]),
                    items([grid(301, template, 'equip', equipid=301, enhance={'1': 0, '2': 1, '3': 2})]),
                    message('SC_EQUIP_ENHANCE', dict(equip_inst_id=301, equip_data=dict(enhance={'1': 4, '2': -1})))])
            for template, entry in loadout._weapon_refine_catalog().items():
                levels = entry.get('skillLevelToRefine') or {}
                if not levels:
                    continue
                level = int(next(iter(levels)))
                observed_skill = dict(inst_id=88, source='Weapon', level=level,
                    skill_id=dict(type='Skill', int_id=entry['mainSkillNumId']))
                add('bundled-scene-refinement-'+template, [bag([bag_character()], team=[101]),
                    items([grid(501, template)]), message('SC_SELF_SCENE_INFO', dict(detail=dict(char_list=[dict(
                        common_info=dict(id=101, templateid='chr_test'), battle_info=dict(battle_inst_id=11,
                        skill_list=[observed_skill]))]))),
                    message('SC_WEAPON_ATTACH_GEM', dict(weaponid=501, gemid=601)),
                    items([grid(601, 'gem', 'gem', gem_id=601, weapon_id=501,
                        terms=[dict(term_num_id=entry['mainSkillGemTermNumId'], cost=0)])]),
                    message('SC_OBJECT_ENTER_VIEW', dict(detail=dict(char_list=[dict(common_info=dict(id=101, templateid='chr_test'),
                        battle_info=dict(battle_inst_id=11, skill_list=[observed_skill]))]))),
                    batch([operation('BattleOpModifyBattleState', dict(is_in_battle=True), 'modify_battle_state_op_data')])])
    fixture = 'session-inventory' if args.inventory else 'session-scene' if args.scene else 'session-business'
    output = args.output or Path(__file__).resolve().parents[3] / f'_internal/dotnet/Specs/Fixtures/{fixture}.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(cases, ensure_ascii=True, separators=(',', ':')), encoding='utf8')
    resource_hashes = {}
    if args.resource_root:
        for relative in ['data/akedata/weapon', 'data/akedata/equip', 'data/akedata/attribute_type',
                         'data/local_tables/weapon', 'data/local_tables/equip']:
            for path in (args.resource_root / relative).rglob('*.json'):
                resource_hashes[path.relative_to(args.resource_root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    output.with_suffix('.reference.json').write_text(json.dumps(dict(source_head=metadata['head'], cases=len(cases), resource_hashes=resource_hashes,
        protobuf_version=protobuf_version, unavailable_messages=['SC_ATTACH_SERVER_SKILL', 'SC_UPDATE_SERVER_SKILL',
        'SC_DETACH_SERVER_SKILL'], dependencies=dependencies), indent=2), encoding='utf8')
    print('Session business fixtures:', len(cases))


if __name__ == '__main__':
    main()
