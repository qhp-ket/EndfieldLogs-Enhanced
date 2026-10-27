from __future__ import annotations

import bisect
import copy
import gzip
import hashlib
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import (
    date,
    datetime,
    time,
    timedelta,
)
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from math import isclose, isfinite, log
from pathlib import Path
from typing import Any

from parser_core.ingestion.state import IngestionState

from parser_core.parser import (
    parse_raw_battle_log_text,
)

from parser_core.reporting.battle import (
    _build_raw_battle_report,
)

from parser_core.ingestion.stream import (
    _raw_battle_ingestion,
)

from parser_core.reporting.hit_details import build_debug_hits

from parser_core.reporting.critical import attach_critical_context

from parser_core.reporting.effect_windows import prepare_effect_windows

from parser_core.reporting.evidence import prepare_buff_sources

from parser_core.effects.lifecycle import (
    _build_buff_record_index,
    _resolve_weapon_buff_sources,
)

from parser_core.effects.labels import (
    _ZONE_BY_LABEL,
    _zone_from_label,
)

from parser_core.ingestion.skill_identity import (
    _apply_same_frame_trigger_skill_mappings,
    _infer_missing_hit_damage_schools,
    _runtime_skill_trigger_chain_mapping,
    _same_frame_trigger_buff_for_runtime_skill,
    _skill_semantically_reaches_buff,
    _trigger_damage_identity_from_buff,
)

from parser_core.effects.windows import (
    _BUFF_MIRROR_DEDUPE_WINDOW_MS,
    _created_child_buff_ids,
    _dynamic_effect_signature,
    _effect_elements_compatible,
    _event_key_parent_of_default_child,
    _mirror_preference_score,
    _parent_window_covers_created_children,
    _parent_window_covers_default_child,
    _parent_window_covers_specific_siblings,
    _same_event_window_signature_matches,
    _static_effect_signature,
    _window_detail_count,
    _window_matches_same_lane,
    _window_static_effect_pairs,
)

from parser_core.ingestion.identity import (
    _retarget_unknown_enemy_hits,
)

from parser_core.effects.enemy_status import (
    _ENEMY_DEFENSE_EFFECT_BB_KEYS,
    _bb_duration_ms_for_enemy_defense_effect,
    _record_has_enemy_defense_effect,
)

from parser_core.allocation.arts_strength import (
    _arts_strength_entry,
)

from parser_core.catalog.resources import (
    _load_character_potential_rows,
)

from parser_core.catalog.dungeons import (
    _high_difficulty_stage_key,
)

from parser_core.effects.damage_types import (
    _ACTION_DAMAGE_TYPE_TO_ELEMENT,
    _BB_KEY_ELEMENT_RE,
    _damage_increase_element_from_bb_key,
    _element_from_text,
    _normalize_action_damage_type,
)

from parser_core.effects.packet_mapping import (
    _CLASSIFIER_ZONE_TO_INTERNAL,
    _classifier_hint_effect_pairs,
    _classifier_zone_to_internal,
    _packet_record_effect_pairs,
)

from parser_core.effects.classification import (
    _equip_buff_matches_active_suits,
    _weapon_buff_matches_active_weapon,
)

from parser_core.ingestion.loadout import (
    _infer_weapon_refine_from_source_skills,
    extract_char_skill_levels_from_text,
)

from parser_core.catalog.names import (
    _char_prefix,
    _derived_skill_id_from_origin_skill,
    _is_runtime_numeric_skill_id,
)

from parser_core.catalog.buff_templates import (
    _related_child_buff_ids,
    _skill_related_buff_ids,
)

from parser_core.allocation.ledger import (
    _compute_rdps_damage_shares,
)

from parser_core.allocation.hit import (
    _allocate_rdps_for_hit,
)

from parser_core.allocation.basis import (
    _build_rdps_damage_basis,
)

from parser_core.allocation.static_loadout import (
    _static_entry_applies_to_hit,
)

from parser_core.allocation.packet_evidence import (
    _active_target_buff_ids_for_hit,
    _dpd_bucket_value_for_zone,
    _matched_packet_defender_effect_signatures,
    _packet_attr_allowed_effects,
    _packet_modifier_guard_signature,
    _window_matches_packet_uids,
)

