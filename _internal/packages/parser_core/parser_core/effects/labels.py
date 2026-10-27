"""Describe observed effects for display without changing their allocation."""
from __future__ import annotations

from parser_core.allocation.static_loadout import _ATTR_TYPE_TO_EFFECT
from parser_core.effects.approval import _normalize_buff_id
from parser_core.effects.classification import _is_effectless_wrapper_record
from parser_core.effects.classification import _is_noise_buff
from parser_core.effects.classification import _should_ignore_rate_buff
from parser_core.effects.classification import _should_ignore_record_rate_effects
from parser_core.effects.packet_mapping import _packet_numeric_dynamic_effects
from parser_core.effects.packet_mapping import _packet_numeric_effects
from parser_core.effects.semantic_conditions import _collect_semantic_condition_zone_effects
from parser_core.realtime.incremental import memoize_live_record
import re
from typing import Any




_BUFF_LABEL_PRIORITY = {
    "攻击提升": 0,
    "增伤": 1,
    "增幅": 2,
    "导电": 2,
    "腐蚀": 2,
    "燃烧": 2,
    "冻结": 2,
    "碎冰": 2,
    "法术爆发": 2,
    "破防": 2,
    "倒地": 2,
    "击飞": 2,
    "猛击": 2,
    "脆弱": 2,
    "物理脆弱": 2,
    "物理脆弱 / 碎甲": 2,
    "碎甲": 2,
    "易伤": 3,
    "承伤易伤": 3,
    "减抗": 4,
    "连击增伤": 5,
    "暴击": 6,
    "暴击伤害": 7,
}


_BUFF_NOISE_BB_KEYS = {
    "atb",
    "atk_duration",
    "cd",
    "comboskill_cooldown",
    "common_character_perfect_dodge",
    "count",
    "damage_interval",
    "def_decrease_tick",
    "def_decrease_tick_final",
    "duration",
    "dodgeSkillId",
    "end_early",
    "heal_value",
    "healvalue",
    "hit_spellduration",
    "hp_up",
    "imbue_scale",
    "infliction_num",
    "max_stack",
    "max_def_decrease",
    "max_def_decrease_final",
    "phy_spell_up",
    "poise",
    "posie",
    "potential_1",
    "potential_3",
    "potential_3_atb",
    "rate_add",
    "shatter_dmg",
    "skill_bg_type",
    "speed",
    "stack_cond",
    "start_def_decrease",
    "time_warning",
    "usp_everyone",
    "usp_self",
    "vfx_buff_name",
}


_BUFF_EFFECT_BB_KEY_IGNORE_BY_ID = {
    # Seraph's ultimate uses atk_up as an internal base for elemental EnhancedAction.
    # The actual buffs are emitted separately as common_affixes_enhance_* children.
    "buff_chr_0011_seraph_atk_buff": {"atk_up"},
    # Seraph's heal-side potential wrapper passes atk_up into a child action. The
    # actual attack buff is emitted separately by the weapon buff.
    "buff_chr_0011_seraph_potential_1_atkup": {"atk_up"},
    # suit_atk02 stores child trigger parameters on the persistent wearer buff.
    # Only atk_up is a direct stat effect here; dmg_up belongs to the later
    # add-combo-damage child.
    "buff_equipsuit_atk_02": {"dmg_up", "max_stack"},
    # Fracture carries trigger damage parameters next to the actual debuff.
    # The rDPS effect is physical_res_down; atk_scale belongs to the triggered hit.
    "buff_physical_do_fracture": {"atk_scale"},
    # Mixed weapon buffs carry owner-side parameters next to external rDPS keys.
    "buff_wpn_funnel_0006_valid": {"atk_up"},
    "buff_wpn_funnel_0011_valid": {"nature_dmg_up"},
    "buff_wpn_sword_0012_atk_up": {"atk_up"},
    "buff_wpn_sword_0013_atk_up": {"atk_up", "atk_up_add", "atk_up_mult"},
    "buff_wpn_sword_0016_team": {"phy_dmg_up", "phy_dmg_up2"},
    "buff_wpn_sword_0016_valid": {"phy_dmg_up", "phy_dmg_up2"},
    "buff_wpn_sword_0020_cryst": {"atk_up"},
}


