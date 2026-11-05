"""BUFF event entry preserves existing snapshot and pending-record semantics."""
import pytest

from parser_core.ingestion.structured import consume_trace_event
from endfield_pcap.trace.legacy_buff import buff_legacy_lines
from test_structured_entity import state
from test_structured_identity import event


@pytest.mark.parametrize('kind,values,body', [
    ('blackboard_calculation', {'key': 'rate', 'final_value': -0.0, 'value_a': 1.234567891},
     'BB_SIMPLE_CALC seq=0 tick=0 inst=9007199254740993 ownerId=unknown owner=? packetSessionId=unknown skill=unknown_skill actionId=47 key=rate final=-0.0 valueA=1.234567891'),
    ('blackboard_modify', {'value': 1.234567891},
     'BB_MULTI_MODIFY seq=0 tick=0 inst=9007199254740993 ownerId=unknown owner=? packetSessionId=unknown skill=unknown_skill actionId=47 value=1.23457'),
    ('blackboard_preset', {'modified_value': '甲 "乙"'},
     'BB_SET_PRESET seq=0 tick=0 inst=9007199254740993 ownerId=unknown owner=? packetSessionId=unknown skill=unknown_skill actionId=47 modifiedValue="甲 \\"乙\\""'),
])
def test_blackboard_auxiliary_export_keeps_precision_presence_and_diagnostic_role(kind, values, body):
    from parser_core.ingestion.blackboard_wire import blackboard_data
    from endfield_pcap.trace.legacy_blackboard import blackboard_legacy_lines
    item = event(kind, blackboard_data({'inst_id': 9007199254740993}, 47, '?', 'unknown_skill', **values), 1000)
    stream = state()
    consume_trace_event(stream, item, 8)
    assert not stream.buff_starts and not stream.hits and not stream.dynamic_bb_events
    assert blackboard_legacy_lines(item, timezone_offset_minutes=330) == [f'[05:30:01.000] {body}\n']
    assert stream.last_context_ms == 1000


def test_release_identity_unknown_and_order_are_restored_without_placeholders_on_wire():
    from parser_core.ingestion.blackboard_wire import release_data
    from endfield_pcap.trace.legacy_blackboard import blackboard_legacy_lines
    proof = {'schema_version': 1, 'template_key': 'buff_test', 'action_id': 14,
        'session_id': None, 'operation_seq': 0, 'client_tick_ms': None,
        'buff_uid': '0007', 'owner_id': 'None', 'source_actor_id': 'None', 'projectile_id': '9007199254740993'}
    item = event('ink_release', release_data(proof), 0)
    assert item.data['observation']['buff_inst_id'] == '7'
    assert item.data['observation']['owner_id'] is None and item.data['observation']['projectile_id'] == '9007199254740993'
    assert blackboard_legacy_lines(item, timezone_offset_minutes=0) == [
        '[00:00:00.000] INK_RELEASE {"schema_version":1,"template_key":"buff_test","action_id":14,"session_id":null,"operation_seq":0,"client_tick_ms":null,"buff_uid":"0007","owner_id":"None","source_actor_id":"None","projectile_id":"9007199254740993"}\n']


