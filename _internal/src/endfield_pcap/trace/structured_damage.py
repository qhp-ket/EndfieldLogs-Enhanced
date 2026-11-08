"""Produce one normalized damage event from one decoded detail, without trace text."""
from __future__ import annotations

from copy import deepcopy

from endfield_pcap.trace.formatting import _intish
from parser_core.trace_jsonl import TraceEvent
from parser_core.trace_model import compact_data


def damage_event(sequence, captured_at_ms, event, detail, detail_index, presence, *,
                 hit_seq, attacker, attacker_id, target, target_id, skill, original_template_int_id,
                 dynamic_rows, calculation_rows):
    action = {'skill': skill}
    for output, value in (
        ('skill_level', event.get('level')), ('template_int_id', event.get('template_int_id')),
        ('template_type', event.get('template_type')), ('action_id', (event.get('action') or {}).get('action_id')),
        ('original_template_int_id', original_template_int_id), ('damage_unit_index', detail.get('damage_unit_index')),
    ):
        if value is not None:
            action[output] = value if output == 'template_type' else _intish(value)
    for output, value in (('event_inst_id', event.get('inst_id')), ('event_owner_id', event.get('owner_id')),
                          ('part_inst_id', detail.get('part_inst_id'))):
        if value is not None:
            action[output] = value
    source = {'detail_index': detail_index}
    if isinstance(event.get('session_id'), str) and event['session_id']:
        source['session_id'] = event['session_id']
    if type(event.get('seq_id')) is int:
        source['operation_seq'] = event['seq_id']
    if type(event.get('generation')) is int and 0 <= event['generation'] < 2**32:
        source['generation'] = event['generation']
    owner = event.get('operation_owner_id')
    if type(owner) in (int, str) and str(owner).isascii() and str(owner).isdigit() and 0 <= int(owner) < 2**64:
        source['owner_id'] = str(int(owner))
    amounts = {output: detail[key] for key, output in (('value', 'value'), ('cur_hp', 'current_hp'), ('is_crit', 'is_crit')) if key in detail}
    evidence = {key: value for key, value in detail.items()
                if key not in {'value', 'cur_hp', 'is_crit', 'target_id', 'damage_unit_index', 'part_inst_id'}}
    evidence['presence'] = presence
    actors = {'attacker': attacker, 'target': target}
    if attacker_id is not None:
        actors['attacker_id'] = attacker_id
    if target_id is not None:
        actors['target_id'] = target_id
    data = {'hit_seq': hit_seq, 'actors': actors, 'action': action, 'amounts': amounts,
            'blackboards': {'dynamic': [{'action_id': a, 'value': v} for a, v in dynamic_rows],
                           'calculation': [{'action_id': a, 'key': k, 'value': v} for a, k, v in calculation_rows]},
            'evidence': evidence}
    projected = compact_data(data, source, event.get('client_tick_tms'))
    return TraceEvent(sequence, captured_at_ms, 'damage', projected, deepcopy(source),
                      event.get('client_tick_tms') if type(event.get('client_tick_tms')) is int else None)
