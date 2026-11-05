"""Entity observations keep the existing full/partial state and export meanings."""
from copy import deepcopy
from datetime import date
from math import copysign

import pytest

from parser_core.ingestion.state import IngestionState
from parser_core.ingestion.structured import consume_trace_event, consume_trace_events
from parser_core.trace_jsonl import TraceEvent, parse, serialize
from parser_core.trace_values import project_value


def state():
    return IngestionState(reference_date=date(2026, 10, 31), first_hit_hint_ms=None,
                          last_hit_hint_ms=None, context_enemy_hint=None, trace_identity_inference_seen=False,
                          loadout_override_by_char=None, critical_attributes_override_by_actor=None)


def event(rows, *, partial=False, template='chr_0001_alpha', timestamp=1793412000123, **fields):
    data, layout = project_value({'entity_id': 9007199254740993, 'template': template,
                                 **({} if partial else {'kind': 'character'}), 'attributes': rows, **fields})
    data['legacy_layout'] = layout
    return parse(serialize(TraceEvent(1, timestamp, 'entity_attributes' if partial else 'entity_stats', data, {})), header=False)


def test_full_and_partial_attributes_share_state_without_text(monkeypatch):
    import parser_core.ingestion.entities as entities
    from endfield_pcap.trace.legacy_entity import entity_legacy_lines
    full = event([{'attr_type': 9, 'value': 0.123456789, 'basic_value': 0.12},
                  {'attr_type': 10, 'value': 0.5}, {'attr_type': 3, 'value': 100}], level=80)
    assert full.data['attributes'][0]['value'] == 0.123456789
    stream = state()
    monkeypatch.setattr(entities, '_parse_entity_stats_snapshot', lambda *_: pytest.fail('Typed entity used text parser'))
    consume_trace_event(stream, full, 4)
    identity = '9007199254740993'
    snapshot = stream.entity_stats_timelines[identity][0][1]
    assert snapshot['attrs'] == {9: 0.123457, 10: 0.5, 3: 100}
    assert snapshot['basic_attrs'][9] == 0.12 and snapshot['level'] == 80
    assert stream.party_actor_ids == {identity}
    update = event([{'attr_type': 9, 'value': 0.25}, {'attr_type': 3, 'value': 200}], partial=True,
                   timestamp=full.captured_at_ms - 1)
    consume_trace_events(stream, [(5, update)])
    assert len(stream.entity_stats_timelines[identity]) == 1 and snapshot['attrs'][3] == 100
    assert stream.critical_stats_by_actor[identity]['values'] == {9: 0.25, 10: 0.5}
    assert stream.critical_stats_by_actor[identity]['times'][9] == full.captured_at_ms - 1
    assert stream.last_context_ms == full.captured_at_ms - 1
    consume_trace_event(stream, event([{'attr_type': 9, 'value': 1}, {'attr_type': 9, 'value': 2},
                                      {'attr_type': 9, 'value': 3}], partial=True), 6)
    assert stream.critical_stats_by_actor[identity]['values'] == {10: 0.5}
    consume_trace_event(stream, event([], partial=True, template='chr_0002_beta'), 7)
    assert identity not in stream.critical_stats_by_actor
    assert '9:0.123457/0.12' in entity_legacy_lines(full, timezone_offset_minutes=480)[0]


def test_entity_unknown_values_export_and_epoch_boundary():
    from endfield_pcap.trace.legacy_entity import entity_legacy_lines
    item = event([{'attr_type': 9, 'value': float('nan')}, {'attr_type': 10, 'value': float('inf')},
                  {'attr_type': 3, 'value': -0.0}, {'attr_type': 4}, {'value': 99},
                  {'attr_type': 5, 'value': 1, 'basic_value': float('-inf')}], timestamp=-1, hp=None)
    stream = state()
    consume_trace_event(stream, item, 1)
    snapshot = stream.entity_stats_timelines['9007199254740993'][0][1]
    assert snapshot['invalid_attr_types'] == [9, 10]
    assert snapshot['attrs'][4] == 0 and 5 not in snapshot['basic_attrs']
    assert copysign(1, snapshot['attrs'][3]) == -1
    assert entity_legacy_lines(item, timezone_offset_minutes=330) == [
        '[05:29:59.999] ENTITY_STATS id=9007199254740993 template=chr_0001_alpha kind=character '
        'level=unknown hp=unknown attrs=[9:nan/nan 10:inf/inf 3:-0/-0 4:0/0 5:1/-inf]\n']
    assert 'level' not in item.data and item.data['hp'] is None


