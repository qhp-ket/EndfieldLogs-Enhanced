"""Equipment JSONL shares the existing merge, completeness and bound-gem rules."""
from copy import deepcopy

import pytest

from parser_core.ingestion.loadout_wire import loadout_data
from parser_core.ingestion.structured import consume_trace_event
from endfield_pcap.trace.legacy_loadout import loadout_legacy_lines
from test_structured_entity import state
from test_structured_identity import event


OWNER = 'chr_0001_alpha'


def slot(**fields):
    return {'char': OWNER, 'slot': 0, 'char_inst_id': 11, 'weapon_inst_id': 91,
            'weapon_template': 'wpn_test', **fields}


def observation(row, *, stats=False, timestamp=1000):
    return event('loadout_stats' if stats else 'loadout_slot', loadout_data(row, stats=stats), timestamp)


def group(reason='SC_SELF_SCENE_INFO', *, timestamp=1000):
    return event('loadout_group', {'reason': reason, 'slot_count': 1, 'member_count': 1,
                                 'roster': [{'entity_id': 11}]}, timestamp)


def test_typed_snapshot_uses_shared_models_without_legacy_row_parsing(monkeypatch):
    import parser_core.ingestion.loadout as loadout
    monkeypatch.setattr(loadout, '_load_weapon_catalog', lambda: {'wpn_test': {'base_atk_values': [100, 120]}})
    monkeypatch.setattr(loadout, '_load_equip_item_catalog', lambda: {})
    monkeypatch.setattr(loadout, '_parse_suit_counts', lambda blob: [])
    for name in ('_parse_loadout_slot_snapshot', '_parse_loadout_stats_snapshot', '_parse_inline_equips', '_token_field', '_extract_fields'):
        monkeypatch.setattr(loadout, name, lambda *_a, **_k: pytest.fail('Typed loadout reparsed a legacy row'))
    stream = state()
    consume_trace_event(stream, group(), 1)
    item = observation(slot(weapon_inst_id='00091', weapon_lv=0, refine=None, char_level=0,
        equips='{[0]=piece|lv=[0]=2}', equip_suit='{[suit_a]=3}', skill_int_ids='4,5',
        equipment_snapshot_complete=True, unresolved_equip_inst_ids=['00123']))
    assert item.data['weapon_id'] == '91' and item.data['unplaced_equipment'][0]['entity_id'] == '123'
    consume_trace_event(stream, item, 2)
    result = stream.loadout_by_char[OWNER]
    assert result['weapon_inst_id'] == '91'
    assert not {'weapon_level', 'weapon_base_atk', 'character_level', 'weapon_refine'} & result.keys()
    assert result['equipment_snapshot_complete'] is True and result['unresolved_equip_inst_ids'] == ['123']
    assert result['equips'][0]['item_id'] == 'piece' and result['skill_int_ids'] == ['4', '5']
    assert stream.active_suits_by_char[OWNER] == {'suit_a'}
    assert not stream.party_actor_ids and not stream.squad_actor_keys
    item.data['unplaced_equipment'][0]['entity_id'] = '999'
    assert result['unresolved_equip_inst_ids'] == ['123']
    assert stream.current_loadout_group['line_no'] == 1 and stream.current_loadout_group['ts_ms'] == 1000


@pytest.mark.parametrize('complete', [None, False, True])
def test_empty_complete_equipment_clears_but_partial_does_not(monkeypatch, complete):
    import parser_core.ingestion.loadout as loadout
    monkeypatch.setattr(loadout, '_load_equip_item_catalog', lambda: {})
    stream = state()
    consume_trace_event(stream, observation(slot(equips='{[0]=piece}', equipment_snapshot_complete=True)), 1)
    old_group = deepcopy(stream.loadout_groups[0])
    fields = {} if complete is None else {'equipment_snapshot_complete': complete}
    consume_trace_event(stream, observation(slot(equips='{}', **fields), timestamp=2000), 2)
    assert bool(stream.loadout_by_char[OWNER]['equips']) is (complete is not True)
    assert stream.loadout_groups[0] == old_group


def test_weapon_replacement_clears_stale_state_and_keeps_history():
    stream = state()
    stream.loadout_by_char[OWNER] = {'character_key': OWNER, 'weapon_inst_id': '91', 'weapon_template': 'wpn_old',
        'weapon_refine': 5, 'weapon_refine_source': 'source_skill', 'gem_template': 'old', 'gem_terms': {'rate': 1},
        'weapon_source_skills': [{'skill_id': 'old', 'bb': {'scale': 0.5}}]}
    consume_trace_event(stream, observation(slot(weapon_template='wpn_old')), 1)
    old_group = deepcopy(stream.loadout_groups[0])
    consume_trace_event(stream, observation(slot(weapon_inst_id=92, weapon_template='wpn_new'), timestamp=2000), 2)
    current = stream.loadout_by_char[OWNER]
    assert current['weapon_inst_id'] == '92' and current['weapon_template'] == 'wpn_new'
    assert current['weapon_refine'] is None and current['weapon_source_skills'] == []
    assert current['gem_template'] is None and current['gem_terms'] == {}
    assert stream.loadout_groups[0] == old_group


