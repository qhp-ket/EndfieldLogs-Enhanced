"""Exact action classification and element/attribute applicability."""
from __future__ import annotations

from parser_core.catalog.names import _canonical_packet_skill_id
from parser_core.catalog.skill_damage import (
    _load_skill_action_damage_units,
    _load_skill_item_metadata,
    _resolve_official_skill_damage_profile,
    _resolve_skill_profile,
)
import re
from typing import Any




_BUFF_SKILL_FILTER = {}
_BUFF_EFFECT_SKILL_FILTER = {}


_ELEMENTAL_ELEMENTS = {"fire", "pulse", "cryst", "natural", "ether"}


_DAMAGE_SCHOOL_BY_SPEC = {
    "CharacterNormalAttack": "physical",
    "CharacterPlungingAttack": "physical",
    "CharacterPowerAttack": "physical",
    "CharacterDashAttack": "physical",
    "CharacterNormalSkill": "spell",
    "CharacterUltimateSkill": "spell",
    "CharacterComboSkill": "spell",
}


_ATTR_TYPE_DAMAGE_MASK = {17: 0x20484, 28: 0x200, 32: 0x100, 33: 0x2000}


def _attr_type_applies_to_skill(
    attr_type: int | None, skill_key: str | None, *, damage_decorate_mask: int | None = None,
    static_damage_decorate_mask: int | None = None,
    static_damage_decorate_mask_source: str | None = None,
) -> bool | None:
    if attr_type is None:
        return True
    mask = _ATTR_TYPE_DAMAGE_MASK.get(attr_type)
    if mask is None:
        return True
    # Current DamagePackData._GetAttackerDamageScaleIncreaseFromSkillType
    # tests these bits independently. Names and damage school are not inputs.
    if damage_decorate_mask is not None:
        if type(damage_decorate_mask) is not int or not 0 <= damage_decorate_mask < 2**64:
            return None
        return bool(damage_decorate_mask & mask)
    # An exact current unit proves its positive skill-category bits only.
    # Runtime-added bits can be absent from the template, so absence is unknown.
    if (static_damage_decorate_mask_source == 'current_typed_skill_or_buff_exact_unit_generation_only'
            and type(static_damage_decorate_mask) is int
            and 0 <= static_damage_decorate_mask < 2**64
            and static_damage_decorate_mask & mask):
        return True
    return None


def _damage_school_from_element(element: str | None) -> str | None:
    if element == "physical":
        return "physical"
    if element in _ELEMENTAL_ELEMENTS:
        return "spell"
    return None


def _infer_skill_action_damage_element(
    skill_key: str | None,
    action_id: int | str | None,
    damage_unit_index: int | str | None = None,
) -> str | None:
    if not skill_key:
        return None
    # Missing, fractional, negative or boolean indices are not unit zero.
    if any(isinstance(value, bool) or not re.fullmatch(r"\d+", str(value))
           for value in (action_id, damage_unit_index)):
        return None
    units = _load_skill_action_damage_units(str(skill_key)).get(int(action_id), [])
    matches = [unit for unit in units if type(unit.get("index")) is int
               and unit["index"] == int(damage_unit_index)]
    if len(matches) != 1 or matches[0].get("damage_attribute_type") != "hp":
        return None
    element = matches[0].get("element")
    return element if element in {"physical", "fire", "pulse", "cryst", "natural"} else None


def _normalize_effect_element(element: str | None) -> str:
    return element or "all"


def _effect_applies_to_damage_element(
    effect_element: str,
    damage_element: str | None,
    damage_school: str | None = None,
) -> bool:
    normalized = _normalize_effect_element(effect_element)
    if normalized == "all":
        return True
    if normalized in {"physical", "spell"}:
        if damage_school is not None:
            return normalized == damage_school
        if damage_element is None:
            return False
        if normalized == "physical":
            return damage_element == "physical"
        return damage_element in _ELEMENTAL_ELEMENTS
    if damage_element is None:
        return False
    return normalized == damage_element


def _infer_skill_damage_element(skill_key: str | None, character_key: str | None) -> str | None:
    """Use only an exact official skill profile with one element."""
    if not skill_key:
        return None
    profile = _resolve_official_skill_damage_profile(skill_key)
    if profile is None or not profile.get("resolved"):
        return None
    elements = [str(value) for value in (profile.get("elements") or []) if value]
    return elements[0] if len(set(elements)) == 1 else None


def _infer_skill_damage_school(
    skill_key: str | None,
    character_key: str | None,
    *,
    raw_skill_key: str | None = None,
) -> str | None:
    candidate_keys = [str(skill_key or "")]
    raw_key = str(raw_skill_key or "")
    if raw_key and raw_key not in candidate_keys:
        candidate_keys.append(raw_key)

    for candidate in candidate_keys:
        if not candidate:
            continue
        canonical = _canonical_packet_skill_id(candidate)
        profile = _resolve_skill_profile(canonical)
        spec = str(profile.get("skill_specification") or "") if profile is not None else ""
        if not spec:
            item_meta = _load_skill_item_metadata(canonical)
            spec = str(item_meta.get("skill_specification") or "")
        school = _DAMAGE_SCHOOL_BY_SPEC.get(spec)
        inferred_element = _infer_skill_damage_element(canonical, character_key)
        if school:
            return school
        if inferred_element:
            return _damage_school_from_element(inferred_element)

    return None



_ACTION_DAMAGE_TYPE_TO_ELEMENT = {
    "physical": "physical",
    "real": "real",
    "fire": "fire",
    "pulse": "pulse",
    "cryst": "cryst",
    "crystal": "cryst",
    "lifedrain": "lifedrain",
    "natural": "natural",
    "ether": "ether",
}


_BB_KEY_ELEMENT_RE = re.compile(r"(fire|pulse|crystal|cryst|natural|physical|physic|spell)")


def _normalize_action_damage_type(value: Any) -> str | None:
    return _ACTION_DAMAGE_TYPE_TO_ELEMENT.get(str(value or "").strip().lower())


def _element_from_text(value: str | None) -> str | None:
    if not value:
        return None
    match = _BB_KEY_ELEMENT_RE.search(value.lower())
    if not match:
        return None
    token = match.group(1)
    if token == "crystal":
        return "cryst"
    if token == "physic":
        return "physical"
    return token


def _damage_increase_element_from_bb_key(bb_key: str | None) -> str | None:
    lowered = (bb_key or "").lower()
    if lowered == "pd_up":
        return "physical"
    return _element_from_text(lowered)
