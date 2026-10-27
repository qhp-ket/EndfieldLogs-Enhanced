"""Observed numeric buff identities and guarded protocol semantics."""
from __future__ import annotations

from parser_core.catalog.packet_semantics import (
    _load_mechanism_registry_by_buff_id,
    _load_num_id_str_buff_map,
    _load_packet_canonical_buff_map,
    _load_packet_numeric_buff_map,
)
from parser_core.effects.approval import _normalize_buff_id
from parser_core.ingestion.skill_identity import _canonical_num_table_buff_number
from typing import Any

from parser_core.effects.conditions import _attach_bb_key_damage_type_condition
from parser_core.effects.damage_types import _normalize_effect_element
from parser_core.effects.typed_actions import _enhanced_action_child_effect_specs
from parser_core.ingestion.fields import _positive_int
from parser_core.ingestion.fields import _safe_positive_rate




def _mechanism_registry_buff_hint(buff_id: str | None) -> dict[str, Any]:
    key = str(buff_id or "")
    if not key:
        return {}
    canonical_key = _load_num_id_str_buff_map().get(key, key) if key.isdigit() else key
    rows = _load_mechanism_registry_by_buff_id().get(canonical_key) or []
    if len(rows) != 1:
        return {}
    row = dict(rows[0])
    row["canonical_buff_id"] = str(row.get("canonical_buff_id") or canonical_key)
    if row.get("source_kind") == "weapon" and row.get("source_id") and not row.get("weapon_id"):
        row["weapon_id"] = row.get("source_id")
    if row.get("source_kind") == "suit" and row.get("source_id") and not row.get("suit_id"):
        row["suit_id"] = row.get("source_id")
    row.setdefault("scope", "loadout_guarded")
    row.setdefault("confidence", "compiled_from_unpack")
    return row


def _packet_numeric_buff_hint(buff_id: str | None) -> dict[str, Any]:
    key = str(buff_id or "")
    direct = _load_packet_numeric_buff_map().get(key)
    if isinstance(direct, dict):
        return direct
    canonical = _load_packet_canonical_buff_map().get(key)
    if isinstance(canonical, dict):
        return canonical
    return _mechanism_registry_buff_hint(key)


def _packet_mapping_applies(
    mapping: dict[str, Any],
    *,
    owner_key: str | None,
    source_key: str | None,
    active_suits_by_char: dict[str, set[str]] | None = None,
    active_weapons_by_char: dict[str, str] | None = None,
) -> bool:
    character_id = str(mapping.get("character_id") or "")
    if character_id and character_id not in {owner_key, source_key}:
        return False

    suit_id = str(mapping.get("suit_id") or "")
    if suit_id and active_suits_by_char:
        guard_key = str(source_key or owner_key or "")
        has_actor_loadout = bool(guard_key and guard_key in active_suits_by_char)
        active_suits = active_suits_by_char.get(guard_key, set()) if has_actor_loadout else set()
        if has_actor_loadout and suit_id not in active_suits:
            return False

    weapon_id = str(mapping.get("weapon_id") or "")
    if weapon_id and active_weapons_by_char:
        guard_key = str(source_key or owner_key or "")
        active_weapon = active_weapons_by_char.get(guard_key) if guard_key else None
        if active_weapon and weapon_id != active_weapon:
            return False

    return True


_STATIC_PACKET_BUFF_ALIASES = {
    # Early packet traces used this synthetic alias for suit_usp02's actual
    # damage-up child. Normalize it to the static buff id so suit gating and
    # semantic lookup see the real equipment buff.
    "buff_equipsuit_usp_02_dmgup": "buff_equipsuit_usp_02_AddAttack",
}


def _canonical_packet_buff_id(
    buff_id: str | None,
    *,
    owner_key: str | None = None,
    source_key: str | None = None,
    active_suits_by_char: dict[str, set[str]] | None = None,
    active_weapons_by_char: dict[str, str] | None = None,
) -> str:
    raw_buff_id = _normalize_buff_id(buff_id)
    if raw_buff_id in _STATIC_PACKET_BUFF_ALIASES:
        return _STATIC_PACKET_BUFF_ALIASES[raw_buff_id]
    hint = _packet_numeric_buff_hint(raw_buff_id)
    if hint and not _packet_mapping_applies(
        hint,
        owner_key=owner_key,
        source_key=source_key,
        active_suits_by_char=active_suits_by_char,
        active_weapons_by_char=active_weapons_by_char,
    ):
        return raw_buff_id
    canonical = hint.get("canonical_buff_id")
    if canonical:
        return str(canonical)
    fallback_ids = {
        fallback
        for candidate_key in (source_key, owner_key, None)
        if (fallback := _canonical_num_table_buff_number(raw_buff_id, candidate_key))
    }
    if len(fallback_ids) == 1:
        return next(iter(fallback_ids))
    return raw_buff_id


