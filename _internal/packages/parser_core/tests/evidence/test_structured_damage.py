"""Structured damage and legacy text share the existing state and evidence rules."""
from dataclasses import replace
from datetime import date
from copy import deepcopy
from types import SimpleNamespace
import pytest

from parser_core.ingestion.damage_observation import DamageObservation
from parser_core.ingestion.hits import consume_damage_observation, consume_hit_and_buff_lifecycle
from parser_core.ingestion.state import IngestionState
from parser_core.ingestion.structured_damage import consume_structured_damage, damage_observation


def state():
    return IngestionState(reference_date=date(2026, 10, 31), first_hit_hint_ms=None,
                          last_hit_hint_ms=None, context_enemy_hint=None, trace_identity_inference_seen=False,
                          loadout_override_by_char=None, critical_attributes_override_by_actor=None)


def observation():
    return DamageObservation(sequence=1, source="chr_0001_alpha", attacker="chr_0001_alpha", target="eny_0001_target",
                             source_actor="11", target_actor="22", skill="skill_test", hit=100, hit_observed=True,
                             unresolved_hit_text="100", enemy_hp=1000, enemy_hp_observed=True,
                             critical=1, critical_observed=True, packet_sequence=7, packet_session="session",
                             action=14, unit_index=0, dynamic_signature="14:0.5", dynamic_values={14: 0.5},
                             calculation_signature="14:scale=2", calculation_values={14: {"scale": 2.0}})


def test_typed_damage_matches_legacy_without_text_parser(monkeypatch):
    legacy = state()
    line = (" HP_V2 #1 src=chr_0001_alpha atk=chr_0001_alpha tgt=eny_0001_target atkId=11 tgtId=22 "
            "skill=skill_test hit=100 eHP=1000 critFlag=1 packetSeq=7 packetSessionId=session "
            "actionId=14 damageUnitIndex=0 dynBB=14:0.5 calcBB=14:scale=2")
    consume_hit_and_buff_lifecycle(legacy, line, 2, 20)

    def no_text(*args, **kwargs):
        raise AssertionError("Structured ingestion must not parse a trace line")

    monkeypatch.setattr("parser_core.ingestion.hits._extract_fields", no_text)
    monkeypatch.setattr(DamageObservation, "from_legacy", no_text)
    typed = state()
    consume_damage_observation(typed, observation(), 2, 20)
    assert typed.hits == legacy.hits
    assert typed.participant_totals == legacy.participant_totals
    assert typed.skill_totals == legacy.skill_totals
    assert typed.enemy_counter == legacy.enemy_counter
    assert typed.last_enemy_hp_by_target == legacy.last_enemy_hp_by_target


def test_typed_damage_owns_evidence_and_preserves_overkill():
    stream = state()
    event = observation()
    consume_damage_observation(stream, event, 2, 20)
    event.dynamic_values[14] = 99
    event.calculation_values[14]["scale"] = 99
    assert stream.hits[0]["dynamic_bb_values"] == {14: 0.5}
    assert stream.hits[0]["calc_bb_values"] == {14: {"scale": 2.0}}
    consume_damage_observation(stream, replace(event, sequence=2, hit=2000, enemy_hp=0), 3, 30)
    assert stream.hits[-1]["hit_value"] == 1000
    assert stream.hits[-1]["overkill_damage"] == 1000
    consume_damage_observation(stream, replace(event, sequence=3, hit=0, hit_observed=False, enemy_hp_observed=False), 4, 40)
    assert stream.hits[-1]["packet_hit_value"] is None
    assert not stream.hits[-1]["enemy_hp_after_observed"]
    assert stream.hits[-1]["damage_value_source"] == "missing_packet_hit"


def test_typed_rejected_and_accepted_hits_keep_buff_boundary():
    stream = state()
    pending = {"uid": "8"}
    stream.pending_buff_record = pending
    event = observation()
    assert consume_damage_observation(stream, replace(event, source="eny_0001_target", attacker="eny_0001_target",
                                                    target="chr_0001_alpha"), 2, 20)
    assert stream.pending_buff_record is pending
    assert consume_damage_observation(stream, replace(event, source="chr_0002_beta"), 3, 30)
    assert stream.pending_buff_record is pending
    assert stream.unresolved_hits[-1]["reason"] == "conflicting_damage_actor"
    assert not stream.hits
    assert not consume_damage_observation(stream, event, 4, 40)
    assert stream.pending_buff_record is None


