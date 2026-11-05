"""Observed loadout fields, exact weapon levels and evidence-preserving equipment merges."""
from __future__ import annotations

from parser_core.catalog.names import _resolve_character_name
from parser_core.catalog.resources import (
    _load_equip_item_catalog,
    _load_weapon_catalog,
    _load_weapon_refine_catalog,
    _parse_suit_counts,
)
from parser_core.ingestion.fields import (
    _braced_field,
    _coerce_int,
    _extract_fields,
    _parse_bb_assignments,
    _parse_equip_levels,
    _parse_inline_equip_stats,
    _parse_skill_int_ids,
    _split_top_level,
    _token_field,
    _parse_loadout_suits,
)
from parser_core.ingestion.skill_identity import _canonical_num_table_skill_id
from parser_core.ingestion.skills import _is_generic_runtime_skill_id
import copy
import re
from typing import Any

from parser_core.ingestion.state import IngestionState
from parser_core.ingestion.loadout_observation import LoadoutSlotObservation, LoadoutStatsObservation




def _infer_verified_weapon_refine_from_levels(weapon_template: str, source_skills: Any, *, gem_terms: Any = None) -> int | None:
    entry = _load_weapon_refine_catalog().get(weapon_template, {})
    main_id = str(entry.get('mainSkillId') or '')
    accepted_ids = {main_id, str(entry.get('mainSkillNumId') or '')} - {''}
    gem_cost = None
    if gem_terms is not None:
        # Callers must bind this complete gem snapshot to the equipped weapon.
        if not isinstance(gem_terms, list) or not gem_terms:
            return None
        terms = {}
        for term in gem_terms:
            if (not isinstance(term, dict) or type(term.get('term_num_id')) is not int
                    or type(term.get('cost')) is not int or term['term_num_id'] <= 0
                    or not 0 <= term['cost'] <= 6 or term['term_num_id'] in terms):
                return None
            terms[term['term_num_id']] = term['cost']
        term_id = entry.get('mainSkillGemTermNumId')
        if type(term_id) is not int or not entry.get('mainSkillBounds') or not entry.get('refineBonusBounds'):
            return None
        gem_cost = terms.get(term_id, 0)
    values = set()
    for skill in source_skills or []:
        if not isinstance(skill, dict):
            continue
        ids = {str(skill[key]) for key in ('skill_id', 'skillKey', 'skill_str_id', 'skill_int_id') if skill.get(key) not in (None, '', 0)}
        if not ids.intersection(accepted_ids):
            continue
        if not ids.issubset(accepted_ids):
            return None
        level = skill.get('level')
        if isinstance(level, bool) or not str(level).isdigit():
            return None
        # Base breakthrough/gem levels and refinement bonuses overlap.
        # Accept only totals with one possible refinement in the official tables.
        value = entry.get('skillLevelToRefine', {}).get(str(int(level)))
        if gem_cost is not None:
            if int(level) not in entry.get('supportedSkillLevels', []):
                return None
            candidates = {int(refine) for refine, bonus in entry['refineBonusBounds'].items()
                          for bound in entry['mainSkillBounds']
                          if min(bound['lowerBound'] + bonus['lowerBound'] + gem_cost,
                                 bound['upperBound'] + bonus['upperBound']) == int(level)}
            value = next(iter(candidates)) if len(candidates) == 1 else None
        if value is None:
            return None
        values.add(int(value))
    return next(iter(values)) if len(values) == 1 else None


def _parse_inline_equips(raw_line: str) -> list[dict[str, Any]]:
    return _inline_equips_blob(_braced_field(raw_line, "equips"))


