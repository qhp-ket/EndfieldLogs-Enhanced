"""Version-bound official skill damage profiles and exact action damage units."""
from __future__ import annotations

from functools import lru_cache
from parser_core.catalog.buff_templates import _load_current_buff_roots
from parser_core.catalog.names import _CURRENT_TYPED_RESOURCE_BINDING, _canonical_packet_skill_id
from parser_core.catalog.resources import _repo_root
from parser_core.ingestion.fields import _coerce_optional_int
import copy
import json
import re
from typing import Any


_DAMAGE_TAG_TO_ELEMENT = {
    "pd": "physical",
    "fire": "fire",
    "cryst": "cryst",
    "pulse": "pulse",
    "natur": "natural",
    "natural": "natural",
}


@lru_cache(maxsize=1)
def _load_character_profiles() -> dict[str, dict[str, str]]:
    manifest_path = _repo_root() / "data" / "local_tables" / "character" / "manifest.json"
    if not manifest_path.exists():
        return {}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = manifest.get("entries") if isinstance(manifest, dict) else manifest
    return {
        str(entry.get("charId")): {
            "name": str(entry.get("name") or ""),
            "char_type": str(entry.get("charTypeId") or entry.get("charTypeName") or ""),
            "profession": str(entry.get("professionName") or entry.get("profession") or ""),
            "weapon_type": str(entry.get("weaponTypeName") or ""),
        }
        for entry in (entries or [])
        if entry.get("charId")
    }


@lru_cache(maxsize=1)
def _load_official_skill_damage_catalog() -> dict[str, dict[str, Any]]:
    path = _repo_root() / "data" / "local_static" / "skill" / "damage_element_catalog.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict) or payload.get("source") != "official_local_skilldata_memorypack":
        return {}
    decoder = payload.get('decoder')
    if not isinstance(decoder, dict):
        return {}
    if (payload.get('schemaVersion') != 2
            or decoder.get('kind') != 'typed_root_deserialization'
            or any(decoder.get(key) != value for key, value in _CURRENT_TYPED_RESOURCE_BINDING.items())
            or payload.get('decodeErrors')):
        return {}
    summary = payload.get('summary') or {}
    count = summary.get('inputResourceCount')
    if type(count) is not int or count <= 0 or summary.get('completeRootCount') != count:
        return {}
    skills = payload.get("skills")
    if not isinstance(skills, dict):
        return {}
    verified = {}
    for key, profile in skills.items():
        if not isinstance(profile, dict) or profile.get('derivedFrom'):
            continue
        proof = profile.get('proof') or {}
        if (proof.get('actionBoundaries') != 'typed_root_deserialization'
                or type(proof.get('sourceBytes')) is not int
                or proof['sourceBytes'] <= 0
                or proof.get('consumedBytes') != proof['sourceBytes']):
            continue
        actions = profile.get('actions')
        if not isinstance(actions, dict) or any(
            not isinstance(units, list) or any(
                not isinstance(unit, dict) or unit.get('source') != 'typed_memorypack_full_object'
                for unit in units
            ) for units in actions.values()
        ):
            continue
        verified[key] = profile
    return verified


@lru_cache(maxsize=1)
def _load_official_skill_damage_prefixes() -> list[tuple[str, dict[str, Any]]]:
    return sorted(_load_official_skill_damage_catalog().items(), key=lambda item: len(item[0]), reverse=True)


def _resolve_official_skill_damage_profile(skill_key: str | None) -> dict[str, Any] | None:
    if not skill_key:
        return None
    canonical = _canonical_packet_skill_id(skill_key)
    exact = _load_official_skill_damage_catalog().get(canonical)
    return exact