def produced_details(monkeypatch, details=None):
    from endfield_pcap.trace.bridge import TraceBridge
    events = []
    bridge = TraceBridge(write_enabled=False, damage_sink=events.append)
    bridge.id_to_name.update({11: 'chr_0001_alpha', 22: 'eny_0001_target'})
    bridge.recent_dynamic_bb_by_inst[700] = [(14, 1.23456789)]
    bridge.recent_calc_bb_by_inst[700] = [(14, 'scale', 2.123456789)]
    def no_text(*args, **kwargs):
        raise AssertionError('Structured damage must not render or parse a legacy trace line')
    monkeypatch.setattr(bridge, '_line', no_text)
    monkeypatch.setattr(DamageObservation, 'from_legacy', no_text)
    monkeypatch.setattr('parser_core.ingestion.hits._extract_fields', no_text)
    monkeypatch.setattr('parser_core.ingestion.packet_evidence.json', SimpleNamespace(loads=no_text))
    detail = {'value': -123.45678901234567, 'cur_hp': 900.5, 'target_id': 22, 'is_crit': False,
              'damage_unit_index': 0, 'part_inst_id': 9007199254740993,
              'modifier_args': {'attacker_modifiers': [{'index': 0, 'buff_inst_id': '99',
                  'debug_args': {'scale': [0.5]}}], 'defender_modifiers': []},
              'battle_report_info': {'attacker_attr_modify_info': [{'attr_type': 9, 'attrs': [0.25]}]},
              'calculate_damage_check_args': {'client_final_value': 123.45678901234567}}
    payload = {'attacker_id': 11, 'details': details if details is not None else [detail]}
    original = {'type': 'BattleOpTriggerAction', 'timestamp_ms': 1793412000123,
                'owner_id': 11, 'inst_id': 700, 'template_str_id': 'chr_0001_alpha_skill',
                'template_type': 'Skill', 'session_id': '合成', 'seq_id': 7, 'generation': 0,
                'operation_owner_id': '18446744073709551615', 'client_tick_tms': 0,
                'damage_detail_presence': [{'has_battle_report_info': False, 'has_calculation_check_args': True}],
                'action': {'action_id': 14, 'action_type': 'BattleActionDamage', 'damage_action': payload}}
    bridge.handle_event(original)
    return events, original, bridge


def test_business_damage_enters_state_without_text_or_json_roundtrip(monkeypatch):
    events, original, bridge = produced_details(monkeypatch)
    assert len(events) == 1
    event = events[0]
    assert event.data['amounts']['value'] == -123.45678901234567
    assert event.data['action']['part_inst_id'] == '9007199254740993'
    assert event.source == {'session_id': '合成', 'operation_seq': 7, 'generation': 0,
                                'owner_id': '18446744073709551615', 'detail_index': 0}
    stream = state()
    consume_structured_damage(stream, event, 4)
    hit = stream.hits[0]
    assert hit['hit_value'] == 123 and hit['packet_raw_value'] == 123.46
    assert hit['dynamic_bb_values'] == {14: 1.23457}
    assert hit['calc_bb_values'] == {14: {'scale': 2.12346}}
    assert hit['packet_attribute_report_present'] is False
    assert hit['packet_attr_details']['attacker'] == ['9:0.25']
    assert hit['packet_modifier_handles']['attacker'][0]['debug_args'] == {'scale': [0.5]}
    original['action']['damage_action']['details'][0]['modifier_args']['attacker_modifiers'][0]['debug_args']['scale'][0] = 8
    assert event.data['evidence']['modifier_args']['attacker_modifiers'][0]['debug_args']['scale'] == [0.5]
    event.data['evidence']['modifier_args']['attacker_modifiers'][0]['debug_args']['scale'][0] = 9
    assert hit['packet_modifier_handles']['attacker'][0]['debug_args']['scale'] == [0.5]
    assert stream.first_context_ms == stream.last_context_ms == 1793412000123
    assert not bridge.recent_dynamic_bb_by_inst and not bridge.recent_calc_bb_by_inst


