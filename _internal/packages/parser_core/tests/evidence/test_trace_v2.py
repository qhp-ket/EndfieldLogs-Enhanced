"""V2 reference framing, native evidence and the explicit v1 read boundary."""
from dataclasses import replace
from io import BytesIO
import json
from pathlib import Path

import pytest

from parser_core.trace_jsonl import TraceEvent, TraceHeader, TraceJsonlReader, TraceJsonlWriter, serialize
from parser_core.trace_model import compact_data, event_data


def header():
    return TraceHeader('v2-test', 1, None, 'python', 'test', 'UTC', 0, {})


def test_v2_definitions_preserve_events_reconnections_and_partial_utf8():
    data = {'actors': {'attacker_id': '101', 'target_id': '201'}, 'action': {'skill': 'skill_template'},
            'evidence': {'debug': {'entity_ref': 88}}, 'same_number': 101}
    events = [TraceEvent(1, 1000, 'damage', data, {'session_id': '捕获一', 'owner_id': '101', 'operation_seq': 8}),
              TraceEvent(2, 999, 'damage', data, {'session_id': '捕获一', 'owner_id': '101', 'operation_seq': 9}),
              TraceEvent(3, 1001, 'damage', data, {'session_id': '捕获二', 'owner_id': '101', 'operation_seq': 0})]
    stream = BytesIO()
    writer = TraceJsonlWriter(stream, header())
    for event in events:
        writer.write(event)
    wire = stream.getvalue()
    rows = [json.loads(line) for line in wire.splitlines()]
    definitions = [row for row in rows if row.get('type') == 'definition']
    assert rows[0]['version'] == 2
    assert [row['session_id'] for row in definitions if row['kind'] == 'capture_session'] == ['捕获一', '捕获二']
    assert [row['id'] for row in definitions if row['kind'] == 'entity'] == ['101', '201']
    assert [row['template'] for row in definitions if row['kind'] == 'template'] == ['skill_template']
    assert [row['seq'] for row in rows[1:] if row['type'] != 'definition'] == [1, 2, 3]
    assert rows[-1]['data']['same_number'] == 101  # Different facts are not interned as identities.
    reader, actual = TraceJsonlReader(), []
    for byte in wire[:-1]:
        actual.extend(reader.feed(bytes([byte])))
    assert reader.pending_bytes
    actual.extend(reader.feed(wire[-1:]))
    assert actual == [header(), *events]


@pytest.mark.parametrize('row', [
    [],
    None,
    {'type': 'definition', 'kind': 'capture_session', 'ref': True, 'session_id': 'session'},
    {'type': 'definition', 'kind': 'entity', 'ref': 2, 'id': '101'},
    {'seq': 1, 'captured_at_ms': 0, 'type': 'damage', 'source': {'session_ref': 9}, 'data': {}},
    {'seq': 1, 'captured_at_ms': 0, 'type': 'damage', 'source': {}, 'data': {'entity_id': {'entity_ref': 1}}},
    {'seq': 1, 'captured_at_ms': 0, 'type': 'damage', 'source': {}, 'data': {'legacy_layout': {}}},
])
def test_v2_rejects_undefined_references_and_legacy_layouts(row):
    reader = TraceJsonlReader()
    reader.feed(serialize(header()))
    with pytest.raises(ValueError):
        reader.feed((json.dumps(row) + '\n').encode())


def test_source_sharing_preserves_independent_facts_missing_fields_and_invalid_ids():
    source = {'session_id': 'session', 'owner_id': '101', 'operation_seq': 8}
    data = compact_data({'operation_seq': 8, 'owner_id': 101, 'event_owner_id': 101,
        'observation': {'operation_seq': 8, 'target_id': 101, 'source_actor_id': True},
        'evidence': {'packet_context': {'packetSeq': 99, 'packetSessionId': 'other'}}}, source, event_type='buff_origin')
    assert data['owner_id'] == data['event_owner_id'] == data['observation']['target_id'] == '101'
    assert 'operation_seq' not in data and 'operation_seq' not in data['observation']
    assert data['observation']['source_actor_id'] is None
    assert data['normalization_errors'] == [{'path': '/observation/source_actor_id', 'status': 'invalid_identity', 'raw': True}]
    assert data['evidence']['packet_context']['packetSeq'] == 99
    native = event_data(TraceEvent(1, 0, 'buff_origin', data, source, 100))
    assert native['observation']['operation_seq'] == 8
    assert 'session_id' not in native['observation'] and 'client_tick_ms' not in native['observation']


