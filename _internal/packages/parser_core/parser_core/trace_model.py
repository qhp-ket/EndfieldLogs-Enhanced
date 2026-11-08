"""Native trace values. Compatibility formatting belongs to the export adapter."""
from __future__ import annotations

from math import isfinite
import re

from parser_core.trace_schema import INSTANCE_FIELDS, OPAQUE_FIELDS


INTEGER_FIELDS = frozenset({'operation_seq', 'operation_generation', 'generation', 'client_tick_ms',
    'tick_ms', 'client_ts', 'server_ts', 'logical_ts', 'message_id', 'hit_seq', 'detail_index',
    'action_id', 'skill_level', 'template_int_id', 'original_template_int_id', 'damage_unit_index',
    'char_level', 'weapon_lv', 'slot', 'potential', 'refine', 'breakthrough'})


def _typed_fields(data):
    # Only declared business containers have numeric fields. Opaque protocol
    # arguments and anomaly raw values must not be interpreted by key spelling.
    errors = data.setdefault('normalization_errors', [])
    for path, fields in (('', data), ('/observation', data.get('observation')),
                         ('/action', data.get('action'))):
        if not isinstance(fields, dict):
            continue
        for key in sorted(fields.keys() & INTEGER_FIELDS):
            value = fields[key]
            if value is None or type(value) is int:
                continue
            if isinstance(value, str) and re.fullmatch(r'[+-]?[0-9]+', value):
                fields[key] = int(value)
            else:
                errors.append({'path': path + '/' + key, 'status': 'invalid_integer', 'raw': value})
                fields[key] = None
    if not errors:
        del data['normalization_errors']
    return data


def normalize_value(value, *, identity=False, _errors=None, _path='', _opaque=False):
    if _errors is None:
        errors = []
        result = normalize_value(value, identity=identity, _errors=errors, _opaque=_opaque)
        if errors and isinstance(result, dict):
            result['normalization_errors'] = errors
        return result
    if identity:
        if value is None:
            return None
        if type(value) is int and value >= 0:
            return str(value)
        if isinstance(value, str) and value.isascii() and value.isdecimal():
            return str(int(value))
        # Invalid observations remain explicit; never turn a float/bool into an ID.
        _errors.append({'path': _path, 'status': 'invalid_identity', 'raw': normalize_value(value, _errors=[], _path=_path, _opaque=True)})
        return None
    if isinstance(value, float) and not isfinite(value):
        return {'number_status': 'nan' if value != value else 'positive_infinity' if value > 0 else 'negative_infinity'}
    if isinstance(value, dict):
        return {key: normalize_value(child, identity=not _opaque and key in INSTANCE_FIELDS,
                                    _errors=_errors, _path=_path + '/' + key,
                                    _opaque=_opaque or key in OPAQUE_FIELDS)
                for key, child in value.items()}
    if isinstance(value, list):
        return [normalize_value(child, _errors=_errors, _path=_path + '/' + str(index), _opaque=_opaque) for index, child in enumerate(value)]
    return value


# These fields are explicitly copied from the event envelope by the producers.
# Entity owner/target, action owner and observation time are independent facts.
CONTEXT_FIELDS = {'session_id': 'session_id', 'operation_seq': 'operation_seq',
                  'operation_owner_id': 'owner_id', 'operation_generation': 'generation',
                  'client_tick_ms': 'client_tick_ms', 'generation': 'generation'}
OBSERVATION_CONTEXT = {
    'buff_creation': ('session_id', 'operation_seq', 'operation_owner_id', 'operation_generation'),
    'buff_origin': ('operation_seq',),
    'buff_enable': ('operation_seq', 'client_tick_ms', 'generation'),
    'buff_keyword': ('session_id', 'operation_seq', 'client_tick_ms', 'generation'),
    'blackboard_dynamic': ('session_id', 'operation_seq', 'operation_owner_id', 'generation', 'client_tick_ms'),
    'buff_attribute_refresh': ('session_id', 'operation_seq', 'operation_owner_id', 'generation', 'client_tick_ms'),
    'blackboard_skill_setting': ('session_id', 'operation_seq', 'operation_owner_id', 'generation', 'client_tick_ms'),
    'ink_release': ('session_id', 'operation_seq', 'client_tick_ms'),
}


def compact_data(data, source, tick=None, event_type=None):
    result = _typed_fields(normalize_value(data))
    context = {**source}
    if tick is not None:
        context['client_tick_ms'] = tick
    for fields in (result, result.get('observation', {})):
        mapping = ({'operation_seq': 'operation_seq', 'client_tick_ms': 'client_tick_ms', 'packet_session_id': 'session_id'}
                   if fields is result else {key: CONTEXT_FIELDS[key] for key in OBSERVATION_CONTEXT.get(event_type, ())})
        for key, common in mapping.items():
            if key in fields and common in context and type(fields[key]) is type(context[common]) and fields[key] == context[common]:
                del fields[key]
    if isinstance(result.get('evidence'), dict):
        packet = result['evidence'].get('packet_context')
        expected = {'packetSeq': source.get('operation_seq'), 'packetSessionId': source.get('session_id')}
        if packet == expected:
            del result['evidence']['packet_context']
    return result


def event_data(event):
    """V1 adapts once at the boundary; v2 never restores Python scalar layouts."""
    data = event.data
    if 'legacy_layout' in data:
        from parser_core.trace_v1 import native_data
        return native_data(data)
    if 'observation' not in data and event.type not in {
            'skill_cast', 'atb', 'poise', 'entity_value', 'ability_spawn',
            'blackboard_calculation', 'blackboard_modify', 'blackboard_preset',
            'clock_tick', 'battle_timer', 'battle_phase', 'buff_unresolved'}:
        return data
    context = {**event.source}
    if event.client_tick_ms is not None:
        context['client_tick_ms'] = event.client_tick_ms
    mapping = {'operation_seq': 'operation_seq', 'client_tick_ms': 'client_tick_ms', 'packet_session_id': 'session_id'}
    missing = {key: context[common] for key, common in mapping.items() if key not in data and common in context}
    result = {**data, **missing} if missing else data
    if 'observation' in data:
        target = data['observation']
        missing = {key: context[CONTEXT_FIELDS[key]] for key in OBSERVATION_CONTEXT.get(event.type, ())
                   if key not in target and CONTEXT_FIELDS[key] in context}
        if missing:
            result = {**result, 'observation': {**target, **missing}}
    return result