def test_independent_damage_export_preserves_timestamp_rounding_placeholders_and_newline():
    from parser_core.trace_jsonl import TraceEvent, parse, serialize
    from parser_core.trace_values import project_value
    from endfield_pcap.trace.legacy_damage import damage_legacy_lines
    data, layout = project_value({'hit_seq': 4, 'actors': {'attacker': 'chr_alpha', 'target': '?'},
        'action': {'skill': '技能'}, 'amounts': {'value': -12.5, 'current_hp': -0.0},
        'blackboards': {'dynamic': [], 'calculation': []},
        'evidence': {'packet_context': {'packetSeq': None, 'packetSessionId': None}, 'presence': {}}})
    data['legacy_layout'] = layout
    saved = parse(serialize(TraceEvent(1, -1, 'damage', data, {})), header=False)
    assert damage_legacy_lines(saved, timezone_offset_minutes=330) == [
        '[05:29:59.999] HP_V2 #4 hit=13 cum=13 raw=12.50 packetFinalValue=12.5 pHP=0 eHP=0 skill="技能" hits=1 '
        'skillLv=unknown templateIntId=unknown templateType=unknown actionId=unknown origTemplateIntId=unknown '
        'damageUnitIndex=unknown partInstId=unknown dynBB=unknown calcBB=unknown src=chr_alpha tgt=? atk=chr_alpha '
        'atkId=unknown tgtId=unknown seg=0 shared=2 critFlag=0 critDmg=-1.0000 eventInstId=unknown eventOwnerId=unknown '
        'packetSeq=unknown clientTick=unknown \n']


def test_producer_normalizes_nested_ids_and_exports_modifier_facts(monkeypatch):
    import json
    from parser_core.trace_jsonl import parse, serialize
    from endfield_pcap.trace.legacy_damage import damage_legacy_lines
    events, _, _ = produced_details(monkeypatch, [{'value': -50, 'target_id': 22, 'part_inst_id': '00077',
        'modifier_args': {'attacker_modifiers': [{'index': 3, 'buff_inst_id': 18446744073709551615,
                                               'debug_args': {'z': 1.5, 'a': -0.0}}]}}])
    event = parse(serialize(events[0]), header=False)
    assert event.data['action']['part_inst_id'] == '77'
    assert event.data['evidence']['modifier_args']['attacker_modifiers'][0]['buff_inst_id'] == '18446744073709551615'
    lines = damage_legacy_lines(event, timezone_offset_minutes=480)
    detail = next(json.loads(line[line.index('{'):]) for line in lines if 'PKT_MOD_DETAIL' in line)
    assert detail['attacker'] == [{'index': 3, 'buff_inst_id': '18446744073709551615', 'debug_args': {'z': 1.5, 'a': -0.0}}]
    assert detail['partInstId'] == '77'
    assert 'legacy_layout' not in event.data and 'packet_context' not in event.data['evidence']
    stream = state()
    consume_structured_damage(stream, event, 1)
    assert stream.hits[0]['packet_modifier_handles']['attacker'][0]['buff_inst_id'] == '18446744073709551615'


def test_damage_detail_indices_survive_skipped_rows_and_late_capture(monkeypatch):
    events, original, bridge = produced_details(monkeypatch, [
        {'value': 0}, {'value': -100, 'target_id': 22}, {'value': -25, 'target_id': 22}])
    assert [item.source['detail_index'] for item in events] == [1, 2]
    assert [item.sequence for item in events] == [1, 2]
    original['timestamp_ms'] -= 1
    bridge.handle_event(original)
    assert [item.sequence for item in events] == [1, 2, 3, 4]
    assert events[2].captured_at_ms < events[1].captured_at_ms


@pytest.mark.parametrize('mutation', ['numeric_id', 'missing_amount', 'malformed_blackboards'])
def test_malformed_damage_is_rejected_before_state_changes(monkeypatch, mutation):
    events, _, _ = produced_details(monkeypatch)
    event = deepcopy(events[0])
    if mutation == 'numeric_id':
        event.data['actors']['attacker_id'] = 9007199254740993
    elif mutation == 'missing_amount':
        event.data['amounts'].pop('value')
    else:
        event.data['blackboards']['dynamic'] = [7]
    stream = state()
    with pytest.raises(ValueError):
        consume_structured_damage(stream, event, 1)
    assert not stream.hits and stream.first_context_ms is None


def test_structured_damage_cannot_create_incomplete_legacy_archive(tmp_path):
    from endfield_pcap.trace.bridge import TraceBridge
    with pytest.raises(ValueError, match='不完整'):
        TraceBridge(tmp_path / 'not-created.log', damage_sink=lambda item: None)
    assert not (tmp_path / 'not-created.log').exists()