def test_v1_layout_remains_readable_but_cannot_leak_into_v2():
    from parser_core.trace_values import project_value
    raw = {'entity_id': 101, 'template': 'chr_test'}
    data, layout = project_value(raw)
    data['legacy_layout'] = layout
    event = TraceEvent(1, 0, 'actor_mapping', data, {})
    stream = BytesIO()
    TraceJsonlWriter(stream, replace(header(), version=1)).write(event)
    actual = TraceJsonlReader().feed(stream.getvalue())
    assert actual[0].version == 1 and event_data(actual[1]) == {'entity_id': '101', 'template': 'chr_test'}
    from parser_core.trace_v1 import export_data
    assert export_data(actual[1].data) == {**raw, 'legacy_layout': layout}
    with pytest.raises(ValueError, match='legacy'):
        TraceJsonlWriter(BytesIO(), header()).write(event)


def test_integer_types_do_not_depend_on_legacy_scalar_representations():
    data = compact_data({'tick_ms': '00042', 'operation_seq': '8',
        'observation': {'client_tick_ms': '00042', 'generation': True},
        'evidence': {'debug_args': {'generation': 'opaque'}}}, {'operation_seq': 8}, 42)
    assert data['tick_ms'] == 42 and 'operation_seq' not in data
    assert data['observation']['client_tick_ms'] == 42 and data['observation']['generation'] is None
    assert data['normalization_errors'] == [{'path': '/observation/generation', 'status': 'invalid_integer', 'raw': True}]
    assert data['evidence']['debug_args']['generation'] == 'opaque'


def test_shared_v2_fixture_roundtrips_business_facts():
    fixture = Path(__file__).resolve().parents[1] / 'fixtures/trace_v2_cross_language.jsonl'
    records = TraceJsonlReader().feed(fixture.read_bytes())
    head, hit, loadout, origin = records
    assert head.version == 2 and hit.data['amounts']['value'] == 12345.6
    assert hit.data['action']['event_owner_id'] == hit.source['owner_id'] == '101'
    assert loadout.data['equip_inst_ids'] == [{'slot': 0, 'entity_id': '401'}]
    assert origin.source['session_id'] == 'session-b'
    assert origin.data['observation']['value'] == {'number_status': 'nan'}
    stream = BytesIO()
    writer = TraceJsonlWriter(stream, head)
    for event in records[1:]:
        writer.write(event)
    assert TraceJsonlReader().feed(stream.getvalue()) == records


def test_invalid_equipment_preserves_raw_evidence_without_becoming_known_empty():
    from parser_core.trace_loadout import typed_loadout, legacy_loadout
    from parser_core.ingestion.loadout_wire import slot_observation
    raw = {'template': 'chr_test', 'equip_inst_ids': '{[bad-slot]=4}',
           'equips': 'damaged', 'equipment_snapshot_complete': True}
    data = typed_loadout(raw)
    assert data['invalid_fields'] == {'equip_inst_ids': raw['equip_inst_ids'], 'equips': 'damaged'}
    assert slot_observation(data).equipment_complete is None
    assert legacy_loadout(data)['equip_inst_ids'] == raw['equip_inst_ids']
    assert 'invalid_fields' not in raw


def test_v2_nonfinite_attributes_remain_unknown_after_disk_roundtrip():
    from endfield_pcap.trace.structured_events import observation_event
    from parser_core.ingestion.structured import consume_trace_event
    from test_structured_entity import state
    event = observation_event(1, 1000, 'entity_stats', {
        'entity_id': 101, 'template': 'chr_0001_alpha', 'kind': 'character',
        'attributes': [{'attr_type': 9, 'value': float('nan')},
                       {'attr_type': 10, 'value': float('inf')}, {'attr_type': 3}]}, {})
    stream = BytesIO()
    TraceJsonlWriter(stream, header()).write(event)
    native = state()
    consume_trace_event(native, TraceJsonlReader().feed(stream.getvalue())[1], 1)
    observed = native.entity_stats_timelines['101'][0][1]
    assert observed['invalid_attr_types'] == [9, 10]
    assert 9 not in observed['attrs'] and 10 not in observed['attrs']
    assert observed['attrs'][3] == 0