_PACKET_RDPS_BB_KEY_HINTS = {
    "atk_up",
    "atk_up2",
    "crit_up",
    "crit_up2",
    "crit_dmg_up",
    "def_decrease",
    "def_decrease_tick",
    "def_decrease_tick_final",
    "dmg_up",
    "fire_dmg_up",
    "ignore_fire_resist",
    "max_def_decrease",
    "max_def_decrease_final",
    "normal_atk_up_valid",
    "pd_up",
    "phy_dmg_up",
    "phy_dmg_up2",
    "spell_damage_taken_up",
    "spell_dmg_up",
    "spell_taken_up",
    "spell_up",
    "start_def_decrease",
}


_PACKET_UTILITY_BB_KEY_HINTS = {
    "atb",
    "atk_duration",
    "cd",
    "comboskill_cooldown",
    "common_character_perfect_dodge",
    "count",
    "damage_interval",
    "duration",
    "dodgeSkillId",
    "heal_value",
    "healvalue",
    "hp_up",
    "lv",
    "max_stack",
    "poise",
    "posie",
    "probability",
    "ratio",
    "shelter",
    "skill_bg_type",
    "speed",
    "vfx_buff_name",
}


def _packet_bb_key_has_rdps_shape(key: str) -> bool:
    lowered = key.lower()
    if lowered in _PACKET_RDPS_BB_KEY_HINTS:
        return True
    if any(token in lowered for token in ("def_decrease", "resist", "taken_up", "vulnerable", "fragile")):
        return True
    if any(token in lowered for token in ("dmg_up", "damage_up", "spell_up", "atk_up", "crit")):
        return True
    return lowered.startswith("ignore_") and ("res" in lowered or "def" in lowered)


def _is_internal_trigger_damage_record(record: dict[str, Any]) -> bool:
    raw_buff_id = _normalize_buff_id(record.get("raw_event_key") or record.get("event_key"))
    if not raw_buff_id.isdigit():
        return False
    bb_keys = {str(key).lower() for key in record.get("bb_keys") or []}
    bb_keys.update(str(key).lower() for key in (record.get("bb_values") or {}).keys())
    trigger_keys = {"phy_dmg_up", "final_phy_dmg_up", "shatter_dmg", "consumed_layer"}
    if not trigger_keys.issubset(bb_keys):
        return False
    owner = str(record.get("owner_raw") or record.get("target_character_key") or record.get("target_enemy_key") or "")
    source = str(record.get("raw_source") or record.get("source_character_key") or "")
    return owner.startswith("eny_") and source.startswith("chr_")


def _classify_packet_buff_record(record: dict[str, Any]) -> dict[str, Any]:
    raw_buff_id = _normalize_buff_id(record.get("raw_event_key") or record.get("event_key"))
    mapping = record.get("packet_mapping")
    if isinstance(mapping, dict):
        return {
            "status": "mapped",
            "class": str(mapping.get("role") or "mapped"),
            "label": "已接受映射",
            "reason": str(mapping.get("reason") or ""),
        }
    if not raw_buff_id.isdigit():
        return {
            "status": "static_id",
            "class": "static",
            "label": "静态 ID",
            "reason": "buff id is already a static string id",
        }
    owner = str(record.get("owner_raw") or record.get("target_character_key") or record.get("target_enemy_key") or "")
    source = str(record.get("raw_source") or record.get("source_character_key") or "")
    if not any(value.startswith(("chr_", "eny_")) for value in (owner, source)):
        return {
            "status": "unmapped",
            "class": "orphan_actor",
            "label": "孤立 actor",
            "reason": "numeric buff has no character/enemy owner or source context",
        }
    bb_keys = {str(key) for key in record.get("bb_keys") or []}
    bb_keys.update(str(key) for key in (record.get("bb_values") or {}).keys())
    if _is_internal_trigger_damage_record(record):
        return {
            "status": "unmapped",
            "class": "utility_or_marker",
            "label": "内部触发窗",
            "reason": "numeric buff matches common cryst-triggered helper keys and should not be treated as an external damage buff",
        }
    rdps_keys = sorted(key for key in bb_keys if _packet_bb_key_has_rdps_shape(key))
    if rdps_keys:
        return {
            "status": "unmapped",
            "class": "rdps_effect",
            "label": "疑似 rDPS 效果",
            "reason": "numeric buff has rDPS-shaped blackboard keys: " + ", ".join(rdps_keys),
        }
    if bb_keys:
        utility_keys = {key for key in bb_keys if key.lower() in _PACKET_UTILITY_BB_KEY_HINTS}
        if utility_keys == bb_keys:
            return {
                "status": "unmapped",
                "class": "utility_or_marker",
                "label": "工具/标记",
                "reason": "only utility blackboard keys were observed",
            }
        return {
            "status": "unmapped",
            "class": "unknown_blackboard",
            "label": "未知黑板",
            "reason": "blackboard keys exist but do not match accepted rDPS patterns",
        }
    return {
        "status": "unmapped",
        "class": "no_blackboard",
        "label": "无黑板",
        "reason": "numeric buff carried no blackboard values in this trace",
    }


