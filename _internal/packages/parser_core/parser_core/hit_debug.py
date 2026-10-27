"""Compatibility exports; internal callers use the owning modules."""
import xml.etree.ElementTree as ET
import json
import re
import zipfile
from collections import (
    Counter,
    defaultdict,
)
from functools import (
    lru_cache,
)
from math import (
    log,
)
from parser_core.allocation.hit import (
    _allocate_rdps_for_hit,
)
from parser_core.allocation.packet_evidence import (
    _window_matches_packet_uids,
)
from parser_core.allocation.static_loadout import (
    _ATTR_TYPE_TO_EFFECT,
    _character_base_stats,
    _derive_static_self_multiplier_entries,
)
from parser_core.catalog.diagnostics import (
    _REPO_ROOT,
    _build_affix_rows,
    _clean_text,
    _load_character_attr_type_catalog,
    _load_equip_affix_catalog,
    _load_exported_character_skill_groups,
    _load_skill_action_graph_candidate_map,
    _load_weapon_affix_catalog,
    _normalize_value_options,
    _read_json_file,
    _selected_option_for_level,
    _sub_affix_key_order,
)
from parser_core.catalog.display import (
    _resolve_enemy_name,
)
from parser_core.catalog.dungeons import (
    UNKNOWN_DUNGEON_NAME,
    _resolve_dungeon_context,
)
from parser_core.catalog.names import (
    _is_runtime_numeric_skill_id,
    _packet_numeric_skill_hint,
    _resolve_character_name,
    _resolve_skill_name,
    _runtime_skill_number,
)
from parser_core.catalog.skill_damage import (
    _resolve_skill_profile,
)
from parser_core.constants import (
    UNKNOWN_DUNGEON_KEY,
    _CHR_BORROW_WINDOW_MS,
    _GENERIC_BUFF_PREFIXES,
)
from parser_core.diagnostics.buffs import (
    _apply_enemy_target_bb_duration_override,
    _build_buff_audit_rows,
    _build_buff_record_index,
    _build_buff_windows,
    _format_effect_summary,
)
from parser_core.diagnostics.coefficients import (
    _XLSX_NS,
    _damage_doc_workbook_path,
    _load_damage_doc_sheet_rows,
    _load_damage_doc_skill_scalar_catalog,
    _parse_doc_scalar,
    _skill_doc_scalar,
)
from parser_core.diagnostics.explanation import (
    DPD_ZONE_BUCKETS,
    ELEMENT_LABELS,
    ZONE_LABELS,
    ZONE_ORDER,
    _ACTOR_MAP_RE,
    _BASELINE_KV_RE,
    _BASELINE_RE,
    _DPD_RAW_RE,
    _HIT_SEQ_RE,
    _PKT_ATTR_RE,
    _PKT_MOD_RE,
    _action_graph_skill_candidates,
    _dpd_bucket_for_zone,
    _explain_hit,
    _format_ts_ms,
    _packet_attr_allowed_effects,
    _parse_baseline_line,
    _parse_dpd_raw_line,
    _parse_hex_int,
    _parse_packet_attr_line,
    _parse_packet_modifier_line,
    _parse_zone_values,
    _record_applicable_effect,
    _record_baseline_self,
    _record_dpd_self_residual,
    _round4,
    _skill_mapping_info,
    _sort_zones,
)
from parser_core.diagnostics.hit_debug import (
    parse_hit_debug_log_text,
)
from parser_core.diagnostics.loadout import (
    _ATTR_NAME_TO_TYPE,
    _RAW_LOG_PROOF_BEGIN_PREFIX,
    _RAW_LOG_PROOF_END,
    _active_loadout_maps_from_rows,
    _enrich_equip_row,
    _estimate_visible_panel_attack,
    _extract_embedded_raw_log_proof,
    _extract_loadout_from_text,
    _is_valid_equip_row,
    _loadout_skill_ids_by_char,
)
from parser_core.effects.approval import (
    _normalize_buff_id,
)
from parser_core.effects.classification import (
    _equip_buff_matches_active_suits,
    _is_noise_buff,
    _should_ignore_rate_buff,
    _weapon_buff_matches_active_weapon,
)
from parser_core.effects.damage_types import (
    _BUFF_EFFECT_SKILL_FILTER,
    _BUFF_SKILL_FILTER,
    _attr_type_applies_to_skill,
    _damage_school_from_element,
    _effect_applies_to_damage_element,
    _infer_skill_action_damage_element,
    _infer_skill_damage_element,
    _infer_skill_damage_school,
    _normalize_effect_element,
)
from parser_core.effects.enemy_status import (
    _annotate_hit_enemy_hp_state,
    _apply_enemy_status_bb_overrides,
    _bb_duration_ms_for_enemy_defense_effect,
    _cap_enemy_overkill_damage,
    _enemy_hp_state_key,
    _record_has_enemy_defense_effect,
)
from parser_core.effects.evaluation import (
    _window_effects_at_ts,
)
from parser_core.effects.imbue import (
    _build_special_combo_windows,
)
from parser_core.effects.labels import (
    _ATTR_TYPE_BUFF_LABELS,
    _collect_buff_labels,
)
from parser_core.effects.lifecycle import (
    _extend_buff_records_from_packet_modifiers,
    _infer_related_buff_end_times,
    _normalize_buff_duration_ms,
    _prefer_packet_buff_record,
    _resolve_weapon_buff_sources,
)
from parser_core.effects.packet_mapping import (
    _canonical_packet_buff_id,
    _classify_packet_buff_record,
    _packet_mapping_applies,
    _packet_mapping_stack_limit,
    _packet_numeric_buff_hint,
    _preserve_raw_numeric_internal_trigger_buff_id,
)
from parser_core.effects.registry import (
    _RDPS_ALLOCATABLE_ZONES,
)
from parser_core.effects.specifications import (
    _collect_zone_effects,
    _extract_dynamic_effect_specs,
)
from parser_core.effects.stacking_rules import (
    _buff_stack_limit,
)
from parser_core.effects.windows import (
    _apply_buff_stack_limits,
    _dedupe_mirrored_buff_windows,
    _merge_buff_windows,
)
from parser_core.ingestion.fields import (
    _coerce_float,
    _damage_element_from_dpd_raw,
    _duration_ms_from_seconds,
    _parse_hint_timestamp_ms,
    _parse_loadout_suits,
    _parse_prefixed_timestamp_ms,
    _parse_dpd_raw_line as _parse_runtime_dpd_raw_line,
    _parse_zone_values as _parse_runtime_zone_values,
    _safe_positive_rate,
    _coerce_int,
    _coerce_optional_float,
    _extract_fields,
)
from parser_core.ingestion.hits import (
    _WEAPON_BUFF_RE,
)
from parser_core.ingestion.identity import (
    _collect_party_actor_ids,
    _extract_character_key,
    _extract_enemy_key,
    _infer_context_enemy_hint,
    _recover_enemy_target_from_mislabeled_actor,
)
from parser_core.ingestion.loadout import (
    _merge_loadout_snapshot,
    _parse_loadout_slot_snapshot,
    _parse_loadout_stats_snapshot,
)
from parser_core.ingestion.skill_identity import (
    _apply_same_frame_trigger_skill_mappings,
    _canonical_hit_skill_id,
    _canonical_hit_skill_id_from_cast_context,
    _canonical_num_table_skill_id,
    _canonical_runtime_buff_skill_id,
    _infer_missing_hit_damage_schools,
    _resolve_skill_family_key,
    _runtime_skill_trigger_chain_mapping,
    _same_frame_trigger_buff_for_runtime_skill,
    _trigger_damage_identity_from_buff,
)
from parser_core.reporting.buffs import (
    _packet_buff_semantic_candidates,
)
from pathlib import (
    Path,
)
from statistics import (
    median,
)
from typing import (
    Any,
)