@pytest.mark.parametrize('mode', ['exact', 'wrong_reason', 'later_timestamp', 'other_weapon', 'no_gem', 'no_weapon', 'duplicate_term', 'malformed'])
def test_gem_refinement_requires_same_group_and_weapon(monkeypatch, mode):
    import parser_core.ingestion.loadout as loadout
    monkeypatch.setattr(loadout, '_load_weapon_refine_catalog', lambda: {'wpn_test': {
        'mainSkillId': 'main', 'mainSkillNumId': '7', 'mainSkillGemTermNumId': 66,
        'supportedSkillLevels': [1, 2, 3, 4, 5], 'mainSkillBounds': [{'lowerBound': 1, 'upperBound': 4}],
        'refineBonusBounds': {'0': {'lowerBound': 0, 'upperBound': 0}, '1': {'lowerBound': 1, 'upperBound': 1}}}})
    stream = state()
    consume_trace_event(stream, group('packet' if mode == 'wrong_reason' else 'SC_SELF_SCENE_INFO'), 1)
    row = slot(weapon_source_skills='7:level=4:potentialLv=3:bb={rate=0.123456789}',
               attached_gem=42, gem_weapon_id=91, gem_template=71, gem_terms='66:label@cost3')
    if mode == 'other_weapon': row['gem_weapon_id'] = 92
    if mode == 'no_gem': row['attached_gem'] = 0
    if mode == 'no_weapon': row['weapon_inst_id'] = 0
    if mode == 'duplicate_term': row['gem_terms'] += ',66:label@cost1'
    if mode == 'malformed': row['gem_terms'] = '66:broken'
    consume_trace_event(stream, observation(row, stats=True, timestamp=2000 if mode == 'later_timestamp' else 1000), 2)
    result = stream.loadout_by_char[OWNER]
    if mode == 'exact':
        assert result['weapon_refine'] == 0
    else:
        assert 'weapon_refine' not in result


def test_override_applies_to_current_and_group_active_weapon():
    stream = state()
    stream.weapon_override_by_char[OWNER] = {'weapon_template': 'wpn_override', 'weapon_inst_id': '93'}
    consume_trace_event(stream, observation(slot()), 1)
    assert stream.active_weapons_by_char[OWNER] == 'wpn_override'
    assert stream.loadout_by_char[OWNER]['weapon_inst_id'] == '93'
    assert stream.current_loadout_group['rows'][OWNER]['weapon_template'] == 'wpn_override'


def test_raw_stats_precision_and_absence_survive_export_without_changing_analysis():
    stream = state()
    item = observation(slot(weapon_inst_id=9007199254740993, weapon_base_atk=123.456789,
        weapon_base_atk_lv1=0, gem_terms='66:label@cost3'), stats=True, timestamp=-1)
    assert 'weapon_base_atk_max' not in item.data
    assert item.data['weapon_base_atk'] == 123.456789 and item.data['weapon_base_atk_lv1'] == 0
    consume_trace_event(stream, item, 1)
    assert 'weapon_base_atk' not in stream.loadout_by_char[OWNER]
    assert loadout_legacy_lines(item, timezone_offset_minutes=330) == [
        '[05:29:59.999] LOADOUT_STATS slot=0 char=chr_0001_alpha weaponInstId=9007199254740993 '
        'weaponTemplate=wpn_test weaponSync=missing weaponBaseAtk=123.456789 weaponBaseAtkLv1=0 '
        'weaponBaseAtkMax=unknown weaponRefineStatsSource=unknown weaponRefineStats={} weaponSourceSkills={} '
        'gemInstId=0 gemWeaponId=0 gemTemplate=0 gemTerms={66:label@cost3}\n']


def test_bad_later_identity_is_rejected_before_any_equipment_state_changes():
    stream = state()
    item = observation(slot(unresolved_equip_inst_ids=[11, 22]))
    item.data['unplaced_equipment'][1]['entity_id'] = 22
    with pytest.raises(ValueError):
        consume_trace_event(stream, item, 1)
    assert not stream.loadout_by_char and not stream.loadout_groups and stream.first_context_ms is None


def test_business_loadout_keeps_sparse_roster_count_and_independent_row_events():
    from endfield_pcap.trace.bridge import TraceBridge
    events, fallback = [], []
    bridge = TraceBridge(write_enabled=False, line_sink=fallback.append, event_sink=events.append)
    origin = {'type': 'LOADOUT', 'timestamp_ms': 1793412000123, 'reason': 'SC_SELF_SCENE_INFO',
              'rows': [slot(weapon_lv=0, equipment_snapshot_complete=False), None, {'slot': 1}]}
    bridge.handle_event(origin)
    assert not fallback
    assert [row.type for row in events] == ['squad', 'loadout_group', 'loadout_slot', 'loadout_stats', 'loadout_slot', 'loadout_stats']
    assert [row.sequence for row in events] == list(range(1, 7))
    assert events[1].data['slot_count'] == events[1].data['member_count'] == 3
    assert events[1].data['roster'] == [{'entity_id': '11'}]
    assert events[2].data['equipment_snapshot_complete'] is False and 'equips' not in events[2].data
    origin['rows'][0]['weapon_lv'] = 99
    assert events[2].data['weapon_lv'] == 0