def _inline_equips_blob(equips_blob):
    if not equips_blob:
        return []
    matches = list(re.finditer(r"\[(\d+)\]=", equips_blob))
    equips: list[dict[str, Any]] = []
    catalog = _load_equip_item_catalog()
    for index, match in enumerate(matches):
        slot = int(match.group(1))
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(equips_blob)
        entry = equips_blob[start:end].strip()
        item_id = entry.split("|", 1)[0].strip()
        meta = catalog.get(item_id, {})
        level_match = re.search(r"\|lv=([^|]+)", entry)
        stats_match = re.search(r"\|stats=(.*)$", entry)
        equips.append(
            {
                "slot": slot,
                "item_id": item_id,
                "item_name": meta.get("item_name") or item_id,
                "suit_id": meta.get("suit_id") or "",
                "suit_name": meta.get("suit_name") or "",
                "part_name": meta.get("part_name") or "",
                "rarity": meta.get("rarity"),
                "enhance_levels": _parse_equip_levels(level_match.group(1) if level_match else None),
                "stats": _parse_inline_equip_stats(stats_match.group(1) if stats_match else None),
                "catalog_main_attr": meta.get("main_attr"),
                "catalog_sub_attrs": meta.get("sub_attrs") or {},
            }
        )
    return equips


def _parse_weapon_source_skills(blob: str | None) -> list[dict[str, Any]]:
    if not blob:
        return []
    skills: list[dict[str, Any]] = []
    for entry in _split_top_level(blob, ";"):
        if ":" not in entry:
            continue
        skill_id, rest = entry.split(":", 1)
        level_match = re.search(r"(?:^|:)level=([^:]+)", rest)
        potential_match = re.search(r"(?:^|:)potentialLv=([^:]+)", rest)
        bb_blob = _braced_field(f"bb={{{rest.split('bb={', 1)[1]}" if "bb={" in rest else "", "bb")
        skills.append(
            {
                "skill_id": skill_id.strip(),
                "level": _coerce_int(level_match.group(1), default=0) if level_match else None,
                "potential_level": _coerce_int(potential_match.group(1), default=0) if potential_match else None,
                "bb": _parse_bb_assignments(bb_blob),
            }
        )
    return skills


def _selected_weapon_base_atk(weapon_template: str, weapon_level: int | None) -> Any:
    values = _load_weapon_catalog().get(weapon_template, {}).get("base_atk_values")
    if not isinstance(values, list) or weapon_level is None:
        return None
    if 0 < weapon_level <= len(values):
        return values[weapon_level - 1]
    return None


def _parse_loadout_slot_snapshot(raw_line: str) -> dict[str, Any] | None:
    char_key = _token_field(raw_line, "char")
    if not char_key or not char_key.startswith("chr_"):
        return None
    weapon_template = _token_field(raw_line, "weaponTemplate") or ""
    # The wire format uses weaponLv=0 when the instance level is not present
    # (for example template_only syncs). Preserve that distinction instead of
    # exposing zero as a real level; static attack curves require a positive
    # level and must remain unknown otherwise.
    raw_weapon_level = _coerce_int(_token_field(raw_line, "weaponLv"), default=0)
    weapon_level = raw_weapon_level if raw_weapon_level > 0 else None
    equip_suit_blob = _braced_field(raw_line, "equipSuit") or ""
    raw_refine = _token_field(raw_line, "refine") or ""
    weapon_refine = int(raw_refine) if re.fullmatch(r"[0-5]", raw_refine) else None
    unplaced = re.search(r'\bunplacedEquipInstIds=\[([^\]]*)\]', raw_line)
    complete = _token_field(raw_line, 'equipsComplete')
    return loadout_slot_snapshot(LoadoutSlotObservation(
        character=char_key, slot=_coerce_int(_token_field(raw_line, "slot"), default=0),
        character_level=_coerce_int(_token_field(raw_line, "charLv"), default=0) or None,
        potential=_coerce_int(_token_field(raw_line, "potential"), default=0),
        weapon_instance=_token_field(raw_line, "weaponInstId"), weapon=weapon_template,
        weapon_level=weapon_level, refine=weapon_refine, breakthrough=_coerce_int(_token_field(raw_line, "break"), default=0),
        suit_blob=equip_suit_blob, equipment_blob=_braced_field(raw_line, "equips"), skill_ids=_parse_skill_int_ids(raw_line),
        unplaced_ids=re.findall(r'\d+', unplaced.group(1)) if unplaced else None,
        equipment_complete=complete == '1' if complete in {'0', '1'} else None))


