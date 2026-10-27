"""Diagnostic loadout evidence, affix presentation and visible panel estimate."""
from __future__ import annotations
import json
import re
from collections import defaultdict
from typing import Any
from parser_core.ingestion.fields import _parse_loadout_suits
from parser_core.ingestion.loadout import _merge_loadout_snapshot
from parser_core.ingestion.loadout import _parse_loadout_slot_snapshot
from parser_core.ingestion.loadout import _parse_loadout_stats_snapshot
from parser_core.catalog.diagnostics import (
    _load_character_attr_type_catalog,
    _load_equip_affix_catalog,
    _load_weapon_affix_catalog,
    _selected_option_for_level,
)


_RAW_LOG_PROOF_BEGIN_PREFIX = "## ENDFIELD_RAW_LOG_INTEGRITY_BEGIN sep="


_RAW_LOG_PROOF_END = "## ENDFIELD_RAW_LOG_INTEGRITY_END"


def _extract_embedded_raw_log_proof(text: str) -> dict[str, Any] | None:
    begin_idx = text.rfind(_RAW_LOG_PROOF_BEGIN_PREFIX)
    if begin_idx < 0:
        return None
    begin_line_end = text.find("\n", begin_idx)
    if begin_line_end < 0:
        return None
    end_marker = "\n" + _RAW_LOG_PROOF_END
    end_idx = text.find(end_marker, begin_line_end + 1)
    if end_idx < 0:
        return None
    try:
        proof = json.loads(text[begin_line_end + 1:end_idx])
    except json.JSONDecodeError:
        return None
    return proof if isinstance(proof, dict) else None


def _enrich_equip_row(equip: dict[str, Any]) -> dict[str, Any]:
    item_id = str(equip.get("item_id") or equip.get("itemId") or "")
    meta = _load_equip_affix_catalog().get(item_id, {})
    row = dict(equip)
    row.setdefault("item_id", item_id)
    row.setdefault("piece_name", meta.get("piece_name") or item_id)
    row.setdefault("suit_id", meta.get("suit_id") or "")
    row.setdefault("suit_name", meta.get("suit_name") or "")
    row.setdefault("part_name", meta.get("part_name") or "")
    levels = row.get("enhance_levels")
    if not isinstance(levels, list):
        levels = []
    levels = [int(value) for value in levels if isinstance(value, int) or str(value).lstrip("-").isdigit()]
    raw_affixes = row.get("affixes") if isinstance(row.get("affixes"), list) else meta.get("affixes") or []
    affixes: list[dict[str, Any]] = []
    main_attr: dict[str, Any] | None = None
    sub_attrs: list[dict[str, Any]] = []
    for raw_attr in raw_affixes:
        if not isinstance(raw_attr, dict):
            continue
        attr = dict(raw_attr)
        if attr.get("kind") == "sub":
            index = int(attr.get("index") or 0)
            level = levels[index] if index < len(levels) else attr.get("level")
            options = attr.get("value_options") if isinstance(attr.get("value_options"), list) else []
            selected = _selected_option_for_level(options, level)
            attr["level"] = level
            attr["selected_value"] = selected
            if selected is not None:
                attr["value"] = selected
            sub_attrs.append(attr)
        elif main_attr is None:
            main_attr = attr
        affixes.append(attr)
    row["enhance_levels"] = levels
    row["affixes"] = affixes
    row["main_attr"] = row.get("main_attr") or main_attr
    row["sub_attrs"] = row.get("sub_attrs") if isinstance(row.get("sub_attrs"), list) and row.get("sub_attrs") else sub_attrs
    try:
        failed_times = int(row.get("enhance_failed_times"))
    except (TypeError, ValueError):
        failed_times = None
    row["enhance_failed_times"] = failed_times if failed_times and 0 < failed_times <= 10000 else None
    return row


def _is_valid_equip_row(equip: dict[str, Any]) -> bool:
    item_id = str(equip.get("item_id") or equip.get("itemId") or "")
    return item_id.startswith("item_")


_ATTR_NAME_TO_TYPE = {
    "力量": 39,
    "敏捷": 40,
    "智识": 41,
    "意志": 42,
}


