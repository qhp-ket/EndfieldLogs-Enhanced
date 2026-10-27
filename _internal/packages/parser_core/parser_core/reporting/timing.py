"""Apply official challenge evidence and scope hits by lifecycle line order."""
from __future__ import annotations

from parser_core.catalog.dungeons import _resolve_dungeon_context
from parser_core.ingestion.fields import _extract_fields
from parser_core.ingestion.fields import _parse_prefixed_timestamp_ms
from parser_core.reporting.state import ReportState
from parser_core.timing.timer_evidence import collect_timer_evidence
from typing import Any




def apply_official_timing(report_state: ReportState, text: str, live_projection: Any) -> tuple[dict[str, Any] | None, int | None, dict[str, Any] | None]:
    """Apply official challenge evidence and scope hits by lifecycle line order."""
    timer_evidence = collect_timer_evidence(text, _extract_fields, _parse_prefixed_timestamp_ms, report_state.timer_observed_times,
        indexed_lines=getattr(live_projection, 'timer_lines', None))
    if timer_evidence is not None:
        start = timer_evidence.get('start') or {}
        complete = timer_evidence.get('complete') or {}
        if start.get('gameId'):
            report_state.dungeon_context_id = str(start['gameId'])
            report_state.dungeon_context = _resolve_dungeon_context(report_state.dungeon_context_id)
        report_state.official_timer_start_ms = start.get('observedMs')
        report_state.official_timer_end_ms = complete.get('observedMs')
        report_state.official_pass_confirmed = complete.get('isPass') == '1'
        report_state.challenge_pass_confirmed = report_state.challenge_pass_confirmed or report_state.official_pass_confirmed
        report_state.official_timer_elapsed_ms = None
        raw_pass_time = complete.get('passTimeMs')
        if isinstance(raw_pass_time, str) and raw_pass_time.isdecimal() and int(raw_pass_time) > 0:
            report_state.official_timer_elapsed_ms = int(raw_pass_time)
        report_state.game_timer_start_ms = report_state.official_timer_start_ms
        report_state.game_timer_end_ms = report_state.official_timer_end_ms
        report_state.game_timer_elapsed_ms = report_state.official_timer_elapsed_ms if report_state.official_timer_elapsed_ms is not None else report_state.live_timer_elapsed_ms
        report_state.game_timer_window_elapsed_ms = report_state.game_timer_elapsed_ms
        report_state.timer_start_seen = report_state.official_timer_start_ms is not None
        report_state.timer_end_seen = report_state.official_timer_end_ms is not None
        report_state.completion_source = 'official_timer_end' if report_state.official_pass_confirmed else report_state.completion_source
    # Packet receipt timestamps are diagnostic only. A negative wall-clock
    # difference may be a date boundary; it does not disprove server passTime.
    official_timer_observed_elapsed_ms = (
        report_state.official_timer_end_ms - report_state.official_timer_start_ms
        if report_state.official_timer_start_ms is not None and report_state.official_timer_end_ms is not None
        and report_state.official_timer_end_ms >= report_state.official_timer_start_ms else None
    )

    official_scope = (timer_evidence or {}).get('start')
    if official_scope is not None:
        # Membership follows explicit lifecycle events, not receipt-clock
        # proximity. A new challenge cannot inherit a previous one's hits.
        scope_end_line = ((timer_evidence or {}).get('complete') or {}).get('line')
        if scope_end_line is None:
            scope_end_line = (live_projection.line_count if live_projection is not None else len(text.splitlines()))+1
        scope_end_line = min([scope_end_line] + [
            event['line'] for event in timer_evidence['events']
            if event.get('kind') == 'boundary'
            and event.get('gameId') in (None, '', official_scope.get('gameId'))
        ])
        report_state.hits = [hit for hit in report_state.hits if official_scope['line'] < hit['line_no'] < scope_end_line]
    return timer_evidence, official_timer_observed_elapsed_ms, official_scope


def _filter_buff_starts_for_timer_window(
    buff_starts: list[dict[str, Any]],
    *,
    battle_start_ms: int,
) -> list[dict[str, Any]]:
    def overlaps_start(buff_record: dict[str, Any]) -> bool:
        start_ts_ms = int(buff_record.get("ts_ms") or 0)
        if start_ts_ms >= battle_start_ms:
            return True
        end_ts_ms = buff_record.get("end_ts_ms")
        if end_ts_ms is not None:
            return int(end_ts_ms) >= battle_start_ms
        raw_duration_ms = buff_record.get("raw_duration_ms")
        if raw_duration_ms is not None and int(raw_duration_ms or 0) > 0:
            return start_ts_ms + int(raw_duration_ms) >= battle_start_ms
        packet_seen_ts_ms = buff_record.get("packet_modifier_last_seen_ts_ms")
        if packet_seen_ts_ms is not None:
            return int(packet_seen_ts_ms) >= battle_start_ms
        return False

    return [
        buff_record
        for buff_record in buff_starts
        if not (
            buff_record.get("target_enemy_key")
            and int(buff_record.get("ts_ms") or 0) < battle_start_ms
            and not overlaps_start(buff_record)
        )
    ]
