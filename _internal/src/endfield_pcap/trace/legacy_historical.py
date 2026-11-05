"""Independent formatting for historical evidence; no full legacy line is stored."""
from datetime import datetime, timedelta, timezone

from parser_core.ingestion.historical_wire import historical_fields
from parser_core.trace_values import restore_value


def historical_body(kind, data):
    observation = data['observation']
    if kind == 'damage_raw':
        probe = ' probe=' + observation['probe'] if 'probe' in observation else ''
        return (f"DPD_RAW #{observation['sequence_token']}{probe} calc={observation['calc']} atkScale={observation['atk_scale']} "
                f"blocked={observation['blocked']} damageType={observation['damage_type']} decorateMask={observation['decorate_mask']} "
                f"collider=\"{observation['collider']}\" atkZones=[{observation['atk_zones']}] defZones=[{observation['def_zones']}]")
    if kind == 'damage_baseline':
        values = ' '.join(row['attribute_type'] + '=' + row['value'] for row in observation['values'])
        return f"BASELINE #{observation['sequence_token']} {values}"
    marker = {'legacy_attribute_modifier': 'ATTR_MOD', 'legacy_damage_modifier': 'DMG_MOD'}.get(kind)
    if kind == 'clock_tick' and data.get('source') in ('GAME_TIMER_TICK', 'HEARTBEAT'):
        marker = data['source']
    if marker is None:
        raise ValueError('Expected historical event')
    fields = [row['name'] + '=' + ('"' + row['value'] + '"' if row['quoted'] else row['value']) for row in historical_fields(data)]
    return marker + (' ' + ' '.join(fields) if fields else '')


def historical_legacy_lines(event, *, timezone_offset_minutes):
    if 'legacy_layout' not in event.data:
        raise ValueError('Historical event lacks legacy export layout')
    data = restore_value(event.data, event.data['legacy_layout'])
    local = datetime.fromtimestamp(event.captured_at_ms / 1000, timezone(timedelta(minutes=timezone_offset_minutes)))
    return [f"[{local.strftime('%H:%M:%S.%f')[:-3]}] {historical_body(event.type, data)}\n"]
