"""Project damage events and exact observed cast intervals onto battle coordinates."""
from __future__ import annotations

from parser_core.catalog.names import _resolve_character_name
from parser_core.reporting.skill_stats import _build_cast_start_index
from parser_core.reporting.skill_stats import _matching_cast_for_hit
from parser_core.reporting.state import ReportState
from parser_core.reporting.window import BattleTimeline
from typing import Any

from parser_core.catalog.names import _resolve_skill_name
from parser_core.ingestion.skill_identity import _canonical_num_table_skill_id
from parser_core.ingestion.skills import _is_generic_runtime_skill_id
import re

from collections import defaultdict
import bisect

from parser_core.catalog.buff_templates import _load_current_buff_roots
from parser_core.effects.evaluation import _window_effects_at_ts


def build_hit_events(report_state: ReportState, timeline: BattleTimeline) -> list[dict[str, Any]]:
    """Project damage events and exact observed cast intervals onto battle coordinates."""
    battle_offset_ms = timeline.offset_ms
    battle_offset_ms_unclamped = timeline.offset_ms_unclamped
    cast_start_index = _build_cast_start_index(report_state.skill_casts)

    timeline_events = []
    for hit in report_state.hits:
        matching_cast = _matching_cast_for_hit(hit, cast_start_index)
        actual_start_ms = int(matching_cast["ts_ms"]) if matching_cast is not None else None
        actual_end_ms = (
            int(matching_cast["end_ts_ms"])
            if matching_cast is not None and matching_cast.get("end_ts_ms") is not None
            else None
        )
        timeline_events.append(
            {
                "ts_ms_from_start": battle_offset_ms(hit["ts_ms"]),
                "lane_type": "skill",
                "source_character_key": hit["character_key"],
                "source_character_name": hit["character_name"],
                "target_character_key": hit["target_enemy_key"],
                "target_character_name": hit["target_enemy_name"],
                "event_type": "damage",
                "event_key": hit.get("skill_family_key") or hit["skill_key"],
                "event_group_key": hit.get("timeline_group_key"),
                "event_name": hit["skill_name"],
                "value": hit["hit_value"],
                "damage_element": hit.get("damage_element"),
                "damage_school": hit.get("damage_school"),
                "value_source": hit.get("damage_value_source"),
                "packet_hit_value": hit.get("packet_hit_value"),
                "packet_raw_value": hit.get("packet_raw_value"),
                "packet_final_value": hit.get("packet_final_value"),
                "overkill_damage": hit.get("overkill_damage"),
                "rdps_basis_value": hit.get("rdps_basis_value"),
                "rdps_basis_source": hit.get("rdps_basis_source"),
                "rdps_contributions": [
                    {
                        "character_key": character_key,
                        "character_name": _resolve_character_name(character_key) or character_key,
                        "value": round(value, 4),
                    }
                    for character_key, value in sorted((hit.get("rdps_contributions") or {}).items())
                ],
                "packet_modifier_uids": hit.get("packet_modifier_uids") or {"attacker": [], "defender": []},
                "packet_attr_details": hit.get("packet_attr_details") or {"attacker": [], "defender": []},
                # Evidence-only projection for local analysis. Entity snapshots
                # are observations, not a reconstructed hit-time resistance.
                "packet_attr_conflict": bool(hit.get("packet_attr_conflict")),
                "target_actor_id": hit.get("target_actor_id"),
                "target_entity": {key: hit[key] for key in (
                    "target_defense", "target_defense_source", "target_resistance_points",
                    "target_resistance_points_source", "target_resistance_scalars", "target_resistance_source",
                    "target_stats_snapshot_ts_ms", "target_stats_snapshot_line_no", "target_stats_invalid_attr_types",
                ) if key in hit},
                "poise_damage": hit.get("poise_damage"),
                "hit_context": {"critical": hit["critical_context"]},
                "duration_ms": None,
                "actual_start_ms_from_start": (
                    battle_offset_ms_unclamped(actual_start_ms) if actual_start_ms is not None else None
                ),
                "actual_end_ms_from_start": (
                    battle_offset_ms_unclamped(actual_end_ms) if actual_end_ms is not None else None
                ),
                "actual_duration_ms": (
                    max(actual_end_ms - actual_start_ms, 1)
                    if actual_start_ms is not None and actual_end_ms is not None
                    else None
                ),
                "important": True,
            }
        )
    return timeline_events


