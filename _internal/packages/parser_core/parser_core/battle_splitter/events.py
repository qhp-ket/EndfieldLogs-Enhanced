"""Stream event boundary metadata through the existing trace selection rules."""
from parser_core.battle_splitter.trace import _split_observed_records
from parser_core.ingestion.structured_context import context_timer_observation
from parser_core.ingestion.structured_timer import TIMER_TYPES, timer_observation


def split_event_battles(events, *, timezone_offset_minutes=0, idle_split_ms=30_000):
    rows, hits, loadouts, hit_times = [], [], set(), {}
    origin = None
    for index, event in enumerate(events):
        stamp = (event.captured_at_ms + timezone_offset_minutes * 60_000) % 86_400_000
        if origin is None:
            origin = stamp
        absolute = origin + (stamp - origin) % 86_400_000
        seconds, millis = divmod(stamp, 1000)
        hours, seconds = divmod(seconds, 3600)
        minutes, seconds = divmod(seconds, 60)
        marker, fields = '', {}
        if event.type in TIMER_TYPES:
            marker, fields = timer_observation(event)
        elif event.type == 'game_instance':
            marker, fields = context_timer_observation(event)
        elapsed = None
        if marker == 'OFFICIAL_TIMER_END':
            elapsed = fields.get('passTime')
        elif marker == 'GAME_TIMER_END' and fields.get('sane') not in (None, '', '0'):
            elapsed = fields.get('elapsedMs')
        try:
            elapsed = int(elapsed)
        except (ValueError, TypeError):
            elapsed = None
        row = dict(line_index=index, abs_ts_ms=absolute,
            hint=f'{hours:02d}-{minutes:02d}-{seconds:02d}-{millis:03d}',
            game_id=fields.get('gameId'), challenge_start_ts=fields.get('challengeStartTs'),
            timer_source=fields.get('source'), timer_start_tick=fields.get('startMs'),
            is_boundary=marker in ('GAME_TIMER_RESET', 'GAME_INST_RESTART', 'GAME_INST_LEAVE'),
            is_hit=event.type == 'damage', is_dungeon_context=event.type == 'dungeon',
            is_official_timer_start=marker == 'OFFICIAL_TIMER_START',
            is_game_timer_start=marker == 'GAME_TIMER_START',
            is_official_timer_end=marker == 'OFFICIAL_TIMER_END',
            is_game_timer_end=marker == 'GAME_TIMER_END',
            is_timer_end=marker in ('OFFICIAL_TIMER_END', 'GAME_TIMER_END'),
            timer_elapsed_ms=elapsed if elapsed is not None and elapsed > 0 else None)
        rows.append(row)
        if row['is_hit']:
            hits.append(row)
            hit_times[index] = event.captured_at_ms
        if event.type in ('loadout_slot', 'loadout_stats'):
            loadouts.add(index)
    bounds = _split_observed_records(rows, hits, len(rows), loadouts, set(), idle_split_ms=idle_split_ms)
    for segment in bounds:
        segment['first_hit_captured_at_ms'] = hit_times[segment['first_hit_line_index']]
    return bounds