@pytest.mark.parametrize('conflict', [False, True])
@pytest.mark.parametrize('legacy_binding', [False, True])
def test_structured_ink_ledger_uses_events_across_updates_without_old_text_or_json(monkeypatch, conflict, legacy_binding):
    import json
    from copy import deepcopy
    from parser_test_support.ink import Trace, ATTACKER, SUPPORT
    from parser_core import battle_log_parser as core
    from parser_core.ink_provenance import BUFF, OWNER, EXPLOSION, _ink_provenance_ingestion, ink_trace_observation
    from parser_core.ingestion.blackboard_wire import blackboard_data, release_data
    from parser_core.ingestion.dynamic_wire import dynamic_data
    trace = Trace()
    trace.source(100, 120, {ATTACKER: 100, SUPPORT: 20})
    trace.dynamic(101, 45, 120)
    trace.add(102, 0, 12)
    if conflict:
        trace.add(102, 0, 13)
    trace.release(legacy=legacy_binding)
    trace.explosion(12)
    hits = deepcopy(trace.hits)
    expected_summary = trace.run()
    source = dict(inst_id=7001, owner_id=3001, session_id='test', client_tick_tms=1000)
    def dynamic(seq, action, value):
        identity = dict(schemaVersion=1, sessionId='test', operationSeq=seq, ownerType='1', ownerId='3001',
            environmentInstId='7001', templateType='Buff', actionId=action, clientTickMs='1000', triggerType=0,
            actionType=7, actionRuntimeCase='modify_dynamic_blackboard_action', operationPayloadCase='trigger_action_op_data')
        return event('blackboard_dynamic', dynamic_data(dict(source, seq_id=seq), action, value, '?', BUFF, identity))
    def calc(value):
        return event('blackboard_calculation', blackboard_data(dict(source, seq_id=102), 47, '?', BUFF,
            key='EntityBB_ink_damage', value_a=0, value_b=value, final_value=value))
    items = [event('blackboard_preset', {'modified_value': 'context'}), event('damage', {}), dynamic(101, 45, 120), calc(12)]
    if conflict:
        items.append(calc(13))
    if legacy_binding:
        items.extend([dynamic(129, 13, 0), event('actor_mapping', dict(entity_id='8001', template=OWNER,
            mapping_source='launch_projectile')), event('skill_cast', dict(phase='start', skill_inst_id=8002,
            owner_id=8001, client_tick_ms=1000, operation_seq=131, skill=EXPLOSION))])
    else:
        items.append(event('ink_release', release_data(dict(schema_version=1, template_key=BUFF, action_id=14,
            session_id='test', operation_seq=130, buff_uid='7001', owner_id='3001', source_actor_id='4001',
            projectile_id='8001', client_tick_ms=1000))))
    items.extend([dynamic(132, 15, 0), event('damage', {})])
    roots = core._load_current_buff_roots()
    monkeypatch.setattr(json, 'loads', lambda *_a, **_k: pytest.fail('Direct ink observations parsed JSON'))
    import parser_core.ink_provenance as ink
    monkeypatch.setattr(ink, '_legacy_ink_observation', lambda *_: pytest.fail('Typed ledger entered the text adapter'))
    observations = [(index, ink_trace_observation(item)) for index, item in enumerate(items, 1)]
    stream = _ink_provenance_ingestion(root_lookup=roots, extract_fields=lambda *_: pytest.fail('Parsed legacy fields'))
    next(stream)
    stream.send((observations[:4], hits[:1], trace.records))
    result = stream.send((observations[4:], hits, trace.records))
    assert result == expected_summary and hits == trace.hits
    stream.close()


def start(uid=71, timestamp=1000, **fields):
    return event('buff_start', {'buff_seq': 1, 'buff_inst_id': uid, 'template': 'buff_test',
        'owner': 'eny_0001_test', 'source': 'chr_0001_alpha', 'target_id': 21,
        'source_actor_id': 11, **fields}, timestamp)


def blackboard(uid=71, timestamp=1000, **values):
    return event('buff_blackboard', {'buff_inst_id': uid,
        'values': [{'key': key, 'value': value} for key, value in values.items()]}, timestamp)


