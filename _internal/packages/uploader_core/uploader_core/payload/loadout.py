"""Normalize and project upload loadout fields while retaining evidence precedence."""
from __future__ import annotations
from typing import Any
from parser_core.catalog.names import _load_num_id_str_skill_map
from uploader_core.payload.catalog import (
    _infer_weapon_level_from_base_atk,
    _load_equip_catalog,
    _load_weapon_catalog,
)


_ADMIN_CANONICAL_KEY = "chr_9000_endmin"


_ENDMIN_VARIANTS = {"chr_0002_endminm", "chr_0003_endminf"}


def _is_character_key(value: object) -> bool:
    return isinstance(value, str) and value.startswith("chr_")


def _loadout_lookup_keys(character_key: str | None) -> list[str]:
    key = str(character_key or "")
    if not key:
        return []
    if key == _ADMIN_CANONICAL_KEY:
        return [key, *_ENDMIN_VARIANTS]
    if key in _ENDMIN_VARIANTS:
        return [key, _ADMIN_CANONICAL_KEY]
    return [key]


def _resolve_loadout_character_key(character_key: str | None, active_keys: set[str]) -> str | None:
    key = str(character_key or "")
    if not key:
        return None
    if key == _ADMIN_CANONICAL_KEY:
        matches = [candidate for candidate in sorted(_ENDMIN_VARIANTS) if candidate in active_keys]
        if len(matches) == 1:
            return matches[0]
    return key


def _lookup_loadout_payload(loadout_by_key: dict[str, dict], character_key: str | None) -> dict[str, Any]:
    for key in _loadout_lookup_keys(character_key):
        payload = loadout_by_key.get(key)
        if isinstance(payload, dict):
            return payload
    return {}


def _lookup_loadout_name(loadout_name_by_key: dict[str, str], character_key: str | None) -> str | None:
    for key in _loadout_lookup_keys(character_key):
        name = str(loadout_name_by_key.get(key) or "")
        if name:
            return name
    return None


def _load_loadout_entries(proof: dict | None) -> list[dict]:
    meta = proof.get("meta") if isinstance(proof, dict) else None
    loadout_meta = None
    if isinstance(meta, dict):
        if isinstance(meta.get("loadout"), list):
            loadout_meta = meta.get("loadout")
        elif isinstance(meta.get("roster"), list):
            loadout_meta = meta.get("roster")
    if not isinstance(loadout_meta, list):
        return []
    return [_normalize_loadout_entry(entry) for entry in loadout_meta if isinstance(entry, dict)]


def _normalize_equip_entry(entry: dict) -> dict:
    normalized = dict(entry)
    if normalized.get("item_id") is None:
        normalized["item_id"] = normalized.get("itemId")
    if normalized.get("piece_name") is None:
        normalized["piece_name"] = normalized.get("pieceName") or normalized.get("item_name")
    if normalized.get("suit_name") is None:
        normalized["suit_name"] = normalized.get("suitName")
    if normalized.get("part_name") is None:
        normalized["part_name"] = normalized.get("partName")
    return normalized


def _normalize_loadout_entry(entry: dict) -> dict:
    normalized = dict(entry)
    if normalized.get("char_key") is None:
        normalized["char_key"] = normalized.get("character_key") or normalized.get("characterKey")
    if normalized.get("char_name") is None:
        normalized["char_name"] = normalized.get("character_name") or normalized.get("characterName")
    if normalized.get("character_level") is None:
        normalized["character_level"] = (
            normalized.get("characterLevel")
            if normalized.get("characterLevel") is not None
            else normalized.get("char_level")
        )
    if normalized.get("potential") is None:
        normalized["potential"] = (
            normalized.get("character_potential")
            if normalized.get("character_potential") is not None
            else normalized.get("characterPotential")
        )
    if normalized.get("weapon_template") is None:
        normalized["weapon_template"] = normalized.get("weaponTemplate")
    if normalized.get("weapon_name") is None:
        normalized["weapon_name"] = normalized.get("weaponName")
    if normalized.get("weapon_level") is None:
        normalized["weapon_level"] = normalized.get("weaponLevel")
    if normalized.get("weapon_refine") is None:
        normalized["weapon_refine"] = normalized.get("weaponRefine")
    equips = normalized.get("equips")
    if isinstance(equips, list):
        normalized["equips"] = [_normalize_equip_entry(equip) for equip in equips if isinstance(equip, dict)]
    return normalized


def _merge_equip_entries(base: list[dict], update: list[dict]) -> list[dict]:
    merged: list[dict] = [dict(equip) for equip in base if isinstance(equip, dict)]
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
            merged[slot_index[slot]] = {**existing, **{key: value for key, value in equip.items() if value not in (None, "", [], {})}}
        else:
            merged.append(dict(equip))
            if slot is not None:
                slot_index[slot] = len(merged) - 1
    return merged


