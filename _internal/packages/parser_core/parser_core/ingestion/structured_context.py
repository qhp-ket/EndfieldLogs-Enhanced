"""Context and diagnostic evidence; absence of a timer completion never creates elapsed time."""
from parser_core.ingestion.structured_damage import _object

CONTEXT_TYPES = ('game_instance', 'game_mechanics', 'scene_battle', 'battle_reset', 'session_warning')
MECHANICS = {
    'CS_GAME_MECHANICS_NTF_INST_PREPARE_FINISH': ('game_mechanics', 'prepare_finish', 'GAME_MECHANICS_PREPARE_FINISH'),
    'CS_GAME_MECHANICS_REQ_START': ('game_mechanics', 'request_start', 'GAME_MECHANICS_REQ_START'),
    'CS_GAME_MECHANICS_REQ_STOP': ('game_mechanics', 'request_stop', 'GAME_MECHANICS_REQ_STOP'),
    'SC_GAME_MECHANICS_MODIFY_INST_TIME_FREEZE': ('game_mechanics', 'time_freeze', 'GAME_MECHANICS_TIME_FREEZE'),
    'SC_GAME_MECHANICS_SYNC_COMPLETION_REWARD': ('game_mechanics', 'completion_reward', 'SC_GAME_MECHANICS_SYNC_COMPLETION_REWARD'),
    'SC_GAME_MECHANICS_SYNC_ENTER_GAME_INST': ('game_instance', 'enter', 'GAME_INST_ENTER'),
    'SC_GAME_MECHANICS_SYNC_LEAVE_GAME_INST': ('game_instance', 'leave', 'GAME_INST_LEAVE'),
    'SC_GAME_MECHANICS_SYNC_RESTART_GAME_INST': ('game_instance', 'restart', 'GAME_INST_RESTART'),
}
MECHANIC_FIELDS = ('game_inst_id', 'game_unique_id', 'is_hunter_mode', 'interactive_obj_id', 'npc_proxy_id', 'npc_obj_id', 'time_freeze_infos')


def context_data(kind, event, *, source=None, game_id=''):
    if kind in ('game_instance', 'game_mechanics'):
        expected, action, _ = MECHANICS[source]
        if kind != expected:
            raise ValueError('Inconsistent mechanics type')
        data = {'source': source, 'action': action}
        if game_id:
            data['game_id'] = game_id
        fields = MECHANIC_FIELDS
    elif kind == 'scene_battle':
        data, fields = {'source': source}, ('in_battle',)
    elif kind == 'battle_reset':
        data, fields = {}, ('reason', 'inst_id', 'battle_inst_id')
    elif kind == 'session_warning':
        data, fields = {}, ('kind', 'direction', 'missing_bytes', 'startup_tcp_gap_count')
    else:
        raise ValueError('Expected context event')
    for key in fields:
        if key in event:
            data['event_inst_id' if key == 'inst_id' else key] = event[key]
    return data


def context_observation(event):
    if event.type not in CONTEXT_TYPES:
        raise ValueError('Expected context event')
    data = _object(event.data)
    if event.type in ('game_instance', 'game_mechanics'):
        declaration = MECHANICS.get(data.get('source'))
        if declaration is None or declaration[:2] != (event.type, data.get('action')):
            raise ValueError('Invalid mechanics source/action')
    elif event.type == 'scene_battle' and not isinstance(data.get('source'), str):
        raise ValueError('Scene source is required')
    return data


def consume_structured_context(ingestion, event, evidence_index):
    data = context_observation(event)
    if event.type == 'game_instance' or event.type == 'game_mechanics' and data['action'] == 'time_freeze':
        ingestion.timer_observed_times[evidence_index] = event.captured_at_ms
    if ingestion.timestamp_clock_origin is None:
        ingestion.timestamp_clock_origin = event.captured_at_ms
    if ingestion.first_context_ms is None:
        ingestion.first_context_ms = event.captured_at_ms
    ingestion.last_context_ms = event.captured_at_ms


def context_timer_observation(event):
    """Project only official lifecycle fields; no legacy row is constructed or parsed."""
    from parser_core.ingestion.skill_wire import integer
    data = context_observation(event)
    if event.type not in ('game_instance', 'game_mechanics'):
        return None
    marker = MECHANICS[data['source']][2]
    fields = {'source': data['source']}
    if data.get('game_id'):
        fields['gameId'] = data['game_id']
    freezes = data.get('time_freeze_infos')
    if data['action'] == 'time_freeze' and isinstance(freezes, list):
        fields['count'] = str(len(freezes))
        rows = [(integer(row.get('time_key')) or 0, integer(row.get('total_freeze_time_in_ms')) or 0)
                for row in freezes if isinstance(row, dict)]
        if rows:
            fields['freezeInfos'] = '[' + ','.join(f'{key}:{value}' for key, value in rows) + ']'
    return marker, fields