def test_snapshots_reuse_instance_and_end_latest_with_capture_time(monkeypatch):
    import parser_core.ingestion.hits as hits
    import parser_core.ingestion.buff_observations as buffs
    monkeypatch.setattr(hits, '_extract_fields', lambda *_: pytest.fail('Typed BUFF parsed legacy text'))
    monkeypatch.setattr(buffs, '_extract_fields', lambda *_: pytest.fail('Typed BB parsed legacy text'))
    stream = state()
    consume_trace_event(stream, start(), 3)
    consume_trace_event(stream, blackboard(def_decrease=-0.123456789, rate=0), 4)
    first = stream.buff_starts[0]
    assert first['bb_values'] == {'def_decrease': -0.123457, 'rate': 0.0}
    consume_trace_event(stream, start(timestamp=1500), 5)
    second = stream.buff_starts[1]
    assert second['instance_start_line_no'] == 3 and second['snapshot_update']
    assert first['snapshot_end_ts_ms'] == 1500 and first['snapshot_end_line_no'] == 5
    assert second['bb_values'] == first['bb_values'] and second['bb_values'] is not first['bb_values']
    consume_trace_event(stream, blackboard(timestamp=1500, rate=2), 6)
    assert second['bb_values']['rate'] == 2 and first['bb_values']['rate'] == 0
    consume_trace_event(stream, event('buff_end', {'buff_seq': 2, 'buff_inst_id': 71}, 1200), 7)
    assert second['end_ts_ms'] == 1200 and second['end_line_no'] == 7
    assert first['end_ts_ms'] is None and not stream.active_buff_starts_by_uid
    assert stream.pending_buff_record is second and not stream.party_actor_ids


@pytest.mark.parametrize('uid', [0, 4294967295])
def test_sentinel_ids_remain_observation_only(uid):
    stream = state()
    consume_trace_event(stream, start(uid), 1)
    assert stream.buff_starts[0]['uid'] == '' and stream.buff_starts[0]['uid_observation_only']
    assert not stream.active_buff_starts_by_uid


def test_missing_actor_does_not_make_a_window_and_blackboard_never_rebinds_uid():
    stream = state()
    consume_trace_event(stream, start(), 1)
    consume_trace_event(stream, blackboard(uid=999, rate=2), 2)
    assert stream.buff_starts[0]['bb_values']['rate'] == 2
    consume_trace_event(stream, start(uid=72, owner=None, source=None), 3)
    assert stream.pending_buff_record is None and len(stream.buff_starts) == 1
    consume_trace_event(stream, blackboard(rate=3), 4)
    assert stream.buff_starts[0]['bb_values']['rate'] == 2


def test_wide_ids_raw_precision_and_independent_export():
    item = start(uid=18446744073709551615, source_actor_id=9007199254740993)
    assert item.data['buff_inst_id'] == '18446744073709551615'
    assert item.data['source_actor_id'] == '9007199254740993'
    assert buff_legacy_lines(item, timezone_offset_minutes=480) == [
        '[08:00:01.000] BUFF_START #1 id="buff_test" uid=18446744073709551615 owner=eny_0001_test '
        'src=chr_0001_alpha ownerId=21 srcId=9007199254740993 dur=unknown lifeT=unknown passed=unknown enh=unknown\n']
    bb = blackboard(rate=1.23456789)
    assert bb.data['values'][0]['value'] == 1.23456789
    assert buff_legacy_lines(bb, timezone_offset_minutes=-60) == ['[23:00:01.000] BB[71]: rate=1.23457\n']


def test_nonfinite_blackboards_keep_keys_without_creating_values():
    stream = state()
    consume_trace_event(stream, start(), 1)
    item = blackboard(rate=float('nan'), another=float('inf'))
    consume_trace_event(stream, item, 2)
    assert stream.buff_starts[0]['bb_keys'] == ['rate', 'another']
    assert stream.buff_starts[0]['bb_values'] == {}
    assert buff_legacy_lines(item, timezone_offset_minutes=0) == ['[00:00:01.000] BB[71]: rate=nan another=inf\n']