@lru_cache(maxsize=1)
def _load_skill_profiles() -> dict[str, dict[str, Any]]:
    character_root = _repo_root() / "data" / "akedata" / "character" / "items"
    skill_item_root = _repo_root() / "data" / "akedata" / "skill" / "items"
    if not character_root.exists():
        return {}

    profiles = _load_character_profiles()
    mapping: dict[str, dict[str, Any]] = {}
    damage_tag_re = re.compile(r"<@ba\.([a-z_]+)>")
    for path in character_root.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        char_key = str(data.get("charId") or "")
        if not char_key:
            continue
        char_profile = profiles.get(char_key, {})
        char_type = char_profile.get("char_type") or str(data.get("charType") or "")
        profession = char_profile.get("profession") or str(data.get("profession") or "")
        weapon_type = char_profile.get("weapon_type") or str(data.get("weapontype") or "")
        for skill in data.get("skills") or []:
            try:
                group_type = int(skill.get("groupType") or 0)
            except (TypeError, ValueError):
                group_type = 0
            skill_ids = [str(skill_id or "") for skill_id in (skill.get("skillIds") or []) if skill_id]
            description = str(skill.get("description") or "")
            tags = {match.group(1) for match in damage_tag_re.finditer(description)}
            elements = {
                _DAMAGE_TAG_TO_ELEMENT[tag]
                for tag in tags
                if tag in _DAMAGE_TAG_TO_ELEMENT
            }
            family_skill_key = skill_ids[0] if group_type == 3 and skill_ids else ""
            for skill_key in skill_ids:
                skill_item_spec = ""
                skill_item_path = skill_item_root / f"{skill_key}.json"
                if skill_item_path.exists():
                    try:
                        skill_item = json.loads(skill_item_path.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        skill_item = {}
                    skill_item_spec = str(skill_item.get("skillSpecification") or "")
                mapping[skill_key] = {
                    "char_key": char_key,
                    "char_type": char_type,
                    "profession": profession,
                    "weapon_type": weapon_type,
                    "group_type": group_type,
                    "skill_specification": skill_item_spec,
                    "elements": sorted(elements),
                    # combo => 连携，同一条连携的多个分段应共享展示家族
                    "family_skill_key": family_skill_key or skill_key,
                }
    return mapping


@lru_cache(maxsize=4096)
def _load_skill_item_metadata(skill_key: str) -> dict[str, Any]:
    if not skill_key:
        return {}
    path = _repo_root() / "data" / "akedata" / "skill" / "items" / f"{skill_key}.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    dynamic_action_keys: dict[int, str] = {}
    pending_nodes: list[Any] = [payload]
    while pending_nodes:
        node = pending_nodes.pop()
        if isinstance(node, dict):
            node_type = str(node.get("$type") or "").replace("+", ".")
            if ("ModifyDynamicBlackboard.Data" in node_type
                    or "SimpleCalcBBAction.Data" in node_type):
                action_index = _coerce_optional_int(node.get("serverActionIndex"))
                key = str(node.get("key") or "")
                if action_index is not None and key:
                    dynamic_action_keys[action_index] = key
            pending_nodes.extend(node.values())
        elif isinstance(node, list):
            pending_nodes.extend(node)
    return {
        "skill_specification": str(payload.get("skillSpecification") or ""),
        "cast_type": str(payload.get("castType") or ""),
        "attack_range_type": str(payload.get("attackRangeType") or ""),
        "dynamic_action_keys": dynamic_action_keys,
    }


@lru_cache(maxsize=4096)
def _load_skill_action_damage_units(skill_key: str) -> dict[int, list[dict[str, Any]]]:
    if not skill_key:
        return {}
    canonical = _canonical_packet_skill_id(skill_key)
    profile = _load_official_skill_damage_catalog().get(canonical)
    if not isinstance(profile, dict):
        return {}
    actions: dict[int, list[dict[str, Any]]] = {}
    # Diagnostic masks come only from the version-bound current Buff root.
    # They must not be promoted to observed hit masks until end-to-end native
    # propagation through damage processors is established.
    static_masks: dict[tuple[int, int], list[tuple[int, str, str]]] = {}
    static_payload = _load_current_buff_roots().get(canonical)
    if isinstance(static_payload, dict):
        pending_nodes: list[Any] = [static_payload]
        while pending_nodes:
            node = pending_nodes.pop()
            if isinstance(node, dict):
                raw_units = node.get("damageUnits")
                if isinstance(raw_units, list):
                    action_index = _coerce_optional_int(node.get("serverActionIndex"))
                    if action_index is not None:
                        for index, unit in enumerate(raw_units):
                            if not isinstance(unit, dict) or unit.get("ignoreDamageImmuneLevel") != "None":
                                continue
                            mask = _coerce_optional_int(unit.get("damageDecorateMask"))
                            if mask is not None and mask >= 0:
                                static_masks.setdefault((action_index, index), []).append((
                                    mask,
                                    str(unit.get("damageType") or "").strip().lower(),
                                    str(unit.get("damageAttributeType") or "").strip().lower(),
                                ))
                pending_nodes.extend(node.values())
            elif isinstance(node, list):
                pending_nodes.extend(node)
    for raw_action_id, raw_units in (profile.get("actions") or {}).items():
        try:
            action_id = int(raw_action_id)
        except (TypeError, ValueError):
            continue
        units = []
        for unit in raw_units:
            unit_index = unit.get("index") if isinstance(unit, dict) else None
            mask_candidates = static_masks.get((action_id, unit_index), []) if type(unit_index) is int else []
            if (isinstance(unit, dict)
                    and type(unit.get('damageDecorateMask')) is int
                    and unit.get('ignoreDamageImmuneLevel') == 'None'):
                mask_candidates = list(mask_candidates) + [(
                    int(unit['damageDecorateMask']),
                    str(unit.get('element') or '').lower(),
                    str(unit.get('damageAttribute') or '').lower(),
                )]
            mask_candidates = list(dict.fromkeys(mask_candidates))
            direct_mask = mask_candidates[0] if len(mask_candidates) == 1 else None
            mask_source = None
            if (direct_mask is not None
                    and direct_mask[1] == str(unit.get("element") or "").lower()
                    and direct_mask[2] == str(unit.get("damageAttribute") or "").lower()):
                mask_value = direct_mask[0]
                mask_source = "current_typed_skill_or_buff_exact_unit_generation_only"
            else:
                # An action/unit index mismatch has no protocol proof.
                mask_value = None
            if not isinstance(unit, dict):
                continue
            units.append({
                "index": unit.get("index"),
                "damage_type": str(unit.get("element") or ""),
                "damage_attribute_type": str(unit.get("damageAttribute") or ""),
                "element": str(unit.get("element") or ""),
                "damage_decorate_mask": mask_value,
                "damage_decorate_mask_source": mask_source,
                "damage_calculation": ({**copy.deepcopy(unit['damageCalculation']),
                    'source': 'current_typed_damage_unit',
                    'sourceProof': {**_CURRENT_TYPED_RESOURCE_BINDING,
                        'scope': 'typed_layout_and_exact_resource_only',
                        'resourceId': canonical,
                        'sourceSha256': (profile.get('proof') or {}).get('sourceSha256'),
                        'sourceAsset': (profile.get('proof') or {}).get('sourceAsset'),
                        'sourceBytes': (profile.get('proof') or {}).get('sourceBytes'),
                        'consumedBytes': (profile.get('proof') or {}).get('consumedBytes'),
                        'actionId': action_id, 'damageUnitIndex': unit.get('index'),
                        'byteOffset': unit.get('byteOffset'), 'byteEnd': unit.get('byteEnd')}}
                    if isinstance(unit.get('damageCalculation'), dict) else None),
            })
        if units:
            actions[action_id] = units
    return actions


def _resolve_skill_profile(skill_key: str | None) -> dict[str, Any] | None:
    if not skill_key:
        return None
    skill_key = _canonical_packet_skill_id(skill_key)
    mapping = _load_skill_profiles()
    return mapping.get(skill_key)
