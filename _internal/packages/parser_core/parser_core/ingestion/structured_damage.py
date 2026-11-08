"""Damage JSONL payloads enter the existing hit and packet-evidence state directly."""
from __future__ import annotations

from math import isfinite

from parser_core.ingestion.damage_observation import DamageObservation
from parser_core.ingestion.hits import _apply_damage_observation
from parser_core.ingestion.packet_evidence import (
    observe_attribute_report, observe_attributes, observe_modifier_handles, observe_modifiers,
)
from parser_core.ingestion.state import IngestionState
from parser_core.trace_jsonl import TraceEvent
from parser_core.trace_model import event_data


def _object(value) -> dict:
    if not isinstance(value, dict):
        raise ValueError('Expected damage object')
    return value


def _number(value, default=None):
    if value is None:
        return default
    if type(value) not in (int, float) or not isfinite(value):
        raise ValueError('Expected finite damage number')
    return float(value)


def _integer(value):
    if value is not None and type(value) is not int:
        raise ValueError('Expected damage integer')
    return value


def _identity(value):
    if value is None:
        return None
    if not isinstance(value, str) or not value or any(c < '0' or c > '9' for c in value):
        raise ValueError('Damage instance IDs must be decimal strings')
    return value if int(value) > 0 else None


def _rows(value):
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise ValueError('Expected damage blackboard rows')
    return value


def damage_observation(event: TraceEvent) -> DamageObservation:
    if event.type != 'damage':
        raise ValueError('Expected damage event')
    data = _object(event.data)
    actors, action = _object(data.get('actors')), _object(data.get('action'))
    amounts, blackboards = _object(data.get('amounts')), _object(data.get('blackboards'))
    _object(data.get('evidence'))
    sequence = _integer(data.get('hit_seq'))
    if sequence is None or sequence <= 0:
        raise ValueError('Damage hit_seq must be positive')
    if amounts.get('value') is None:
        raise ValueError('Missing damage amount')
    raw = abs(_number(amounts['value']))
    if int(raw + 0.5) <= 0:
        raise ValueError('Damage detail must contain a positive hit')
    hp = _number(amounts.get('current_hp'), 0) or 0.0
    critical = amounts.get('is_crit', False)
    if type(critical) is not bool:
        raise ValueError('Expected damage critical flag')
    for key in ('attacker', 'target'):
        if not isinstance(actors.get(key), str):
            raise ValueError('Expected damage actor label')
    if not isinstance(action.get('skill'), str):
        raise ValueError('Expected damage skill label')
    dynamic_values, calculation_values = {}, {}
    dynamic_tokens, calculation_tokens = [], []
    for row in _rows(blackboards.get('dynamic')):
        identity = _integer(row.get('action_id'))
        if identity is None:
            raise ValueError('Missing blackboard action')
        token = format(_number(row.get('value')), '.6g')
        dynamic_tokens.append(f'{identity}:{token}')
        dynamic_values[identity] = float(token)
    for row in _rows(blackboards.get('calculation')):
        identity, key = _integer(row.get('action_id')), row.get('key')
        if identity is None or not isinstance(key, str) or not key:
            raise ValueError('Missing calculation blackboard identity')
        token = format(_number(row.get('value')), '.6g')
        calculation_tokens.append(f'{identity}:{key}={token}')
        calculation_values.setdefault(identity, {})[key] = float(token)
    source = _object(event.source)
    owner = _identity(source.get('owner_id'))
    if owner is not None and (owner.startswith('0') or int(owner) >= 2**64):
        owner = None
    def positive(key):
        value = _integer(action.get(key))
        return value if value is not None and value > 0 else None
    def index(value):
        value = _integer(value)
        return value if value is not None and value >= 0 else None
    return DamageObservation(
        sequence=sequence, source=actors['attacker'], attacker=actors['attacker'], target=actors['target'],
        source_actor=_identity(actors.get('attacker_id')), target_actor=_identity(actors.get('target_id')),
        skill=action['skill'], template_type=action.get('template_type') or 'unknown',
        hit=int(raw + 0.5), hit_observed=True, raw=float(format(raw, '.2f')), final=raw,
        enemy_hp=int(format(hp, '.0f')), enemy_hp_observed=True,
        critical=int(critical), critical_observed=True, skill_level=positive('skill_level'),
        template_integer=positive('template_int_id'), original_template=positive('original_template_int_id'),
        event_instance=_identity(action.get('event_inst_id')), event_owner=_identity(action.get('event_owner_id')),
        action=index(action.get('action_id')), unit_index=index(action.get('damage_unit_index')),
        part_instance=int(part) if (part := _identity(action.get('part_inst_id'))) else None,
        client_tick=index(event.client_tick_ms), packet_sequence=index(source.get('operation_seq')),
        packet_owner=owner, packet_generation=index(source.get('generation')),
        packet_session=source.get('session_id') or None,
        dynamic_signature=','.join(dynamic_tokens) or 'unknown', dynamic_values=dynamic_values,
        calculation_signature=','.join(calculation_tokens) or 'unknown', calculation_values=calculation_values,
    )