from parser_core.allocation.arts_strength import (
    _arts_strength_effect_contributors,
)

from parser_core.allocation.debug import (
    _RDPS_DEBUG_ZONE_ORDER,
    _rdps_contribution_rows,
    _rdps_debug_record_applicable_effect,
    _rdps_debug_record_arts_effect_provenance,
    _rdps_debug_record_baseline_self,
    _rdps_debug_record_dpd_self_residual,
    _rdps_debug_record_static_self,
    _sort_rdps_debug_zones,
)

from parser_core.allocation.preflight import (
    _build_rdps_preflight,
    _known_non_rdps_buff_record,
    _record_could_affect_external_rdps,
    _record_overlaps_window,
)

from parser_core.reporting.buffs import (
    _buff_window_identity,
    _build_buff_events,
    _effect_segments_for_event,
    _effect_summary_rows,
    _packet_buff_semantic_candidates,
)

from parser_core.effects.imbue import (
    _build_special_combo_windows,
)

from parser_core.effects.combo import (
    _COMBO_CONSUME_MAX_WINDOW_MS,
    _COMBO_TOTAL_RATES_BY_GROUP_TYPE,
    _COMBO_TRIGGER_GROUP_WINDOW_MS,
    _GENERIC_COMBO_IMBUE_BUFF_IDS,
    _HIDDEN_COMBO_RULES,
    _build_combo_consume_windows,
    _build_hidden_combo_windows,
    _combo_marginal_layer_rates,
    _matches_hidden_combo_rule,
    _resolve_combo_consume_context,
)

from parser_core.effects.windows import (
    _apply_buff_stack_limits,
    _dedupe_mirrored_buff_windows,
    _merge_buff_windows,
)

from parser_core.effects.lifecycle import (
    _RELATED_BUFF_LIFECYCLE_START_TOLERANCE_MS,
    _buff_record_end_ts_ms,
    _buff_record_lifecycle_lane_matches,
    _buff_record_lifecycle_target_key,
    _buff_record_static_effect_pairs,
    _buff_records_have_matching_lifecycle_effects,
    _buff_records_lifecycle_related,
    _buff_semantically_reaches_buff,
    _extend_buff_records_from_packet_modifiers,
    _infer_related_buff_end_times,
    _is_canonical_packet_buff_key,
    _normalize_buff_duration_ms,
    _prefer_packet_buff_record,
    _record_has_authoritative_bb_duration,
)

from parser_core.effects.labels import (
    _ATTR_TYPE_BUFF_LABELS,
    _BUFF_EFFECT_BB_KEY_IGNORE_BY_ID,
    _BUFF_LABEL_PRIORITY,
    _BUFF_NOISE_BB_KEYS,
    _DEF_DECREASE_BASE_KEYS,
    _EFFECT_ZONE_LABELS,
    _FRAGILE_ATTR_TYPES,
    _GENERIC_COMBO_TRIGGER_BUFF_ID,
    _add_label,
    _anomaly_status_labels,
    _buff_effect_bb_key_ignored,
    _collect_buff_labels,
    _is_damage_increase_bb_key,
    _label_from_bb_key,
)

from parser_core.effects.specifications import (
    _collect_zone_effects,
    _extract_dynamic_effect_specs,
)

from parser_core.effects.semantic_conditions import (
    _collect_semantic_condition_zone_effects,
    _semantic_blackboard_defaults,
    _semantic_damage_effect_condition,
    _semantic_damage_effect_zone,
    _semantic_entry_bb_keys,
    _semantic_entry_has_rdps,
)

from parser_core.effects.packet_mapping import (
    _DPD_ZONE_BUCKETS,
    _packet_mapping_allows_static_rate,
    _packet_mapping_stack_limit,
    _packet_numeric_dynamic_effects,
    _packet_numeric_effects,
)

from parser_core.effects.typed_actions import (
    _ENHANCED_ACTION_SUBTYPE_TO_ELEMENT,
    _enhanced_action_child_effect_specs,
    _walk_enhanced_action_child_specs,
)

from parser_core.effects.conditions import (
    _decoded_damage_modifier_condition_rows,
    _normalize_condition_damage_type,
)