_ATTR_TYPE_BUFF_LABELS = {
    2: "攻击提升",
    9: "暴击",
    10: "暴击伤害",
    17: "增伤",
    28: "增伤",
    32: "增伤",
    33: "增伤",
    50: "增伤",
    51: "增伤",
    53: "增伤",
    65: "增幅",
    66: "增幅",
    67: "增幅",
    68: "增幅",
    70: "易伤",
}


_FRAGILE_ATTR_TYPES = set(range(70, 86))


_EFFECT_ZONE_LABELS = {
    "atk": "攻击提升",
    "dmg_inc": "增伤",
    "amp": "增幅",
    "fragile": "脆弱",
    "vuln_taken": "易伤",
    "res": "减抗",
    "combo": "连击增伤",
    "arts_strength": "源石技艺强度",
    "crit": "暴击",
    "speedup": "加速",
    "slow": "缓速",
}


_DEF_DECREASE_BASE_KEYS = {"def_decrease", "additional_def_decrease"}


_GENERIC_COMBO_TRIGGER_BUFF_ID = "buff_common_affixes_combo_trigger"


def _is_damage_increase_bb_key(bb_key: str | None) -> bool:
    lowered = (bb_key or "").lower()
    return lowered in {"dmg_up", "pd_up", "spell_up"} or lowered.endswith("_dmg_up") or lowered.endswith("_dmg_up2")


def _add_label(labels: set[str], label: str | None) -> None:
    if label:
        labels.add(label)


def _anomaly_status_labels(
    buff_id: str,
    *,
    source_key: str,
    target_is_enemy: bool,
    bb_values: dict[str, Any],
) -> set[str]:
    labels: set[str] = set()
    lowered = buff_id.lower()

    if lowered == "buff_physical_no_guard":
        labels.add("破防")
    elif lowered == "buff_physical_knockdown":
        labels.add("倒地")
    elif lowered == "buff_physical_airborne":
        labels.add("击飞")
    elif lowered == "buff_physical_crushed":
        labels.add("猛击")
    elif lowered == "buff_common_cryst_triggered_physical_break":
        labels.add("猛击")

    if "conduct_triggered" in lowered:
        labels.add("导电")
    if (
        "corrupt_triggered" in lowered
        or "corrupt_do" in lowered
        or re.match(r"^buff_common_(?:try_)?natural_(?:fire|pulse|cryst|natural)_triggered(?:_wrapper)?$", lowered)
    ):
        labels.add("腐蚀")
    if "fire_fire_triggered" in lowered or "burn" in lowered:
        labels.add("燃烧")

    same_element_burst = re.match(
        r"^buff_common_(fire|pulse|cryst|natural|spell)_\1_triggered(?:_wrapper|_do)?$",
        lowered,
    )
    if same_element_burst:
        labels.add("法术爆发")

    if (
        "frozen" in lowered
        and "physical_res_down" not in bb_values
        and "phy_resist_down" not in bb_values
    ):
        labels.add("冻结")

    if target_is_enemy and source_key == "chr_0029_pograni" and "physical_res_down" in bb_values:
        labels.add("碎甲")

    return labels


