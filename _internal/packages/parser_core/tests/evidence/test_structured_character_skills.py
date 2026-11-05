"""Structured skill lists keep level conflicts, refinement authority and raw export."""
from copy import deepcopy

import pytest

from parser_core.ingestion.structured import consume_trace_event
from endfield_pcap.trace.legacy_identity import identity_legacy_lines
from test_structured_entity import state
from test_structured_identity import event


OWNER = 'chr_0001_alpha'


def skills(rows, owner_id=11, timestamp=1793412000123):
    return event('character_skills', {'template': OWNER, 'entity_id': owner_id,
        'skills': [{'skill': skill, 'level': level} for skill, level in rows]}, timestamp)


def test_typed_levels_share_conflict_rules_without_calling_text_parsers(monkeypatch):
    import parser_core.ingestion.loadout as loadout
    monkeypatch.setattr(loadout, '_canonical_num_table_skill_id', lambda skill, owner: {'42': 'canonical'}.get(skill))
    for name in ('_parse_char_skills_line', '_parse_loadout_stats_snapshot', '_extract_fields', '_token_field'):
        monkeypatch.setattr(loadout, name, lambda *_a, **_k: pytest.fail('Typed observation reparsed a legacy line'))
    stream = state()
    item = skills([('42', 3), ('canonical', 4), ('canonical', 3), ('keep', '2.0'),
                   ('zero', 0), ('negative', -1), ('bad', 2.5), ('unknown', None), ('99999', 7)])
    consume_trace_event(stream, item, 4)
    assert stream.char_skill_levels == {OWNER: {'keep': 2}}
    item.data['skills'][3]['level'] = 99
    assert stream.char_skill_levels[OWNER]['keep'] == 2
    consume_trace_event(stream, skills([('only_invalid', 0)]), 5)
    assert stream.char_skill_levels == {OWNER: {'keep': 2}}
    assert stream.first_context_ms == stream.last_context_ms == 1793412000123
    assert not stream.party_actor_ids and not stream.squad_actor_keys


@pytest.mark.parametrize('mode', ['exact', 'wrong_owner', 'duplicate_owner', 'missing_weapon_instance',
                                 'wrong_character', 'wrong_weapon', 'ambiguous_level', 'conflicting_level', 'known_refine'])
def test_refinement_uses_existing_binding_and_preserves_historical_groups(monkeypatch, mode):
    import parser_core.ingestion.loadout as loadout
    monkeypatch.setattr(loadout, '_load_weapon_refine_catalog', lambda: {
        'wpn_test': {'mainSkillId': 'wpn_main', 'skillLevelToRefine': {'9': 5}}})
    stream = state()
    stream.squad_actor_keys = {'11': OWNER}
    previous = {'character_key': OWNER, 'weapon_inst_id': '91', 'weapon_template': 'wpn_test',
                'weapon_refine': None, 'nested': {'evidence': [1]}}
    if mode == 'wrong_owner': stream.squad_actor_keys = {'12': OWNER}
    if mode == 'duplicate_owner': stream.squad_actor_keys['12'] = OWNER
    if mode == 'missing_weapon_instance': previous['weapon_inst_id'] = None
    if mode == 'wrong_character': previous['character_key'] = 'chr_other'
    if mode == 'wrong_weapon': previous['weapon_template'] = 'wpn_unknown'
    if mode == 'known_refine': previous['weapon_refine'] = 0
    stream.loadout_by_char[OWNER] = deepcopy(previous)
    old_group = {'ts_ms': 100, 'line_no': 1, 'reason': 'packet', 'index': 0, 'rows': {OWNER: deepcopy(previous)}}
    stream.loadout_groups.append(old_group)
    rows = [('wpn_main', 8 if mode == 'ambiguous_level' else 9)]
    if mode == 'conflicting_level': rows += [('wpn_main', 1)]
    consume_trace_event(stream, skills(rows), 7)
    assert old_group['rows'][OWNER] == previous
    if mode == 'exact':
        accepted = stream.loadout_by_char[OWNER]
        assert accepted['weapon_refine'] == 5 and accepted['weapon_refine_source'] == 'source_skill'
        assert accepted['weapon_refine_evidence'] == {'source': 'CHAR_SKILLS', 'owner_id': '11',
            'weapon_inst_id': '91', 'skill_id': 'wpn_main', 'level': 9}
        current = stream.loadout_groups[-1]
        assert current['reason'] == 'CHAR_SKILLS' and current['line_no'] == 7
        assert current['ts_ms'] == 1793412000123 and current['index'] == 1
        accepted['nested']['evidence'].append(2)
        assert current['rows'][OWNER]['nested']['evidence'] == [1]
    else:
        assert stream.loadout_by_char[OWNER] == previous and stream.loadout_groups == [old_group]


def test_raw_skill_export_keeps_order_precision_and_unknown_owner():
    item = skills([('skill_a', 0), ('skill_a', 2.0), ('unresolved', 'bad')], owner_id=9007199254740993, timestamp=-1)
    assert identity_legacy_lines(item, timezone_offset_minutes=330) == [
        '[05:29:59.999] CHAR_SKILLS owner=chr_0001_alpha ownerId=9007199254740993 count=3 skills=[skill_a:0 skill_a:2.0 unresolved:bad]\n']
    assert 'ownerId=unknown count=0 skills=[]' in identity_legacy_lines(skills([], None), timezone_offset_minutes=0)[0]


def test_invalid_later_skill_does_not_partially_update_state():
    stream = state()
    item = skills([('first', 3), ('later', 4)])
    del item.data['skills'][1]['level']
    with pytest.raises(ValueError):
        consume_trace_event(stream, item, 1)
    assert not stream.char_skill_levels and stream.first_context_ms is None


def test_business_skill_emission_preserves_dedup_and_later_cast_mapping():
    from endfield_pcap.trace.bridge import TraceBridge
    events, text = [], []
    bridge = TraceBridge(write_enabled=False, line_sink=text.append, event_sink=events.append)
    origin = {'type': 'SC_SELF_SCENE_INFO_SKILLS', 'timestamp_ms': 1793412000123,
              'owner_inst_id': 11, 'owner_templateid': OWNER, 'skills': [
                  {'skill_inst_id': 71, 'template_str_id': 'chr_0001_alpha_skill', 'level': 3},
                  {'skill_inst_id': 72, 'template_str_id': 'chr_0001_alpha_ult'},
                  {'skill_inst_id': 0, 'template_int_id': 42, 'level': 9}]}
    bridge.handle_event(origin)
    bridge.handle_event(origin)
    assert not text and len(events) == 1
    assert events[0].type == 'character_skills' and events[0].data['entity_id'] == '11'
    assert events[0].data['skills'] == [{'skill': 'chr_0001_alpha_skill', 'level': 3}]
    origin['skills'][0]['level'] = 5
    assert events[0].data['skills'][0]['level'] == 3
    assert bridge.skill_id_by_inst[72] == 'chr_0001_alpha_ult'