def append_non_damage_casts(report_state: ReportState, timeline: BattleTimeline, participants: list[dict[str, Any]], timeline_events: list[dict[str, Any]]) -> set[str]:
    """Retain resolved zero-damage skill casts that have no damage event in this battle."""
    first_hit_ms, last_hit_ms = timeline.start_ms, timeline.end_ms
    battle_offset_ms = timeline.offset_ms
    damaging_skill_keys = {
        (hit["character_key"], str(key))
        for hit in report_state.hits
        for key in (hit.get("skill_family_key"), hit.get("skill_key"))
        if key
    }
    participant_keys = {participant["character_key"] for participant in participants}
    last_cast_emit_ms: dict[tuple[str, str], int] = {}
    for cast in sorted(report_state.skill_casts, key=lambda item: int(item["ts_ms"])):
        cast_skill = str(cast.get("skill") or "")
        cast_character_key = cast.get("source_character_key")
        if not cast_character_key or cast_character_key not in participant_keys or not cast_skill:
            continue
        if _is_generic_runtime_skill_id(cast_skill) or re.fullmatch(r".*_skill_\d+", cast_skill):
            # 运行时兜底 id（chr_xxx_skill_100901）：尝试 num 表反解析成真实技能，失败则放弃。
            canonical_skill = _canonical_num_table_skill_id(cast_skill, cast_character_key)
            if not canonical_skill:
                continue
            cast_skill = canonical_skill
        # 归一到技能族：施放会连带范围/位移/派生等子实体（xxx_ultimate_skill_abilityrange），
        # 统一收敛为族名后再判定，避免子实体刷屏、也保证与伤害命中的 family key 对得上。
        family_match = re.match(r"^(.*?_(?:ultimate_skill|normal_skill|combo_skill))", cast_skill)
        if not family_match:
            continue
        cast_skill = family_match.group(1)
        if (cast_character_key, cast_skill) in damaging_skill_keys:
            continue
        cast_ts_ms = int(cast["ts_ms"])
        if cast_ts_ms < first_hit_ms or cast_ts_ms > last_hit_ms:
            continue
        emit_key = (str(cast_character_key), cast_skill)
        last_emit_ms = last_cast_emit_ms.get(emit_key)
        if last_emit_ms is not None and cast_ts_ms - last_emit_ms < 3000:
            continue
        last_cast_emit_ms[emit_key] = cast_ts_ms
        timeline_events.append(
            {
                "ts_ms_from_start": battle_offset_ms(cast_ts_ms),
                "lane_type": "skill",
                "source_character_key": cast_character_key,
                "source_character_name": _resolve_character_name(cast_character_key) or cast_character_key,
                "target_character_key": None,
                "target_character_name": None,
                "event_type": "cast",
                "event_key": cast_skill,
                "event_group_key": None,
                "event_name": _resolve_skill_name(cast_skill) or cast_skill,
                "value": None,
                "damage_element": None,
                "damage_school": None,
                "value_source": None,
                "packet_hit_value": None,
                "packet_raw_value": None,
                "packet_final_value": None,
                "overkill_damage": None,
                "rdps_basis_value": None,
                "rdps_basis_source": None,
                "rdps_contributions": [],
                "packet_modifier_uids": {"attacker": [], "defender": []},
                "packet_attr_details": {"attacker": [], "defender": []},
                "poise_damage": None,
                "duration_ms": None,
                "important": True,
            }
        )
    return participant_keys


