"""Observed blackboard identity and scalar fields, without old-line formatting."""
from parser_core.ingestion.buff_packet_wire import packet_data
from parser_core.ingestion.skill_wire import integer, identity_token, label


def dynamic_data(source, action_id, value, owner, skill, observation):
    data = packet_data(observation)
    for key, target in (('seq_id', 'operation_seq'), ('client_tick_tms', 'client_tick_ms'),
                        ('inst_id', 'buff_inst_id'), ('owner_id', 'owner_id'), ('session_id', 'packet_session_id')):
        if key in source:
            data[target] = source[key]
    data.update(action_id=action_id, value=value, owner=None if owner == '?' else owner,
                skill=None if skill == 'unknown_skill' else skill)
    return data


def dynamic_fields(data):
    return {'seq': str(integer(data.get('operation_seq')) or 0),
            'tick': str(integer(data.get('client_tick_ms')) or 0),
            'inst': identity_token(data.get('buff_inst_id')), 'ownerId': identity_token(data.get('owner_id')),
            'owner': label(data, 'owner', '?'), 'packetSessionId': label(data, 'packet_session_id'),
            'skill': label(data, 'skill', 'unknown_skill'), 'actionId': str(integer(data.get('action_id')) or 0),
            'value': repr(float(data['value']))}