def test_invalid_blackboard_is_validated_before_mutation():
    stream = state()
    consume_trace_event(stream, start(), 1)
    with pytest.raises(ValueError, match='blackboard'):
        consume_trace_event(stream, event('buff_blackboard', {'buff_inst_id': 71,
            'values': [{'key': 'valid', 'value': 1}, {'key': 'invalid', 'value': True}]}, 1000), 2)
    assert stream.buff_starts[0]['bb_values'] == {} and stream.buff_starts[0]['bb_keys'] == []


def test_business_producer_flush_order_and_snapshot_reset():
    from endfield_pcap.trace.bridge import TraceBridge
    items, fallback = [], []
    bridge = TraceBridge(write_enabled=False, event_sink=items.append, line_sink=fallback.append)
    bridge.id_to_name.update({11: 'chr_0001_alpha', 21: 'eny_0001_test'})
    bridge.handle_event({'type': 'BattleOpAddBuff', 'timestamp_ms': 1000, 'buff_inst_id': 71,
        'str_id': 'buff_test', 'src_inst_id': 11, 'target_inst_id': 21, 'seq_id': 7,
        'assigned_items': {'blackboard': {'rate': {'float_value': 1.23456789}}}})
    bridge.handle_event({'type': 'BattleOpFinishBuff', 'timestamp_ms': 1200, 'buff_inst_id': 71})
    assert [item.type for item in items] == ['buff_start', 'buff_blackboard', 'buff_creation', 'buff_end']
    assert items[0].source['operation_seq'] == 7
    assert items[1].data['values'][0]['value'] == 1.23456789
    assert not any(' BUFF_START ' in row or ' BB[' in row or ' BUFF_END ' in row for row in fallback)
    bridge.begin_capture_session(timestamp_ms=2000)
    bridge.handle_event({'type': 'BattleOpFinishBuff', 'timestamp_ms': 2100, 'buff_inst_id': 71})
    assert items[-1].data['template'] is None and items[-1].data['buff_seq'] == 1
    assert [item.sequence for item in items] == list(range(1, len(items) + 1))
    bridge.handle_event({'type': 'BattleOpAddBuff', 'timestamp_ms': 2200, 'buff_inst_id': 72})
    bridge.handle_event({'type': 'BattleOpFinishBuff', 'timestamp_ms': 2300, 'buff_inst_id': 72})
    assert items[-1].data['template'] is None and items[-1].data['template_status'] == 'unresolved'
    assert 'id="unknown_buff" uid=72' in buff_legacy_lines(items[-1], timezone_offset_minutes=0)[0]


def packet(kind, observation, timestamp=1000):
    from parser_core.ingestion.buff_packet_wire import packet_data
    return event(kind, packet_data(observation), timestamp)


def creation(**fields):
    return {'schemaVersion': 1, 'buffUid': '71', 'buffTemplate': 'buff_test',
            'sourceActorId': '11', 'targetActorId': '21', 'sessionId': 's',
            'operationSeq': 1, 'operationOwnerId': '21', 'operationGeneration': 0,
            'generationScope': 'operation_owner', 'sourceEvent': 'BattleOpAddBuff',
            'buffId': 'buff_test', 'assignedItems': [{'target_key': 'rate',
                'use_direct_value': True, 'numeric_value': 0.123456789}], **fields}