def export_casts(report_state: ReportState, timeline: BattleTimeline, participant_keys: set[str]) -> list[dict[str, Any]]:
    """Export observed casts and attach energy gains to the nearest eligible predecessor."""
    first_hit_ms, last_hit_ms = timeline.start_ms, timeline.end_ms
    battle_offset_ms_unclamped = timeline.offset_ms_unclamped
    casts_export: list[dict[str, Any]] = []
    _CAST_EXPORT_NOISE_RE = re.compile(
        r"(_projhit|_abilityrange|_abilityentity|_absorb|_indicator|_blocked|_listener|_aura|_marker)"
    )
    # 技力归属（v34+）：一次技力增加(ATB_UPDATE AddValue)归属到它「之前最近」的同角色施放
    # = 真正触发回技力的那一次(主控重击=连招末段)。若用前向窗口从每个施放往后看，连招
    # 前几段(A1~A4)会把末段(A5)的回技力抢标。先收集(施放起点ms, casts_export下标)，全部
    # 建完后按「gain 归最近前驱 cast」一次性回填 recovers_energy。
    _ATB_RECOVER_WINDOW_MS = 1500
    cast_starts_by_char: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for cast in sorted(report_state.skill_casts, key=lambda item: int(item["ts_ms"])):
        cast_skill = str(cast.get("skill") or "")
        cast_character_key = cast.get("source_character_key")
        if not cast_character_key or cast_character_key not in participant_keys or not cast_skill:
            continue
        if _is_generic_runtime_skill_id(cast_skill) or re.fullmatch(r".*_skill_\d+", cast_skill):
            canonical_skill = _canonical_num_table_skill_id(cast_skill, cast_character_key)
            if not canonical_skill:
                continue
            cast_skill = canonical_skill
        if _CAST_EXPORT_NOISE_RE.search(cast_skill):
            continue
        cast_ts_ms = int(cast["ts_ms"])
        if cast_ts_ms < first_hit_ms - 10_000 or cast_ts_ms > last_hit_ms:
            continue
        cast_end_ts_ms = cast.get("end_ts_ms")
        casts_export.append(
            {
                "ts_ms_from_start": battle_offset_ms_unclamped(cast_ts_ms),
                "end_ms_from_start": (
                    battle_offset_ms_unclamped(int(cast_end_ts_ms)) if cast_end_ts_ms is not None else None
                ),
                "character_key": cast_character_key,
                "skill_key": cast_skill,
                "skill_name": _resolve_skill_name(cast_skill) or cast_skill,
                "skill_source": str(cast.get("skill_source") or "") or None,
                "dynamic_bb_events": list(cast.get("dynamic_bb_events") or []),
                # 技力增加归属回填（下方），默认 False；老客户端无 ATB_UPDATE 恒 False。
                "recovers_energy": False,
            }
        )
        cast_starts_by_char[cast_character_key].append((cast_ts_ms, len(casts_export) - 1))

    # 回填：每次技力增加 → 归属到 (gain-窗口, gain] 内最近的前驱同角色施放。
    for atb_char, gains in report_state.atb_gain_ms_by_char.items():
        starts = cast_starts_by_char.get(atb_char)
        if not starts:
            continue
        start_ms_list = [s for s, _ in starts]
        for gain_ms in gains:
            pos = bisect.bisect_right(start_ms_list, gain_ms) - 1
            if pos < 0:
                continue
            cast_start_ms, cast_idx = starts[pos]
            if 0 <= gain_ms - cast_start_ms <= _ATB_RECOVER_WINDOW_MS:
                casts_export[cast_idx]["recovers_energy"] = True
    return casts_export


