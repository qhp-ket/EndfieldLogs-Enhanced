"""Common producer envelope for the event families already connected to typed ingestion."""
from copy import deepcopy

from parser_core.trace_jsonl import TraceEvent
from parser_core.trace_model import compact_data


def observation_event(sequence, captured_at_ms, event_type, data, origin):
    source = {}
    if isinstance(origin.get('session_id'), str) and origin['session_id']:
        source['session_id'] = origin['session_id']
    if type(origin.get('seq_id')) is int:
        source['operation_seq'] = origin['seq_id']
    if type(origin.get('generation')) is int and 0 <= origin['generation'] < 2**32:
        source['generation'] = origin['generation']
    owner = origin.get('operation_owner_id')
    if type(owner) in (int, str) and str(owner).isascii() and str(owner).isdigit() and 0 <= int(owner) < 2**64:
        source['owner_id'] = str(int(owner))
    tick = origin.get('client_tick_tms')
    if event_type in ('loadout_slot', 'loadout_stats'):
        from parser_core.trace_loadout import typed_loadout
        data = typed_loadout(data)
    projected = compact_data(data, source, tick if type(tick) is int else None, event_type)
    return TraceEvent(sequence, captured_at_ms, event_type, projected, deepcopy(source), tick if type(tick) is int else None)
