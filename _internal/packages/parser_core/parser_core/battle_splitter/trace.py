"""Shared trace battle boundaries, timer tails and retained loadout context."""
from __future__ import annotations

import re
from parser_core.ingestion.fields import _extract_fields


_TIMESTAMP_RE = re.compile(r"^\[(\d{2}):(\d{2}):(\d{2})\.(\d{3})\]")


_GAME_TIMER_END_ELAPSED_RE = re.compile(r"\bGAME_TIMER_END\b.*?\belapsedMs=(\d+).*?\bsane=(\d+)")


_OFFICIAL_TIMER_END_ELAPSED_RE = re.compile(r"\bOFFICIAL_TIMER_END\b.*?\bpassTime=(\d+)")


_DAY_MS = 24 * 60 * 60 * 1000


_IDLE_SPLIT_MS = 30_000


_POST_TIMER_TAIL_MS = 10_000


def _parse_line_timestamp_ms(line: str) -> tuple[int, str] | None:
    match = _TIMESTAMP_RE.match(line)
    if not match:
        return None
    hours, minutes, seconds, millis = (int(part) for part in match.groups())
    relative_ms = (((hours * 60) + minutes) * 60 + seconds) * 1000 + millis
    hint = f"{hours:02d}-{minutes:02d}-{seconds:02d}-{millis:03d}"
    return relative_ms, hint


def _find_line_index_for_abs(records: list[dict], target_abs_ms: int) -> int:
    for record in records:
        if record["abs_ts_ms"] >= target_abs_ms:
            return int(record["line_index"])
    return int(records[-1]["line_index"]) if records else 0


def _parse_game_timer_end_elapsed_ms(line: str) -> int | None:
    match = _GAME_TIMER_END_ELAPSED_RE.search(line)
    if not match:
        return None
    try:
        elapsed_ms = int(match.group(1))
        sane = int(match.group(2))
    except ValueError:
        return None
    if not sane or elapsed_ms <= 0:
        return None
    return elapsed_ms


def _parse_official_timer_end_elapsed_ms(line: str) -> int | None:
    match = _OFFICIAL_TIMER_END_ELAPSED_RE.search(line)
    if not match:
        return None
    try:
        elapsed_ms = int(match.group(1))
    except ValueError:
        return None
    return elapsed_ms if elapsed_ms > 0 else None


def _parse_timer_end_elapsed_ms(line: str) -> int | None:
    return _parse_official_timer_end_elapsed_ms(line) or _parse_game_timer_end_elapsed_ms(line)


def _is_loadout_context_line(line: str) -> bool:
    return " LOADOUT slot=" in line or "LOADOUT slot=" in line or " LOADOUT_STATS " in line or "LOADOUT_STATS " in line


def _find_loadout_context_start_line(lines: list[str], *, start_line: int, min_line: int) -> int | None:
    last_loadout_line: int | None = None
    for index in range(start_line, min_line - 1, -1):
        if _is_loadout_context_line(lines[index]):
            last_loadout_line = index
            break
    if last_loadout_line is None:
        return None

    block_start = last_loadout_line
    for index in range(last_loadout_line - 1, min_line - 1, -1):
        if _is_loadout_context_line(lines[index]):
            block_start = index
            continue
        if lines[index].strip() == "":
            continue
        break
    return block_start


def _find_context_start_line(records: list[dict], *, start_line: int, min_line: int, lines: list[str] | None = None) -> int:
    context_records = [
        record
        for record in records
        if record["is_dungeon_context"] and min_line <= int(record["line_index"]) <= start_line
    ]
    context_start = int(context_records[-1]["line_index"]) if context_records else start_line
    if lines is None:
        return context_start
    loadout_start = _find_loadout_context_start_line(lines, start_line=context_start, min_line=min_line)
    return min(context_start, loadout_start) if loadout_start is not None else context_start


def _extend_timer_tail_end_line(
    records: list[dict],
    *,
    timer_end_record: dict,
    next_start_line: int,
    tail_ms: int = _POST_TIMER_TAIL_MS,
) -> int:
    timer_end_line = int(timer_end_record["line_index"])
    timer_end_abs_ms = int(timer_end_record["abs_ts_ms"])
    end_line = timer_end_line
    for record in records:
        line_index = int(record["line_index"])
        if line_index <= timer_end_line:
            continue
        if line_index >= next_start_line:
            break
        if int(record["abs_ts_ms"]) - timer_end_abs_ms > tail_ms:
            break
        if (
            record["is_hit"]
            or record["is_dungeon_context"]
            or record["is_official_timer_start"]
            or record["is_game_timer_start"]
        ):
            break
        end_line = line_index
    return end_line