def loadout_slot_snapshot(observation):
    char_key, weapon_template = observation.character, observation.weapon
    if not char_key.startswith('chr_'):
        return None
    weapon_level, weapon_refine = observation.weapon_level, observation.refine
    equip_suit_blob = observation.suit_blob
    weapon_meta = _load_weapon_catalog().get(weapon_template, {})
    row = {
        "slot": observation.slot,
        "character_key": char_key,
        "character_name": _resolve_character_name(char_key) or char_key,
        "character_level": observation.character_level,
        "potential": observation.potential,
        "weapon_inst_id": observation.weapon_instance,
        "weapon_template": weapon_template,
        "weapon_name": weapon_meta.get("weapon_name") or weapon_template,
        "weapon_level": weapon_level,
        "weapon_refine": weapon_refine,
        "weapon_refine_source": "loadout" if weapon_refine is not None else None,
        "weapon_break": observation.breakthrough,
        "weapon_base_atk": _selected_weapon_base_atk(weapon_template, weapon_level),
        "weapon_catalog_skilllist": weapon_meta.get("skilllist") or [],
        "equip_suit_raw": "{" + equip_suit_blob + "}" if equip_suit_blob else "{}",
        "suit_effects": _parse_suit_counts(equip_suit_blob),
        "equips": _inline_equips_blob(observation.equipment_blob),
        "skill_int_ids": list(observation.skill_ids),
        "weapon_source_skills": [],
        "weapon_refine_stats": [],
        "gem_template": None,
        "gem_terms": {},
    }
    if observation.unplaced_ids is not None:
        row['unresolved_equip_inst_ids'] = list(observation.unplaced_ids)
    if observation.equipment_complete is not None:
        row['equipment_snapshot_complete'] = observation.equipment_complete
    return row


def _character_skill_refine_snapshot(parsed, owner_id, loadout_context, squad_actor_keys):
    if parsed is None or not loadout_context or not squad_actor_keys:
        return None
    char_key, levels = parsed
    if (squad_actor_keys.get(owner_id) != char_key
            or list(squad_actor_keys.values()).count(char_key) != 1
            or loadout_context.get("character_key") != char_key
            or not re.fullmatch(r"[1-9]\d*", str(loadout_context.get("weapon_inst_id") or ""))
            or loadout_context.get("weapon_refine") is not None):
        return None
    weapon_template = str(loadout_context.get("weapon_template") or "")
    main_skill = _load_weapon_refine_catalog().get(weapon_template, {}).get("mainSkillId")
    if not main_skill or main_skill not in levels:
        return None
    refine = _infer_verified_weapon_refine_from_levels(
        weapon_template, [{"skill_id": main_skill, "level": levels[main_skill]}]
    )
    if refine is None:
        return None
    return {**copy.deepcopy(loadout_context), "weapon_refine": refine,
            "weapon_refine_source": "source_skill",
            "weapon_refine_evidence": {"source": "CHAR_SKILLS", "owner_id": owner_id,
                "weapon_inst_id": str(loadout_context["weapon_inst_id"]),
                "skill_id": main_skill, "level": levels[main_skill]}}


