"""Canonical diagnostic report assembled from parser results."""
from __future__ import annotations
from collections import Counter
from typing import Any
from parser_core.ingestion.fields import _coerce_int
from parser_core.ingestion.fields import _coerce_optional_float
from parser_core.ingestion.fields import _extract_fields
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


def parse_hit_debug_log_text(
    text: str,
    *,
    file_name: str | None = None,
    first_hit_hint: str | None = None,
    last_hit_hint: str | None = None,
    _allow_history: bool = True,
) -> dict[str, Any]:
    """Present the canonical parser's results without a second allocation."""
    from parser_core.parser import parse_raw_battle_log_text
    from parser_core.ingestion.skills import _is_generic_runtime_skill_id
    from parser_core.catalog.names import _RUNTIME_SKILL_NAME_OVERRIDES

    proof = _extract_embedded_raw_log_proof(text)
    metadata = proof.get('meta') if isinstance(proof, dict) else None
    supplied = metadata.get('loadout') if isinstance(metadata, dict) else None
    display_loadout = []
    if isinstance(supplied, list):
        declared = Counter(str(row.get('character_key') or row.get('char_key') or row.get('char') or '')
                           for row in supplied if isinstance(row, dict))
        display_loadout = [row for row in _extract_loadout_from_text(text)
                           if declared.get(row['character_key']) == 1]
    raw = parse_raw_battle_log_text(text, file_name=file_name, first_hit_hint=first_hit_hint,
                                    last_hit_hint=last_hit_hint, include_rdps_debug=True)
    battle = raw['battle']
    context = raw.get('debug_context') or {}
    lines = text.splitlines()
    hits = []
    for item in raw.get('debug_hits') or []:
        hit = dict(item)
        number = hit.get('line_no')
        raw_line = lines[number - 1] if type(number) is int and 0 < number <= len(lines) else ''
        fields = _extract_fields(raw_line)
        original = str(hit.get('raw_skill_key') or hit.get('skill_key') or '')
        canonical = str(hit.get('skill_key') or '')
        unresolved = _is_generic_runtime_skill_id(canonical) or not canonical or canonical == 'unknown_skill'
        status = 'unresolved' if unresolved else 'mapped' if original != canonical else 'static'
        if original in _RUNTIME_SKILL_NAME_OVERRIDES:
            hit['skill_name'] = _RUNTIME_SKILL_NAME_OVERRIDES[original]
        hit.update({
            'raw_line': raw_line, 'time': _format_ts_ms(int(hit.get('ts_ms') or 0)),
            'src_raw': fields.get('src'), 'tgt_raw': fields.get('tgt'), 'atk_raw': fields.get('atk'),
            'raw_damage': _coerce_optional_float(fields.get('raw')), 'cum_damage': _coerce_optional_float(fields.get('cum')),
            'crit_dmg': _coerce_optional_float(fields.get('critDmg')), 'shared': _coerce_int(fields.get('shared'), default=0),
            'skill_mapping': {'status': status, 'status_label': {'unresolved': '未解析', 'mapped': '已映射', 'static': '静态 ID'}[status],
                              'raw_skill_key': original, 'canonical_skill_id': canonical,
                              'evidence_kind': 'canonical_parser_identity', 'candidates': [], 'action_graph_candidates': []},
        })
        hits.append(hit)
    windows = context.get('buff_windows') or []
    audit = []
    for item in raw.get('buff_events') or []:
        row = dict(item)
        row['effective_duration_ms'] = row.get('duration_ms')
        row['bb_raw'] = ' '.join(f'{key}={value}' for key, value in sorted((row.get('bb_values') or {}).items()))
        row['reasons'] = sorted({str(reason.get('reason')) for reason in (raw.get('rdps_preflight') or {}).get('blockers', [])
                                if reason.get('uid') == row.get('uid') and reason.get('reason')})
        if not row.get('zone_effects') and not row.get('dynamic_effects'):
            row['reasons'].append('无可识别正数效果')
        audit.append(row)
    start = context.get('start_ts_ms')
    end = context.get('end_ts_ms')
    return {
        'summary': {
            'file_name': file_name, 'hit_count': len(hits), 'buff_window_count': len(windows),
            'buff_audit_count': len(audit),
            'buff_audit_included_count': sum(row.get('status') == 'included' for row in audit),
            'buff_audit_filtered_count': sum(row.get('status') == 'filtered' for row in audit),
            'buff_audit_merged_count': sum(row.get('status') == 'merged' for row in audit),
            'dpd_count': sum(bool(hit.get('dpd_raw')) for hit in hits),
            'baseline_count': sum(bool(hit.get('baseline')) for hit in hits),
            'external_buff_hit_count': sum(bool(hit.get('external_sources')) for hit in hits),
            'first_hit_ms': start, 'first_hit_time': _format_ts_ms(start) if start is not None else None,
            'last_hit_ms': end, 'last_hit_time': _format_ts_ms(end) if end is not None else None,
            'duration_ms': battle.get('duration_ms'), 'total_damage': battle.get('total_damage'),
            'total_dps': battle.get('total_dps'), 'boss_key': battle.get('boss_key'), 'boss_name': battle.get('boss_name'),
            'dungeon_key': battle.get('dungeon_key'), 'dungeon_name': battle.get('dungeon_name'),
            'dungeon_context_id': battle.get('dungeon_context_id'), 'dungeon_identity_source': battle.get('dungeon_identity_source'),
        },
        'participants': raw.get('participants') or [], 'loadout': raw.get('loadout') or display_loadout,
        'loadout_presentation_source': 'canonical_parser' if raw.get('loadout') else 'embedded_metadata_display_only',
        'hits': hits, 'buff_windows': windows, 'buff_audit': audit,
        **{key: raw[key] for key in ('rdps_preflight','rdps_damage_basis','unresolved_hits','unresolved_buff_actions','snapshot_quality') if key in raw},
    }
