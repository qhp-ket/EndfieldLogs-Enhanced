"""Historical observations retain numeric tokens; they grant no new identity or effect authority."""
import re

from parser_core.ingestion.fields import (
    _DPD_RAW_RE, _BASELINE_RE, _BASELINE_KV_RE, _KV_RE, _extract_fields,
    _coerce_optional_int, _coerce_optional_float, _coerce_float, _parse_zone_values,
)
from parser_core.ingestion.packet_evidence import observe_raw_damage, observe_baseline
from parser_core.ingestion.hits import observe_legacy_modifier

TYPES = ('damage_raw', 'damage_baseline', 'legacy_attribute_modifier', 'legacy_damage_modifier')


def historical_data(line):
    raw = _DPD_RAW_RE.search(line)
    if raw:
        observation = {key: raw.group(key) for key in (
            'calc', 'atk_scale', 'blocked', 'damage_type', 'decorate_mask', 'collider', 'atk_zones', 'def_zones')}
        observation['sequence_token'] = raw.group('seq')
        probe = re.search(r'\bprobe=([^\s]+)', line)
        if probe:
            observation['probe'] = probe.group(1)
        return 'damage_raw', {'hit_seq': int(raw.group('seq')), 'observation': observation}
    baseline = _BASELINE_RE.search(line)
    if baseline:
        return 'damage_baseline', {'hit_seq': int(baseline.group('seq')), 'observation': {
            'sequence_token': baseline.group('seq'),
            'values': [{'attribute_type': key, 'value': value} for key, value in _BASELINE_KV_RE.findall(baseline.group('body'))]}}
    if ' IDENTITY_INFERENCE ' in line:
        fields = _extract_fields(line)
        return 'identity_inference', {'entity_id': fields.get('actorId', 'unknown'), 'template': fields.get('template', 'unknown'),
                                      'inference_source': fields.get('source', 'unknown')}
    kind = ('legacy_attribute_modifier' if ' ATTR_MOD ' in line else
            'legacy_damage_modifier' if ' DMG_MOD ' in line else None)
    clock = re.match(r'^\[[\d:.]+\] (GAME_TIMER_TICK|HEARTBEAT)(?:\s|$)', line)
    if kind is None and clock is None:
        return None
    fields = []
    for name, token in _KV_RE.findall(line):
        quoted = token.startswith('"') and token.endswith('"')
        fields.append({'name': name, 'value': token[1:-1] if quoted else token, 'quoted': quoted})
    data = {'observation': {'fields': fields}}
    if clock:
        data['source'] = clock.group(1)
        extracted = _extract_fields(line)
        for key, target in (('tickMs', 'tick_ms'), ('seq', 'operation_seq')):
            value = _coerce_optional_int(extracted.get(key))
            if value is not None:
                data[target] = value
    return kind or 'clock_tick', data


def historical_fields(data):
    observation = data.get('observation')
    if not isinstance(observation, dict) or not isinstance(observation.get('fields'), list):
        raise ValueError('Historical observation requires ordered fields')
    fields = observation['fields']
    if any(not isinstance(row, dict) or not isinstance(row.get('name'), str)
           or not isinstance(row.get('value'), str) or type(row.get('quoted')) is not bool for row in fields):
        raise ValueError('Invalid historical field')
    return fields


def consume_historical(ingestion, event, evidence_index):
    data = event.data
    if event.type in ('legacy_attribute_modifier', 'legacy_damage_modifier'):
        observe_legacy_modifier(ingestion, {row['name']: row['value'] for row in historical_fields(data)})
        ingestion.pending_buff_record = None
    else:
        sequence, observation = data.get('hit_seq'), data.get('observation')
        if type(sequence) is not int or sequence < 0 or not isinstance(observation, dict):
            raise ValueError('Historical damage requires a hit sequence and observation')
        def token(key):
            value = observation.get(key)
            if not isinstance(value, str):
                raise ValueError('Historical damage token missing: ' + key)
            return value
        if event.type == 'damage_raw':
            raw = {'calc': _coerce_optional_float(token('calc')), 'atk_scale': _coerce_optional_float(token('atk_scale')),
                   'blocked': _coerce_optional_int(token('blocked')), 'damage_type_raw': token('damage_type'),
                   'decorate_mask_raw': token('decorate_mask'), 'collider': token('collider'),
                   'atk_zones': _parse_zone_values(token('atk_zones')), 'def_zones': _parse_zone_values(token('def_zones'))}
            observe_raw_damage(ingestion, sequence, raw)
        elif event.type == 'damage_baseline':
            values = observation.get('values')
            if not isinstance(values, list):
                raise ValueError('Historical baseline requires ordered values')
            parsed = {}
            for row in values:
                if not isinstance(row, dict) or not isinstance(row.get('attribute_type'), str) or not isinstance(row.get('value'), str):
                    raise ValueError('Invalid historical baseline field')
                key = _coerce_optional_int(row['attribute_type'])
                if key is None:
                    raise ValueError('Invalid historical baseline attribute')
                parsed[key] = _coerce_float(row['value'])
            observe_baseline(ingestion, sequence, parsed)
        else:
            raise ValueError('Expected historical packet or modifier observation')
    if ingestion.timestamp_clock_origin is None:
        ingestion.timestamp_clock_origin = event.captured_at_ms
    if ingestion.first_context_ms is None:
        ingestion.first_context_ms = event.captured_at_ms
    ingestion.last_context_ms = event.captured_at_ms
