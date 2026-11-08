"""Stage observations enter the existing ordered context state without trace text."""
from parser_core.trace_model import event_data
from parser_core.ingestion.skill_wire import integer
from parser_core.ingestion.structured_damage import _object
from parser_core.ingestion.timers import apply_stage_context

STAGE_TYPES = ('dungeon', 'contracts', 'battle_result')
FIELDS = (('scene_num_id', 'scene'), ('scene_id', 'sceneId'), ('challenge_expire_ts', 'challengeExpireTs'),
          ('leave_dungeon_ts', 'leaveDungeonTs'), ('char_team_count', 'charTeamCount'),
          ('is_reward', 'isReward'), ('is_calc', 'isCalc'), ('is_pass', 'isPass'))


def stage_data(kind, event, dungeon_id, source):
    data = {'dungeon_id': dungeon_id or None, 'source': source}
    fields = {'dungeon': tuple(key for key, _ in FIELDS), 'battle_result': ('is_calc', 'is_pass'),
              'contracts': ('tag_ids', 'tagIds', 'display_tag_ids', 'score', 'direction', 'msg_id', 'msgId')}[kind]
    names = {'tagIds': 'alternate_tag_ids', 'msg_id': 'message_id', 'msgId': 'alternate_message_id'}
    for key in fields:
        if key in event:
            data[names.get(key, key)] = event[key]
    return data


def contract_tags(data):
    raw = data.get('tag_ids') or data.get('alternate_tag_ids') or data.get('display_tag_ids') or []
    return [number for value in raw if (number := integer(value)) not in (None, 0)]


def stage_observation(event):
    if event.type not in STAGE_TYPES:
        raise ValueError('Expected stage event')
    data = _object(event_data(event))
    if not isinstance(data.get('source'), str) or not data['source']:
        raise ValueError('Stage source is required')
    dungeon = data.get('dungeon_id')
    if dungeon is not None and not isinstance(dungeon, str):
        raise ValueError('Stage dungeon identity must be text or null')
    if event.type != 'contracts' and not dungeon:
        raise ValueError('Stage dungeon identity is required')
    fields = {'dungeonId': dungeon or 'unknown', 'source': data['source']}
    if event.type == 'battle_result':
        fields['isPass'] = str(int(bool(data.get('is_pass'))))
    tags = None
    if event.type == 'contracts':
        # Legacy import extracts digits, including the magnitude of negative IDs.
        # Keep that established analysis projection; the event retains raw signs.
        tags = [abs(value) for value in contract_tags(data)]
        if (score := integer(data.get('score'))) is not None:
            fields['score'] = str(score)
    return {'dungeon': 'DUNGEON_CONTEXT', 'contracts': 'CONTRACT_TAGS', 'battle_result': 'BATTLE_RESULT'}[event.type], fields, tags


def consume_structured_stage(ingestion, event, evidence_index):
    marker, fields, tags = stage_observation(event)
    apply_stage_context(ingestion, marker, fields, tag_ids=tags)
    if ingestion.timestamp_clock_origin is None:
        ingestion.timestamp_clock_origin = event.captured_at_ms
    if ingestion.first_context_ms is None:
        ingestion.first_context_ms = event.captured_at_ms
    ingestion.last_context_ms = event.captured_at_ms