def append_buff_events(report_state: ReportState, timeline: BattleTimeline, buff_windows: list[dict[str, Any]], timeline_events: list[dict[str, Any]]) -> None:
    """Project BUFF observations with separate visible bounds and recorded lifetimes."""
    first_hit_ms, last_hit_ms = timeline.start_ms, timeline.end_ms
    battle_offset_ms = timeline.offset_ms
    battle_offset_ms_unclamped = timeline.offset_ms_unclamped
    display_buff_records = {
        (str(row.get('uid') or ''), row['event_key'], int(row['ts_ms'])): row
        for row in report_state.buff_starts
    }
    for event in buff_windows:
        actual_start_ms = int(event["start_ts_ms"])
        actual_end_ms = int(event["end_ts_ms"])
        visible_start_ms = max(int(event["start_ts_ms"]), first_hit_ms)
        visible_end_ms = min(int(event["end_ts_ms"]), last_hit_ms)
        if visible_end_ms < visible_start_ms:
            continue
        visible_duration_ms = max(
            battle_offset_ms_unclamped(visible_end_ms) - battle_offset_ms_unclamped(visible_start_ms),
            1,
        )
        # Snapshot boundaries end an observation, not necessarily the BUFF.
        # Keep the recorded lifetime separate for UI countdowns.
        observed = display_buff_records.get((str(event.get('uid') or ''), event['event_key'], actual_start_ms), {})
        expiry = observed.get('end_ts_ms')
        raw_duration = observed.get('raw_duration_ms')
        if expiry is None and raw_duration is not None and raw_duration > 0:
            expiry = actual_start_ms + raw_duration
        timeline_events.append(
            {
                "ts_ms_from_start": battle_offset_ms(visible_start_ms),
                "lane_type": "buff",
                "source_character_key": event["source_character_key"],
                "source_character_name": event["source_character_name"],
                "target_character_key": event["target_character_key"],
                "target_character_name": event["target_character_name"],
                "target_player_key": event.get("target_player_key"),
                "target_enemy_key": event.get("target_enemy_key"),
                "event_type": "buff",
                "event_key": event["event_key"],
                "event_name": event["event_name"],
                # Presentation evidence only; windows and allocation stay unchanged.
                "buff_uid": event.get("uid"),
                "buff_uid_aliases": list(event.get("uid_aliases") or []),
                "buff_enable_observations": [
                    {"at_ms": battle_offset_ms_unclamped(int(row['ts_ms'])),
                     "line_no": row.get('line_no'), "enabled": row['enabled']}
                    for row in event.get('enable_observations') or []
                ],
                "source_actor_id": event.get("source_actor_id"),
                "target_actor_id": event.get("target_actor_id"),
                "stacking_type": event.get("stacking_type") or (
                    (_load_current_buff_roots().get(event["event_key"]) or {}).get("stackingSettings") or {}
                ).get("stackingType"),
                "stack_limit": event.get("stack_limit"),
                "snapshot_update": bool(event.get("snapshot_update")),
                "end_is_observation_boundary": bool(event.get("end_is_observation_boundary")),
                "buff_lifetime": {
                    "expiry_ms_from_start": battle_offset_ms_unclamped(int(expiry)) if expiry is not None else None,
                    "raw_duration_ms": raw_duration,
                    "source": "BUFF_END" if observed.get('end_ts_ms') is not None else "duration" if expiry is not None else "unknown",
                },
                "value": None,
                "rdps_contributions": [],
                "duration_ms": visible_duration_ms,
                "actual_start_ms_from_start": battle_offset_ms_unclamped(actual_start_ms),
                "actual_end_ms_from_start": battle_offset_ms_unclamped(actual_end_ms),
                "actual_duration_ms": max(
                    battle_offset_ms_unclamped(actual_end_ms) - battle_offset_ms_unclamped(actual_start_ms),
                    1,
                ),
                "effects": _window_effects_at_ts(event, visible_start_ms),
                "dynamic_effects": list(event.get("dynamic_effects") or []),
                "important": True,
            }
        )