def _label_from_bb_key(
    bb_key: str,
    *,
    buff_id: str,
    target_is_enemy: bool,
) -> str | None:
    lowered = bb_key.lower()
    if not lowered or lowered in _BUFF_NOISE_BB_KEYS:
        return None
    if _buff_effect_bb_key_ignored(buff_id, lowered):
        return None
    if lowered in {"atk", "atk_up", "atk_up2"}:
        return "攻击提升"
    if lowered in {"phy_resist_down", "physical_res_down", "physical_vulnerable_dmg_increase"}:
        return "物理脆弱 / 碎甲"
    if lowered == "ratio_speed":
        return "加速"
    if lowered == "ratio_speedreduction":
        return "缓速"
    if lowered in {"crit_up", "crit_up2", "critical_rate"}:
        return "暴击"
    if lowered in {"crit_dmg", "critical_damage_inc"}:
        return "暴击伤害"
    if lowered in {"fire_up", "pulse_up", "cryst_up", "crystal_up", "natural_up", "physical_up", "physic_up"}:
        return "脆弱" if target_is_enemy else "增幅"
    if _is_damage_increase_bb_key(lowered) or lowered.endswith("_up_valid"):
        return "增伤"
    if lowered.endswith("_taken_up"):
        return "承伤易伤"
    if lowered == "def_down_damage":
        return "脆弱"
    if lowered in {"def_decrease", "additional_def_decrease"}:
        return "减抗"
    if lowered.endswith("_vul"):
        return "脆弱"
    if lowered.startswith("rate_") and "vulnerable" in lowered:
        return "脆弱"
    if lowered.startswith("enhance_"):
        return "增幅"
    if re.match(r"^(?:.+_)?taken_up_(?:physical|physic|fire|pulse|cryst|crystal|natural|spell)$", lowered):
        return "承伤易伤"
    if re.match(r"^damage_taken_up_(?:physical|physic|fire|pulse|cryst|crystal|natural|spell)$", lowered):
        return "承伤易伤"
    if lowered.endswith("_resistance_decrease") or lowered.endswith("_resistance_down"):
        return "承伤易伤"
    if lowered.endswith("_res_down") or (lowered.startswith("ignore_") and lowered.endswith("_resist")):
        return "减抗"
    if lowered == "combo_damageup":
        return "连击增伤"
    if lowered in {"atk_scale", "extra_atk_scale", "burning_atk_scale"} and target_is_enemy:
        buff_lower = buff_id.lower()
        if any(token in buff_lower for token in ("vulnerable", "fragile", "fracture")):
            return "脆弱"
        return None
    if lowered == "rate":
        buff_lower = buff_id.lower()
        if buff_lower in {
            "buff_chr_0015_lifeng_purify",
            "buff_chr_0015_lifeng_normal_skill_debuff",
            "buff_chr_0015_lifeng_normal_skill_debuff_icon",
        }:
            return "物理脆弱"
        if any(token in buff_lower for token in ("vulnerable", "fragile", "waterdebuff")):
            return "脆弱"
        if "enhance_" in buff_lower:
            return "增幅"
        if any(token in buff_lower for token in ("spellup", "dmg", "damage_increase")):
            return "增伤"
        if "criticalrate" in buff_lower:
            return "暴击"
        if "combo_damage" in buff_lower:
            return "连击增伤"
    return None


def _buff_effect_bb_key_ignored(buff_id: str, bb_key: str) -> bool:
    ignored_keys = _BUFF_EFFECT_BB_KEY_IGNORE_BY_ID.get(str(buff_id or "").lower())
    return ignored_keys is not None and str(bb_key or "").lower() in ignored_keys