from parser_core.effects.classification import (
    _BUFF_NOISE_IDS,
    _BUFF_NOISE_PREFIXES,
    _RATE_IGNORE_BUFF_PATTERNS,
    _is_effectless_wrapper_record,
    _is_noise_buff,
    _is_packet_effectless_wrapper,
    _should_ignore_rate_buff,
    _should_ignore_record_rate_effects,
)

from parser_core.effects.stacking_rules import (
    _FOOD_POTION_BUFF_RE,
    _WEAPON_ID_FROM_BUFF_RE,
    _buff_stack_limit,
    _is_food_potion_buff,
    _is_nonstacking_refresh_event,
)

from parser_core.catalog.buff_templates import (
    _buff_classifier_hint,
    _buff_decoded_detail_path,
    _buff_effect_hint_candidates,
)

from parser_core.effects.registry import (
    _RDPS_ALLOCATABLE_ZONES,
    _RDPS_REGISTRY_CONTROL_BB_KEYS,
    _classify_non_rdps_entry,
    _rdps_registry_candidate_effect_entry,
    _rdps_registry_effect_runtime_rate,
    _rdps_registry_ignored_bb_keys,
    _rdps_registry_known_non_rdps_entry,
    _rdps_registry_stack_limit,
    _rdps_registry_suppresses_zone_effects,
    _rdps_registry_unrecognized_effect_bb_keys,
    _rdps_registry_validation_error,
    _rdps_registry_verified_effect_entry,
    _rdps_registry_zone_effects,
)

from parser_core.reporting.timeline import append_buff_events

from parser_core.reporting.timeline import export_casts

from parser_core.reporting.timeline import append_non_damage_casts

from parser_core.reporting.timeline import build_hit_events

from parser_core.reporting.participants import build_participants

from parser_core.reporting.baseline import prepare_static_baseline

from parser_core.effects.evaluation import (
    _window_effects_at_ts,
)

from parser_core.reporting.skill_stats import (
    _CAST_CHILD_ENTITY_RE,
    _TIMELINE_SKILL_GROUP_GAP_MS,
    _TIMELINE_ULTIMATE_GROUP_GAP_MS,
    _assign_skill_timeline_group_keys,
    _build_cast_start_index,
    _build_role_skill_stats_from_timeline_groups,
    _cast_skill_family_key,
    _matching_cast_for_hit,
    _timeline_skill_group_gap_ms,
)

from parser_core.allocation.static_loadout import (
    _ATTR_TYPE_TO_EFFECT,
    _RDPS_DEBUG_ZONE_LABELS,
    _character_base_stats,
    _derive_static_arts_strength_entries,
    _derive_static_self_multiplier_entries,
)

from parser_core.reporting.timing import (
    _filter_buff_starts_for_timer_window,
)

from parser_core.reporting.empty import build_empty_report

from parser_core.reporting.loadout import (
    _loadout_without_mismatched_weapon_skills,
    _repair_weapon_puton_loadout_groups,
    _select_loadout_snapshot_for_battle,
)

from parser_core.reporting.timing import apply_official_timing
from parser_core.reporting.state import ReportState
from parser_core.reporting.window import BattleTimeline, select_hit_window

from parser_core.allocation.shares import allocate_log_marginal, _round4

from parser_core.reporting.evidence import bind_dynamic_observations

from parser_core.allocation.attack_model import observed_attack_dependence
from parser_core.catalog import packet_semantics as _packet_catalog, buff_templates as _buff_catalog
from parser_core.integrity import build_canonical_sha256
from parser_core.critical_context import build_critical_context, critical_buff_profile, update_critical_observation
from parser_core.timing.timer_evidence import collect_timer_evidence, validate_timer_evidence
from parser_core.snapshot_quality import with_snapshot_quality

from parser_core.ingestion.buff_observations import consume_buff_blackboard, consume_buff_observation

