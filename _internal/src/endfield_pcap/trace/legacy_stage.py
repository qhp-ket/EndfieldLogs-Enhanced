"""Independent export of stage fields in their established legacy order."""
from datetime import datetime, timedelta, timezone

from parser_core.ingestion.skill_wire import integer
from endfield_pcap.trace.export_values import export_data


def stage_legacy_lines(event, *, timezone_offset_minutes):
    if event.type not in ('dungeon', 'contracts', 'battle_result'):
        raise ValueError('Expected stage event')
    data = export_data(event)
    if event.type == 'dungeon':
        parts = ['DUNGEON_CONTEXT', 'dungeonId=' + data['dungeon_id'], 'source=' + data['source']]
        for key, name in (('scene_num_id', 'scene'), ('scene_id', 'sceneId'), ('challenge_expire_ts', 'challengeExpireTs'),
                          ('leave_dungeon_ts', 'leaveDungeonTs'), ('char_team_count', 'charTeamCount')):
            if key in data and data[key] is not None:
                parts.append(f'{name}={data[key]}')
        for key, name in (('is_reward', 'isReward'), ('is_calc', 'isCalc'), ('is_pass', 'isPass')):
            if key in data and data[key] is not None:
                parts.append(f'{name}={int(bool(data[key]))}')
    elif event.type == 'battle_result':
        parts = ['BATTLE_RESULT', 'source=' + data['source'], 'dungeonId=' + data['dungeon_id'],
                 'isCalc=' + str(int(bool(data.get('is_calc')))), 'isPass=' + str(int(bool(data.get('is_pass'))))]
    else:
        raw = data.get('tag_ids') or data.get('alternate_tag_ids') or data.get('display_tag_ids') or []
        tags = [value for item in raw if (value := integer(item)) not in (None, 0)]
        parts = ['CONTRACT_TAGS', 'dungeonId=' + (data.get('dungeon_id') or 'unknown'), 'source=' + data['source'],
                 'tagIds=[' + ','.join(str(value) for value in tags) + ']']
        if (score := integer(data.get('score'))) is not None:
            parts.append(f'score={score}')
        if direction := str(data.get('direction') or ''):
            parts.append('direction=' + direction)
        if (message := integer(data.get('message_id') or data.get('alternate_message_id'))) is not None:
            parts.append(f'msgId={message}')
    local = datetime.fromtimestamp(event.captured_at_ms / 1000, timezone(timedelta(minutes=timezone_offset_minutes)))
    return [f"[{local.strftime('%H:%M:%S.%f')[:-3]}] {' '.join(parts)}\n"]