@memoize_live_record
def _collect_buff_labels(record: dict[str, Any], *, root_lookup_cache: dict | None = None) -> list[str]:
    buff_id = _normalize_buff_id(record.get("event_key"))
    target_is_enemy = bool(record.get("target_enemy_key"))
    source_key = str(record.get("source_character_key") or "")
    bb_values = {str(key).lower(): value for key, value in (record.get("bb_values") or {}).items()}
    semantic_condition_effects = _collect_semantic_condition_zone_effects(record, root_lookup_cache=root_lookup_cache)
    anomaly_labels = _anomaly_status_labels(
        buff_id,
        source_key=source_key,
        target_is_enemy=target_is_enemy,
        bb_values=bb_values,
    )
    if _should_ignore_record_rate_effects(record):
        return sorted(anomaly_labels, key=lambda item: (_BUFF_LABEL_PRIORITY.get(item, 99), item))
    if (_is_noise_buff(buff_id) or _should_ignore_rate_buff(buff_id)) and not semantic_condition_effects:
        return sorted(anomaly_labels, key=lambda item: (_BUFF_LABEL_PRIORITY.get(item, 99), item))
    if _is_effectless_wrapper_record(record) and anomaly_labels and not semantic_condition_effects:
        return sorted(anomaly_labels, key=lambda item: (_BUFF_LABEL_PRIORITY.get(item, 99), item))
    if _is_effectless_wrapper_record(record) and not semantic_condition_effects:
        return []

    labels: set[str] = set(anomaly_labels)
    special_bb_labels: dict[str, str] = {}

    if buff_id == _GENERIC_COMBO_TRIGGER_BUFF_ID:
        labels.add("连击增伤")
    if buff_id in {
        "buff_chr_0015_lifeng_purify",
        "buff_chr_0015_lifeng_normal_skill_debuff",
        "buff_chr_0015_lifeng_normal_skill_debuff_icon",
    }:
        labels.add("物理脆弱")
    if buff_id == "buff_chr_0029_pograni_talent2":
        labels.add("铁卫标记")
    if "physical_res_down" in bb_values:
        if source_key == "chr_0029_pograni":
            special_bb_labels["physical_res_down"] = "碎甲"
            labels.add("碎甲")
        else:
            special_bb_labels["physical_res_down"] = "物理脆弱"
            labels.add("物理脆弱")
    if "phy_resist_down" in bb_values:
        special_bb_labels["phy_resist_down"] = "物理脆弱"

    semantic_bb_keys = {
        str(effect.get("bb_key") or "")
        for effect in semantic_condition_effects
        if str(effect.get("bb_key") or "")
    }
    semantic_bb_keys_lower = {key.lower() for key in semantic_bb_keys}
    packet_label_effects = [
        effect
        for effect in _packet_numeric_effects(record)
        if not (str(effect.get("bb_key") or "") and str(effect.get("bb_key") or "") in semantic_bb_keys)
    ]
    for effect in packet_label_effects + _packet_numeric_dynamic_effects(record):
        zone = str(effect.get("zone") or "")
        label = _EFFECT_ZONE_LABELS.get(zone)
        if label:
            labels.add(label)
    for effect in semantic_condition_effects:
        zone = str(effect.get("zone") or "")
        label = '承伤易伤' if zone == 'vuln_taken' else _EFFECT_ZONE_LABELS.get(zone)
        if label:
            labels.add(label)
    for bb_key in record.get("bb_keys") or []:
        lowered = str(bb_key).lower()
        if lowered in semantic_bb_keys_lower:
            continue
        if lowered in special_bb_labels:
            labels.add(special_bb_labels[lowered])
            continue
        _add_label(
            labels,
            _label_from_bb_key(
                str(bb_key),
                buff_id=buff_id,
                target_is_enemy=target_is_enemy,
            ),
        )

    attr_label_rows = record.get("attr_mods") or [
        {"attr_type": attr_type, "bb_key": ""}
        for attr_type in record.get("attr_types") or []
    ]
    for attr_mod in attr_label_rows:
        try:
            attr_type_int = int(attr_mod.get("attr_type"))
        except (TypeError, ValueError):
            continue
        bb_key = str(attr_mod.get("bb_key") or "").lower()
        if _buff_effect_bb_key_ignored(buff_id, bb_key):
            continue
        if bb_key in special_bb_labels:
            labels.add(special_bb_labels[bb_key])
            continue
        attr_effect = _ATTR_TYPE_TO_EFFECT.get(attr_type_int)
        if (
            attr_effect is not None
            and attr_effect[0] == "amp"
            and _is_damage_increase_bb_key(str(attr_mod.get("bb_key") or ""))
        ):
            continue
        if str(attr_mod.get("bb_key") or "") in _DEF_DECREASE_BASE_KEYS:
            labels.add("减抗")
            continue
        if attr_type_int in _FRAGILE_ATTR_TYPES:
            labels.add("脆弱")
            continue
        _add_label(labels, _ATTR_TYPE_BUFF_LABELS.get(attr_type_int))

    return sorted(labels, key=lambda item: (_BUFF_LABEL_PRIORITY.get(item, 99), item))



_ZONE_BY_LABEL = {
    "攻击提升": "atk",
    "增伤": "dmg_inc",
    "增幅": "amp",
    "脆弱": "fragile",
    "物理脆弱": "fragile",
    "物理脆弱 / 碎甲": "vuln_taken",
    "碎甲": "vuln_taken",
    "易伤": "vuln_taken",
    "承伤易伤": "vuln_taken",
    "减抗": "res",
    "连击增伤": "combo",
    "源石技艺强度": "arts_strength",
    "加速": "speedup",
    "缓速": "slow",
}


def _zone_from_label(label: str) -> str | None:
    return _ZONE_BY_LABEL.get(label)
