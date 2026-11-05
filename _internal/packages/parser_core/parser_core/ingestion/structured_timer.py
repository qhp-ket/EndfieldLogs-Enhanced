"""Structured timer boundaries call the same ordered state updates as legacy import."""
from parser_core.ingestion.structured_damage import _object
from parser_core.ingestion.timers import apply_timer_observation

TIMER_TYPES = ('battle_timer', 'official_timer', 'battle_phase', 'battle_timer_missing')
FIELDS = {'source': 'source', 'operation_seq': 'seq', 'scene_num_id': 'scene', 'game_id': 'gameId',
          'start_ms': 'startMs', 'end_ms': 'endMs', 'elapsed_ms': 'elapsedMs', 'expire_ms': 'expireMs',
          'packet_elapsed_ms': 'packetElapsedMs', 'wall_elapsed_ms': 'wallElapsedMs', 'official': 'official',
          'sane': 'sane', 'fallback': 'fallback', 'is_pass': 'isPass', 'pass_time': 'passTime',
          'challenge_start_ts': 'challengeStartTs', 'challenge_expire_ts': 'challengeExpireTs',
          'prepare_seconds': 'prepareSeconds', 'force_leave_ts': 'forceLeaveTs', 'bp_score': 'bpScore', 'danger_meter': 'dangerMeter',
          'boundary': 'boundary', 'packet_battle_active': 'packetBattleActive',
          'official_expected': 'officialExpected', 'official_start_seen': 'officialStartSeen'}
FLAGS = ('is_pass', 'packet_battle_active', 'official_expected', 'official_start_seen')


def official_timer_data(event, phase, game_id, source):
    data = {'phase': phase, 'source': source}
    if game_id:
        data['game_id'] = game_id
    for key, target in (('challenge_start_ts', 'challenge_start_ts'), ('challenge_expire_ts', 'challenge_expire_ts'),
                        ('prepare_challenge_seconds', 'prepare_seconds'), ('is_pass', 'is_pass'),
                        ('pass_time', 'pass_time'), ('force_leave_ts', 'force_leave_ts')):
        if key in event:
            data[target] = event[key]
    return data


def timer_observation(event):
    if event.type not in TIMER_TYPES:
        raise ValueError('Expected timer event')
    data = _object(event.data)
    phase = data.get('phase')
    missing = event.type == 'battle_timer_missing' or event.type == 'official_timer' and phase == 'missing'
    required = 'boundary' if missing else 'source'
    if not isinstance(data.get(required), str) or not data[required]:
        raise ValueError('Timer ' + required + ' is required')
    if event.type == 'battle_timer' and phase not in ('start', 'end', 'reset') or event.type == 'official_timer' and phase not in ('start', 'end', 'await', 'missing'):
        raise ValueError('Invalid timer phase')
    marker = ('BATTLE_PHASE_START' if event.type == 'battle_phase' else 'BATTLE_TIMER_MISSING' if event.type == 'battle_timer_missing'
              else ('GAME_TIMER_' if event.type == 'battle_timer' else 'OFFICIAL_TIMER_') + phase.upper())
    fields = {}
    for key, target in FIELDS.items():
        if key not in data or data[key] is None:
            continue
        value = data[key]
        if key in FLAGS:
            value = int(bool(value))
        elif event.type == 'battle_timer' and type(value) is bool:
            value = int(value)
        fields[target] = str(value)
    return marker, fields


def consume_structured_timer(ingestion, event, evidence_index):
    marker, fields = timer_observation(event)
    if marker == 'GAME_TIMER_RESET' and fields.get('source') == 'CAPTURE_SESSION_START':
        ingestion.critical_stats_by_actor.clear()
    apply_timer_observation(ingestion, marker, fields, event.captured_at_ms)
    if event.type != 'battle_phase':
        ingestion.timer_observed_times[evidence_index] = event.captured_at_ms
    if ingestion.timestamp_clock_origin is None:
        ingestion.timestamp_clock_origin = event.captured_at_ms
    if ingestion.first_context_ms is None:
        ingestion.first_context_ms = event.captured_at_ms
    ingestion.last_context_ms = event.captured_at_ms