def _preserve_raw_numeric_internal_trigger_buff_id(record: dict[str, Any]) -> None:
    raw_buff_id = _normalize_buff_id(record.get("raw_event_key") or record.get("event_key"))
    if not raw_buff_id.isdigit():
        return
    if isinstance(record.get("packet_mapping"), dict):
        return
    if _is_internal_trigger_damage_record(record):
        record["event_key"] = raw_buff_id



_DPD_ZONE_BUCKETS = {
    "dmg_inc": ("atk", 1),
    "amp": ("atk", 3),
    "combo": ("atk", 4),
    "vuln_taken": ("def", 1),
    "fragile": ("def", 5),
}


def _packet_mapping_allows_static_rate(hint: dict[str, Any]) -> bool:
    return bool(
        hint.get("allow_static_rate")
        or hint.get("allow_static_rates")
        or str(hint.get("value_source") or "").lower() in {"static_literal", "constant"}
    )


def _packet_numeric_effects(record: dict[str, Any]) -> list[dict[str, Any]]:
    raw_buff_id = _normalize_buff_id(record.get("raw_event_key") or record.get("event_key"))
    hint = record.get("packet_mapping")
    if not isinstance(hint, dict):
        hint = _packet_numeric_buff_hint(raw_buff_id)
    specs = hint.get("effects")
    bb_values = {str(key): value for key, value in (record.get("bb_values") or {}).items()}
    if not isinstance(specs, list):
        specs = _enhanced_action_child_effect_specs(str(record.get("event_key") or ""))
        if not specs:
            return []
    allow_static_rate = _packet_mapping_allows_static_rate(hint)
    effects: list[dict[str, Any]] = []
    for spec in specs:
        if not isinstance(spec, dict):
            continue
        zone = str(spec.get("zone") or "")
        if zone not in _DPD_ZONE_BUCKETS and zone != "crit":
            continue
        element = _normalize_effect_element(str(spec.get("element") or "all"))
        bb_key = str(spec.get("bb_key") or "")
        rate = _safe_positive_rate(bb_values.get(bb_key)) if bb_key else None
        if rate is None and str(spec.get("prefer_runtime_rate_key") or ""):
            rate = _safe_positive_rate(bb_values.get(str(spec.get("prefer_runtime_rate_key") or "")))
        if rate is None and allow_static_rate:
            rate = _safe_positive_rate(spec.get("rate"))
        if rate is None:
            continue
        effect = {"zone": zone, "element": element, "rate": rate}
        if bb_key:
            effect["bb_key"] = bb_key
            _attach_bb_key_damage_type_condition(effect, bb_key)
        effects.append(effect)
    return effects


