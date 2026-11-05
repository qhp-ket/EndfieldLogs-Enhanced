"""Independent timer export with the original ordering and optional evidence."""
from datetime import datetime, timedelta, timezone

from parser_core.trace_values import restore_value


def timer_legacy_lines(event, *, timezone_offset_minutes):
    if event.type not in ('battle_timer', 'official_timer', 'battle_phase', 'battle_timer_missing'):
        raise ValueError('Expected timer event')
    if 'legacy_layout' not in event.data:
        raise ValueError('Timer event lacks legacy export layout')
    data = restore_value(event.data, event.data['legacy_layout'])
    phase = data.get('phase')
    if event.type == 'battle_phase':
        fields = [('operation_seq', 'seq'), ('source', 'source'), ('game_id', 'gameId')]
        marker = 'BATTLE_PHASE_START'
    elif event.type == 'battle_timer_missing' or event.type == 'official_timer' and phase == 'missing':
        fields = [('boundary', 'boundary'), ('packet_battle_active', 'packetBattleActive'),
                  ('official_expected', 'officialExpected'), ('official_start_seen', 'officialStartSeen'), ('game_id', 'gameId')]
        marker = 'BATTLE_TIMER_MISSING' if event.type == 'battle_timer_missing' else 'OFFICIAL_TIMER_MISSING'
    elif event.type == 'battle_timer':
        fields = {
            'start': [('operation_seq', 'seq'), ('source', 'source'), ('start_ms', 'startMs'), ('expire_ms', 'expireMs'), ('official', 'official')],
            'end': [('operation_seq', 'seq'), ('source', 'source'), ('elapsed_ms', 'elapsedMs'), ('start_ms', 'startMs'), ('end_ms', 'endMs'),
                    ('expire_ms', 'expireMs'), ('sane', 'sane'), ('official', 'official'), ('packet_elapsed_ms', 'packetElapsedMs'), ('wall_elapsed_ms', 'wallElapsedMs')],
            'reset': [('source', 'source'), ('scene_num_id', 'scene')]}[phase]
        marker = 'GAME_TIMER_' + phase.upper()
    else:
        fields = {'start': [('source', 'source'), ('game_id', 'gameId'), ('challenge_start_ts', 'challengeStartTs'),
                            ('challenge_expire_ts', 'challengeExpireTs'), ('prepare_seconds', 'prepareSeconds')],
                  'end': [('source', 'source'), ('game_id', 'gameId'), ('is_pass', 'isPass'), ('pass_time', 'passTime'),
                          ('force_leave_ts', 'forceLeaveTs'), ('bp_score', 'bpScore'), ('danger_meter', 'dangerMeter')],
                  'await': [('source', 'source'), ('game_id', 'gameId'), ('official_start_seen', 'officialStartSeen')]}[phase]
        marker = 'OFFICIAL_TIMER_' + phase.upper()
    parts = [marker]
    for key, target in fields:
        if key in data and data[key] is not None:
            value = int(bool(data[key])) if key in ('is_pass', 'packet_battle_active', 'official_expected', 'official_start_seen') else int(data[key]) if event.type == 'battle_timer' and type(data[key]) is bool else data[key]
            parts.append(f'{target}={value}')
    local = datetime.fromtimestamp(event.captured_at_ms / 1000, timezone(timedelta(minutes=timezone_offset_minutes)))
    return [f"[{local.strftime('%H:%M:%S.%f')[:-3]}] {' '.join(parts)}\n"]
