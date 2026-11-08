"""Formatting values for the independent official-log exporter."""
from parser_core.trace_model import event_data


def _numbers(value):
    if isinstance(value, dict):
        if set(value) == {'number_status'}:
            return {'nan': float('nan'), 'positive_infinity': float('inf'), 'negative_infinity': -float('inf')}[value['number_status']]
        return {key: _numbers(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_numbers(child) for child in value]
    return value


def export_data(event):
    if 'legacy_layout' in event.data:
        from parser_core.trace_v1 import export_data as export_v1
        return export_v1(event.data)
    data = _numbers(event_data(event))
    if event.type in ('loadout_slot', 'loadout_stats'):
        from parser_core.trace_loadout import legacy_loadout
        return legacy_loadout(data)
    return data