def test_business_entity_producer_owns_evidence_and_avoids_formatter(monkeypatch):
    import endfield_pcap.trace.actors as actors
    from endfield_pcap.trace.bridge import TraceBridge
    monkeypatch.setattr(actors, '_entity_attr_tokens', lambda *_: pytest.fail('Typed producer used legacy formatter'))
    events = []
    bridge = TraceBridge(write_enabled=False, line_sink=lambda *_: pytest.fail('Unexpected text output'), event_sink=events.append)
    original = {'type': 'SC_SELF_SCENE_INFO', 'timestamp_ms': 1793412000123,
                'session_id': '合成', 'seq_id': 7, 'generation': 0, 'operation_owner_id': 11, 'client_tick_tms': 0,
                'char_list': [{'battle_inst_id': 9007199254740993, 'templateid': 'chr_0001_alpha',
                               'attrs': [{'attr_type': 9, 'value': 0.123456789}]}]}
    bridge.handle_event(original)
    original['char_list'][0]['attrs'][0]['value'] = 99
    assert events[0].data['entity_id'] == '9007199254740993'
    assert events[0].data['attributes'][0]['value'] == 0.123456789
    assert events[0].source == {'session_id': '合成', 'operation_seq': 7, 'generation': 0, 'owner_id': '11'}
    assert events[0].client_tick_ms == 0
    bridge.handle_event({'type': 'SC_SYNC_ATTR', 'timestamp_ms': 1793412000122, 'battle_inst_id': 9007199254740993,
                         'obj_id': 0, 'attrs': [{'attr_type': 9, 'value': 0.25}]})
    assert [item.sequence for item in events] == [1, 2]
    assert events[1].data['object_id'] == '0' and events[1].data['template'] == 'chr_0001_alpha'
    stream = state()
    consume_trace_events(stream, enumerate(events, 1))
    events[0].data['attributes'][0]['value'] = 77
    assert stream.entity_stats_timelines['9007199254740993'][0][1]['attrs'][9] == 0.123457


@pytest.mark.parametrize('mutation', ['numeric_id', 'missing_id', 'label'])
def test_invalid_entity_rejected_before_stream_mutation(mutation):
    item = deepcopy(event([]))
    if mutation == 'numeric_id':
        item.data['entity_id'] = 11
    elif mutation == 'missing_id':
        item.data.pop('entity_id')
    else:
        item.data['template'] = []
    stream = state()
    with pytest.raises(ValueError):
        consume_trace_event(stream, item, 1)
    assert not stream.entity_stats_timelines and not stream.party_actor_ids and stream.first_context_ms is None


def test_partial_event_destination_cannot_create_incomplete_archive(tmp_path):
    from endfield_pcap.trace.bridge import TraceBridge
    with pytest.raises(ValueError, match='不完整'):
        TraceBridge(tmp_path / 'not-created.log', event_sink=lambda *_: None)
    with pytest.raises(ValueError, match='one structured'):
        TraceBridge(write_enabled=False, event_sink=lambda *_: None, damage_sink=lambda *_: None)
    assert not (tmp_path / 'not-created.log').exists()