from parser_core.effects.packet_mapping import (
    _preserve_raw_numeric_internal_trigger_buff_id,
    _PACKET_RDPS_BB_KEY_HINTS,
    _PACKET_UTILITY_BB_KEY_HINTS,
    _STATIC_PACKET_BUFF_ALIASES,
    _canonical_packet_buff_id,
    _classify_packet_buff_record,
    _is_internal_trigger_damage_record,
    _mechanism_registry_buff_hint,
    _packet_bb_key_has_rdps_shape,
    _packet_mapping_applies,
    _packet_numeric_buff_hint,
)

from parser_core.ingestion.loadout import (
    consume_character_skills,
    consume_loadout_snapshot,
    _LOADOUT_SLOT_RE,
    consume_loadout_group,
    _WEAPON_LOADOUT_STATE_FIELDS,
    _loadout_weapon_source_skill_ids,
    _loadout_with_weapon_state,
    _merge_tracked_loadout_state,
    _infer_verified_weapon_refine_from_levels,
    _merge_loadout_equips_by_slot,
    _merge_loadout_snapshot,
    _parse_char_skills_line,
    _parse_inline_equips,
    _parse_loadout_slot_snapshot,
    _parse_loadout_stats_snapshot,
    _parse_weapon_source_skills,
    _selected_weapon_base_atk,
    _suit_effect_count_map,
)


from parser_core.ingestion.hits import (
    consume_hit_and_buff_lifecycle,
    _COMBO_CONSUME_SKILL_ALIASES,
    _HIT_SEQ_RE,
    _WEAPON_BUFF_RE,
)

from parser_core.allocation.arts_strength import (
    _arts_strength_damage_multiplier,
    _arts_strength_effect_multiplier,
    _is_arts_strength_damage_hit,
)

from parser_core.effects.enemy_status import (
    _annotate_hit_enemy_hp_state,
    _apply_enemy_status_bb_overrides,
    _cap_enemy_overkill_damage,
    _enemy_hp_state_key,
)


from parser_core.ingestion.skill_identity import (
    _canonical_hit_skill_id,
    _canonical_hit_skill_id_from_cast_context,
    _canonical_num_table_buff_number,
    _canonical_num_table_skill_id,
    _canonical_runtime_buff_skill_id,
    _recent_source_skill_context_for_buff,
    _resolve_skill_family_key,
)


from parser_core.effects.approval import (
    _normalize_buff_id,
    _rdps_registry_bb_keys_allowed,
    _rdps_registry_effect_bb_keys,
    _rdps_registry_entry_matches_guard,
    _rdps_registry_matching_effect_entry,
    _record_bb_key_set,
)

from parser_core.ingestion.dynamic_evidence import (
    consume_dynamic_observation,
)

from parser_core.ingestion.packet_evidence import (
    consume_packet_evidence,
)

from parser_core.ingestion.timers import (
    consume_stage_context,
    consume_timer_observation,
    _timer_is_authoritative,
    _GAME_TIMER_END_RE,
    _GAME_TIMER_START_RE,
    _LIVE_TIMER_TICK_RE,
    _OFFICIAL_TIMER_END_RE,
    _OFFICIAL_TIMER_START_RE,
)

from parser_core.ingestion.skills import (
    consume_skill_observation,
    _is_generic_runtime_skill_id,
)


from parser_core.ingestion.entities import (
    consume_entity_observation,
    _attach_attacker_entity_stats,
    _attach_target_entity_stats,
    _entity_stats_snapshot_at,
    _parse_entity_stats_snapshot,
)

from parser_core.catalog.display import (
    _ATTACK_VARIANT_RE,
    _BUFF_DAMAGE_NAME_OVERRIDES,
    _DASH_ATTACK_RE,
    _ELEMENT_TOKEN_TO_NAME,
    _PASSIVE_RE,
    _PLUNGING_ATTACK_RE,
    _POTENTIAL_RE,
    _TALENT_RE,
    _humanize_buff_damage_name,
    _humanize_character_skill_name,
    _humanize_generic_skill_name,
    _humanize_generic_skill_tokens,
    _humanize_skill_suffix_text,
    _load_buff_manifest_names,
    _load_enemy_names,
    _resolve_enemy_name,
)

from parser_core.reporting.poise import (
    _POISE_RE,
    _apply_poise_damage_events_to_hits,
    _parse_poise_damage_event,
)


