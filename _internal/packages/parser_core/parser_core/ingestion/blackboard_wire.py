"""Blackboard scalars and projectile releases, independent of trace text."""
from parser_core.ingestion.skill_wire import integer, identity_token, label
from parser_core.ingestion.structured_damage import _object, _identity
from parser_core.trace_values import restore_value


TYPES = ('blackboard_calculation', 'blackboard_modify', 'blackboard_preset', 'ink_release')


def blackboard_data(source, action_id, owner, skill, **values):
    data = {target: source[key] for key, target in (
        ('seq_id', 'operation_seq'), ('client_tick_tms', 'client_tick_ms'),
        ('inst_id', 'buff_inst_id'), ('owner_id', 'owner_id'), ('session_id', 'packet_session_id')) if key in source}
    data.update(action_id=action_id, owner=None if owner == '?' else owner,
                skill=None if skill == 'unknown_skill' else skill, **values)
    return data


def blackboard_fields(data):
    return {'seq': str(integer(data.get('operation_seq')) or 0),
            'tick': str(integer(data.get('client_tick_ms')) or 0),
            'inst': identity_token(data.get('buff_inst_id')), 'ownerId': identity_token(data.get('owner_id')),
            'owner': label(data, 'owner', '?'), 'packetSessionId': label(data, 'packet_session_id'),
            'skill': label(data, 'skill', 'unknown_skill'), 'actionId': str(integer(data.get('action_id')) or 0)}


def release_data(observation):
    return {'observation': {'buff_inst_id' if key == 'buff_uid' else key: value for key, value in observation.items()}}


def release_observation(data):
    return {'buff_uid' if key == 'buff_inst_id' else key: value for key, value in data['observation'].items()}


def blackboard_observation(event):
    """Validate the owner boundary; the ordered ink ledger consumes its own observations."""
    if event.type not in TYPES:
        raise ValueError('Expected blackboard or ink event')
    data = _object(event.data)
    fields = _object(data['observation']) if event.type == 'ink_release' else data
    for key in ('buff_inst_id', 'owner_id', 'source_actor_id', 'projectile_id'):
        if key in fields:
            _identity(fields[key])
    if event.type == 'blackboard_calculation' and (not isinstance(data.get('key'), str) or 'final_value' not in data):
        raise ValueError('Expected calculation key and result')
    if event.type == 'blackboard_preset' and not isinstance(data.get('modified_value'), str):
        raise ValueError('Expected preset value')
    return restore_value(data, _object(data.get('legacy_layout', {})))


def consume_structured_blackboard(ingestion, event, evidence_index):
    blackboard_observation(event)
    # Calculation/release state belongs to the persistent ink ledger. Other
    # blackboard actions are diagnostics, as with the legacy ingestion path.
    if ingestion.timestamp_clock_origin is None:
        ingestion.timestamp_clock_origin = event.captured_at_ms
    if ingestion.first_context_ms is None:
        ingestion.first_context_ms = event.captured_at_ms
    ingestion.last_context_ms = event.captured_at_ms
