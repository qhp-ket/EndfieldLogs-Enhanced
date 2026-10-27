"""Attach observed static loadout evidence while retaining unresolved source blockers."""
from __future__ import annotations

from parser_core.allocation.static_loadout import _character_base_stats
from parser_core.allocation.static_loadout import _derive_static_arts_strength_entries
from parser_core.allocation.static_loadout import _derive_static_self_multiplier_entries
from parser_core.effects.enemy_status import _annotate_hit_enemy_hp_state
from parser_core.ingestion.fields import _coerce_optional_float
from parser_core.reporting.loadout import _select_loadout_snapshot_for_battle
from parser_core.reporting.state import ReportState
from typing import Any
import copy


def prepare_static_baseline(report_state: ReportState, first_hit_ms: int) -> tuple[dict[str, dict[str, Any]], bool, dict[str, float]]:
    """Attach observed static loadout evidence while retaining unresolved source blockers."""
    battle_loadout_by_char = _select_loadout_snapshot_for_battle(
        report_state.loadout_groups,
        report_state.loadout_by_char,
        anchor_ms=int(report_state.hits[0]["ts_ms"]) if report_state.hits else first_hit_ms,
        anchor_line_no=int(report_state.hits[0].get("line_no") or 0) or None if report_state.hits else None,
    )
    observed_damage_characters = {
        str(hit.get("character_key") or "")
        for hit in report_state.hits
        if str(hit.get("character_key") or "").startswith("chr_")
    }
    selected_loadout_characters = set(battle_loadout_by_char)
    loadout_stale = bool(
        selected_loadout_characters
        and observed_damage_characters - selected_loadout_characters
    )
    if loadout_stale:
        battle_loadout_by_char = {}
        report_state.active_suits_by_char.clear()
    report_state.active_weapons_by_char = {
        str(character_key): str(row.get("weapon_template") or "")
        for character_key, row in battle_loadout_by_char.items()
        if isinstance(row, dict) and row.get("weapon_template")
    }
    for loadout_row in battle_loadout_by_char.values():
        if isinstance(loadout_row, dict):
            loadout_row["static_multiplier_entries"] = _derive_static_self_multiplier_entries(loadout_row)
            loadout_row["static_arts_strength_entries"] = _derive_static_arts_strength_entries(loadout_row)
    static_entries_by_char = {
        str(character_key): list(row.get("static_multiplier_entries") or [])
        for character_key, row in battle_loadout_by_char.items()
        if isinstance(row, dict)
    }
    static_arts_strength_entries_by_char = {
        str(character_key): list(row.get("static_arts_strength_entries") or [])
        for character_key, row in battle_loadout_by_char.items()
        if isinstance(row, dict)
    }
    static_arts_strength_by_char = {
        character_key: sum(float(entry.get("rate") or 0.0) for entry in entries)
        for character_key, entries in static_arts_strength_entries_by_char.items()
    }
    # Static loadout effects remain unresolved unless their exact packet-level
    # application and hit-time contribution are modeled.  Repeated snapshots,
    # matching totals, or the presence of a runtime BB are observations only;
    # they cannot retire a blocker or retroactively alter the rDPS baseline.
    for hit in report_state.hits:
        character_key = str(hit.get("character_key") or "")
        hit["static_multiplier_entries"] = list(static_entries_by_char.get(character_key, []))
        loadout_row = battle_loadout_by_char.get(character_key) or {}
        static_sources = list(loadout_row.get(
            'rdps_unresolved_static_multiplier_sources', []))
        # Field count and an equipment marker do not prove that each passive
        # has been modeled or is represented by a hit-time baseline.
        hit['rdps_unresolved_static_multiplier_sources'] = static_sources
        hit["static_arts_strength_entries"] = static_arts_strength_entries_by_char.get(character_key, [])
        flat_entries = [entry for entry in loadout_row.get('equipment_baseline_attributes') or []
                        if entry.get('attr_type') == 2 and entry.get('modifier_type') == 7]
        hit['static_flat_attack'] = sum(float(entry['value']) for entry in flat_entries)
        hit['static_flat_attack_entries'] = copy.deepcopy(flat_entries)
        level = hit.get('attacker_stats_level') or loadout_row.get('character_level')
        base_stats = _character_base_stats(character_key, level) or {}
        basic_attack = _coerce_optional_float((hit.get('attacker_stats_basic_attrs') or {}).get(2))
        if basic_attack is None:
            basic_attack = _coerce_optional_float(base_stats.get('atk'))
        weapon_attack = _coerce_optional_float(loadout_row.get('weapon_base_atk'))
        if basic_attack is not None and basic_attack > 0 and weapon_attack is not None and weapon_attack > 0:
            hit['base_attack_for_percent'] = basic_attack + weapon_attack
        attrs = hit.get('attacker_stats_attrs') or {}
        main_value = _coerce_optional_float(attrs.get(base_stats.get('main_attr_type')))
        sub_value = _coerce_optional_float(attrs.get(base_stats.get('sub_attr_type')))
        main_scale = _coerce_optional_float(attrs.get(78))
        sub_scale = _coerce_optional_float(attrs.get(79))
        if all(value is not None and value >= 0 for value in (main_value, sub_value, main_scale, sub_scale)):
            hit['attack_ability_factor'] = 1.0 + int(main_value) * main_scale + int(sub_value) * sub_scale
    _annotate_hit_enemy_hp_state(report_state.hits)
    return battle_loadout_by_char, loadout_stale, static_arts_strength_by_char