from parser_core.effects.window_identity import (
    _buff_window_stack_group_key,
    _effect_condition_signature,
    _effect_row_signature,
    _merge_effect_lists,
    _merge_window_content,
    _merge_window_uid_aliases,
    _prefer_window_event_name,
    _window_uid_aliases,
)

from parser_core.effects.conditions import (
    _PHYSICAL_DAMAGE_ELEMENT_BB_KEYS,
    _attach_bb_key_damage_type_condition,
    _bb_key_damage_type_condition,
    _condition_damage_type_elements,
    _effect_condition_failure,
    _effect_damage_type_condition_elements,
    _effect_element_applies_to_hit,
    _element_filter_debug_fields,
)
from parser_core.ink_provenance import EXPLOSION as INK_EXPLOSION, apply_ink_provenance, ink_allocation_result

from parser_core.effects.damage_types import (
    _BUFF_SKILL_FILTER,
    _BUFF_EFFECT_SKILL_FILTER,
    _ATTR_TYPE_DAMAGE_MASK,
    _DAMAGE_SCHOOL_BY_SPEC,
    _ELEMENTAL_ELEMENTS,
    _attr_type_applies_to_skill,
    _damage_school_from_element,
    _effect_applies_to_damage_element,
    _infer_skill_action_damage_element,
    _infer_skill_damage_element,
    _infer_skill_damage_school,
    _normalize_effect_element,
)

from parser_core.catalog.skill_damage import (
    _DAMAGE_TAG_TO_ELEMENT,
    _load_character_profiles,
    _load_official_skill_damage_catalog,
    _load_official_skill_damage_prefixes,
    _load_skill_action_damage_units,
    _load_skill_item_metadata,
    _load_skill_profiles,
    _resolve_official_skill_damage_profile,
    _resolve_skill_profile,
)

from parser_core.catalog.packet_semantics import (
    _CURRENT_KEYWORD_BINDING,
    _load_mechanism_registry_by_buff_id,
    _load_num_id_str_buff_map,
    _load_packet_canonical_buff_map,
    _load_packet_numeric_buff_map,
    _load_rdps_semantics_registry,
    _merge_packet_buff_mapping_rows,
)

from parser_core.catalog.buff_templates import (
    _blackboard_max_stack_from_weapon_skill,
    _buff_child_family_ids,
    _load_classifier_hints,
    _load_current_buff_roots,
    _load_damage_zone_config,
    _load_equip_suit_allowed_buffs,
    _load_local_buff_semantic_entries,
    _load_local_skill_semantic_entries,
    _load_nonstacking_weapon_ids,
    _load_weapon_buff_stack_limits,
    _load_weapon_id_stack_limits,
)
from parser_core.realtime.incremental import memoize_live_record

from parser_core.reporting.totals import (
    _VISUAL_HIT_GROUP_WINDOW_MS,
    _new_participant_totals,
    _new_skill_totals,
    _rebuild_hit_totals,
    _recompute_participant_visual_max_hits,
)

from parser_core.catalog.names import (
    _COMPOSITE_RUNTIME_SKILL_RE,
    _CURRENT_TYPED_RESOURCE_BINDING,
    _ENDMIN_VARIANTS,
    _RUNTIME_SKILL_ID_RE,
    _RUNTIME_SKILL_NAME_OVERRIDES,
    _canonical_num_table_skill_number,
    _canonical_packet_skill_id,
    _character_key_matches_static_family,
    _load_canonical_skill_display_names,
    _load_character_names,
    _load_num_id_str_skill_map,
    _load_packet_numeric_skill_map,
    _load_skill_exact_names,
    _load_skill_name_prefixes,
    _packet_numeric_skill_hint,
    _resolve_character_name,
    _resolve_skill_name,
    _runtime_owner_matches_static_domain,
    _runtime_skill_number,
)

from parser_core.catalog.dungeons import (
    UNKNOWN_DUNGEON_NAME,
    _DUNGEON_CONTEXT_ALIASES,
    _apply_dungeon_catalog_overrides,
    _contract_tag_payload,
    _contract_tag_text,
    _dungeon_item_path,
    _dungeon_table_sources,
    _iter_dungeon_manifest_entries,
    _iter_dungeon_table_payloads,
    _load_contract_tag_catalog,
    _load_contract_tag_texts,
    _load_dungeon_by_id,
    _resolve_dungeon_context,
)

