"""Compact projection of canonical results. No damage or attribution rules."""
from parser_core.snapshot_quality import build_snapshot_quality


def canonical_rates(total_damage, total_rd, duration_ms):
    seconds = duration_ms/1000
    return round(total_damage/seconds, 2), round(total_rd/seconds, 2)


def clock_summary(previous, state, timer_line):
    """Reuse allocations only when a clock cannot expand semantic membership.

    Called only for a proven clock-only input suffix. Future-dated records,
    uncertain timing, and a regressing clock take the normal semantic path.
    """
    from parser_core.ingestion.fields import _build_iso_datetime
    from parser_core.ingestion.fields import _coerce_int
    from parser_core.ingestion.fields import _extract_fields
    from parser_core.realtime.live_copy import isolated_copy
    battle = previous['battle']
    if (not timer_line or battle.get('time_source') != 'game_timer'
            or not battle.get('official_timer_start_seen') or battle.get('official_timer_end_seen')
            or battle.get('timer_window_valid') is not True or battle.get('duration_ms', 0) <= 0):
        return None
    start = state.get('official_timer_start_ms')
    if start is None:
        return None
    old_end = start+battle['duration_ms']
    elapsed = _coerce_int(_extract_fields(timer_line).get('elapsedMs'), default=0)
    if elapsed < battle['duration_ms']:
        return None
    for key in ('hits', 'buff_starts', 'unresolved_hits', 'unresolved_buff_actions', 'skill_casts', 'dynamic_bb_events'):
        for row in state.get(key) or []:
            if (row.get('ts_ms') or 0) > old_end:
                return None
    result = isolated_copy(previous)
    result['battle'].update(duration_ms=elapsed,
        battle_end_at=_build_iso_datetime(state['reference_date'], start+elapsed),
        total_dps=canonical_rates(battle['total_damage'], 0, elapsed)[0])
    seconds = elapsed/1000
    active, zero = [], []
    for row in result['participants']:
        if row.get('total_damage') or row.get('total_rd'):
            row['dps'], _ = canonical_rates(row['total_damage'], row['total_rd'], elapsed)
            row['rdps'] = row['total_rd']/seconds if seconds > .5 else 0.0
            active.append(row)
        else:
            zero.append(row)
    active.sort(key=lambda row: (-row['dps'], -canonical_rates(0, row['total_rd'], elapsed)[1], row['character_name']))
    result['participants'] = active+zero
    result['battle']['roster'] = [{'slot':index, 'character_key':row['character_key'],
                                 'character_name':row['character_name']} for index,row in enumerate(active,1)]
    return result

BATTLE_FIELDS = (
    'dungeon_key', 'dungeon_name', 'boss_key', 'boss_name', 'battle_start_at',
    'battle_end_at', 'duration_ms', 'total_damage', 'total_dps', 'roster',
    'time_source', 'timer_start_seen', 'timer_end_seen', 'timer_window_valid',
    'official_timer_start_seen', 'official_timer_end_seen', 'timer_integrity_ok',
    'timer_integrity_reasons', 'clear_flag', 'official_pass_confirmed',
    'completion_source', 'parser_version', 'rules_version',
)


def summary_from_report(report, *, maxima=None):
    """Also accepts complete historical reports, without altering their contract."""
    from parser_core.unified import overlay_snapshot_from_report
    # The compact builder supplies maxima directly from allocated hits, avoiding
    # construction of timeline rows merely to discover each source's maximum.
    projected = overlay_snapshot_from_report(report, rdps_max=maxima)
    quality = build_snapshot_quality(report, include_evidence=False)
    basis = report.get('rdps_damage_basis') or {}
    preflight = report.get('rdps_preflight') or {}
    quality['counts'] = {
        'blockers': preflight.get('blocker_count'),
        **{key: basis.get(key) for key in (
            'hit_count', 'unresolved_damage_actor_count', 'missing_packet_hit_count',
            'hit_conservation_mismatch_count')},
    }
    return {'battle': {key: report['battle'][key] for key in BATTLE_FIELDS if key in report['battle']},
            'participants': projected['participants'], 'quality_summary': quality}


def finish_live_report(report, summary=False, *, hits=()):
    if not summary:
        from parser_core.snapshot_quality import with_snapshot_quality
        return with_snapshot_quality(report)
    maxima = {}
    from parser_core.realtime.incremental import ACTIVE_ALLOCATION_CACHE
    cache = ACTIVE_ALLOCATION_CACHE.get()
    if cache is not None and cache.maxima_prefix:
        maxima = cache.maxima_prefix[-1]
    else:
        for hit in hits:
            for key, value in (hit.get('rdps_contributions') or {}).items():
                maxima[key] = max(maxima.get(key, 0.0), round(value, 4))
    return summary_from_report(report, maxima=maxima)