def test_diagnostic_entities_preserve_presence_vectors_and_independent_export(monkeypatch):
    from endfield_pcap.trace.bridge import TraceBridge
    from endfield_pcap.trace.legacy_entity import entity_legacy_lines
    import parser_core.ingestion.entities as entities
    events = []
    bridge = TraceBridge(write_enabled=False, line_sink=lambda *_: pytest.fail('Structured diagnostic emitted text'),
                         event_sink=events.append)
    bridge.handle_event({'type': 'BattleOpEntityValueModify', 'timestamp_ms': -1, 'entity_inst_id': '0007',
                         'seq_id': None, 'scene_num_id': 0, 'hp': float('inf'), 'delta_value': -0.0,
                         'template_int_id': 0})
    bridge.handle_event({'type': 'BattleOpEntityDie', 'timestamp_ms': -1, 'entity_inst_id': '0007'})
    bridge.handle_event({'type': 'BattleOpEntityDie', 'timestamp_ms': -1})
    spawn = {'type': 'BattleOpTriggerAction', 'timestamp_ms': -1, 'seq_id': 0, 'client_tick_tms': 0,
             'inst_id': 0, 'owner_id': '0007', 'action': {'action_type': 'BattleActionSpawnAbilityEntity', 'action_id': 4,
             'spawn_ability_entity_action': {'details': [None, {'source_id': 0, 'client_ability_entity_id': 9007199254740993,
                 'init_pos': {'x': 1.23456789, 'y': None, 'z': -0.0}, 'rotation': {'x': float('inf')}}, {}]}}}
    bridge.handle_event(spawn)
    spawn['action']['spawn_ability_entity_action']['details'][1]['init_pos']['x'] = 99
    events = [parse(serialize(item), header=False) for item in events]
    assert [item.type for item in events] == ['entity_value', 'entity_die', 'entity_die', 'ability_spawn', 'ability_spawn']
    assert [item.sequence for item in events] == list(range(1, 6))
    assert events[0].data['entity_id'] == '7' and 'ultimate_sp' not in events[0].data
    assert 'entity_id' not in events[2].data and events[3].data['detail']['source_actor_id'] == '0'
    assert events[3].data['detail']['position']['x'] == 1.23456789
    assert events[4].data['detail'] == {} and 'template_int_id' not in events[4].data
    bodies = [line for item in events for line in entity_legacy_lines(item, timezone_offset_minutes=0)]
    assert bodies == [
        '[23:59:59.999] ENTITY_VALUE seq=None id=7 scene=0 hp=inf ult=unknown delta=-0.0 srcType=unknown srcInt=0 origSrcType=unknown origSrcInt=unknown\n',
        '[23:59:59.999] ENTITY_DIE id=0007\n', '[23:59:59.999] ENTITY_DIE id=None\n',
        '[23:59:59.999] ABILITY_ENTITY_SPAWN seq=0 tick=0 actionId=4 inst=0 skill=unknown_skill templateIntId=unknown ownerId=7 owner=id_7 sourceId=7 source=id_7 entityId=9007199254740993 pos=1.23456789,unknown,-0.0 rot=inf,unknown,unknown\n',
        '[23:59:59.999] ABILITY_ENTITY_SPAWN seq=0 tick=0 actionId=4 inst=0 skill=unknown_skill templateIntId=unknown ownerId=7 owner=id_7 sourceId=7 source=id_7 entityId=unknown pos=unknown,unknown,unknown rot=unknown,unknown,unknown\n']
    monkeypatch.setattr(entities, '_parse_entity_stats_snapshot', lambda *_: pytest.fail('Diagnostic used old parser'))
    stream = state()
    consume_trace_events(stream, enumerate(events, 1))
    assert stream.last_context_ms == -1 and not stream.party_actor_ids
    assert not stream.entity_stats_timelines and not stream.critical_stats_by_actor and not stream.hits


def test_malformed_diagnostic_identity_does_not_mutate_stream():
    for kind, data in [('entity_die', {'entity_id': 7}), ('entity_value', {'entity_id': '-1'}),
                       ('ability_spawn', {'detail': {'source_actor_id': 1}})]:
        stream = state()
        with pytest.raises(ValueError):
            consume_trace_event(stream, TraceEvent(1, 0, kind, data, {}), 1)
        assert stream.first_context_ms is None and not stream.party_actor_ids
