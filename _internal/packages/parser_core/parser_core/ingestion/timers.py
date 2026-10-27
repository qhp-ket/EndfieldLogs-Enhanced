"""Ordered official and compatibility timer observations."""
from __future__ import annotations

from parser_core.ingestion.fields import _coerce_int, _extract_fields, _parse_contract_tag_ids
from parser_core.ingestion.state import IngestionState
from typing import Any
import re


_GAME_TIMER_END_RE = re.compile(r"\bGAME_TIMER_END\b")

_GAME_TIMER_START_RE = re.compile(r"\bGAME_TIMER_START\b")

_LIVE_TIMER_TICK_RE = re.compile(r"\bLIVE_TIMER_TICK\b")

_OFFICIAL_TIMER_END_RE = re.compile(r"\bOFFICIAL_TIMER_END\b")

_OFFICIAL_TIMER_START_RE = re.compile(r"\bOFFICIAL_TIMER_START\b")

def consume_timer_observation(ingestion: IngestionState, raw_line: str, line_no: int, ts_ms: int) -> bool:
    if _OFFICIAL_TIMER_START_RE.search(raw_line):
        fields = _extract_fields(raw_line)
        ingestion.set_dungeon_context(fields.get("gameId") or fields.get("game_id"))
        # A new explicit challenge start opens a new timer scope. A prior
        # attempt's completion and elapsed time cannot certify this one.
        ingestion.official_timer_elapsed_ms = None
        ingestion.official_timer_end_ms = None
        ingestion.live_timer_elapsed_ms = None
        ingestion.game_timer_end_ms = None
        ingestion.game_timer_elapsed_ms = None
        ingestion.game_timer_window_elapsed_ms = None
        ingestion.packet_timer_elapsed_ms = None
        ingestion.timer_end_seen = False
        ingestion.timer_window_valid = True
        ingestion.challenge_pass_confirmed = False
        ingestion.official_pass_confirmed = False
        ingestion.completion_source = ""
        ingestion.official_timer_start_ms = ts_ms
        ingestion.game_timer_start_ms = ts_ms
        ingestion.timer_start_seen = True
        return True

    if _LIVE_TIMER_TICK_RE.search(raw_line):
        fields = _extract_fields(raw_line)
        elapsed_ms = _coerce_int(fields.get("elapsedMs"), default=0)
        if elapsed_ms > 0:
            ingestion.live_timer_elapsed_ms = elapsed_ms
            ingestion.game_timer_end_ms = ts_ms
            ingestion.game_timer_elapsed_ms = elapsed_ms
            ingestion.game_timer_window_elapsed_ms = elapsed_ms
        return True

    if _OFFICIAL_TIMER_END_RE.search(raw_line):
        fields = _extract_fields(raw_line)
        ingestion.set_dungeon_context(fields.get("gameId") or fields.get("game_id"))
        ingestion.official_timer_end_ms = ts_ms
        if _coerce_int(fields.get("isPass"), default=0) == 1:
            ingestion.challenge_pass_confirmed = True
            ingestion.official_pass_confirmed = True
            ingestion.completion_source = "official_timer_end"
        pass_time_ms = _coerce_int(fields.get("passTime"), default=0)
        if pass_time_ms > 0:
            ingestion.game_timer_end_ms = ts_ms
            ingestion.game_timer_elapsed_ms = pass_time_ms
            ingestion.game_timer_window_elapsed_ms = pass_time_ms
            ingestion.official_timer_elapsed_ms = pass_time_ms
            ingestion.timer_end_seen = True
        return True

    if _GAME_TIMER_START_RE.search(raw_line):
        fields = _extract_fields(raw_line)
        start_ms = _coerce_int(fields.get("startMs"), default=0)
        if ingestion.official_timer_start_ms is None and _timer_is_authoritative(fields) and start_ms >= 0:
            ingestion.game_timer_start_ms = ts_ms
            ingestion.timer_start_seen = True
        return True

    if _GAME_TIMER_END_RE.search(raw_line):
        fields = _extract_fields(raw_line)
        timer_is_authoritative = _timer_is_authoritative(fields)
        if timer_is_authoritative and _coerce_int(fields.get("isPass"), default=0) == 1:
            ingestion.challenge_pass_confirmed = True
            ingestion.completion_source = str(fields.get("source") or "game_timer_end")
        elapsed_ms = _coerce_int(fields.get("elapsedMs"), default=0)
        wall_elapsed_ms = _coerce_int(fields.get("wallElapsedMs"), default=0)
        packet_elapsed_ms = _coerce_int(fields.get("packetElapsedMs"), default=0)
        if packet_elapsed_ms > 0:
            ingestion.packet_timer_elapsed_ms = packet_elapsed_ms
        sane = _coerce_int(fields.get("sane"), default=1)
        if (
            ingestion.official_timer_elapsed_ms is None
            and timer_is_authoritative
            and sane
            and elapsed_ms > 0
        ):
            ingestion.game_timer_end_ms = ts_ms
            ingestion.game_timer_elapsed_ms = wall_elapsed_ms if wall_elapsed_ms > 0 else elapsed_ms
            ingestion.game_timer_window_elapsed_ms = ingestion.game_timer_elapsed_ms
            ingestion.timer_end_seen = True
        return True
    return False


def _timer_is_authoritative(fields: dict[str, Any]) -> bool:
    if _coerce_int(fields.get("fallback"), default=0) != 0:
        return False
    if str(fields.get("source") or "").endswith("Fallback"):
        return False
    if "official" in fields:
        return _coerce_int(fields.get("official"), default=1) != 0
    return str(fields.get("source") or "") != "BattleOpModifyBattleState"


def consume_stage_context(ingestion: IngestionState, raw_line: str, line_no: int, ts_ms: int) -> bool:
    if " DUNGEON_CONTEXT " in raw_line:
        fields = _extract_fields(raw_line)
        ingestion.set_dungeon_context(fields.get("dungeonId") or fields.get("dungeon_id"))
        return True

    if " BATTLE_RESULT " in raw_line:
        fields = _extract_fields(raw_line)
        ingestion.set_dungeon_context(fields.get("dungeonId") or fields.get("dungeon_id"))
        if _coerce_int(fields.get("isPass"), default=0) == 1:
            ingestion.challenge_pass_confirmed = True
            ingestion.completion_source = str(fields.get("source") or "battle_result")
        return True

    if " CONTRACT_TAGS " in raw_line:
        fields = _extract_fields(raw_line)
        ingestion.set_dungeon_context(fields.get("dungeonId") or fields.get("dungeon_id"))
        parsed_tag_ids = _parse_contract_tag_ids(fields.get("tagIds") or fields.get("tag_ids"))
        if parsed_tag_ids:
            ingestion.contract_tag_ids = parsed_tag_ids
        if fields.get("score") is not None:
            ingestion.contract_tag_score = _coerce_int(fields.get("score"), default=0)
        return True
    return False