def _parse_loadout_stats_snapshot(
    raw_line: str,
    *,
    loadout_context: dict[str, Any] | None = None,
    squad_actor_keys: dict[str, str] | None = None,
    allow_bound_gem: bool = False,
) -> dict[str, Any] | None:
    if " CHAR_SKILLS " in raw_line:
        parsed = _parse_char_skills_line(raw_line)
        owner_id = str(_token_field(raw_line, "ownerId") or "")
        return _character_skill_refine_snapshot(parsed, owner_id, loadout_context, squad_actor_keys)
    char_key = _token_field(raw_line, "char")
    if not char_key or not char_key.startswith("chr_"):
        return None
    weapon_template = _token_field(raw_line, "weaponTemplate") or ""
    raw_weapon_level = _coerce_int(_token_field(raw_line, "weaponLv"), default=0)
    weapon_level = raw_weapon_level if raw_weapon_level > 0 else None
    return loadout_stats_snapshot(LoadoutStatsObservation(character=char_key, weapon=weapon_template,
        weapon_instance=str(_token_field(raw_line, "weaponInstId") or ""), weapon_level=weapon_level,
        refine_stats_blob=_braced_field(raw_line, "weaponRefineStats"), source_skills_blob=_braced_field(raw_line, "weaponSourceSkills"),
        base_attack=_coerce_int(_token_field(raw_line, "weaponBaseAtk"), default=0),
        base_attack_lv1=_coerce_int(_token_field(raw_line, "weaponBaseAtkLv1"), default=0),
        base_attack_max=_coerce_int(_token_field(raw_line, "weaponBaseAtkMax"), default=0),
        gem_instance=str(_token_field(raw_line, "gemInstId") or ""), gem_weapon=str(_token_field(raw_line, "gemWeaponId") or ""),
        gem_template=_token_field(raw_line, "gemTemplate"), terms_blob=_braced_field(raw_line, "gemTerms") or ''),
        allow_bound_gem=allow_bound_gem)


def loadout_stats_snapshot(observation, *, allow_bound_gem=False):
    char_key, weapon_template, weapon_level = observation.character, observation.weapon, observation.weapon_level
    if not char_key.startswith('chr_'):
        return None
    weapon_refine_stats = _parse_weapon_source_skills(observation.refine_stats_blob)
    weapon_source_skills = _parse_weapon_source_skills(observation.source_skills_blob)
    gem_terms = None
    weapon_inst, gem_inst, raw_terms = observation.weapon_instance, observation.gem_instance, observation.terms_blob
    if (allow_bound_gem and re.fullmatch(r"[1-9]\d*", weapon_inst) and re.fullmatch(r"[1-9]\d*", gem_inst)
            and observation.gem_weapon == weapon_inst and raw_terms):
        matches = [re.fullmatch(r"(\d+):[^,@{}]*@cost(\d+)", part.strip()) for part in raw_terms.split(',')]
        if all(matches):
            gem_terms = [{"term_num_id": int(match[1]), "cost": int(match[2])} for match in matches]
    inferred_refine = _infer_verified_weapon_refine_from_levels(
        weapon_template,
        weapon_source_skills or weapon_refine_stats,
        gem_terms=gem_terms,
    )
    return {
        "character_key": char_key,
        "weapon_template": weapon_template,
        "weapon_refine": inferred_refine,
        "weapon_refine_source": "source_skill" if inferred_refine is not None else None,
        "weapon_base_atk": observation.base_attack or _selected_weapon_base_atk(weapon_template, weapon_level),
        "weapon_base_atk_lv1": observation.base_attack_lv1,
        "weapon_base_atk_max": observation.base_attack_max,
        "weapon_refine_stats": weapon_refine_stats,
        "weapon_source_skills": weapon_source_skills,
        "gem_template": observation.gem_template,
        "gem_terms": _parse_bb_assignments(raw_terms.replace(":", "=")),
    }