def _merge_loadout_entry(base: dict | None, update: dict) -> dict:
    if base is None:
        return dict(update)
    merged = dict(base)
    current_refine_source = merged.get("weapon_refine_source")
    update_refine_source = update.get("weapon_refine_source")
    for key, value in update.items():
        if value in (None, "", [], {}):
            continue
        if key == "equips" and isinstance(value, list):
            current_equips = merged.get("equips")
            if isinstance(current_equips, list) and current_equips:
                merged["equips"] = _merge_equip_entries(current_equips, value)
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


def _loadout_entries_with_fallback(
    proof: dict | None,
    parsed_loadout: object,
    *,
    raw_loadout_entries: list[dict] | None = None,
) -> list[dict]:
    entries_by_key: dict[str, dict] = {}
    order: list[str] = []

    entry_sources = []
    if raw_loadout_entries:
        entry_sources.append(raw_loadout_entries)
    entry_sources.append(parsed_loadout if isinstance(parsed_loadout, list) else [])

    for raw_entry in [entry for source in entry_sources for entry in source]:
        if not isinstance(raw_entry, dict):
            continue
        entry = _normalize_loadout_entry(raw_entry)
        char_key = str(entry.get("char_key") or "")
        if not char_key:
            continue
        if char_key not in entries_by_key:
            order.append(char_key)
        entries_by_key[char_key] = _merge_loadout_entry(entries_by_key.get(char_key), entry)

    # Integrity-proof metadata is not battle-time evidence. It may only fill
    # fields that the raw/parsed battle record did not provide; it must never
    # overwrite an observed value. Every such fill is marked for diagnostics.
    for raw_entry in _load_loadout_entries(proof):
        entry = _normalize_loadout_entry(raw_entry)
        char_key = str(entry.get("char_key") or "")
        if not char_key:
            continue
        if char_key not in entries_by_key:
            order.append(char_key)
            entries_by_key[char_key] = dict(entry)
            entries_by_key[char_key]["_loadout_fallback_used"] = True
            continue
        current = entries_by_key[char_key]
        filled = False
        critical_fallback_used = False
        for key, value in entry.items():
            if value in (None, "", [], {}):
                continue
            if key == "equips" and isinstance(value, list):
                existing_equips = current.get("equips")
                existing_equips = existing_equips if isinstance(existing_equips, list) else []
                by_slot = {
                    int(equip.get("slot")): equip
                    for equip in existing_equips
                    if isinstance(equip, dict) and equip.get("slot") is not None
                }
                for proof_equip in value:
                    if not isinstance(proof_equip, dict) or proof_equip.get("slot") is None:
                        continue
                    slot = int(proof_equip["slot"])
                    if slot not in by_slot:
                        existing_equips.append(dict(proof_equip))
                        by_slot[slot] = existing_equips[-1]
                        filled = True
                        critical_fallback_used = True
                        continue
                    target = by_slot[slot]
                    for equip_key, equip_value in proof_equip.items():
                        if equip_value not in (None, "", [], {}) and target.get(equip_key) in (None, "", [], {}):
                            target[equip_key] = equip_value
                            filled = True
                            critical_fallback_used = True
                current["equips"] = existing_equips
                continue
            if current.get(key) in (None, "", [], {}):
                current[key] = value
                filled = True
                if key != "char_name":
                    critical_fallback_used = True
        if filled and critical_fallback_used:
            current["_loadout_fallback_used"] = True

    return [entries_by_key[char_key] for char_key in order]


def _normalize_payload_equip_slots(equips: list[dict]) -> list[dict]:
    ordered = sorted(equips, key=lambda item: int(item.get("slot") or 0))
    raw_slots: list[int] = []
    for equip in ordered:
        try:
            raw_slots.append(int(equip.get("slot")))
        except (TypeError, ValueError):
            raw_slots.append(-1)
    looks_one_based = (
        len(raw_slots) == 4
        and 0 not in raw_slots
        and all(1 <= slot <= 4 for slot in raw_slots)
    )

    slots: list[dict | None] = [None, None, None, None]
    pending: list[dict] = []
    for equip in ordered:
        try:
            slot = int(equip.get("slot"))
        except (TypeError, ValueError):
            slot = -1
        normalized_slot = slot - 1 if looks_one_based else slot
        payload = {**equip, "slot": normalized_slot}
        if 0 <= normalized_slot < len(slots) and slots[normalized_slot] is None:
            slots[normalized_slot] = payload
        else:
            pending.append(payload)

    for equip in pending:
        try:
            original_slot = int(equip.get("slot"))
        except (TypeError, ValueError):
            original_slot = -1
        empty_index = next((index for index, value in enumerate(slots) if value is None), None)
        if empty_index is None:
            continue
        slots[empty_index] = {**equip, "slot": empty_index if original_slot < 0 or original_slot >= len(slots) else original_slot}

    return [equip for equip in slots if equip is not None]