def _attribute_rows(report: dict, side: str) -> list[str]:
    result = []
    def attribute_text(value):
        try:
            return str(float(value))
        except (TypeError, ValueError):
            return str(value)
    for row in report.get(side + '_attr_modify_info') or []:
        if not isinstance(row, dict):
            continue
        try:
            kind = int(row.get('attr_type'))
        except (TypeError, ValueError, OverflowError):
            continue
        if kind is not None:
            attrs = row.get('attrs') if isinstance(row.get('attrs'), list) else []
            values = ','.join(attribute_text(value) for value in attrs)
            result.append(f'{kind}:{values}')
    return result


def consume_structured_damage(ingestion: IngestionState, event: TraceEvent, evidence_index: int) -> None:
    observation = damage_observation(event)
    evidence = event_data(event)['evidence']
    # Validate/prepare before changing stream state. Presence and handle conflicts are
    # still handled by the shared evidence rules, not silently repaired here.
    mods = _object(evidence.get('modifier_args') or {})
    report = _object(evidence.get('battle_report_info') or {})
    presence = _object(evidence.get('presence') or {})
    modifier_lists = {side: [str(row['buff_inst_id']) for row in mods.get(side + '_modifiers') or []
                             if isinstance(row, dict) and row.get('buff_inst_id')]
                      for side in ('attacker', 'defender')}
    attrs = {side: _attribute_rows(report, side) for side in ('attacker', 'defender')}
    context = _object(evidence.get('packet_context',
        {'packetSeq': event.source.get('operation_seq'), 'packetSessionId': event.source.get('session_id')}))
    stamp = event.captured_at_ms
    ingestion.timestamp_clock_origin = ingestion.timestamp_clock_origin if ingestion.timestamp_clock_origin is not None else stamp
    if ingestion.first_context_ms is None:
        ingestion.first_context_ms = stamp
    ingestion.last_context_ms = stamp
    # This decoder owns its freshly created blackboard dictionaries. Public
    # caller-owned DamageObservation input still uses the copying boundary.
    _apply_damage_observation(ingestion, observation, evidence_index, stamp, own_values=False)
    seq = observation.sequence
    if any(modifier_lists.values()):
        observe_modifiers(ingestion, seq, modifier_lists['attacker'], modifier_lists['defender'], stamp)
        observe_modifier_handles(ingestion, seq, {**context,
            'attacker': mods.get('attacker_modifiers') or [], 'defender': mods.get('defender_modifiers') or []})
    report_present = presence.get('has_battle_report_info')
    if type(report_present) is not bool:
        report_present = True if isinstance(evidence.get('battle_report_info'), dict) else None
    if report_present is not None:
        observe_attribute_report(ingestion, seq, {**context, 'reportPresent': report_present})
    if any(attrs.values()):
        observe_attributes(ingestion, seq, attrs['attacker'], attrs['defender'])
