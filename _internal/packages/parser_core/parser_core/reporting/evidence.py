"""Bind observations only to matching owner, instance, template and lifetime."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from parser_core.catalog.names import _resolve_character_name
from parser_core.constants import UNKNOWN_ENEMY_KEY
from parser_core.effects.lifecycle import _extend_buff_records_from_packet_modifiers
from parser_core.effects.lifecycle import _infer_related_buff_end_times
from parser_core.effects.lifecycle import _resolve_weapon_buff_sources
from parser_core.ingestion.identity import _retarget_unknown_enemy_hits
from parser_core.ingestion.skill_identity import _apply_same_frame_trigger_skill_mappings
from parser_core.reporting.state import ReportState
from parser_core.reporting.totals import _rebuild_hit_totals


def bind_dynamic_observations(
    hits: list[dict[str, Any]], buff_starts: list[dict[str, Any]],
    skill_casts: list[dict[str, Any]], dynamic_bb_events: list[dict[str, Any]],
) -> None:
    """Bind observations only to matching owner, instance, template and lifetime."""
    buff_records_by_instance: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in buff_starts:
        record["dynamic_bb_events"] = []
        uid = str(record.get("uid") or "")
        if uid:
            buff_records_by_instance[uid].append(record)
    for event in dynamic_bb_events:
        stamp = (int(event["ts_ms"]), int(event["line_no"]))
        candidates = [
            record for record in buff_records_by_instance.get(str(event.get("instance_id") or ""), [])
            if event.get("owner_id") and record.get("target_actor_id")
            and str(event["owner_id"]) == str(record["target_actor_id"])
            and event.get("skill_key") == record.get("event_key")
            and stamp >= (int(record["ts_ms"]), int(record["line_no"]))
            and (record.get("end_ts_ms") is None or stamp < (
                int(record["end_ts_ms"]), int(record.get("end_line_no") or 0)))
            and (record.get('snapshot_end_ts_ms') is None or stamp < (
                int(record['snapshot_end_ts_ms']), int(record.get('snapshot_end_line_no') or 0)))
        ]
        if len(candidates) == 1:
            candidates[0]["dynamic_bb_events"].append(event)
        elif len(candidates) > 1:
            event["binding_error"] = "ambiguous_buff_instance"

    # Cast observations require matching owner/instance/template. HP_V2 does
    # not carry the cast instance, so proximity cannot bind these to a hit.
    casts_by_binding = defaultdict(list)
    for cast in skill_casts:
        cast["dynamic_bb_events"] = []
        casts_by_binding[(str(cast.get("owner_id") or ""), cast.get("skill_inst_id"), cast.get("skill"))].append(cast)
    for event in dynamic_bb_events:
        stamp = (int(event["ts_ms"]), int(event["line_no"]))
        candidates = [cast for cast in casts_by_binding.get((str(event.get("owner_id") or ""), event.get("instance_id"), event.get("skill_key")), ())
            if event.get("owner_id") and cast.get("owner_id")
            and str(event["owner_id"]) == str(cast["owner_id"])
            and event.get("instance_id") == cast.get("skill_inst_id")
            and event.get("skill_key") == cast.get("skill")
            and cast.get("end_ts_ms") is not None
            and (int(cast["ts_ms"]), int(cast["line_no"])) <= stamp
            < (int(cast["end_ts_ms"]), int(cast.get("end_line_no") or 0))]
        if len(candidates) == 1:
            candidates[0]["dynamic_bb_events"].append(event)
        elif len(candidates) > 1:
            event["binding_error"] = "ambiguous_skill_instance"
    for hit in hits:
        hit["dynamic_bb_observations"] = []


def prepare_buff_sources(report_state: ReportState, context_enemy_hint: str | None) -> bool:
    """Prepare recorded lifetimes and participant identities in original source order."""
    _extend_buff_records_from_packet_modifiers(report_state.buff_starts, report_state.packet_modifier_last_seen_by_uid)
    _infer_related_buff_end_times(report_state.buff_starts, report_state.skill_casts)
    _apply_same_frame_trigger_skill_mappings(report_state.hits, report_state.buff_starts)
    _resolve_weapon_buff_sources(report_state.buff_starts)
    for buff_record in report_state.buff_starts:
        source_key = buff_record.get("source_character_key")
        if not source_key:
            continue
        if source_key not in report_state.roster_seen:
            report_state.roster_seen.add(source_key)
            report_state.roster_order.append(source_key)
        source_participant = report_state.participant_totals[source_key]
        source_participant["character_key"] = source_key
        source_participant["character_name"] = _resolve_character_name(source_key) or source_key

    known_enemy_keys = {
        enemy_key
        for enemy_key in report_state.enemy_counter
        if enemy_key and enemy_key != UNKNOWN_ENEMY_KEY
    }
    should_retarget_unknown = (
        bool(context_enemy_hint)
        and UNKNOWN_ENEMY_KEY in report_state.enemy_counter
        and (not known_enemy_keys or known_enemy_keys == {context_enemy_hint})
    )
    identity_retargeted = bool(
        should_retarget_unknown
        and _retarget_unknown_enemy_hits(report_state.hits, report_state.buff_starts, context_enemy_hint)
    )
    if identity_retargeted:
        (
            report_state.participant_totals,
            skill_totals,
            report_state.roster_order,
            report_state.roster_seen,
            report_state.enemy_counter,
        ) = _rebuild_hit_totals(report_state.hits, report_state.buff_starts)
    return identity_retargeted