def test_packet_creation_origin_enable_share_rules_without_legacy_parsing(monkeypatch):
    import parser_core.ingestion.buff_observations as buffs
    monkeypatch.setattr(buffs, '_read_buff_packet', lambda *_: pytest.fail('Typed proof parsed old JSON text'))
    stream = state()
    consume_trace_event(stream, start(), 1)
    consume_trace_event(stream, packet('buff_creation', creation()), 2)
    record = stream.buff_starts[0]
    assert record['creation_observations'][0]['bb_values'] == {'rate': 0.123456789}
    consume_trace_event(stream, packet('buff_origin', {'schemaVersion': 1, 'buffUid': '71',
        'buffTemplate': 'buff_test', 'sourceActorId': '11', 'targetActorId': '21',
        'environmentInstId': '11', 'actionId': 4, 'operationSeq': 1, 'triggerType': 0}), 3)
    assert record['origin_observations'][0]['_boundCreateRecord'] is True
    for enabled in (True, False):
        consume_trace_event(stream, packet('buff_enable', {'schemaVersion': 1, 'buffUid': '71',
            'enabled': enabled, 'ownerId': '21', 'operationSeq': 2}), 4)
    assert record['rdps_conflicting_enable_state'] is True
    assert [row['enabled'] for row in record['enable_observations']] == [True, False]
    assert stream.unresolved_buff_actions[-1]['reason'] == 'conflicting_buff_enable_state'
    consume_trace_event(stream, packet('buff_creation', creation(operationSeq=0)), 5)
    assert record['repeated_creation_observations'][-1]['status'] == 'out_of_order'
    consume_trace_event(stream, packet('buff_creation', creation()), 6)
    assert record['repeated_creation_observations'][-1]['status'] == 'duplicate'
    consume_trace_event(stream, packet('buff_creation', creation(sessionId=None)), 7)
    assert len(record['creation_observations']) == 1
    assert stream.unresolved_buff_actions[-1]['reason'] == 'unbound_buff_creation_observation'


def test_keyword_packets_keep_approval_conflicts_and_invalid_row_evidence(monkeypatch):
    import parser_core.ingestion.buff_observations as buffs
    approved = {'_rdps_whitelist_keys': ['buff_chr_0023_antal_normal_fragile'], '_keyword_origin': [{'actionId': 5}]}
    monkeypatch.setattr(buffs, '_rdps_registry_matching_effect_entry', lambda *_args, **_kwargs: approved)
    monkeypatch.setattr(buffs, '_load_num_id_str_buff_map', lambda: {'9': 'buff_mark'})
    monkeypatch.setattr(buffs, '_load_current_buff_roots', lambda: {'buff_chr_0023_antal_tageffect': {
        '$type': 'Beyond.Gameplay.Core.VulnerableAction.Data', 'serverActionIndex': 5,
        'enhancingList': [{'operationType': 'Add', 'value': {'useBlackboardKey': True,
            'blackboardKey': 'potential_5_rate'}, 'buffIds': ['buff_mark']}]}})
    stream = state()
    consume_trace_event(stream, start(), 1)
    consume_trace_event(stream, packet('buff_creation', creation()), 2)
    observation = {'schemaVersion': 1, 'buffUid': '71', 'ownerId': '21', 'sessionId': 's',
        'operationSeq': 2, 'generation': 0, 'addedBuffNumId': 9,
        'operationPayloadCase': 'trigger_keyword_op_data', 'modify': [{'configIndex': 0, 'rateAfter': 0.5}]}
    consume_trace_event(stream, packet('buff_keyword', observation), 3)
    record = stream.buff_starts[0]
    assert record['keyword_rate_snapshots'][0]['rate_after'] == 0.5
    observation['modify'][0]['rateAfter'] = 0.7
    consume_trace_event(stream, packet('buff_keyword', observation), 4)
    assert record['keyword_rate_snapshots'][0]['status'] == 'conflicting_keyword_update'
    for sequence, row, reason in ((3, [], 'invalid_keyword_config_index'), (4, 7, 'invalid_keyword_modify_row')):
        consume_trace_event(stream, packet('buff_keyword', {**observation, 'operationSeq': sequence, 'modify': [row]}), 5)
        assert record['keyword_rate_snapshots'][-1]['status'] == 'unresolved_keyword_update'
        assert stream.unresolved_buff_actions[-1]['reason'] == reason
    monkeypatch.setattr(buffs, '_rdps_registry_matching_effect_entry', lambda *_args, **_kwargs: None)
    consume_trace_event(stream, packet('buff_keyword', {**observation, 'operationSeq': 5}), 6)
    assert stream.unresolved_buff_actions[-1]['reason'] == 'keyword_update_without_approved_origin'
    assert len(record['keyword_rate_snapshots']) == 3