from parser_core.ingestion.identity import (
    _CHAR_KEY_RE,
    _ENEMY_KEY_RE,
    _FULL_ENEMY_KEY_RE,
    _SQUAD_MEMBER_RE,
    _apply_short_actor_aliases,
    _collect_party_actor_ids,
    _extract_character_key,
    _extract_enemy_key,
    _infer_context_enemy_hint,
    _recover_enemy_target_from_mislabeled_actor,
)

from parser_core.ingestion.fields import (
    _BASELINE_KV_RE,
    _BASELINE_RE,
    _DPD_RAW_RE,
    _KV_RE,
    _LOADOUT_FIELD_RE_TEMPLATE,
    _PKT_ATTR_RE,
    _PKT_MOD_RE,
    _SHORT_ID_RE,
    _TIMESTAMP_RE,
    _braced_field,
    _build_iso_datetime,
    _coerce_float,
    _coerce_int,
    _coerce_optional_float,
    _coerce_optional_int,
    _damage_element_from_dpd_raw,
    _duration_ms_from_seconds,
    _extract_fields,
    _ms_time_text,
    _parse_baseline_line,
    _parse_bb_assignments,
    _parse_contract_tag_ids,
    _parse_dpd_raw_line,
    _parse_equip_levels,
    _parse_hint_timestamp_ms,
    _parse_inline_equip_stats,
    _parse_loadout_skill_ids,
    _parse_loadout_suits,
    _parse_packet_attr_line,
    _parse_packet_modifier_line,
    _parse_prefixed_timestamp_ms,
    _parse_skill_int_ids,
    _parse_zone_values,
    _positive_int,
    _safe_positive_rate,
    _short_actor_number,
    _split_top_level,
    _token_field,
)
from parser_core.catalog.resources import (
    _parse_suit_counts,
    _NATIVE_DAMAGE_SEMANTICS_BINDING,
    _iter_json_entries,
    _load_character_base_stat_catalog,
    _load_equip_item_catalog,
    _load_suit_catalog,
    _load_weapon_catalog,
    _load_weapon_refine_catalog,
    _repo_root,
)

from parser_core.constants import PARSER_VERSION, RULES_VERSION, UNKNOWN_DUNGEON_KEY, UNKNOWN_ENEMY_KEY


# Compatibility exports for old callers. Name-based effect filters are retired;
# current typed conditions and observed hit masks determine applicability.
# Complete typed resources have an independent layout provenance. This does
# not renew the separate native zone/keyword/equipment semantics proofs above.
# Independently re-proved GetKeywordBuffName switches and metadata literals.
# This does not renew the unrelated legacy zone/mask/equipment native proof.




# Derived indexes belong to the exact immutable resources loaded below. Test
# overrides and replacement catalogs fall back to their own complete scans.






# Compatibility stubs: heuristic identity inference was removed. Callers must
# treat a missing result as unresolved evidence.



from parser_core.constants import (
    _STATIC_TRIGGER_DAMAGE_BUFF_RE,
    _BUFF_MERGE_GAP_MS,
    _CHAR_TYPE_TO_ELEMENT,
    _ATTR_TYPE_TO_LABEL,
    _ATTR_LABEL_TO_TYPE,
    _DEF_DECREASE_ATTR_TYPE_TO_EFFECT,
    _DPD_DAMAGE_TYPE_TO_ELEMENT,
    _ELEMENT_LABELS,
    _SINGLETON_REFRESH_EVENT_PATTERNS,
    _STACKABLE_EVENT_NAME_RE,
    _GENERIC_BUFF_PREFIXES,
    _PLAYER_TARGET_GENERIC_BUFF_PREFIXES,
    _CHR_BORROW_WINDOW_MS,
    _DEF_DECREASE_TICKS_PER_SEC,
    _ATTACK_INDEX_RE,
    _COMBO_SKILL_RE,
    _COMBO_DAMAGE_SKILL_KEY_RE,
    _FINAL_BB_KEY_OVERRIDES,
)
