"""Build battle effect windows from exact observed sources and approved specifications."""
from __future__ import annotations

from parser_core.catalog.buff_templates import _load_current_buff_roots
from parser_core.effects.classification import _equip_buff_matches_active_suits
from parser_core.effects.classification import _weapon_buff_matches_active_weapon
from parser_core.effects.imbue import _build_special_combo_windows
from parser_core.effects.labels import _collect_buff_labels
from parser_core.effects.lifecycle import _buff_record_end_ts_ms
from parser_core.effects.packet_mapping import _packet_mapping_stack_limit
from parser_core.effects.registry import _rdps_registry_stack_limit
from parser_core.effects.specifications import _collect_zone_effects
from parser_core.effects.specifications import _extract_dynamic_effect_specs
from parser_core.effects.stacking_rules import _buff_stack_limit
from parser_core.effects.windows import _apply_buff_stack_limits
from parser_core.effects.windows import _dedupe_mirrored_buff_windows
from parser_core.effects.windows import _merge_buff_windows
from parser_core.reporting.state import ReportState
from typing import Any
import copy


def prepare_effect_windows(report_state: ReportState, static_arts_strength_by_char: dict[str, float], last_hit_ms: int) -> list[dict[str, Any]]:
    """Build battle effect windows from exact observed sources and approved specifications."""
    buff_windows = []
    for buff_record in report_state.buff_starts:
        if buff_record.get("uid_observation_only"):
            continue
        labels = _collect_buff_labels(buff_record, root_lookup_cache=report_state.buff_root_action_indices)
        zone_effects = _collect_zone_effects(buff_record, root_lookup_cache=report_state.buff_root_action_indices)
        dynamic_effects = _extract_dynamic_effect_specs(buff_record, root_lookup_cache=report_state.buff_root_action_indices)
        if not zone_effects and not dynamic_effects:
            continue
        if not _equip_buff_matches_active_suits(
            buff_record.get("event_key"),
            buff_record.get("source_character_key"),
            report_state.active_suits_by_char,
        ):
            continue
        if not _weapon_buff_matches_active_weapon(
            buff_record.get("event_key"),
            buff_record.get("source_character_key"),
            report_state.active_weapons_by_char,
        ):
            continue
        start_ts_ms = buff_record["ts_ms"]
        window_end_ms = _buff_record_end_ts_ms(buff_record, last_hit_ms)
        end_line_no = None
        if buff_record.get('snapshot_end_ts_ms') == window_end_ms:
            end_line_no = buff_record.get('snapshot_end_line_no')
        elif buff_record.get('end_ts_ms') == window_end_ms:
            end_line_no = buff_record.get('end_line_no')
        buff_windows.append(
            {
                "start_ts_ms": start_ts_ms,
                "start_line_no": buff_record.get("line_no"),
                "end_ts_ms": window_end_ms,
                "end_line_no": end_line_no,
                "duration_ms": max(0, window_end_ms - start_ts_ms),
                "snapshot_end_ts_ms": buff_record.get('snapshot_end_ts_ms'),
                "snapshot_end_line_no": buff_record.get('snapshot_end_line_no'),
                "snapshot_update": bool(buff_record.get('snapshot_update')),
                "lifetime_mode": buff_record.get('lifetime_mode'),
                "lifetime_source": buff_record.get('lifetime_source'),
                "end_is_observation_boundary": buff_record.get('end_ts_ms') is None and buff_record.get('snapshot_end_ts_ms') is None and buff_record.get('lifetime_mode') == 'Infinity',
                "uid": buff_record.get("uid"),
                "uid_aliases": [],
                "source_character_key": buff_record["source_character_key"],
                "source_character_name": buff_record["source_character_name"],
                "source_static_arts_strength": static_arts_strength_by_char.get(
                    str(buff_record.get("source_character_key") or ""),
                    0.0,
                ),
                "source_skill_key": buff_record.get("source_skill_key"),
                "source_skill_family_key": buff_record.get("source_skill_family_key"),
                "raw_source_character_key": buff_record.get("raw_source_character_key"),
                "raw_source_character_name": buff_record.get("raw_source_character_name"),
                "raw_source": buff_record.get("raw_source"),
                "target_character_key": buff_record["target_character_key"] or buff_record["target_enemy_key"],
                "target_character_name": buff_record["target_character_name"] or buff_record["target_enemy_name"],
                "target_player_key": buff_record["target_character_key"],
                "target_enemy_key": buff_record["target_enemy_key"],
                "owner_raw": buff_record.get("owner_raw"),
                "target_actor_id": buff_record.get("target_actor_id"),
                "source_actor_id": buff_record.get("source_actor_id"),
                "source_weapon_template": buff_record.get("source_weapon_template"),
                "event_key": buff_record["event_key"],
                "event_name": " / ".join(labels) if labels else buff_record["event_key"],
                "bb_values": copy.deepcopy(buff_record.get('bb_values') or {}),
                "zone_effects": zone_effects,
                "dynamic_effects": dynamic_effects,
                "requires_enable_observation": (
                    ((_load_current_buff_roots().get(buff_record['event_key']) or {}).get('stackingSettings') or {})
                    .get('stackingType') in {'HighPriority', 'HighPriorityWithMaxStack'}
                ),
                "modifier_count": len(buff_record.get("attr_mods") or []),
                "enable_observations": copy.deepcopy(buff_record.get('enable_observations') or []),
                "rdps_conflicting_enable_state": bool(buff_record.get('rdps_conflicting_enable_state')),
                "skill_family_key": None,
                "stack_limit": (
                    _packet_mapping_stack_limit(buff_record)
                    or _rdps_registry_stack_limit(buff_record)
                    or _buff_stack_limit(buff_record["event_key"], buff_record.get('bb_values'))
                ),
            }
        )
    buff_windows = _dedupe_mirrored_buff_windows(_merge_buff_windows(buff_windows))
    buff_windows.extend(_build_special_combo_windows(report_state.hits, report_state.buff_starts, battle_end_ms=last_hit_ms))
    buff_windows = _dedupe_mirrored_buff_windows(_merge_buff_windows(buff_windows))
    buff_windows = _apply_buff_stack_limits(buff_windows)
    return buff_windows