def test_packet_export_preserves_nested_order_ascii_and_unknown_template():
    from endfield_pcap.trace.legacy_buff_packet import buff_packet_legacy_lines
    item = packet('buff_creation', {'buffTemplate': 'unknown_buff', 'buffUid': '9007199254740993',
        'assignedItems': [{'numeric_value': 0.123456789, 'target_key': '增伤'}]})
    assert item.data['observation']['template'] is None and item.data['template_status'] == 'unresolved'
    assert buff_packet_legacy_lines(item, timezone_offset_minutes=0) == [
        '[00:00:01.000] BUFF_CREATE_OBSERVED {"buffTemplate":"unknown_buff","buffUid":"9007199254740993",'
        '"assignedItems":[{"numeric_value":0.123456789,"target_key":"增伤"}]}\n']
    enabled = packet('buff_enable', {'enabled': True, 'sessionId': '会话', 'buffUid': '71'})
    assert buff_packet_legacy_lines(enabled, timezone_offset_minutes=0) == [
        '[00:00:01.000] BUFF_ENABLE {"enabled":true,"sessionId":"\\u4f1a\\u8bdd","buffUid":"71"}\n']


@pytest.mark.parametrize('extra,seq', [({}, 'unknown'), ({'operation_seq': None}, 'None'), ({'operation_seq': 0}, '0')])
def test_unresolved_packet_preserves_missing_and_explicit_null(extra, seq):
    from endfield_pcap.trace.legacy_buff_packet import buff_packet_legacy_lines
    item = event('buff_unresolved', {'buff_inst_id': 71, 'action_id': None, 'trigger_type': None,
        'target_id': 21, 'source_actor_id': None, **extra}, 1000)
    stream = state()
    consume_trace_event(stream, item, 3)
    assert stream.unresolved_buff_actions[0]['seq'] == seq
    assert stream.unresolved_buff_actions[0]['target_actor_id'] == '21'
    assert buff_packet_legacy_lines(item, timezone_offset_minutes=0) == [
        f'[00:00:01.000] BUFF_ACTION_UNRESOLVED uid=71 seq={seq} triggerType=unknown actionId=None ownerId=21 srcId=None\n']


def dynamic_identity(sequence, *, refresh=False):
    return {'schemaVersion': 1, 'sessionId': 's', 'operationSeq': sequence, 'operationOwnerId': '21',
            'ownerType': 1, 'ownerId': '21', 'environmentInstId': '71', 'generation': 0,
            'templateType': 'Buff', 'templateIdCase': 'str_id', 'templateStrId': 'buff_test',
            'templateIntId': None, 'actionId': 2 if refresh else 1, 'triggerType': 0,
            'actionType': 31 if refresh else 7,
            'actionRuntimeCase': 'refresh_buff_attr_modifier_value_action' if refresh else 'modify_dynamic_blackboard_action',
            'operationPayloadCase': 'trigger_action_op_data', **({'buffUid': '71'} if refresh else {})}


def dynamic_update(sequence, value):
    from parser_core.ingestion.dynamic_wire import dynamic_data
    return event('blackboard_dynamic', dynamic_data({'seq_id': sequence, 'client_tick_tms': 700,
        'inst_id': 71, 'owner_id': 21}, 1, value, 'eny_0001_test', 'buff_test', dynamic_identity(sequence)), 1000)


