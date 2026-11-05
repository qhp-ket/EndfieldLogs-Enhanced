"""Explicit squad updates and diagnostic mappings retain legacy authority rules."""
from parser_core.ingestion.identity import _SQUAD_MEMBER_RE, squad_bindings
from parser_core.ingestion.structured import consume_trace_event
from parser_core.trace_jsonl import TraceEvent, parse, serialize
from parser_core.trace_values import project_value
from test_structured_entity import state

import pytest


def event(kind, data, timestamp=1793412000123):
    projected, layout = project_value(data)
    projected['legacy_layout'] = layout
    return parse(serialize(TraceEvent(1, timestamp, kind, projected, {})), header=False)


def test_squad_order_duplicate_invalid_and_empty_membership():
    stream = state()
    def squad(members):
        return event('squad', {'members': [{'template': template, 'entity_id': identity} for template, identity in members]})
    first = squad([('chr_0002_beta', 22), ('chr_0001_alpha', '0011'), ('sample', 33), ('chr_0003_gamma', None)])
    consume_trace_event(stream, first, 1)
    assert list(stream.squad_actor_keys.items()) == [('22', 'chr_0002_beta'), ('0011', 'chr_0001_alpha')]
    assert stream.party_actor_ids == {'22', '0011'}
    consume_trace_event(stream, squad([('chr_0002_beta', 22), ('chr_0001_alpha', 22)]), 2)
    assert stream.squad_actor_keys == {} and stream.party_actor_ids == {'22', '0011'}
    consume_trace_event(stream, squad([]), 3)
    assert stream.squad_actor_keys == {} and stream.party_actor_ids == {'22', '0011'}


def test_separate_fields_retain_legacy_member_policy_without_building_log_rows():
    templates = ['chr_0001_alpha', 'sample', 'chr_0001_alpha_123', 'chr_0001_alpha_chr_0002_beta',
                 'chr_0001_alpha_1chr_0002_beta', 'prefix chr_0001_alpha']
    identities = [None, -11, 0, 11, '0011', '11x', 'bad chr_0003_gamma_33']
    for template in templates:
        for identity in identities:
            old = [(match.group(2), match.group(1)) for match in _SQUAD_MEMBER_RE.finditer(f'{template}_{identity}')]
            assert squad_bindings([(template, identity)]) == old


def test_mapping_diagnostic_is_not_new_identity_authority_and_exports_independently():
    from endfield_pcap.trace.legacy_identity import identity_legacy_lines
    stream = state()
    item = event('actor_mapping', {'entity_id': 9007199254740993, 'template': 'chr_0001_alpha',
                                  'mapping_source': 'skill_attach', 'skill': None}, -1)
    consume_trace_event(stream, item, 1)
    assert not stream.party_actor_ids and not stream.squad_actor_keys
    assert stream.first_context_ms == stream.last_context_ms == -1
    assert identity_legacy_lines(item, timezone_offset_minutes=330) == [
        '[05:29:59.999] ACTOR_MAP id=9007199254740993 template=chr_0001_alpha source=skill_attach skill=None\n']
    squad = event('squad', {'members': [{'entity_id': '0011', 'template': 'chr_0001_alpha'},
                                      {'entity_id': None, 'template': 'chr_0002_beta'}]}, -1)
    assert identity_legacy_lines(squad, timezone_offset_minutes=330) == [
        '[05:29:59.999] SQUAD size=2 members=[chr_0001_alpha_0011 chr_0002_beta_None]\n']


def test_business_mapping_and_squad_share_sequence_and_existing_deduplication():
    from endfield_pcap.trace.bridge import TraceBridge
    events = []
    bridge = TraceBridge(write_enabled=False, line_sink=lambda *_: pytest.fail('Connected identity leaked into text'), event_sink=events.append)
    attach = {'type': 'BattleOpSkillAttach', 'timestamp_ms': 1793412000123, 'skill_inst_id': 100,
              'src_inst_id': 11, 'template_str_id': 'chr_0001_alpha_skill'}
    bridge.handle_event(attach)
    bridge.handle_event(attach)
    bridge.handle_event({'type': 'SC_SELF_SCENE_INFO', 'timestamp_ms': 1793412000123,
                         'char_list': [{'battle_inst_id': 11, 'id': 111, 'templateid': 'chr_0001_alpha'}]})
    assert [item.type for item in events] == ['actor_mapping', 'squad']
    assert [item.sequence for item in events] == [1, 2]
    assert events[0].data['mapping_source'] == 'skill_attach'
    assert events[1].data['members'] == [{'template': 'chr_0001_alpha', 'entity_id': '11'}]


def test_malformed_later_member_does_not_partially_update_squad():
    stream = state()
    item = event('squad', {'members': [{'entity_id': 11, 'template': 'chr_0001_alpha'},
                                     {'entity_id': 22, 'template': 'chr_0002_beta'}]})
    item.data['members'][1]['entity_id'] = 22
    with pytest.raises(ValueError):
        consume_trace_event(stream, item, 1)
    assert not stream.squad_actor_keys and not stream.party_actor_ids and stream.first_context_ms is None
