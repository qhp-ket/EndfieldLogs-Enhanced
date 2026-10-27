"""Static resource paths and equipment catalogs; caches belong to this module."""
from __future__ import annotations
import hashlib
import json
import os
import re
import sys
from functools import lru_cache
from math import isfinite
from pathlib import Path
from typing import Any
from parser_core.ingestion.fields import _coerce_optional_int




def _parse_suit_counts(raw: str | None) -> list[dict[str, Any]]:
    suits: list[dict[str, Any]] = []
    catalog = _load_suit_catalog()
    for suit_id, count_text in re.findall(r"\[([^\]]+)\]=(\d+)", str(raw or "")):
        count = int(count_text)
        meta = catalog.get(suit_id, {})
        suits.append(
            {
                "suit_id": suit_id,
                "suit_name": meta.get("suit_name") or suit_id,
                "piece_count": count,
                "required_piece_count": meta.get("required_piece_count"),
                "active": (type(meta.get("required_piece_count")) is int
                           and count >= int(meta["required_piece_count"])),
                "description": meta.get("description") or "",
                "value": meta.get("value") or {},
            }
        )
    return suits


_NATIVE_DAMAGE_SEMANTICS_BINDING = {
    'gameAssemblySha256': 'c24495e51b406f03b03890c4788ee618ae022c991405be5d5b8b787cb775ae89',
    'metadataSha256': '0076743397acadf03d3b0064343a963c7c88863b8160526d397e4b3efb96f02e',
}


