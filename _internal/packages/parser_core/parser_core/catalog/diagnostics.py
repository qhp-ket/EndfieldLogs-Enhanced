"""Diagnostic resource catalogs, affix descriptions and exported skill candidates."""
from __future__ import annotations
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any


_REPO_ROOT = Path(__file__).resolve().parents[4]


def _read_json_file(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _normalize_value_options(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def _selected_option_for_level(options: list[Any], level: Any) -> Any:
    if not options or level is None or isinstance(level, bool) or not isinstance(level, (int, str)):
        return None
    try:
        level_int = int(level)
    except (TypeError, ValueError):
        return None
    if 0 <= level_int < len(options):
        return options[level_int]
    return None


def _sub_affix_key_order(raw_key: Any) -> tuple[int, str]:
    match = re.search(r"(\d+)", str(raw_key))
    return (int(match.group(1)) if match else 99, str(raw_key))


def _build_affix_rows(item: dict[str, Any], levels: list[int] | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    levels = levels or []
    main_attr = item.get("主词条")
    if isinstance(main_attr, dict):
        rows.append(
            {
                "kind": "main",
                "index": 0,
                "desc": _clean_text(main_attr.get("desc")),
                "value": main_attr.get("value"),
                "value_options": _normalize_value_options(main_attr.get("value")),
                "level": None,
                "selected_value": main_attr.get("value"),
            }
        )
    sub_attrs = item.get("副词条")
    if isinstance(sub_attrs, dict):
        for index, key in enumerate(sorted(sub_attrs.keys(), key=_sub_affix_key_order)):
            attr = sub_attrs.get(key)
            if not isinstance(attr, dict):
                continue
            options = _normalize_value_options(attr.get("value"))
            level = levels[index] if index < len(levels) else None
            selected = _selected_option_for_level(options, level)
            rows.append(
                {
                    "kind": "sub",
                    "index": index,
                    "desc": _clean_text(attr.get("desc")),
                    "value": selected,
                    "value_options": options,
                    "level": level,
                    "selected_value": selected,
                }
            )
    return rows


@lru_cache(maxsize=1)
def _load_equip_affix_catalog() -> dict[str, dict[str, Any]]:
    catalog: dict[str, dict[str, Any]] = {}
    equip_root = _REPO_ROOT / "data" / "akedata" / "equip" / "items"
    if not equip_root.exists():
        return catalog
    for path in sorted(equip_root.glob("*.json")):
        payload = _read_json_file(path)
        if not isinstance(payload, dict):
            continue
        suit_id = str(payload.get("suitID") or path.stem)
        suit_name = _clean_text(payload.get("套组名称") or payload.get("displayName") or payload.get("name"))
        equip_items = payload.get("equip")
        if not isinstance(equip_items, dict):
            continue
        for item_id, item in equip_items.items():
            if not isinstance(item, dict):
                continue
            item_key = str(item.get("itemId") or item_id)
            catalog[item_key] = {
                "item_id": item_key,
                "piece_name": _clean_text(item.get("name")),
                "suit_id": suit_id,
                "suit_name": suit_name,
                "part_name": _clean_text(item.get("部位")),
                "affixes": _build_affix_rows(item),
            }
    return catalog


@lru_cache(maxsize=1)
def _load_weapon_affix_catalog() -> dict[str, dict[str, Any]]:
    catalog: dict[str, dict[str, Any]] = {}
    weapon_root = _REPO_ROOT / "data" / "akedata" / "weapon" / "items"
    if not weapon_root.exists():
        return catalog
    for path in sorted(weapon_root.glob("*.json")):
        payload = _read_json_file(path)
        if not isinstance(payload, dict):
            continue
        weapon_id = str(payload.get("weaponId") or path.stem)
        catalog[weapon_id] = {
            "weapon_template": weapon_id,
            "weapon_name": _clean_text(payload.get("title") or payload.get("name") or weapon_id),
            "weapon_base_atk_values": payload.get("baseAtk") if isinstance(payload.get("baseAtk"), list) else [],
            "weapon_skilllist": payload.get("skilllist") if isinstance(payload.get("skilllist"), list) else [],
        }
    return catalog


@lru_cache(maxsize=1)
def _load_character_attr_type_catalog() -> dict[str, dict[str, int | None]]:
    root = _REPO_ROOT / "data" / "local_tables" / "character" / "items"
    catalog: dict[str, dict[str, int | None]] = {}
    if not root.is_dir():
        return catalog
    for path in root.glob("chr_*.json"):
        payload = _read_json_file(path)
        raw = payload.get("raw") if isinstance(payload, dict) and isinstance(payload.get("raw"), dict) else {}
        main_attr_type = raw.get("mainAttrType")
        sub_attr_type = raw.get("subAttrType")
        try:
            main_attr_int = int(main_attr_type) if main_attr_type is not None else None
        except (TypeError, ValueError):
            main_attr_int = None
        try:
            sub_attr_int = int(sub_attr_type) if sub_attr_type is not None else None
        except (TypeError, ValueError):
            sub_attr_int = None
        catalog[path.stem] = {
            "main_attr_type": main_attr_int,
            "sub_attr_type": sub_attr_int,
        }
    return catalog


@lru_cache(maxsize=None)
def _load_exported_character_skill_groups(character_key: str) -> list[dict[str, Any]]:
    path = _REPO_ROOT / "data" / "akedata" / "character" / "items" / f"{character_key}.json"
    payload = _read_json_file(path)
    if not isinstance(payload, dict):
        return []
    labels = {0: "普攻", 1: "战技", 2: "终结", 3: "连携"}
    groups: list[dict[str, Any]] = []
    for skill in payload.get("skills") or []:
        if not isinstance(skill, dict):
            continue
        try:
            group_type = int(skill.get("groupType") or 0)
        except (TypeError, ValueError):
            group_type = 0
        skill_ids = [str(skill_id) for skill_id in skill.get("skillIds") or [] if skill_id]
        if not skill_ids:
            continue
        groups.append(
            {
                "group_type": group_type,
                "group_label": labels.get(group_type, str(group_type)),
                "name": _clean_text(skill.get("name")) or labels.get(group_type, ""),
                "skill_ids": skill_ids,
            }
        )
    return groups


@lru_cache(maxsize=1)
def _load_skill_action_graph_candidate_map() -> dict[str, list[dict[str, Any]]]:
    return {}

    path = _REPO_ROOT / "data" / "packet_semantics" / "skill_action_graph_candidates.json"
    payload = _read_json_file(path)
    if not isinstance(payload, dict):
        return {}
    candidates = payload.get("candidates")
    if not isinstance(candidates, dict):
        return {}
    result: dict[str, list[dict[str, Any]]] = {}
    for skill_key, rows in candidates.items():
        if not isinstance(rows, list):
            continue
        normalized_rows: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            candidate_skill_id = str(row.get("candidate_skill_id") or "")
            if not candidate_skill_id:
                continue
            normalized_rows.append(
                {
                    "candidate_skill_id": candidate_skill_id,
                    "display_name": str(row.get("display_name") or candidate_skill_id),
                    "confidence": str(row.get("confidence") or "action_graph_candidate"),
                    "source": str(row.get("source") or "akedata_action_graph"),
                    "reason": str(row.get("reason") or ""),
                    "evidence": [str(item) for item in row.get("evidence") or []],
                }
            )
        if normalized_rows:
            result[str(skill_key)] = normalized_rows
    return result
