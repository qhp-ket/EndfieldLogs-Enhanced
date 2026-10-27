"""Drive one ordered ingestion stream and dispatch evidence without report finalization."""
from __future__ import annotations

from datetime import datetime
from parser_core.ingestion.buff_observations import consume_buff_blackboard
from parser_core.ingestion.buff_observations import consume_buff_observation
from parser_core.ingestion.dynamic_evidence import consume_dynamic_observation
from parser_core.ingestion.entities import consume_entity_observation
from parser_core.ingestion.fields import _parse_hint_timestamp_ms
from parser_core.ingestion.fields import _parse_prefixed_timestamp_ms
from parser_core.ingestion.hits import consume_hit_and_buff_lifecycle
from parser_core.ingestion.identity import _SQUAD_MEMBER_RE
from parser_core.ingestion.identity import _apply_short_actor_aliases
from parser_core.ingestion.identity import _collect_party_actor_ids
from parser_core.ingestion.identity import _infer_context_enemy_hint
from parser_core.ingestion.loadout import consume_character_skills
from parser_core.ingestion.loadout import consume_loadout_group
from parser_core.ingestion.loadout import consume_loadout_snapshot
from parser_core.ingestion.packet_evidence import consume_packet_evidence
from parser_core.ingestion.skills import consume_skill_observation
from parser_core.ingestion.state import IngestionState
from parser_core.ingestion.timers import consume_stage_context
from parser_core.ingestion.timers import consume_timer_observation
from typing import Any


def _raw_battle_ingestion(
    text: str,
    *,
    file_name: str | None = None,
    first_hit_hint: str | None = None,
    last_hit_hint: str | None = None,
    reference_date: date | None = None,
    include_rdps_debug: bool = False,
    loadout_override_by_char: dict[str, dict[str, Any]] | None = None,
    critical_attributes_override_by_actor: dict[str, dict[str, Any]] | None = None,
):
    reference_date = reference_date or datetime.now().astimezone().date()
    text = _apply_short_actor_aliases(text)
    context_enemy_hint = _infer_context_enemy_hint(text)
    trace_identity_inference_seen = " IDENTITY_INFERENCE " in text
    first_hit_hint_ms = _parse_hint_timestamp_ms(first_hit_hint)
    last_hit_hint_ms = _parse_hint_timestamp_ms(last_hit_hint)

    ingestion = IngestionState(
        reference_date=reference_date, first_hit_hint_ms=first_hit_hint_ms,
        last_hit_hint_ms=last_hit_hint_ms, context_enemy_hint=context_enemy_hint,
        trace_identity_inference_seen=trace_identity_inference_seen,
        loadout_override_by_char=loadout_override_by_char,
        critical_attributes_override_by_actor=critical_attributes_override_by_actor,
    )
    while True:
        batch = yield ingestion.snapshot()
        for line_no, raw_line in batch:
            if "GAME_TIMER_RESET source=CAPTURE_SESSION_START" in raw_line:
                ingestion.critical_stats_by_actor.clear()
            ts_ms = _parse_prefixed_timestamp_ms(raw_line)
            if ts_ms is None:
                continue
            # Legacy trace timestamps are time-of-day, not dated instants. Express
            # them in one fixed modulo-24h coordinate system for this segment.
            # Never increment a day on a decreasing observation: late/replayed
            # events must keep the same coordinate. This is not server elapsed
            # time and is never used to validate or reconstruct passTime.
            if ingestion.timestamp_clock_origin is None:
                ingestion.timestamp_clock_origin = ts_ms
            ts_ms = ingestion.timestamp_clock_origin + (ts_ms - ingestion.timestamp_clock_origin) % 86_400_000
            if 'TIMER_' in raw_line or 'GAME_INST_' in raw_line or 'GAME_MECHANICS_TIME_FREEZE' in raw_line:
                ingestion.timer_observed_times[line_no] = ts_ms
            if ingestion.first_context_ms is None:
                ingestion.first_context_ms = ts_ms
            ingestion.last_context_ms = ts_ms
            ingestion.party_actor_ids.update(_collect_party_actor_ids(raw_line))
            if " SQUAD " in raw_line:
                members = [(match.group(2), match.group(1)) for match in _SQUAD_MEMBER_RE.finditer(raw_line)]
                ingestion.squad_actor_keys = dict(members) if len({pair[0] for pair in members}) == len(members) else {}

            if consume_entity_observation(ingestion, raw_line, line_no, ts_ms):
                continue

            if consume_buff_observation(ingestion, raw_line, line_no, ts_ms):
                continue

            if consume_loadout_group(ingestion, raw_line, line_no, ts_ms):
                continue

            if consume_stage_context(ingestion, raw_line, line_no, ts_ms):
                continue

            if consume_loadout_snapshot(ingestion, raw_line, line_no, ts_ms):
                continue

            if consume_timer_observation(ingestion, raw_line, line_no, ts_ms):
                continue

            if consume_skill_observation(ingestion, raw_line, line_no, ts_ms):
                continue

            if consume_character_skills(ingestion, raw_line, line_no, ts_ms):
                continue

            if consume_dynamic_observation(ingestion, raw_line, line_no, ts_ms):
                continue

            if consume_buff_blackboard(ingestion, raw_line, line_no, ts_ms):
                continue

            if consume_packet_evidence(ingestion, raw_line, line_no, ts_ms):
                continue

            if consume_hit_and_buff_lifecycle(ingestion, raw_line, line_no, ts_ms):
                continue