def _iter_json_entries(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    entries = payload.get("entries") if isinstance(payload, dict) else payload
    if not isinstance(entries, list):
        return []
    return [entry for entry in entries if isinstance(entry, dict)]


def _repo_root() -> Path:
    override = os.environ.get("ENDFIELD_LOGS_DATA_ROOT")
    if override:
        return Path(override)
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(frozen_root)
    return Path(__file__).resolve().parents[4]


@lru_cache(maxsize=1)
def _load_weapon_catalog() -> dict[str, dict[str, Any]]:
    root = _repo_root() / "data" / "akedata" / "weapon" / "items"
    catalog: dict[str, dict[str, Any]] = {}
    try:
        attack_catalog = json.loads((_repo_root() / 'data/packet_semantics/weapon_static_attack_catalog.json').read_text(encoding='utf8'))
    except (OSError, json.JSONDecodeError):
        attack_catalog = {}
    attack_fields = (attack_catalog.get('entries') or []) if (
        attack_catalog.get('schemaVersion') == 1
        and attack_catalog.get('source') == 'current_WeaponSkill_cardAttributeModifier'
        and attack_catalog.get('decoder') == _NATIVE_DAMAGE_SEMANTICS_BINDING) else []
    for path in root.glob("*.json") if root.is_dir() else []:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        weapon_id = str(payload.get("weaponId") or path.stem)
        catalog[weapon_id] = {
            "weapon_template": weapon_id,
            "weapon_name": str(payload.get("title") or payload.get("name") or weapon_id),
            "weapon_type": payload.get("weapontype"),
            "rarity": payload.get("rarity"),
            "base_atk_values": payload.get("baseAtk") if isinstance(payload.get("baseAtk"), list) else [],
            "skilllist": payload.get("skilllist") if isinstance(payload.get("skilllist"), list) else [],
        }
    local_manifest = _repo_root() / "data" / "local_tables" / "weapon" / "manifest.json"
    try:
        local_payload = json.loads(local_manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        local_payload = {}
    for item in local_payload.get("entries", []) if isinstance(local_payload, dict) else []:
        if not isinstance(item, dict):
            continue
        weapon_id = str(item.get("weaponId") or item.get("id") or "")
        if not weapon_id:
            continue
        current = catalog.setdefault(weapon_id, {"weapon_template": weapon_id, "base_atk_values": [], "skilllist": []})
        current["weapon_name"] = str(item.get("name") or current.get("weapon_name") or weapon_id)
        current["weapon_type"] = item.get("weaponType") or current.get("weapon_type")
        current["rarity"] = item.get("rarity") or current.get("rarity")
        definition_path = _repo_root() / 'data/local_tables/weapon/items' / f'{weapon_id}.json'
        try:
            definition_bytes = definition_path.read_bytes()
            definition = json.loads(definition_bytes)
        except (OSError, json.JSONDecodeError):
            continue
        skills = (definition.get('raw') or {}).get('weaponSkillList')
        if isinstance(skills, list) and all(isinstance(skill, str) for skill in skills):
            current['weapon_skill_ids'] = list(skills)
            current['weapon_definition_sha256'] = hashlib.sha256(definition_bytes).hexdigest()
            current['static_attack_fields'] = [dict(field) for field in attack_fields
                if field.get('weaponId') == weapon_id and field.get('skillId') in skills
                and field.get('modifyAttributeType') == 'Specific'
                and field.get('formulaItem') in {'BaseMultiplier', 'BaseFinalAddition'}
                and isinstance(field.get('bbKey'), str)
                and isinstance(field.get('sourceRootSha256'), str)
                and re.fullmatch(r'[0-9a-f]{64}', field['sourceRootSha256'])]
    return catalog


@lru_cache(maxsize=1)
def _load_character_base_stat_catalog() -> dict[str, dict[int, dict[str, Any]]]:
    root = _repo_root() / "data" / "local_tables" / "character" / "items"
    catalog: dict[str, dict[int, dict[str, Any]]] = {}
    if not root.is_dir():
        return catalog
    for path in root.glob("chr_*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        raw = payload.get("raw") if isinstance(payload.get("raw"), dict) else {}
        attributes = raw.get("attributes") if isinstance(raw, dict) else []
        if not isinstance(attributes, list):
            continue
        level_rows: dict[int, dict[str, Any]] = {}
        ambiguous_levels: set[int] = set()
        for row in attributes:
            if not isinstance(row, dict):
                continue
            attr_blob = row.get("Attribute") if isinstance(row.get("Attribute"), dict) else {}
            attrs = attr_blob.get("attrs") if isinstance(attr_blob, dict) else []
            if not isinstance(attrs, list):
                continue
            values: dict[int, float] = {}
            level = None
            for item in attrs:
                if not isinstance(item, dict):
                    continue
                try:
                    attr_type = int(item.get("attrType"))
                    attr_value = float(item.get("attrValue"))
                except (TypeError, ValueError):
                    continue
                values[attr_type] = attr_value
                if attr_type == 0 and isfinite(attr_value) and attr_value.is_integer():
                    level = int(attr_value)
            if level is None or level in ambiguous_levels:
                continue
            break_stage = _coerce_optional_int(row.get("breakStage"))
            previous = level_rows.get(level)
            current = {
                "level": level,
                "main_attr_type": raw.get('mainAttrType'),
                "sub_attr_type": raw.get('subAttrType'),
                "break_stage": break_stage,
                "hp": values.get(1),
                "atk": values.get(2),
                "def": values.get(3),
                "attr_39": values.get(39),
                "attr_40": values.get(40),
                "attr_41": values.get(41),
                "attr_42": values.get(42),
            }
            if previous is not None and previous != current:
                level_rows.pop(level)
                ambiguous_levels.add(level)
                continue
            level_rows[level] = current
        if level_rows:
            catalog[path.stem] = level_rows
    return catalog


@lru_cache(maxsize=1)
def _load_suit_catalog() -> dict[str, dict[str, Any]]:
    root = _repo_root() / "data" / "akedata" / "equip" / "items"
    catalog: dict[str, dict[str, Any]] = {}
    for path in root.glob("*.json") if root.is_dir() else []:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        suit_id = str(payload.get("suitID") or path.stem)
        catalog[suit_id] = {
            "suit_id": suit_id,
            "suit_name": str(payload.get("套组名称") or payload.get("name") or suit_id),
            "description": str(payload.get("技能描述") or ""),
            "value": payload.get("value") if isinstance(payload.get("value"), dict) else {},
        }
    local_root = _repo_root() / "data" / "local_tables" / "equip" / "items"
    for path in local_root.glob("*.json") if local_root.is_dir() else []:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        suit_id = str(payload.get("suitID") or path.stem)
        current = catalog.setdefault(suit_id, {"suit_id": suit_id})
        current.update({
            "suit_name": str(payload.get("name") or payload.get("displayName") or current.get("suit_name") or suit_id),
            "description": str(payload.get("skillDescription") or current.get("description") or ""),
            "value": payload.get("value") if isinstance(payload.get("value"), dict) else current.get("value", {}),
            "required_piece_count": payload.get("requiredPieceCount") if type(payload.get("requiredPieceCount")) is int else None,
        })
    return catalog


@lru_cache(maxsize=1)
def _load_weapon_refine_catalog() -> dict[str, Any]:
    path = _repo_root() / 'data' / 'local_tables' / 'weapon' / 'refine_catalog.json'
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return {}
    return data.get('entries', {}) if isinstance(data, dict) else {}


@lru_cache(maxsize=1)
def _load_equip_item_catalog() -> dict[str, dict[str, Any]]:
    root = _repo_root() / "data" / "akedata" / "equip" / "items"
    catalog: dict[str, dict[str, Any]] = {}
    for path in root.glob("*.json") if root.is_dir() else []:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        suit_id = str(payload.get("suitID") or path.stem)
        suit_name = str(payload.get("套组名称") or suit_id)
        equip_items = payload.get("equip")
        if not isinstance(equip_items, dict):
            continue
        for item_id, item in equip_items.items():
            if not isinstance(item, dict):
                continue
            key = str(item.get("itemId") or item_id)
            catalog[key] = {
                "item_id": key,
                "item_name": str(item.get("name") or key),
                "suit_id": suit_id,
                "suit_name": suit_name,
                "part_name": str(item.get("部位") or ""),
                "rarity": item.get("rarity"),
                "main_attr": item.get("主词条") if isinstance(item.get("主词条"), dict) else None,
                "sub_attrs": item.get("副词条") if isinstance(item.get("副词条"), dict) else {},
            }
    local_root = _repo_root() / "data" / "local_tables" / "equip"
    suit_names: dict[str, str] = {}
    for suit_path in (local_root / "items").glob("*.json") if (local_root / "items").is_dir() else []:
        try:
            suit_payload = json.loads(suit_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(suit_payload, dict):
            suit_id = str(suit_payload.get("suitID") or suit_path.stem)
            suit_names[suit_id] = str(suit_payload.get("name") or suit_payload.get("displayName") or suit_id)
    pieces_path = local_root / "pieces.json"
    try:
        pieces_payload = json.loads(pieces_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pieces_payload = {}
    for item in pieces_payload.get("entries", []) if isinstance(pieces_payload, dict) else []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("itemId") or item.get("id") or "")
        if not key:
            continue
        typed_attributes = item.get('equipAttrModifiers')
        typed_proof = pieces_payload.get('sourceTableSha256')
        if key in catalog:
            catalog[key]['attribute_modifiers'] = typed_attributes
            catalog[key]['attribute_source_sha256'] = typed_proof
            continue
        main = item.get("displayBaseAttrModifier")
        sub_rows = item.get("displayAttrModifiers") if isinstance(item.get("displayAttrModifiers"), list) else []
        main_attr = None
        if isinstance(main, dict):
            main_attr = {"desc": f"attribute_type_{main.get('attrType')}", "value": main.get("attrValue")}
        sub_attrs: dict[str, dict[str, Any]] = {}
        for index, row in enumerate(sub_rows, start=1):
            if not isinstance(row, dict):
                continue
            values = [row.get("attrValue"), *(row.get("enhancedAttrValues") or [])]
            sub_attrs[f"词条{index}"] = {"desc": f"attribute_type_{row.get('attrType')}", "value": values}
        suit_id = str(item.get("suitID") or "suit_none")
        catalog[key] = {
            "item_id": key,
            "item_name": str(item.get("name") or key),
            "suit_id": suit_id,
            "suit_name": suit_names.get(suit_id, suit_id),
            "part_name": str(item.get("partName") or ""),
            "rarity": item.get("rarity"),
            "main_attr": main_attr,
            "sub_attrs": sub_attrs,
            "attribute_modifiers": typed_attributes,
            "attribute_source_sha256": typed_proof,
        }
    return catalog


@lru_cache(maxsize=None)
def _load_character_potential_rows(character_key: str) -> list[dict[str, Any]]:
    path = _repo_root() / "data" / "akedata" / "character" / "items" / f"{character_key}.json"
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [row for row in payload.get("potentials") or [] if isinstance(row, dict)]