def test_dynamic_value_requires_refresh_and_late_conflict_invalidates_snapshot(monkeypatch):
    import parser_core.ingestion.dynamic_evidence as dynamics
    root = {'actions': [
        {'$type': 'Beyond.Gameplay.Core.ModifyDynamicBlackboard.Data', 'serverActionIndex': 1,
         'isEnable': True, 'key': 'rate', 'operation': 'Add', 'value': {}},
        {'$type': 'Beyond.Gameplay.Core.RefreshBuffAttrModifierValue.Data', 'serverActionIndex': 2, 'isEnable': True}],
        'attributeModifier': {'attributeModifiers': [{'attributeType': 'Atk', 'formulaItem': 'Add',
            'param': {'useBlackboardKey': True, 'blackboardKey': 'rate'}}]}}
    monkeypatch.setattr(dynamics, '_load_current_buff_roots', lambda: {'buff_test': root})
    stream = state()
    consume_trace_event(stream, start(), 1)
    consume_trace_event(stream, packet('buff_creation', creation()), 2)
    update = dynamic_update(2, 0.5)
    refresh = packet('buff_attribute_refresh', dynamic_identity(3, refresh=True))
    conflict = dynamic_update(2, 0.7)
    monkeypatch.setattr(dynamics.json, 'loads', lambda *_args, **_kwargs: pytest.fail('Typed runtime parsed JSON'))
    consume_trace_event(stream, update, 3)
    record = stream.buff_starts[0]
    assert stream.dynamic_bb_events[-1]['state_status'] == 'pending_attribute_refresh'
    assert record['_dynamic_pending_state']['values']['rate'] == 0.5
    assert not record['attribute_refresh_snapshots'] and record['bb_values'] == {}
    consume_trace_event(stream, refresh, 4)
    saved = record['attribute_refresh_snapshots'][0]
    assert saved['status'] == 'attribute_parameters_observed' and saved['bb_values']['rate'] == 0.5
    assert saved['final_modifiers_verified'] is False
    consume_trace_event(stream, conflict, 5)
    assert saved['status'] == 'conflicting_dynamic_operation' and saved['conflicting_operation_seqs'] == [2]
    assert stream.dynamic_bb_events[-1]['state_error'] == 'conflicting_dynamic_operation_order'


def test_dynamic_missing_anchor_and_skill_setting_diagnostic_semantics():
    stream = state()
    consume_trace_event(stream, start(), 1)
    consume_trace_event(stream, dynamic_update(2, 0.5), 2)
    assert stream.dynamic_bb_events[-1]['state_error'] == 'missing_compatible_buff_creation_observation'
    consume_trace_event(stream, packet('blackboard_skill_setting', {'runtime': {}, 'actionSerialization': None,
        'validationErrors': ['invalid_skill_setting_runtime']}), 3)
    assert len(stream.dynamic_bb_events) == 1 and not stream.buff_attribute_refresh_events
    assert not stream.buff_starts[0]['attribute_refresh_snapshots']


def test_dynamic_independent_export_keeps_scalar_and_nested_proof_order():
    from endfield_pcap.trace.legacy_dynamic import dynamic_legacy_lines
    from parser_core.ingestion.dynamic_wire import dynamic_data
    item = event('blackboard_dynamic', dynamic_data({'seq_id': 0, 'inst_id': 71}, 1, -0.0,
        '?', 'unknown_skill', {'schemaVersion': 1, 'eventContext': {'seq_id': 0, 'inst_id': 71}}), 1000)
    assert dynamic_legacy_lines(item, timezone_offset_minutes=0) == [
        '[00:00:01.000] BB_MODIFY_DYNAMIC seq=0 tick=0 inst=71 ownerId=unknown owner=? packetSessionId=unknown '
        'skill=unknown_skill actionId=1 value=-0.0 identity={"schemaVersion":1,"eventContext":{"seq_id":0,"inst_id":71}}\n']
    for runtime in ({}, None):
        fields = {'runtime': runtime, 'validationErrors': ['invalid_skill_setting_runtime']}
        item = packet('blackboard_skill_setting', fields)
        assert item.data['observation']['runtime'] == runtime
        assert 'BB_READ_SKILL_SETTING_UNRESOLVED ' in dynamic_legacy_lines(item, timezone_offset_minutes=0)[0]
