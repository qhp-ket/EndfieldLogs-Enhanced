"""Read adapter for the original JSONL representation; not a v2 dependency."""
from parser_core.trace_values import restore_value


def native_data(data):
    from parser_core.trace_loadout import typed_loadout
    from parser_core.trace_model import compact_data
    restored = restore_value(data, data['legacy_layout'])
    return compact_data(typed_loadout({key: value for key, value in restored.items() if key != 'legacy_layout'}), {})


def export_data(data):
    return restore_value(data, data['legacy_layout'])