def _packet_numeric_dynamic_effects(record: dict[str, Any]) -> list[dict[str, Any]]:
    raw_buff_id = _normalize_buff_id(record.get("raw_event_key") or record.get("event_key"))
    hint = record.get("packet_mapping")
    if not isinstance(hint, dict):
        hint = _packet_numeric_buff_hint(raw_buff_id)
    specs = hint.get("dynamic_effects")
    if not isinstance(specs, list):
        return []
    bb_values = {str(key): value for key, value in (record.get("bb_values") or {}).items()}
    allow_static_rate = _packet_mapping_allows_static_rate(hint)
    effects: list[dict[str, Any]] = []
    for spec in specs:
        if not isinstance(spec, dict):
            continue
        zone = str(spec.get("zone") or "")
        if zone not in _DPD_ZONE_BUCKETS and zone != "crit":
            continue
        element = _normalize_effect_element(str(spec.get("element") or "all"))
        base_bb_keys = [str(key) for key in spec.get("base_bb_keys") or [] if str(key)]
        base_bb_key = str(spec.get("base_bb_key") or spec.get("bb_key") or "")
        if not base_bb_keys and base_bb_key:
            base_bb_keys = [base_bb_key]
        base_rate = None
        for candidate_key in base_bb_keys:
            base_rate = _safe_positive_rate(bb_values.get(candidate_key))
            if base_rate is not None:
                base_bb_key = candidate_key
                break
        if base_rate is None:
            base_rate = _safe_positive_rate(spec.get("base_rate")) if allow_static_rate else None
        if base_rate is None:
            base_rate = 0.0
        add_bb_key = str(spec.get("add_bb_key") or "")
        delayed_add_rate = _safe_positive_rate(bb_values.get(add_bb_key)) if add_bb_key else None
        if delayed_add_rate is None:
            delayed_add_rate = _safe_positive_rate(spec.get("delayed_add_rate")) if allow_static_rate else None
        if delayed_add_rate is None:
            delayed_add_rate = 0.0
        delay_bb_key = str(spec.get("delay_bb_key") or "")
        delay_sec = _safe_positive_rate(bb_values.get(delay_bb_key)) if delay_bb_key else None
        if delay_sec is None and allow_static_rate:
            delay_sec = _safe_positive_rate(spec.get("delay_sec")) or 0.0
        if delay_sec is None:
            delay_sec = 0.0
        tick_rate = (_safe_positive_rate(spec.get("tick_rate")) or 0.0) if allow_static_rate else 0.0
        tick_bb_key = ""
        for candidate_key in [str(key) for key in spec.get("tick_bb_keys") or [] if str(key)]:
            runtime_tick_rate = _safe_positive_rate(bb_values.get(candidate_key))
            if runtime_tick_rate is not None:
                tick_bb_key = candidate_key
                tick_rate = runtime_tick_rate * (float(spec.get("tick_multiplier") or 1.0))
                break
        max_bb_key = str(spec.get("max_bb_key") or "")
        max_rate = _safe_positive_rate(bb_values.get(max_bb_key)) if max_bb_key else None
        if max_rate is None:
            max_rate = (_safe_positive_rate(spec.get("max_rate")) or 0.0) if allow_static_rate else 0.0
        if base_rate <= 0 and delayed_add_rate <= 0 and tick_rate <= 0:
            continue
        effect = {
            "zone": zone,
            "element": element,
            "base_rate": base_rate,
            "tick_rate": tick_rate,
            "max_rate": max_rate,
            "delayed_add_rate": delayed_add_rate,
            "delay_sec": delay_sec,
        }
        if base_bb_key:
            effect["bb_key"] = base_bb_key
        if add_bb_key:
            effect["add_bb_key"] = add_bb_key
        if delay_bb_key:
            effect["delay_bb_key"] = delay_bb_key
        if tick_bb_key:
            effect["tick_bb_key"] = tick_bb_key
        if max_bb_key:
            effect["max_bb_key"] = max_bb_key
        if spec.get("dynamic_key"):
            effect["dynamic_key"] = spec.get("dynamic_key")
        effects.append(effect)
    return effects


def _packet_mapping_stack_limit(record: dict[str, Any]) -> int | None:
    bb_values = record.get("bb_values") if isinstance(record.get("bb_values"), dict) else {}
    for key in ("max_stack", "stack_limit", "maxStack", "stackLimit"):
        limit = _positive_int(bb_values.get(key))
        if limit is not None:
            return limit
    hint = record.get("packet_mapping")
    if not isinstance(hint, dict):
        raw_buff_id = _normalize_buff_id(record.get("raw_event_key") or record.get("event_key"))
        hint = _packet_numeric_buff_hint(raw_buff_id)
    return _positive_int(hint.get("stack_limit"))



_CLASSIFIER_ZONE_TO_INTERNAL = {
    "ATK": "atk",
    "CRIT": "crit",
    "CRIT_RATE": "crit",
    "DMG_INC": "dmg_inc",
    "AMP": "amp",
    "FRAGILE": "fragile",
    "VULN_TAKEN": "vuln_taken",
    "RES": "res",
    "COMBO": "combo",
    "UTILITY": "utility",
}


def _classifier_zone_to_internal(zone: Any) -> str | None:
    return _CLASSIFIER_ZONE_TO_INTERNAL.get(str(zone or "").strip().upper())


def _packet_record_effect_pairs(record: dict[str, Any]) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for effect in (record.get("zone_effects") or []):
        if not isinstance(effect, dict):
            continue
        zone = str(effect.get("zone") or "").strip()
        if not zone:
            continue
        pairs.add((zone, _normalize_effect_element(effect.get("element"))))
    for effect in (record.get("dynamic_effects") or []):
        if not isinstance(effect, dict):
            continue
        zone = str(effect.get("zone") or "").strip()
        if not zone:
            continue
        pairs.add((zone, _normalize_effect_element(effect.get("element"))))
    return pairs


def _classifier_hint_effect_pairs(hint: dict[str, Any]) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for effect in hint.get("resolvedEffectHints") or hint.get("effectHints") or []:
        if not isinstance(effect, dict):
            continue
        zone = _classifier_zone_to_internal(effect.get("zone"))
        if zone in (None, "utility"):
            continue
        pairs.add((zone, _normalize_effect_element(effect.get("element"))))
    return pairs