def _merged_timer_start_records(records: list[dict]) -> list[dict]:
    # Packet battle-state cycles are phases while an explicit official
    # challenge remains open. Never merge starts by elapsed-time proximity.
    merged = []
    active_official = None
    active_packet = None
    for record in records:
        if record.get('is_boundary') and (
                active_official is None or record.get('game_id') in (None, '', active_official[0])):
            active_official = None
            active_packet = None
        if record['is_official_timer_start']:
            identity = (record.get('game_id'), record.get('challenge_start_ts'))
            if (active_official is not None and identity[1] not in (None, '', '0')
                    and identity == active_official):
                continue
            active_official = identity
            active_packet = None
            merged.append(record)
        elif record['is_official_timer_end']:
            if active_official is not None and record.get('game_id') == active_official[0]:
                active_official = None
                active_packet = None
        elif record['is_game_timer_start']:
            if active_official is not None:
                continue
            identity = (record.get('timer_source'), record.get('timer_start_tick'))
            if identity[1] is not None and identity == active_packet:
                continue
            active_packet = identity
            merged.append(record)
        elif record['is_game_timer_end']:
            active_packet = None
    return merged


def _split_trace_into_battles(raw_content: str, *, idle_split_ms: int = _IDLE_SPLIT_MS) -> list[dict]:
    lines = raw_content.splitlines(keepends=True)
    timestamped_records: list[dict] = []
    hit_records: list[dict] = []
    clock_origin_ms: int | None = None

    for index, line in enumerate(lines):
        parsed = _parse_line_timestamp_ms(line)
        if parsed is None:
            continue
        relative_ms, hint = parsed
        # Fixed time-of-day coordinates; a late observation is not a new day.
        # Official challenge segmentation below uses explicit event order.
        if clock_origin_ms is None:
            clock_origin_ms = relative_ms
        absolute_ms = clock_origin_ms + (relative_ms - clock_origin_ms) % _DAY_MS
        timer_fields = _extract_fields(line) if any(token in line for token in ("TIMER", "GAME_INST_")) else {}
        record = {
            "line_index": index,
            "game_id": timer_fields.get("gameId"),
            "challenge_start_ts": timer_fields.get("challengeStartTs"),
            "timer_source": timer_fields.get("source"),
            "timer_start_tick": timer_fields.get("startMs"),
            "is_boundary": any(token in line for token in ("GAME_TIMER_RESET ", "GAME_INST_RESTART ", "GAME_INST_LEAVE ")),
            "abs_ts_ms": absolute_ms,
            "hint": hint,
            "is_hit": " HP_V2 " in line,
            "is_dungeon_context": "DUNGEON_CONTEXT" in line,
            "is_official_timer_start": "OFFICIAL_TIMER_START" in line,
            "is_game_timer_start": "GAME_TIMER_START" in line,
            "is_official_timer_end": "OFFICIAL_TIMER_END" in line,
            "is_game_timer_end": "GAME_TIMER_END" in line,
            "is_timer_end": "OFFICIAL_TIMER_END" in line or "GAME_TIMER_END" in line,
            "timer_elapsed_ms": _parse_timer_end_elapsed_ms(line),
        }
        timestamped_records.append(record)
        if record["is_hit"]:
            hit_records.append(record)

    if not hit_records:
        raise ValueError("未在日志中识别到可用 battle。")

    timer_start_records = _merged_timer_start_records(timestamped_records)
    if timer_start_records:
        segments: list[dict] = []
        for timer_index, start_record in enumerate(timer_start_records):
            marker_start_line = int(start_record["line_index"])
            min_start_line = (
                int(timer_start_records[timer_index - 1]["line_index"]) + 1
                if timer_index > 0
                else 0
            )
            previous_timer_end_line = max(
                (
                    int(record["line_index"])
                    for record in timestamped_records
                    if record["is_timer_end"] and int(record["line_index"]) < marker_start_line
                ),
                default=-1,
            )
            min_start_line = max(min_start_line, previous_timer_end_line + 1)
            start_line = _find_context_start_line(
                timestamped_records,
                start_line=marker_start_line,
                min_line=min_start_line,
                lines=lines,
            )
            next_start_line = (
                int(timer_start_records[timer_index + 1]["line_index"])
                if timer_index + 1 < len(timer_start_records)
                else len(lines)
            )
            if start_record["is_official_timer_start"]:
                timer_end_record = next(
                    (
                        record
                        for record in timestamped_records
                        if record["is_official_timer_end"]
                        and record.get("game_id") == start_record.get("game_id")
                        and marker_start_line <= int(record["line_index"]) < next_start_line
                    ),
                    None,
                )
                if timer_end_record is None:
                    timer_end_record = next(
                        (record for record in timestamped_records
                         if record.get('is_boundary')
                         and record.get('game_id') in (None, '', start_record.get('game_id'))
                         and marker_start_line < int(record['line_index']) < next_start_line),
                        None,
                    )
            else:
                timer_end_record = next(
                    (
                        record
                        for record in timestamped_records
                        if record["is_timer_end"]
                        and marker_start_line <= int(record["line_index"]) < next_start_line
                    ),
                    None,
                )
            if timer_end_record is not None:
                hit_end_line = int(timer_end_record["line_index"])
                end_line = _extend_timer_tail_end_line(
                    timestamped_records,
                    timer_end_record=timer_end_record,
                    next_start_line=next_start_line,
                )
            else:
                end_line = next_start_line - 1
                hit_end_line = end_line
            battle_hits = [
                record
                for record in hit_records
                if marker_start_line <= int(record["line_index"]) <= hit_end_line
            ]
            if not battle_hits:
                continue
            content = "".join(lines[start_line : end_line + 1]).strip()
            if not content:
                continue
            segments.append(
                {
                    "battle_index": len(segments) + 1,
                    "start_line_index": start_line,
                    "content": content,
                    "first_hit_hint": str(battle_hits[0]["hint"]),
                    "last_hit_hint": str(battle_hits[-1]["hint"]),
                    "first_hit_line_index": int(battle_hits[0]["line_index"]),
                }
            )
        if segments:
            return segments

    timer_end_records = [
        record
        for record in timestamped_records
        if record["is_timer_end"] and record.get("timer_elapsed_ms")
    ]
    if timer_end_records:
        segments = []
        previous_end_line = -1
        for timer_end_record in timer_end_records:
            if int(timer_end_record["line_index"]) <= previous_end_line:
                continue
            elapsed_ms = int(timer_end_record["timer_elapsed_ms"])
            end_abs_ms = int(timer_end_record["abs_ts_ms"])
            start_abs_ms = max(end_abs_ms - elapsed_ms, 0)
            marker_start_line = max(_find_line_index_for_abs(timestamped_records, start_abs_ms), previous_end_line + 1)
            start_line = _find_context_start_line(
                timestamped_records,
                start_line=marker_start_line,
                min_line=previous_end_line + 1,
                lines=lines,
            )
            end_line = _extend_timer_tail_end_line(
                timestamped_records,
                timer_end_record=timer_end_record,
                next_start_line=len(lines),
            )
            battle_hits = [
                record
                for record in hit_records
                if start_line <= int(record["line_index"]) <= end_line
                and start_abs_ms <= int(record["abs_ts_ms"]) <= end_abs_ms
            ]
            if not battle_hits:
                previous_end_line = max(previous_end_line, end_line)
                continue
            content = "".join(lines[start_line : end_line + 1]).strip()
            if not content:
                previous_end_line = max(previous_end_line, end_line)
                continue
            segments.append(
                {
                    "battle_index": len(segments) + 1,
                    "start_line_index": start_line,
                    "content": content,
                    "first_hit_hint": str(battle_hits[0]["hint"]),
                    "last_hit_hint": str(battle_hits[-1]["hint"]),
                    "first_hit_line_index": int(battle_hits[0]["line_index"]),
                }
            )
            previous_end_line = max(previous_end_line, end_line)
        if segments:
            return segments

    battle_hit_spans: list[tuple[int, int]] = []
    span_start = 0
    for index in range(1, len(hit_records)):
        if hit_records[index]["abs_ts_ms"] - hit_records[index - 1]["abs_ts_ms"] > idle_split_ms:
            battle_hit_spans.append((span_start, index - 1))
            span_start = index
    battle_hit_spans.append((span_start, len(hit_records) - 1))

    segment_start_lines: list[int] = []
    for hit_span_start, _ in battle_hit_spans:
        first_hit = hit_records[hit_span_start]
        start_abs_ms = max(int(first_hit["abs_ts_ms"]) - idle_split_ms, 0)
        segment_start_lines.append(_find_line_index_for_abs(timestamped_records, start_abs_ms))

    segments: list[dict] = []
    for segment_index, (hit_span_start, hit_span_end) in enumerate(battle_hit_spans):
        first_hit = hit_records[hit_span_start]
        last_hit = hit_records[hit_span_end]
        start_line = segment_start_lines[segment_index]
        if segment_index + 1 < len(segment_start_lines):
            end_line = max(segment_start_lines[segment_index + 1] - 1, start_line)
        else:
            end_line = len(lines) - 1
        content = "".join(lines[start_line : end_line + 1]).strip()
        if not content:
            continue
        segments.append(
            {
                "battle_index": segment_index + 1,
                "start_line_index": start_line,
                "content": content,
                "first_hit_hint": str(first_hit["hint"]),
                "last_hit_hint": str(last_hit["hint"]),
                "first_hit_line_index": int(first_hit["line_index"]),
            }
        )
    return segments

split_trace_battles = _split_trace_into_battles
