"""Classify effectless wrappers and declared noise without granting allocation proof."""
from __future__ import annotations

from parser_core.catalog.buff_templates import _buff_classifier_hint
from parser_core.catalog.buff_templates import _load_local_buff_semantic_entries
from parser_core.effects.approval import _normalize_buff_id
from parser_core.effects.packet_mapping import _is_internal_trigger_damage_record
from parser_core.effects.packet_mapping import _packet_numeric_buff_hint
import re
from typing import Any

from parser_core.catalog.buff_templates import _load_equip_suit_allowed_buffs
from parser_core.effects.stacking_rules import _WEAPON_ID_FROM_BUFF_RE
from parser_core.ingestion.hits import _WEAPON_BUFF_RE


_BUFF_NOISE_PREFIXES = (
    "buff_common_vfx_",
    "buff_common_normal_skill_fx_",
    "buff_common_combo_attack_fx",
    "buff_common_dash",
    "buff_common_dash_",
    "buff_common_full_immune_weak",
)


_BUFF_NOISE_IDS = {
    "buff_chr_0011_seraph_mainchr_heal",
    "buff_chr_0023_antal_ultimate_icon",
    "buff_chr_0023_antal_ultimate_icon_2",
    "buff_common_obtain_ultimate_sp",
    "buff_common_dash_behit_listener",
    "buff_common_poise_break_damage_taken_scale",
}


_RATE_IGNORE_BUFF_PATTERNS = (
    re.compile(r"^buff_equipsuit_(?:usp_02|combo_cd01)$", re.IGNORECASE),
    re.compile(r"buff_common_affixes_slow", re.IGNORECASE),
    re.compile(r"^buff_chr_0023_antal_(?:normal_skill|tageffect|utimate_skill)$", re.IGNORECASE),
    re.compile(r"^buff_common_affixes_shelter_default_child$", re.IGNORECASE),
    re.compile(r"buff_common_affixes_vulnerable_spell", re.IGNORECASE),
    re.compile(
        r"^buff_common_(?:physical|fire|pulse|cryst|natural|spell)_"
        r"(?:physical|fire|pulse|cryst|natural|spell)_corrupt_triggered$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^buff_common_(?:try_)?(?:physical|fire|pulse|cryst|natural|spell)_triggered(?:_wrapper)?$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^buff_common_try_(?:physical|fire|pulse|cryst|natural|spell)"
        r"_(?:physical|fire|pulse|cryst|natural|spell)_triggered$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^buff_common_(?:physical|fire|pulse|cryst|natural|spell)"
        r"_(?:physical|fire|pulse|cryst|natural|spell)_triggered_wrapper$",
        re.IGNORECASE,
    ),
)


def _is_packet_effectless_wrapper(record_or_buff_id: dict[str, Any] | str | None) -> bool:
    if isinstance(record_or_buff_id, dict):
        hint = record_or_buff_id.get("packet_mapping")
        if not isinstance(hint, dict):
            raw_buff_id = _normalize_buff_id(record_or_buff_id.get("raw_event_key") or record_or_buff_id.get("event_key"))
            hint = _packet_numeric_buff_hint(raw_buff_id)
    else:
        hint = _packet_numeric_buff_hint(record_or_buff_id)
    role = str(hint.get("role") or "").lower()
    has_effect_specs = bool(hint.get("effects") or hint.get("dynamic_effects"))
    return role in {"wrapper", "marker", "utility"} and not has_effect_specs


def _is_noise_buff(buff_id: str) -> bool:
    return buff_id in _BUFF_NOISE_IDS or buff_id.startswith(_BUFF_NOISE_PREFIXES)


def _should_ignore_rate_buff(buff_id: str) -> bool:
    return any(pattern.search(buff_id) for pattern in _RATE_IGNORE_BUFF_PATTERNS)


def _should_ignore_record_rate_effects(record: dict[str, Any]) -> bool:
    buff_id = _normalize_buff_id(record.get("event_key"))
    if buff_id == "buff_equipsuit_atk_02_aruadetect":
        return True
    return False