def _estimate_visible_panel_attack(
    character_key: str,
    loadout_row: dict[str, Any],
    base_stats: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(base_stats, dict):
        return None
    attr_types = _load_character_attr_type_catalog().get(character_key, {})
    main_attr_type = attr_types.get("main_attr_type")
    sub_attr_type = attr_types.get("sub_attr_type")
    if main_attr_type is None or sub_attr_type is None:
        return None

    ability_totals = {
        39: float(base_stats.get("attr_39") or 0.0),
        40: float(base_stats.get("attr_40") or 0.0),
        41: float(base_stats.get("attr_41") or 0.0),
        42: float(base_stats.get("attr_42") or 0.0),
    }
    atk_pct_bonus = 0.0
    flat_atk_bonus = 0.0
    sub_attr_pct_bonus = 0.0

    for skill in loadout_row.get("weapon_source_skills") or []:
        if not isinstance(skill, dict):
            continue
        bb = skill.get("bb") if isinstance(skill.get("bb"), dict) else {}
        for key, raw_value in bb.items():
            try:
                value = float(raw_value)
            except (TypeError, ValueError):
                continue
            lowered = str(key).lower()
            if lowered == "atk":
                atk_pct_bonus += value
            elif lowered == "mainattr":
                ability_totals[main_attr_type] = ability_totals.get(main_attr_type, 0.0) + value
            elif lowered == "second_attr_up":
                sub_attr_pct_bonus += value
            elif lowered in {"str", "agi", "wisd", "will"}:
                attr_type = _ATTR_NAME_TO_TYPE.get({"str": "力量", "agi": "敏捷", "wisd": "智识", "will": "意志"}[lowered])
                if attr_type is not None:
                    ability_totals[attr_type] = ability_totals.get(attr_type, 0.0) + value

    for equip in loadout_row.get("equips") or []:
        if not isinstance(equip, dict):
            continue
        for stat in equip.get("stats") or []:
            if not isinstance(stat, dict):
                continue
            name = str(stat.get("name") or "")
            try:
                value = float(stat.get("value") or 0.0)
            except (TypeError, ValueError):
                continue
            attr_type = _ATTR_NAME_TO_TYPE.get(name)
            if attr_type is not None:
                ability_totals[attr_type] = ability_totals.get(attr_type, 0.0) + value
            elif name == "攻击力":
                flat_atk_bonus += value

    if sub_attr_pct_bonus:
        ability_totals[sub_attr_type] = ability_totals.get(sub_attr_type, 0.0) * (1.0 + sub_attr_pct_bonus)

    try:
        character_base_atk = float(base_stats.get("atk") or 0.0)
    except (TypeError, ValueError):
        character_base_atk = 0.0
    try:
        weapon_base_atk = float(loadout_row.get("weapon_base_atk") or 0.0)
    except (TypeError, ValueError):
        weapon_base_atk = 0.0
    if character_base_atk <= 0 or weapon_base_atk <= 0:
        return None

    main_attr_total = ability_totals.get(main_attr_type, 0.0)
    sub_attr_total = ability_totals.get(sub_attr_type, 0.0)
    ability_bonus_multiplier = 1.0 + int(main_attr_total) * 0.005 + int(sub_attr_total) * 0.002
    panel_attack_estimate = ((character_base_atk + weapon_base_atk) * (1.0 + atk_pct_bonus) + flat_atk_bonus) * ability_bonus_multiplier
    return {
        "main_attr_type": main_attr_type,
        "sub_attr_type": sub_attr_type,
        "main_attr_total": main_attr_total,
        "sub_attr_total": sub_attr_total,
        "atk_pct_bonus": atk_pct_bonus,
        "flat_atk_bonus": flat_atk_bonus,
        "sub_attr_pct_bonus": sub_attr_pct_bonus,
        "ability_bonus_multiplier": ability_bonus_multiplier,
        "panel_attack_estimate": panel_attack_estimate,
    }


def _extract_loadout_from_text(text: str) -> list[dict[str, Any]]:
    def _loadout_from_raw_lines() -> list[dict[str, Any]]:
        self_scene_loadout_by_char: dict[str, dict[str, Any]] = {}
        sync_char_bag_loadout_by_char: dict[str, dict[str, Any]] = {}
        orphan_loadout_by_char: dict[str, dict[str, Any]] = {}
        current_reason: str | None = None
        for raw_line in text.splitlines():
            reason_match = re.search(r"\bLOADOUT\s+reason=([^\s]+)", raw_line)
            if reason_match:
                current_reason = reason_match.group(1)
                if current_reason == "SC_SELF_SCENE_INFO":
                    self_scene_loadout_by_char = {}
                elif current_reason == "SC_SYNC_CHAR_BAG_INFO":
                    sync_char_bag_loadout_by_char = {}
                elif current_reason == "BATTLE_START":
                    orphan_loadout_by_char = {}
                continue
            snapshot: dict[str, Any] | None = None
            if " LOADOUT_STATS " in raw_line or "LOADOUT_STATS " in raw_line:
                snapshot = _parse_loadout_stats_snapshot(raw_line)
            elif " LOADOUT slot=" in raw_line or "LOADOUT slot=" in raw_line:
                snapshot = _parse_loadout_slot_snapshot(raw_line)
            if snapshot is None:
                continue
            char_key = str(snapshot.get("character_key") or "")
            if not char_key:
                continue
            if current_reason == "SC_SELF_SCENE_INFO":
                self_scene_loadout_by_char[char_key] = _merge_loadout_snapshot(
                    self_scene_loadout_by_char.get(char_key, {}),
                    snapshot,
                )
            elif current_reason == "SC_SYNC_CHAR_BAG_INFO":
                sync_char_bag_loadout_by_char[char_key] = _merge_loadout_snapshot(
                    sync_char_bag_loadout_by_char.get(char_key, {}),
                    snapshot,
                )
            elif current_reason is None:
                orphan_loadout_by_char[char_key] = _merge_loadout_snapshot(
                    orphan_loadout_by_char.get(char_key, {}),
                    snapshot,
                )
            else:
                orphan_loadout_by_char[char_key] = _merge_loadout_snapshot(
                    orphan_loadout_by_char.get(char_key, {}),
                    snapshot,
                )
        loadout_by_char = self_scene_loadout_by_char or sync_char_bag_loadout_by_char or orphan_loadout_by_char
        return sorted(loadout_by_char.values(), key=lambda row: int(row.get("slot") or 0))

    proof = _extract_embedded_raw_log_proof(text)
    meta = proof.get("meta") if isinstance(proof, dict) else None
    loadout = meta.get("loadout") if isinstance(meta, dict) else None
    line_loadout = _loadout_from_raw_lines()
    if isinstance(loadout, list):
        line_by_char = {
            str(row.get("character_key") or row.get("char_key") or row.get("char") or ""): row
            for row in line_loadout
            if str(row.get("character_key") or row.get("char_key") or row.get("char") or "")
        }
        merged_loadout: list[dict[str, Any]] = []
        for entry in loadout:
            if not isinstance(entry, dict):
                continue
            char_key = str(entry.get("character_key") or entry.get("char_key") or entry.get("char") or "")
            base = line_by_char.get(char_key, {})
            merged_loadout.append(_merge_loadout_snapshot(base, entry))
        loadout = merged_loadout
    else:
        loadout = line_loadout
    weapon_catalog = _load_weapon_affix_catalog()
    enriched: list[dict[str, Any]] = []
    for entry in loadout:
        if not isinstance(entry, dict):
            continue
        row = dict(entry)
        row["character_key"] = str(row.get("character_key") or row.get("char_key") or row.get("char") or "")
        row["char_key"] = str(row.get("char_key") or row["character_key"])
        row["character_name"] = str(row.get("character_name") or row.get("char_name") or row["character_key"])
        row["char_name"] = str(row.get("char_name") or row["character_name"])
        weapon_template = str(row.get("weapon_template") or "")
        weapon_meta = weapon_catalog.get(weapon_template, {})
        row.setdefault("weapon_name", weapon_meta.get("weapon_name") or weapon_template)
        base_values = weapon_meta.get("weapon_base_atk_values") if isinstance(weapon_meta, dict) else []
        weapon_level = row.get("weapon_level")
        if row.get("weapon_base_atk") is None and isinstance(base_values, list):
            try:
                level_int = int(weapon_level)
            except (TypeError, ValueError):
                level_int = 0
            if 0 < level_int <= len(base_values):
                row["weapon_base_atk"] = base_values[level_int - 1]
        row.setdefault("weapon_skilllist", weapon_meta.get("weapon_skilllist") or [])
        row["equips"] = [
            _enrich_equip_row(equip)
            for equip in row.get("equips") or []
            if isinstance(equip, dict) and _is_valid_equip_row(equip)
        ]
        enriched.append(row)
    return enriched


def _loadout_skill_ids_by_char(loadout: list[dict[str, Any]]) -> dict[str, set[str]]:
    ids_by_char: dict[str, set[str]] = {}
    for row in loadout:
        char_key = str(row.get("character_key") or row.get("char_key") or row.get("char") or "")
        if not char_key:
            continue
        ids_by_char[char_key] = {
            str(skill_id)
            for skill_id in row.get("skill_int_ids") or []
            if str(skill_id)
        }
    return ids_by_char


def _active_loadout_maps_from_rows(
    loadout: list[dict[str, Any]],
) -> tuple[dict[str, set[str]], dict[str, str]]:
    active_suits_by_char: dict[str, set[str]] = {}
    active_weapons_by_char: dict[str, str] = {}
    for row in loadout:
        if not isinstance(row, dict):
            continue
        char_key = str(row.get("character_key") or row.get("char_key") or row.get("char") or "")
        if not char_key:
            continue
        weapon_template = str(row.get("weapon_template") or "")
        if weapon_template:
            active_weapons_by_char[char_key] = weapon_template
        suit_counter: dict[str, int] = defaultdict(int)
        for equip in row.get("equips") or []:
            if not isinstance(equip, dict):
                continue
            suit_id = str(equip.get("suit_id") or equip.get("suitID") or "")
            if suit_id:
                suit_counter[suit_id] += 1
        for suit_effect in row.get("suit_effects") or []:
            if not isinstance(suit_effect, dict):
                continue
            suit_id = str(suit_effect.get("suit_id") or "")
            if suit_id and suit_effect.get("active", True):
                suit_counter[suit_id] = max(suit_counter.get(suit_id, 0), int(suit_effect.get("piece_count") or 3))
        suit_blob = str(row.get("equip_suit") or row.get("equipSuit") or row.get("equip_suit_raw") or "")
        for suit_id in _parse_loadout_suits(suit_blob):
            suit_counter[suit_id] = max(suit_counter.get(suit_id, 0), 3)
        active_suits_by_char[char_key] = {
            suit_id for suit_id, count in suit_counter.items() if count >= 3
        }
    return active_suits_by_char, active_weapons_by_char