def _build_loadout_by_character_key(
    proof: dict | None,
    *,
    loadout_entries: list[dict] | None = None,
) -> dict[str, dict]:
    weapon_catalog = _load_weapon_catalog()
    equip_catalog = _load_equip_catalog()
    loadouts: dict[str, dict] = {}

    for entry in (loadout_entries if loadout_entries is not None else _load_loadout_entries(proof)):
        char_key = str(entry.get("char_key") or "")
        if not char_key:
            continue

        character_level_raw = (
            entry.get("character_level")
            if entry.get("character_level") is not None
            else entry.get("char_level")
            if entry.get("char_level") is not None
            else entry.get("level")
        )

        weapon_template = str(entry.get("weapon_template") or "") or None
        weapon_catalog_entry = weapon_catalog.get(weapon_template or "")
        raw_weapon_name = str(entry.get("weapon_name") or "")
        if raw_weapon_name == weapon_template:
            raw_weapon_name = ""
        weapon_name = str(
            raw_weapon_name
            or (weapon_catalog_entry or {}).get("weaponName")
            or weapon_template
            or "未知武器"
        )

        equips: list[dict] = []
        for equip in sorted(entry.get("equips") or [], key=lambda item: int(item.get("slot") or 0)):
            if not isinstance(equip, dict):
                continue
            item_id = str(equip.get("item_id") or "") or None
            equip_catalog_entry = equip_catalog.get(item_id or "")
            equips.append(
                {
                    "slot": int(equip.get("slot") or 0),
                    "itemId": item_id,
                    "pieceName": str(
                        equip.get("piece_name")
                        or (equip_catalog_entry or {}).get("pieceName")
                        or item_id
                        or "未知装备"
                    ),
                    "suitName": str(equip.get("suit_name") or "") or None,
                    "partName": str(
                        equip.get("part_name")
                        or (equip_catalog_entry or {}).get("partName")
                        or ""
                    )
                    or None,
                    "iconUrl": (equip_catalog_entry or {}).get("iconUrl"),
                    # 排轴导出补全（2026-07-05 排轴器开发者需求）：精锻等级对 + 副词条实值/等级
                    "enhanceLevels": [
                        item for item in (equip.get("enhance_levels") or []) if isinstance(item, dict)
                    ],
                    "stats": [
                        item for item in (equip.get("stats") or []) if isinstance(item, dict)
                    ],
                }
            )
        equips = _normalize_payload_equip_slots(equips)

        # 武器三条词条技能各自的等级（同一把武器三词条可不同级，单一 refine 表达不了）；
        # 数字技能 id 尽量解析为字符串 id，失败保留数字原样。
        skill_id_map = _load_num_id_str_skill_map()
        weapon_skills: list[dict] = []
        for skill in entry.get("weapon_source_skills") or entry.get("weapon_refine_stats") or []:
            if not isinstance(skill, dict):
                continue
            raw_skill_id = str(skill.get("skill_id") or "")
            if not raw_skill_id:
                continue
            weapon_skills.append(
                {
                    "skillKey": skill_id_map.get(raw_skill_id, raw_skill_id),
                    "level": int(skill.get("level")) if skill.get("level") is not None else None,
                    "potentialLevel": (
                        int(skill.get("potential_level")) if skill.get("potential_level") is not None else None
                    ),
                }
            )

        # Never publish a hybrid loadout (for example, 爆破单元's template
        # carrying 四二式·肃阵's source skills).  The parser repairs weapon
        # moves when the surrounding snapshots contain the previous owner;
        # this is the final fail-closed guard for incomplete legacy traces.
        expected_weapon_main_skill = f"sk_{weapon_template}" if weapon_template else None
        weapon_main_skills = {
            str(skill.get("skillKey") or "")
            for skill in weapon_skills
            if str(skill.get("skillKey") or "").startswith("sk_wpn_")
        }
        weapon_skill_mismatch = bool(
            expected_weapon_main_skill
            and weapon_main_skills
            and expected_weapon_main_skill not in weapon_main_skills
        )
        if weapon_skill_mismatch:
            weapon_skills = []

        weapon_refine = (
            int(entry.get("weapon_refine"))
            if entry.get("weapon_refine") is not None
            else None
        )
        if weapon_skill_mismatch and entry.get("weapon_refine_source") == "source_skill":
            weapon_refine = None

        weapon_level_raw = int(entry.get("weapon_level")) if entry.get("weapon_level") is not None else None
        if not weapon_level_raw:
            # 包内 weaponLv 恒为 0：用 baseAtk 阶梯反查真实等级
            weapon_level_raw = _infer_weapon_level_from_base_atk(
                weapon_catalog_entry,
                entry.get("weapon_base_atk") or entry.get("weaponBaseAtk"),
            )

        loadouts[char_key] = {
            "characterLevel": int(character_level_raw) if character_level_raw is not None else None,
            "characterPotential": int(entry.get("potential")) if entry.get("potential") is not None else None,
            "weapon": {
                "weaponTemplate": weapon_template,
                "weaponName": weapon_name,
                "weaponLevel": weapon_level_raw,
                "weaponRefine": weapon_refine,
                "iconUrl": (weapon_catalog_entry or {}).get("iconUrl"),
                "skills": weapon_skills,
            }
            if weapon_name and weapon_name != "?"
            else None,
            "equips": equips,
        }

    return loadouts