def _is_effectless_wrapper_record(record: dict[str, Any]) -> bool:
    buff_id = _normalize_buff_id(record.get("event_key"))
    packet_mapping = record.get("packet_mapping")
    if isinstance(packet_mapping, dict) and str(packet_mapping.get("role") or "").lower() == "effect":
        return False
    entry = _load_local_buff_semantic_entries().get(buff_id)
    if isinstance(entry, dict):
        action_types = {str(item or "") for item in entry.get("actionTypes") or []}
        if "VulnerableAction" in action_types:
            return False
    if _is_internal_trigger_damage_record(record):
        return True
    if record.get("attr_mods"):
        return False
    if _is_packet_effectless_wrapper(record):
        return True
    hint = _buff_classifier_hint(buff_id) or {}
    classification = str(hint.get("classification") or "")
    if classification not in {"wrapper", "marker_or_utility"}:
        return False
    if hint.get("resolvedEffectHints") or int(hint.get("resolvedEffectCount") or 0) > 0:
        return False
    semantic_flags = hint.get("semanticFlags") if isinstance(hint.get("semanticFlags"), dict) else {}
    created_or_referenced_buff_ids = [
        str(child_id)
        for field in ("createdBuffIds", "referencedBuffIds", "binaryCreatedBuffIds", "binaryReferencedBuffIds")
        for child_id in hint.get(field) or []
        if str(child_id or "")
    ]
    if semantic_flags.get("hasDynamicBlackboard"):
        entry = _load_local_buff_semantic_entries().get(buff_id)
        if isinstance(entry, dict):
            action_types = {str(item or "") for item in entry.get("actionTypes") or []}
            created_or_referenced = {
                str(child_id)
                for field in ("createdBuffIds", "referencedBuffIds", "binaryCreatedBuffIds", "binaryReferencedBuffIds")
                for child_id in entry.get(field) or []
                if str(child_id or "")
            }
            if "OnSpellAbnormalStartFinish" in action_types and created_or_referenced:
                return True
        return False
    if classification == "wrapper" and created_or_referenced_buff_ids:
        return True
    created_buff_ids = [
        str(buff_id)
        for buff_id in hint.get("createdBuffIds") or []
        if str(buff_id or "")
    ]
    return bool(created_buff_ids) and all(_is_noise_buff(created_buff_id) for created_buff_id in created_buff_ids)



def _equip_buff_matches_active_suits(
    event_key: str | None,
    source_key: str | None,
    active_suits_by_char: dict[str, set[str]] | None,
) -> bool:
    buff_id = str(event_key or "")
    if not buff_id.startswith("buff_equipsuit_"):
        return True
    source = str(source_key or "")
    if not source or not isinstance(active_suits_by_char, dict):
        return True
    if not active_suits_by_char:
        return True
    if source not in active_suits_by_char:
        # Character trials and squad swaps can emit equipment buff packets
        # without a matching LOADOUT row for the replacement character.
        return True
    active_suits = set(active_suits_by_char.get(source) or set())
    if not active_suits:
        return False
    allowed_by_suit = _load_equip_suit_allowed_buffs()
    for suit_id in active_suits:
        if buff_id in allowed_by_suit.get(str(suit_id), set()):
            return True
    return False


def _weapon_buff_matches_active_weapon(
    event_key: str | None,
    source_key: str | None,
    active_weapons_by_char: dict[str, str] | None,
) -> bool:
    buff_id = str(event_key or "")
    if not _WEAPON_BUFF_RE.match(buff_id):
        return True
    source = str(source_key or "")
    if not source or not isinstance(active_weapons_by_char, dict):
        return True
    if not active_weapons_by_char:
        return True
    active_weapon = active_weapons_by_char.get(source)
    if not active_weapon:
        # Character trials and squad swaps can emit weapon buff packets before a
        # matching LOADOUT_STATS row exists for the new source character.
        return True
    hint = _packet_numeric_buff_hint(buff_id)
    weapon_id = str(hint.get("weapon_id") or "")
    if not weapon_id:
        match = _WEAPON_ID_FROM_BUFF_RE.match(buff_id)
        weapon_id = match.group(1) if match else ""
    return not weapon_id or weapon_id == active_weapon