def _merge_loadout_snapshot(base: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    current_refine_source = merged.get("weapon_refine_source")
    update_refine_source = update.get("weapon_refine_source")
    for key, value in update.items():
        if update.get('equipment_snapshot_complete') is True and key in {
                'equips', 'suit_effects', 'equip_suit_raw', 'unresolved_equip_inst_ids'}:
            merged[key] = copy.deepcopy(value)
            continue
        if value in (None, "", [], {}):
            continue
        if key == "equips" and isinstance(value, list):
            current = merged.get("equips")
            if isinstance(current, list) and current:
                merged["equips"] = _merge_loadout_equips_by_slot(
                    current,
                    value,
                    suit_counts=_suit_effect_count_map(update.get("suit_effects")),
                )
            else:
                merged["equips"] = value
            continue
        if key == "weapon_refine" and current_refine_source == "source_skill" and update_refine_source != "source_skill":
            continue
        if (
            key == "weapon_refine_source"
            and current_refine_source == "source_skill"
            and value != "source_skill"
        ):
            continue
        merged[key] = value
    return merged


def _suit_effect_count_map(value: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in value or []:
        if not isinstance(item, dict):
            continue
        suit_id = str(item.get("suit_id") or "")
        if not suit_id:
            continue
        counts[suit_id] = int(item.get("piece_count") or 0)
    return counts


def _merge_loadout_equips_by_slot(
    base: list[dict[str, Any]],
    update: list[dict[str, Any]],
    *,
    suit_counts: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = [dict(equip) for equip in base if isinstance(equip, dict)]
    slot_index: dict[int, int] = {}
    for index, equip in enumerate(merged):
        try:
            slot_index[int(equip.get("slot"))] = index
        except (TypeError, ValueError):
            continue

    for equip in update:
        if not isinstance(equip, dict):
            continue
        try:
            slot = int(equip.get("slot"))
        except (TypeError, ValueError):
            slot = None
        if slot is not None and slot in slot_index:
            existing = merged[slot_index[slot]]
            # A different item replaces the whole old row. Its absent stats
            # cannot be borrowed from the previous item in this slot.
            merged[slot_index[slot]] = (dict(equip) if existing.get('item_id') != equip.get('item_id') else {
                **existing, **equip})
        else:
            merged.append(dict(equip))
            if slot is not None:
                slot_index[slot] = len(merged) - 1

    return sorted(
        merged,
        key=lambda equip: int(equip.get("slot")) if str(equip.get("slot", "")).lstrip("-").isdigit() else 99,
    )


def _parse_char_skills_line(raw_line: str) -> tuple[str, dict[str, int]] | None:
    """解析 bridge 的 CHAR_SKILLS 行 → (角色key, {技能key: 等级})。
    运行时兜底 id（纯数字 / chr_xxx_skill_766）经 num 表解析，失败自弃。"""
    fields = _extract_fields(raw_line)
    owner_key = str(fields.get("owner") or "")
    tokens_match = re.search(r"skills=\[([^\]]*)\]", raw_line)
    if not owner_key or not tokens_match:
        return None
    pairs = [token.rpartition(":") for token in tokens_match.group(1).split()]
    return character_skill_levels(owner_key, ((skill if separator else "", level) for skill, separator, level in pairs))


def character_skill_levels(owner_key, observations):
    """Fold explicit skill/level fields using the same rules as legacy evidence."""
    if not owner_key:
        return None
    levels: dict[str, int] = {}
    conflicted: set[str] = set()
    for skill_id, level_text in observations:
        level = _coerce_int(level_text, default=0)
        if not skill_id or level <= 0:
            continue
        if _is_generic_runtime_skill_id(skill_id) or re.fullmatch(r".*_skill_\d+", skill_id) or skill_id.isdigit():
            resolved = _canonical_num_table_skill_id(skill_id, owner_key)
            if not resolved:
                continue
            skill_id = resolved
        if skill_id in conflicted:
            continue
        if skill_id in levels and levels[skill_id] != level:
            levels.pop(skill_id)
            conflicted.add(skill_id)
        else:
            levels[skill_id] = level
    if not levels:
        return None
    return owner_key, levels


_WEAPON_LOADOUT_STATE_FIELDS = {
    "weapon_refine_evidence",
    "weapon_inst_id",
    "weapon_template",
    "weapon_name",
    "weapon_level",
    "weapon_refine",
    "weapon_refine_source",
    "weapon_break",
    "weapon_base_atk",
    "weapon_base_atk_lv1",
    "weapon_base_atk_max",
    "weapon_catalog_skilllist",
    "weapon_source_skills",
    "weapon_refine_stats",
    "gem_template",
    "gem_terms",
}


def _loadout_weapon_source_skill_ids(row: dict[str, Any] | None) -> set[int]:
    if not isinstance(row, dict):
        return set()
    result: set[int] = set()
    for item in row.get("weapon_source_skills") or row.get("weapon_refine_stats") or []:
        if not isinstance(item, dict):
            continue
        skill_int_id = _coerce_int(item.get("skill_id"), default=0)
        if skill_int_id:
            result.add(skill_int_id)
    return result


def _loadout_with_weapon_state(
    destination: dict[str, Any],
    source: dict[str, Any],
) -> dict[str, Any]:
    merged = copy.deepcopy(destination)
    previous_source_ids = _loadout_weapon_source_skill_ids(destination)
    for key in _WEAPON_LOADOUT_STATE_FIELDS:
        if key in source:
            merged[key] = copy.deepcopy(source[key])
        else:
            merged.pop(key, None)

    destination_potential = int(destination.get("potential") or 0)
    for field in ("weapon_source_skills", "weapon_refine_stats"):
        for item in merged.get(field) or []:
            if isinstance(item, dict):
                item["potential_level"] = destination_potential

    next_source_ids = _loadout_weapon_source_skill_ids(merged)
    skill_int_ids = [
        int(skill_int_id)
        for skill_int_id in destination.get("skill_int_ids") or []
        if int(skill_int_id) and int(skill_int_id) not in previous_source_ids
    ]
    for skill_int_id in next_source_ids:
        if skill_int_id not in skill_int_ids:
            skill_int_ids.append(skill_int_id)
    merged["skill_int_ids"] = skill_int_ids
    return merged


def _merge_tracked_loadout_state(
    previous: dict[str, Any] | None,
    row: dict[str, Any],
) -> dict[str, Any]:
    """Merge adjacent partial snapshots without retaining the old weapon.

    `_merge_loadout_snapshot` intentionally protects a source-skill-derived
    refine from weaker updates.  That protection must not cross a weapon
    instance change, where the new weapon's whole state is authoritative.
    """

    previous = previous or {}
    merged = _merge_loadout_snapshot(previous, row)
    previous_inst_id = str(previous.get("weapon_inst_id") or "")
    next_inst_id = str(row.get("weapon_inst_id") or "")
    if previous_inst_id and next_inst_id and previous_inst_id != next_inst_id:
        merged = _loadout_with_weapon_state(merged, row)
    return merged


def apply_loadout_group(ingestion, reason, line_no, ts_ms):
    ingestion.current_loadout_group = {
        "ts_ms": ts_ms, "line_no": line_no, "reason": reason,
        "index": len(ingestion.loadout_groups), "rows": {},
    }
    ingestion.loadout_groups.append(ingestion.current_loadout_group)


def consume_loadout_group(ingestion: IngestionState, raw_line: str, line_no: int, ts_ms: int) -> bool:
    if " LOADOUT reason=" in raw_line or "LOADOUT reason=" in raw_line:
        apply_loadout_group(ingestion, str(_extract_fields(raw_line).get("reason") or ""), line_no, ts_ms)
        return True
    return False


_LOADOUT_SLOT_RE = re.compile(
    r"\bLOADOUT\s+slot=(?P<slot>\d+)\s+char=(?P<char>\S+).*?"
    r"weaponTemplate=(?P<weapon>\S+).*?"
    r"equipSuit=(?P<equip_suit>\{.*\})"
)


def apply_loadout_snapshot(ingestion, row, line_no, ts_ms, *, stats=False):
    if row is None:
        return
    char_key = str(row["character_key"])
    initial = {"character_key": char_key} if stats else {}
    ingestion.loadout_by_char[char_key] = _merge_tracked_loadout_state(
        ingestion.loadout_by_char.get(char_key, initial), row)
    if char_key in ingestion.weapon_override_by_char:
        ingestion.loadout_by_char[char_key] = _loadout_with_weapon_state(
            ingestion.loadout_by_char[char_key], ingestion.weapon_override_by_char[char_key])
    if ingestion.current_loadout_group is None or ingestion.current_loadout_group.get("ts_ms") != ts_ms:
        apply_loadout_group(ingestion, "", line_no, ts_ms)
    group_rows = ingestion.current_loadout_group["rows"]
    group_rows[char_key] = _merge_loadout_snapshot(group_rows.get(char_key, initial), row)
    if char_key in ingestion.weapon_override_by_char:
        group_rows[char_key] = _loadout_with_weapon_state(group_rows[char_key], ingestion.weapon_override_by_char[char_key])


def apply_active_loadout(ingestion, character, weapon, suits):
    ingestion.active_weapons_by_char[character] = str(
        ingestion.loadout_by_char.get(character, {}).get("weapon_template") or weapon)
    ingestion.active_suits_by_char[character] = set(suits)


def consume_loadout_snapshot(ingestion: IngestionState, raw_line: str, line_no: int, ts_ms: int) -> bool:
    if " LOADOUT_STATS " in raw_line or "LOADOUT_STATS " in raw_line:
        snapshot = _parse_loadout_stats_snapshot(raw_line,
            allow_bound_gem=bool(ingestion.current_loadout_group and ingestion.current_loadout_group.get("ts_ms") == ts_ms
                and ingestion.current_loadout_group.get("reason") in {"SC_SYNC_CHAR_BAG_INFO", "SC_SELF_SCENE_INFO"}))
        apply_loadout_snapshot(ingestion, snapshot, line_no, ts_ms, stats=True)
        return True
    if " LOADOUT slot=" in raw_line or "LOADOUT slot=" in raw_line:
        apply_loadout_snapshot(ingestion, _parse_loadout_slot_snapshot(raw_line), line_no, ts_ms)
        match = _LOADOUT_SLOT_RE.search(raw_line)
        if match:
            apply_active_loadout(ingestion, match.group("char"), match.group("weapon"),
                                 _parse_loadout_suits(match.group("equip_suit")))
        return True
    return False



def consume_character_skills(ingestion: IngestionState, raw_line: str, line_no: int, ts_ms: int) -> bool:
    if " CHAR_SKILLS " in raw_line:
        apply_character_skills(ingestion, _parse_char_skills_line(raw_line),
                               str(_token_field(raw_line, "ownerId") or ""), line_no, ts_ms)
        return True
    return False


def apply_character_skills(ingestion, parsed, owner_id, line_no, ts_ms):
    if parsed is None:
        return
    char_key, levels = parsed
    ingestion.char_skill_levels[char_key] = levels
    stats_snapshot = _character_skill_refine_snapshot(parsed, owner_id,
        ingestion.loadout_by_char.get(char_key), ingestion.squad_actor_keys)
    if stats_snapshot is not None:
        ingestion.loadout_by_char[char_key] = stats_snapshot
        ingestion.current_loadout_group = {
            "ts_ms": ts_ms, "line_no": line_no, "reason": "CHAR_SKILLS", "index": len(ingestion.loadout_groups),
            "rows": {key: copy.deepcopy(ingestion.loadout_by_char[key])
                     for key in set(ingestion.squad_actor_keys.values()) if key in ingestion.loadout_by_char},
        }
        ingestion.loadout_groups.append(ingestion.current_loadout_group)


def _infer_weapon_refine_from_source_skills(
    weapon_template: str,
    source_skills: list[dict[str, Any]] | None,
) -> int | None:
    return _infer_verified_weapon_refine_from_levels(weapon_template, source_skills)


def extract_char_skill_levels_from_text(text: str) -> dict[str, dict[str, int]]:
    """全文提取 CHAR_SKILLS（bridge 在战前落盘，可能在 battle 分段之外——
    与 _raw_text_loadout_entries 同理由 uploader 对整个 trace 调用）。同角色取最后一次。"""
    result: dict[str, dict[str, int]] = {}
    for raw_line in text.splitlines():
        if " CHAR_SKILLS " not in raw_line:
            continue
        parsed = _parse_char_skills_line(raw_line)
        if parsed is not None:
            result[parsed[0]] = parsed[1]
    return result
