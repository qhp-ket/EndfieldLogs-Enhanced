"""On-demand damage log export; never used by structured realtime ingestion."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from parser_core.trace_jsonl import TraceEvent
from parser_core.trace_values import restore_value
from endfield_pcap.trace.damage_evidence import calculation_tokens, write_damage_evidence
from endfield_pcap.trace.formatting import _floatish, _intish, _trace_string


class _EvidenceSink:
    __slots__ = ('hit_seq', 'bodies')

    def __init__(self, hit_seq, bodies):
        self.hit_seq, self.bodies = hit_seq, bodies

    def _line(self, _timestamp, body):
        self.bodies.append(body)


def damage_legacy_lines(event: TraceEvent, *, timezone_offset_minutes: int) -> list[str]:
    if event.type != 'damage':
        raise ValueError('Expected damage event')
    if 'legacy_layout' not in event.data:
        raise ValueError('Damage event lacks legacy export layout')
    data = restore_value(event.data, event.data['legacy_layout'])
    actors, action, amounts = data['actors'], data['action'], data['amounts']
    evidence = data['evidence']
    context = evidence['packet_context']
    detail = {key: value for key, value in evidence.items() if key not in ('presence', 'packet_context')}
    detail.update({'damage_unit_index': action.get('damage_unit_index'), 'part_inst_id': action.get('part_inst_id')})
    packet = {'session_id': context.get('packetSessionId'), 'seq_id': context.get('packetSeq')}
    raw = abs(_floatish(amounts.get('value')) or 0.0)
    hit = int(raw + 0.5)
    hp = _floatish(amounts.get('current_hp')) or 0.0
    critical = bool(amounts.get('is_crit'))
    def positive(value):
        number = _intish(value)
        return number if number is not None and number > 0 else 'unknown'
    def integer(value):
        number = _intish(value)
        return number if number is not None else 'unknown'
    def nonzero(value):
        return _intish(value) or 'unknown'
    boards = data['blackboards']
    dynamic = ','.join(f"{row['action_id']}:{row['value']:.6g}" for row in boards['dynamic']) or 'unknown'
    calculation = ','.join(f"{row['action_id']}:{row['key']}={row['value']:.6g}" for row in boards['calculation']) or 'unknown'
    source = event.source
    packet_tokens = []
    if source.get('session_id'):
        packet_tokens.append('packetSessionId=' + _trace_string(source['session_id']))
    if 'owner_id' in source:
        packet_tokens.append('packetOwnerId=' + source['owner_id'])
    if 'generation' in source:
        packet_tokens.append('packetGeneration=' + str(source['generation']))
    calc_tokens = calculation_tokens(detail)
    bodies = [
        f"HP_V2 #{data['hit_seq']} hit={hit} cum={hit} raw={raw:.2f} packetFinalValue={raw:.17g} "
        f"pHP=0 eHP={hp:.0f} skill=\"{action['skill']}\" hits=1 "
        f"skillLv={positive(action.get('skill_level'))} templateIntId={positive(action.get('template_int_id'))} "
        f"templateType={action.get('template_type') or 'unknown'} actionId={integer(action.get('action_id'))} "
        f"origTemplateIntId={positive(action.get('original_template_int_id'))} "
        f"damageUnitIndex={integer(action.get('damage_unit_index'))} partInstId={positive(action.get('part_inst_id'))} "
        f"dynBB={dynamic} calcBB={calculation} src={actors['attacker']} tgt={actors['target']} atk={actors['attacker']} "
        f"atkId={nonzero(actors.get('attacker_id'))} tgtId={nonzero(actors.get('target_id'))} seg=0 "
        f"shared={3 if critical else 2} critFlag={int(critical)} critDmg=-1.0000 "
        f"eventInstId={positive(action.get('event_inst_id'))} eventOwnerId={nonzero(action.get('event_owner_id'))} "
        f"packetSeq={source.get('operation_seq', 'unknown')} clientTick={event.client_tick_ms if event.client_tick_ms is not None else 'unknown'} "
        + (' '.join(packet_tokens) + ' ' if packet_tokens else '')
        + (' ' + ' '.join(calc_tokens) if calc_tokens else '')]

    write_damage_evidence(_EvidenceSink(data['hit_seq'], bodies), event.captured_at_ms, packet, detail, evidence.get('presence') or {})
    local = datetime.fromtimestamp(event.captured_at_ms / 1000, timezone(timedelta(minutes=timezone_offset_minutes)))
    stamp = local.strftime('%H:%M:%S.%f')[:-3]
    return [f'[{stamp}] {body}\n' for body in bodies]
