"""Canonical hit templates and explicitly observed skill-family identities."""
from __future__ import annotations

from parser_core.catalog.names import (
    _canonical_num_table_skill_number,
    _canonical_packet_skill_id,
    _character_key_matches_static_family,
    _runtime_owner_matches_static_domain,
    _runtime_skill_number,
)
from parser_core.catalog.packet_semantics import _load_num_id_str_buff_map
from parser_core.catalog.skill_damage import _load_official_skill_damage_catalog
from parser_core.ingestion.identity import _CHAR_KEY_RE
from typing import Any




def _canonical_num_table_skill_id(skill_key: str | None, character_key: str | None) -> str | None:
    skill_number = _runtime_skill_number(skill_key)
    return _canonical_num_table_skill_number(skill_number, character_key)


def _canonical_num_table_buff_number(buff_number: str | None, character_key: str | None) -> str | None:
    if not buff_number:
        return None
    static_id = _load_num_id_str_buff_map().get(str(buff_number))
    if not static_id:
        return None
    if not _runtime_owner_matches_static_domain(character_key, static_id):
        return None
    if not character_key:
        return static_id
    match = _CHAR_KEY_RE.search(static_id)
    if match and not _character_key_matches_static_family(str(character_key), match.group(1)):
        return None
    return static_id


def _canonical_hit_skill_id(skill_key: str | None, character_key: str | None) -> str:
    raw_skill_key = str(skill_key or "")
    number = _runtime_skill_number(raw_skill_key)
    if number and _canonical_num_table_skill_id(raw_skill_key, character_key) and _canonical_num_table_buff_number(number, character_key):
        return raw_skill_key
    num_table_skill = _canonical_num_table_skill_id(raw_skill_key, character_key)
    if num_table_skill:
        return num_table_skill
    return raw_skill_key


def _canonical_runtime_buff_skill_id(
    skill_key: str | None,
    character_key: str | None,
    *,
    action_id: int | None = None,
    damage_unit_index: int | None = None,
) -> str | None:
    skill_number = _runtime_skill_number(skill_key)
    canonical_buff_id = _canonical_num_table_buff_number(skill_number, character_key)
    if not canonical_buff_id:
        return None
    # Skill and Buff number spaces can overlap. An action/unit number alone
    # cannot establish the namespace of a conflicting numeric template.
    if _canonical_num_table_skill_id(skill_key, character_key):
        return None
    if action_id is not None:
        profile = _load_official_skill_damage_catalog().get(canonical_buff_id, {})
        units = (profile.get("actions") or {}).get(str(action_id), [])
        exact_units = [
            unit for unit in units
            if isinstance(unit, dict)
            and unit.get("damageAttribute") == "hp"
            and unit.get("element")
            and unit.get("index") == damage_unit_index
        ]
        if len(exact_units) == 1:
            return canonical_buff_id
    return None


def _canonical_hit_skill_id_from_cast_context(
    skill_key: str | None,
    character_key: str | None,
    ts_ms: int,
    *,
    original_template_int_id: int | None = None,
    target_enemy_key: str | None,
    recent_skill_casts_by_char: dict[str, list[dict[str, Any]]],
    recent_numeric_buffs_by_source: dict[str, list[dict[str, Any]]],
    action_id: int | None = None,
    damage_unit_index: int | None = None,
    template_type: str | None = None,
) -> str | None:
    number = _runtime_skill_number(skill_key)
    if number and template_type == "buff":
        return _canonical_num_table_buff_number(number, character_key) or str(skill_key)
    if number and template_type == "skill":
        return _canonical_num_table_skill_id(skill_key, character_key) or str(skill_key)
    # Runtime proximity/cast context is not identity evidence.
    return _canonical_runtime_buff_skill_id(
        skill_key, character_key, action_id=action_id, damage_unit_index=damage_unit_index,
    )


def _recent_source_skill_context_for_buff(
    source_key: str | None,
    ts_ms: int,
    recent_skill_casts_by_char: dict[str, list[dict[str, Any]]],
) -> dict[str, str] | None:
    return None


def _resolve_skill_family_key(skill_key: str | None, skill_profile: dict[str, Any] | None = None) -> str:
    if not skill_key:
        return ""
    skill_key = _canonical_packet_skill_id(skill_key)
    if skill_profile is not None:
        family_skill_key = str(skill_profile.get("family_skill_key") or skill_key)
        if family_skill_key:
            return family_skill_key

    return skill_key



def _apply_same_frame_trigger_skill_mappings(
    hits: list[dict[str, Any]],
    buff_starts: list[dict[str, Any]],
) -> None:
    return


def _infer_missing_hit_damage_schools(
    hits: list[dict[str, Any]],
    buff_windows: list[dict[str, Any]],
) -> None:
        return


def _same_frame_trigger_buff_for_runtime_skill(*args: Any, **kwargs: Any) -> None:
    return None


def _runtime_skill_trigger_chain_mapping(*args: Any, **kwargs: Any) -> None:
    return None


def _trigger_damage_identity_from_buff(*args: Any, **kwargs: Any) -> tuple[str, str]:
    return ("unknown_skill", "unknown_skill")


def _skill_semantically_reaches_buff(*args: Any, **kwargs: Any) -> bool:
    return False
