"""Decoded entity events share the legacy snapshot and critical-attribute rules."""
from __future__ import annotations

from math import isfinite

from parser_core.ingestion.entities import apply_entity_snapshot, entity_stats_snapshot
from parser_core.ingestion.fields import _coerce_optional_int
from parser_core.ingestion.identity import _extract_character_key
from parser_core.ingestion.structured_damage import _identity, _object
from parser_core.trace_values import restore_value


ENTITY_TYPES = ('entity_stats', 'entity_attributes', 'entity_value', 'entity_die', 'ability_spawn')


def entity_value_data(event):
    return {target: event[key] for key, target in (
        ('entity_inst_id', 'entity_id'), ('seq_id', 'operation_seq'), ('scene_num_id', 'scene_num_id'),
        ('hp', 'hp'), ('ultimatesp', 'ultimate_sp'), ('delta_value', 'delta'),
        ('template_type', 'source_type'), ('template_int_id', 'source_int'),
        ('orig_template_type', 'original_source_type'), ('orig_template_int_id', 'original_source_int')) if key in event}


def ability_spawn_data(event, detail, action_id, owner, source, skill):
    data = {target: event[key] for key, target in (('seq_id', 'operation_seq'), ('client_tick_tms', 'client_tick_ms'),
        ('inst_id', 'event_inst_id'), ('owner_id', 'owner_id'), ('template_int_id', 'template_int_id')) if key in event}
    data.update(action_id=action_id, owner=None if owner == '?' else owner, source=None if source == '?' else source,
                skill=None if skill == 'unknown_skill' else skill)
    data['detail'] = {target: detail[key] for key, target in (('client_ability_entity_id', 'entity_id'),
        ('source_id', 'source_actor_id'), ('init_pos', 'position'), ('rotation', 'rotation')) if key in detail}
    return data


def _integer(value):
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError, OverflowError):
        return None


def _number(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError, OverflowError):
        return None


def entity_observation(event):
    if event.type not in ENTITY_TYPES:
        raise ValueError('Expected entity event')
    data = _object(event.data)
    if event.type in ('entity_value', 'entity_die', 'ability_spawn'):
        for fields in (data, _object(data.get('detail', {}))):
            for key in ('entity_id', 'event_inst_id', 'owner_id', 'source_actor_id'):
                if key in fields:
                    _identity(fields[key])
        # These have always been diagnostics; HP observations do not establish
        # entity attributes or infer a character/target binding.
        return None, None, False
    if 'entity_id' not in data:
        raise ValueError('Missing entity identity')
    _identity(data['entity_id'])
    data = restore_value(data, _object(data.get('legacy_layout', {})))
    template, kind = data.get('template'), data.get('kind')
    if not isinstance(template, str) or (kind is not None and not isinstance(kind, str)):
        raise ValueError('Expected entity labels')
    identity = str(data['entity_id']) if data['entity_id'] is not None else ''
    partial = event.type == 'entity_attributes'
    party_id = identity if not partial and kind == 'character' and _extract_character_key(template) and identity else None
    if not identity or identity[0] == '0' or any(c < '0' or c > '9' for c in identity):
        return None, party_id, partial
    values = []
    def projected(value):
        return float(format(value, '.6g')) if isfinite(value) else None
    rows = data.get('attributes')
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or (attribute := _integer(row.get('attr_type'))) is None:
            continue
        number = _number(row.get('value'))
        number = number if number is not None else 0.0
        basic = _number(row.get('basic_value'))
        basic = basic if basic is not None else number
        values.append((attribute, projected(number), projected(basic), None))
    level = _coerce_optional_int(str(data['level'])) if data.get('level') is not None else None
    snapshot = entity_stats_snapshot(template, kind, level, values,
                                     timestamp_ms=event.captured_at_ms, attribute_list_present=True)
    return (identity, snapshot), party_id, partial


def consume_structured_entity(ingestion, event, evidence_index):
    observation, party_id, partial = entity_observation(event)
    if party_id:
        ingestion.party_actor_ids.add(party_id)
    if observation:
        identity, snapshot = observation
        apply_entity_snapshot(ingestion, identity, snapshot, evidence_index, event.captured_at_ms, partial=partial)
    ingestion.timestamp_clock_origin = ingestion.timestamp_clock_origin if ingestion.timestamp_clock_origin is not None else event.captured_at_ms
    if ingestion.first_context_ms is None:
        ingestion.first_context_ms = event.captured_at_ms
    ingestion.last_context_ms = event.captured_at_ms
