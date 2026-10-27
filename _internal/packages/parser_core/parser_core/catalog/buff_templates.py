"""Typed buff resources, classifier hints and weapon/equipment stack catalogs."""
from __future__ import annotations

from functools import lru_cache
from parser_core.catalog.names import _CURRENT_TYPED_RESOURCE_BINDING
from parser_core.catalog.resources import _NATIVE_DAMAGE_SEMANTICS_BINDING, _iter_json_entries, _repo_root
from parser_core.ingestion.fields import _positive_int
import gzip
import json
from typing import Any

from parser_core.catalog.resources import _repo_root




_BUFF_ACTION_TYPES_INDEX: tuple[dict, dict] | None = None


@lru_cache(maxsize=1)
def _load_classifier_hints() -> dict[str, Any]:
    candidates = [
        _repo_root() / "data" / "local_semantics" / "classifier_hints.json",
    ]
    for path in candidates:
        try:
            if not path.is_file():
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            return data
    return {}


@lru_cache(maxsize=1)
def _load_nonstacking_weapon_ids() -> set[str]:
    roots = [
        _repo_root() / "data" / "akedata" / "weapon" / "items",
    ]
    markers = ("无法叠加", "不能叠加", "不可叠加")
    weapon_ids: set[str] = set()
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.glob("*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict):
                continue
            weapon_id = str(payload.get("weaponId") or path.stem)
            text_parts: list[str] = []
            for skill in payload.get("skilllist") or []:
                if isinstance(skill, dict):
                    text_parts.append(str(skill.get("description") or ""))
            text_parts.append(str(payload.get("description") or ""))
            if any(marker in "\n".join(text_parts) for marker in markers):
                weapon_ids.add(weapon_id)
        if weapon_ids:
            break
    return weapon_ids


def _blackboard_max_stack_from_weapon_skill(skill: dict[str, Any]) -> int | None:
    description = str(skill.get("description") or "")
    if "叠加" not in description and "max_stack" not in description:
        return None
    for item in skill.get("blackboard") or []:
        if not isinstance(item, dict) or item.get("key") != "max_stack":
            continue
        raw_value = item.get("value")
        values = raw_value if isinstance(raw_value, list) else [raw_value]
        stack_values = [value for value in (_positive_int(value) for value in values) if value is not None]
        if stack_values:
            return min(stack_values)
    return None


@lru_cache(maxsize=1)
def _load_weapon_id_stack_limits() -> dict[str, int]:
    roots = [
        _repo_root() / "data" / "akedata" / "weapon" / "items",
    ]
    limits: dict[str, int] = {}
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.glob("*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict):
                continue
            weapon_id = str(payload.get("weaponId") or path.stem)
            for skill in payload.get("skilllist") or []:
                if not isinstance(skill, dict):
                    continue
                max_stack = _blackboard_max_stack_from_weapon_skill(skill)
                if max_stack is not None:
                    limits[weapon_id] = max_stack
                    break
        if limits:
            break
    return limits


@lru_cache(maxsize=1)
def _load_weapon_buff_stack_limits() -> dict[str, int]:
    paths = [
        _repo_root() / "data" / "local_static" / "skill" / "manifest.json",
    ]
    limits: dict[str, int] = {}
    for path in paths:
        if not path.is_file():
            continue
        for entry in _iter_json_entries(path):
            skill_id = str(entry.get("id") or "")
            if not skill_id.startswith("sk_wpn_"):
                continue
            binary_probe = entry.get("binaryProbe")
            if not isinstance(binary_probe, dict):
                continue
            max_stack = None
            for hint in binary_probe.get("blackboardDoubleHints") or []:
                if not isinstance(hint, dict) or hint.get("key") != "max_stack":
                    continue
                max_stack = _positive_int(hint.get("value"))
                if max_stack is not None:
                    break
            if max_stack is None:
                continue
            created_buff_ids = binary_probe.get("highConfidenceCreatedBuffIds") or binary_probe.get("createdBuffIds") or []
            if not isinstance(created_buff_ids, list):
                continue
            for buff_id in created_buff_ids:
                buff_key = str(buff_id or "")
                if buff_key.startswith("buff_wpn_"):
                    limits[buff_key] = max_stack
        if limits:
            break
    return limits


@lru_cache(maxsize=1)
def _load_local_skill_semantic_entries() -> dict[str, dict[str, Any]]:
    details_path = _repo_root() / "data" / "local_semantics" / "skill" / "details.json"
    if not details_path.exists():
        return {}
    try:
        payload = json.loads(details_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    entries = payload.get("entries")
    if not isinstance(entries, dict):
        return {}
    return {
        str(skill_id): entry
        for skill_id, entry in entries.items()
        if isinstance(entry, dict)
    }


@lru_cache(maxsize=1)
def _load_current_buff_roots() -> dict[str, dict[str, Any]]:
    global _BUFF_ACTION_TYPES_INDEX
    _BUFF_ACTION_TYPES_INDEX = None
    path = _repo_root() / 'data/local_static/buff/typed_roots.json.gz'
    damage_path = _repo_root() / 'data/local_static/skill/damage_element_catalog.json'
    try:
        payload = json.loads(gzip.decompress(path.read_bytes()))
        damage_catalog = json.loads(damage_path.read_text(encoding='utf-8'))
    except (OSError, EOFError, ValueError):
        return {}
    if not isinstance(payload, dict) or not isinstance(damage_catalog, dict):
        return {}
    decoder = payload.get('decoder')
    if not isinstance(decoder, dict):
        return {}
    if (payload.get('schemaVersion') != 1
            or payload.get('source') != 'official_local_buffdata_memorypack'
            or decoder.get('kind') != 'typed_root_deserialization'
            or any(decoder.get(key) != value for key, value in _CURRENT_TYPED_RESOURCE_BINDING.items())
            or payload.get('decoder') != damage_catalog.get('decoder')
            or damage_catalog.get('schemaVersion') != 2
            or damage_catalog.get('source') != 'official_local_skilldata_memorypack'):
        return {}
    summary = payload.get('summary') or {}
    entries = payload.get('entries')
    if (not isinstance(entries, dict) or summary.get('completeRootCount') != len(entries)
            or summary.get('inputResourceCount') != len(entries)):
        return {}
    roots = {}
    for key, entry in entries.items():
        if not isinstance(entry, dict):
            continue
        root, proof = entry.get('root'), entry.get('proof') or {}
        size = proof.get('sourceBytes')
        if (not isinstance(root, dict) or root.get('id') != key
                or root.get('$type') != 'Beyond.Gameplay.Core.BuffData'
                or root.get('$offset') != 0
                or type(size) is not int or size <= 0
                or proof.get('consumedBytes') != size or root.get('$end') != size):
            continue
        roots[key] = root
    action_type_index = {}
    for key, root in roots.items():
        types = set()
        pending = [root]
        while pending:
            value = pending.pop()
            if isinstance(value, dict):
                type_name = str(value.get('$type') or '')
                if type_name:
                    types.add(type_name.replace('+', '.'))
                pending.extend(value.values())
            elif isinstance(value, list):
                pending.extend(value)
        action_type_index[key] = frozenset(types)
    _BUFF_ACTION_TYPES_INDEX = (roots, action_type_index)
    return roots


@lru_cache(maxsize=1)
def _load_damage_zone_config() -> dict[str, dict[str, Any]]:
    path = _repo_root() / 'data/local_static/damage_zone_config.json'
    try:
        payload = json.loads(path.read_text(encoding='utf8'))
    except (OSError, ValueError):
        return {}
    decoder = payload.get('decoder') if isinstance(payload, dict) else None
    zones = payload.get('zones') if isinstance(payload, dict) else None
    if (payload.get('schemaVersion') != 1
            or payload.get('source') != 'official_unity_typetree_damage_zone_config'
            or not isinstance(decoder, dict)
            or any(decoder.get(k) != v for k, v in _NATIVE_DAMAGE_SEMANTICS_BINDING.items())
            or not isinstance(zones, list) or not zones):
        return {}
    result = {}
    for index, zone in enumerate(zones):
        if (not isinstance(zone, dict) or type(zone.get('name')) is not str
                or type(zone.get('isMultiplyZone')) is not int
                or type(zone.get('serverIndex')) is not int):
            return {}
        result[zone['name']] = {**zone, 'clientIndex': index}
    return result


@lru_cache(maxsize=1)
def _load_local_buff_semantic_entries() -> dict[str, dict[str, Any]]:
    details_path = _repo_root() / "data" / "local_semantics" / "buff" / "details.json"
    if not details_path.exists():
        return {}
    try:
        payload = json.loads(details_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    entries = payload.get("entries")
    if not isinstance(entries, dict):
        return {}
    return {
        str(buff_id): entry
        for buff_id, entry in entries.items()
        if isinstance(entry, dict)
    }


@lru_cache(maxsize=16384)
def _buff_child_family_ids(buff_id: str) -> set[str]:
    seen: set[str] = set()
    frontier = [str(buff_id or "")]
    entries = _load_local_buff_semantic_entries()
    while frontier:
        current = frontier.pop()
        if not current or current in seen:
            continue
        seen.add(current)
        entry = entries.get(current)
        if not isinstance(entry, dict):
            continue
        for field in ("createdBuffIds", "referencedBuffIds", "binaryCreatedBuffIds", "binaryReferencedBuffIds"):
            for child in entry.get(field) or []:
                child_id = str(child or "")
                if child_id and child_id not in seen:
                    frontier.append(child_id)
    return seen


@lru_cache(maxsize=1)
def _load_equip_suit_allowed_buffs() -> dict[str, set[str]]:
    skill_entries = _load_local_skill_semantic_entries()
    equip_root = _repo_root() / "data" / "local_tables" / "equip" / "items"
    result: dict[str, set[str]] = {}
    if not equip_root.is_dir():
        return result
    for path in sorted(equip_root.glob("suit_*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        suit_id = str(payload.get("suitID") or "")
        passive_skill_id = str(payload.get("passiveSkillId") or "")
        if not suit_id or not passive_skill_id:
            continue
        entry = skill_entries.get(passive_skill_id)
        if not isinstance(entry, dict):
            continue
        root_buffs = {
            str(buff_id or "")
            for field in ("createdBuffIds", "referencedBuffIds", "binaryCreatedBuffIds", "binaryReferencedBuffIds")
            for buff_id in (entry.get(field) or [])
            if str(buff_id or "").startswith("buff_equipsuit_")
        }
        allowed: set[str] = set()
        for buff_id in root_buffs:
            allowed.update(_buff_child_family_ids(buff_id))
        if allowed:
            result[suit_id] = allowed
    return result



def _buff_classifier_hint(buff_id: str) -> dict[str, Any] | None:
    hints = _load_classifier_hints().get("buffHints")
    if not isinstance(hints, dict):
        return None
    hint = hints.get(buff_id)
    return hint if isinstance(hint, dict) else None


def _buff_effect_hint_candidates(buff_id: str) -> list[Any]:
    hint = _buff_classifier_hint(buff_id)
    if not hint:
        return []
    resolved = hint.get("resolvedEffectHints")
    if isinstance(resolved, list) and resolved:
        return resolved
    direct = hint.get("effectHints")
    return direct if isinstance(direct, list) else []


def _buff_decoded_detail_path(buff_id: str) -> Path | None:
    entry = _load_local_buff_semantic_entries().get(str(buff_id or ""))
    if not isinstance(entry, dict):
        return None
    source = entry.get("source") if isinstance(entry.get("source"), dict) else {}
    path_text = str(source.get("decodedDetailPath") or "")
    if path_text:
        path = _repo_root() / path_text
        if path.is_file():
            return path
    fallback = _repo_root() / "data" / "akedata" / "buff" / "items" / f"{buff_id}.json"
    return fallback if fallback.is_file() else None



@lru_cache(maxsize=4096)
def _related_child_buff_ids(buff_id: str) -> set[str]:
    ids: set[str] = set()
    entry = _load_local_buff_semantic_entries().get(str(buff_id or ""))
    if isinstance(entry, dict):
        ids.update(str(value) for value in entry.get("createdBuffIds") or [] if str(value or ""))
        ids.update(str(value) for value in entry.get("referencedBuffIds") or [] if str(value or ""))
    hint = _buff_classifier_hint(str(buff_id or "")) or {}
    ids.update(str(value) for value in hint.get("createdBuffIds") or [] if str(value or ""))
    ids.update(str(value) for value in hint.get("referencedBuffIds") or [] if str(value or ""))
    return ids


@lru_cache(maxsize=4096)
def _skill_related_buff_ids(skill_id: str) -> set[str]:
    ids: set[str] = set()
    entry = _load_local_skill_semantic_entries().get(str(skill_id or ""))
    if isinstance(entry, dict):
        ids.update(str(value) for value in entry.get("createdBuffIds") or [] if str(value or ""))
        ids.update(str(value) for value in entry.get("referencedBuffIds") or [] if str(value or ""))
    return ids