def test_opaque_payload_keys_never_become_identities_or_references():
    raw = {'entity_id': '000101', 'bb': {'entity_id': True, 'skill': 'opaque'},
           'evidence': {'debug_args': {'entity_id': {'entity_ref': 999},
                                      'legacy_layout': {'source_actor_id': '0007'}}}}
    data = compact_data(raw, {})
    assert data['entity_id'] == '101' and data['bb'] == raw['bb']
    assert data['evidence'] == raw['evidence'] and 'normalization_errors' not in data
    stream = BytesIO()
    TraceJsonlWriter(stream, header()).write(TraceEvent(1, 1000, 'actor_mapping', data, {}))
    assert TraceJsonlReader().feed(stream.getvalue())[1].data == data


def test_native_loadout_refuses_legacy_string_fields():
    from parser_core.ingestion.loadout_wire import slot_observation, stats_observation
    with pytest.raises(ValueError, match='native loadout array'):
        slot_observation({'template': 'chr_test', 'equip_suit': '{[suit]=3}'})
    with pytest.raises(ValueError, match='native loadout array'):
        stats_observation({'template': 'chr_test', 'weapon_source_skills': 'old:level=1'})


def test_nonfinite_calculations_remain_unknown_to_ink_ledger():
    from parser_core.ink_provenance import ink_trace_observation
    from endfield_pcap.trace.structured_events import observation_event
    event = observation_event(1, 1000, 'blackboard_calculation', {
        'key': 'ink', 'final_value': float('inf'), 'value_a': float('nan'), 'value_b': 2}, {})
    observed = ink_trace_observation(event)
    assert observed.fields['final'] == observed.fields['valueA'] == 'unknown'
    assert observed.fields['valueB'] == '2.0'
    assert event.data['final_value'] == {'number_status': 'positive_infinity'}


def test_native_equipment_analysis_never_restores_or_reparses_strings(monkeypatch):
    from endfield_pcap.trace.structured_events import observation_event
    from parser_core.ingestion.structured import consume_trace_event
    from test_structured_entity import state
    from parser_core.trace_loadout import typed_loadout
    row = typed_loadout({'template': 'chr_0001_alpha', 'entity_id': 101, 'weapon_id': 91,
        'weapon_template': 'wpn_test', 'weapon_lv': 1, 'equip_suit': '{[suit_a]=3}',
        'equips': '{[0]=piece|lv=0:2|stats=main:Atk=5@2}', 'equip_inst_ids': '{[0]=401}',
        'skill_int_ids': '4,5', 'equipment_snapshot_complete': True})
    event = observation_event(1, 1000, 'loadout_slot', row, {})
    assert event.data['equip_suit'] == [{'suit_id': 'suit_a', 'piece_count': 3}]
    assert event.data['equip_inst_ids'] == [{'slot': 0, 'entity_id': '401'}]
    assert event.data['skill_int_ids'] == [4, 5]
    assert event.data['equips'][0]['stats'][0]['value'] == 5
    def forbidden(*args, **kwargs):
        raise AssertionError('V2 analysis used an old representation decoder')
    monkeypatch.setattr('parser_core.trace_values.restore_value', forbidden)
    monkeypatch.setattr('parser_core.ingestion.loadout_wire.compact_body', forbidden)
    monkeypatch.setattr('parser_core.ingestion.loadout._parse_loadout_suits', forbidden)
    monkeypatch.setattr('parser_core.ingestion.loadout._parse_weapon_source_skills', forbidden)
    native = state()
    consume_trace_event(native, event, 1)
    assert native.active_suits_by_char['chr_0001_alpha'] == {'suit_a'}
    assert native.loadout_by_char['chr_0001_alpha']['equips'][0]['enhance_levels'] == [{'index': 0, 'level': 2}]
    consume_trace_event(native, observation_event(2, 1001, 'loadout_stats', {'template': 'chr_0001_alpha'}, {}), 2)
