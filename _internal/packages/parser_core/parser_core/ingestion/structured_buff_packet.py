"""Packet proofs use the same binding and conflict rules as legacy input."""
from parser_core.ingestion.buff_packet_wire import packet_observation
from parser_core.ingestion.buff_observations import apply_buff_packet, apply_buff_unresolved
from parser_core.ingestion.structured_damage import _identity, _object
from parser_core.ingestion.skill_wire import identity_token
from parser_core.trace_values import restore_value


PACKET_TYPES = {'buff_creation': 'creation', 'buff_origin': 'origin', 'buff_enable': 'enable', 'buff_keyword': 'keyword'}


def unresolved_fields(data):
    return {'uid': identity_token(data.get('buff_inst_id')),
            'seq': str(data['operation_seq']) if 'operation_seq' in data else 'unknown',
            'triggerType': str(data['trigger_type']) if type(data.get('trigger_type')) is int else 'unknown',
            'actionId': str(data.get('action_id')), 'ownerId': str(data.get('target_id')),
            'srcId': str(data.get('source_actor_id'))}


def consume_structured_buff_packet(ingestion, event, evidence_index):
    data = _object(event.data)
    if event.type == 'buff_unresolved':
        observation = data
    elif event.type in PACKET_TYPES:
        observation = _object(data.get('observation'))
    else:
        raise ValueError('Expected BUFF packet event')
    for key in ('buff_inst_id', 'source_actor_id', 'target_id', 'owner_id', 'operation_owner_id', 'environment_inst_id'):
        if key in observation:
            _identity(observation[key])
    restored = restore_value(data, _object(data.get('legacy_layout', {})))
    if event.type == 'buff_unresolved':
        apply_buff_unresolved(ingestion, unresolved_fields(restored), evidence_index, event.captured_at_ms)
    else:
        apply_buff_packet(ingestion, PACKET_TYPES[event.type], packet_observation(restored), evidence_index, event.captured_at_ms)
    if ingestion.timestamp_clock_origin is None:
        ingestion.timestamp_clock_origin = event.captured_at_ms
    if ingestion.first_context_ms is None:
        ingestion.first_context_ms = event.captured_at_ms
    ingestion.last_context_ms = event.captured_at_ms
