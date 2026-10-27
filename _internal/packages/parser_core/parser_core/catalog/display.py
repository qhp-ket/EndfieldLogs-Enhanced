"""Enemy names and conservative legacy display-label formatting."""
from __future__ import annotations

from functools import lru_cache
from parser_core.catalog.names import _load_skill_exact_names, _load_skill_name_prefixes
from parser_core.catalog.resources import _repo_root
import json
import re
from typing import Any


_BUFF_DAMAGE_NAME_OVERRIDES = {
    "buff_physical_airborne": "物理浮空伤害",
    "buff_physical_crushed": "猛击",
    "buff_physical_knockdown": "倒地",
    "buff_physical_no_guard": "破防",
    "buff_chr_0028_wulfa_normal_bleed": "爪印斫痕",
    "buff_chr_0028_wulfa_normal_bleed_effect": "爪印斫痕",
    "buff_chr_0028_wulfa_normal_bleed_crit_extra_damage": "沸血",
    "buff_chr_0028_wulfa_combo_2_damage": "燎影时刻",
    "buff_common_cryst_triggered_physical_break": "猛击",
    "buff_common_heal_moss_1": "治疗苔藓",
    "buff_common_heal_moss_2": "治疗苔藓",
    "buff_common_originum_frozen": "源石冻结",
}


_ELEMENT_TOKEN_TO_NAME = {
    "physical": "物理",
    "fire": "灼热",
    "pulse": "电磁",
    "cryst": "寒冷",
    "crystal": "寒冷",
    "natural": "自然",
    "spell": "法术",
}


_ATTACK_VARIANT_RE = re.compile(
    r"^chr_\d{4}_[a-z0-9]+_attack_?(\d+)(?:_(\d+))?(?:_projhit)?(?:_blocked)?$",
    re.IGNORECASE,
)


_DASH_ATTACK_RE = re.compile(r"^chr_\d{4}_[a-z0-9]+_dash_attack(?:_projhit(?:\d+)?)?$", re.IGNORECASE)


_PLUNGING_ATTACK_RE = re.compile(
    r"^chr_\d{4}_[a-z0-9]+_plunging_attack(?:_(start|end|projhit))?$",
    re.IGNORECASE,
)


_TALENT_RE = re.compile(r"^chr_\d{4}_[a-z0-9]+_talent_?(\d+)(?:_(\d+))?$", re.IGNORECASE)


_POTENTIAL_RE = re.compile(r"^chr_\d{4}_[a-z0-9]+_potential_?(\d+)(?:_(\d+))?$", re.IGNORECASE)


_PASSIVE_RE = re.compile(r"^chr_\d{4}_[a-z0-9]+_passive(?:_(.+))?$", re.IGNORECASE)


@lru_cache(maxsize=1)
def _load_enemy_names() -> dict[str, str]:
    manifest_path = _repo_root() / "data" / "akedata" / "enemy" / "manifest.json"
    if not manifest_path.exists():
        return {}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return {
        str(entry.get("templateId")): str(entry.get("name"))
        for entry in manifest
        if entry.get("templateId") and entry.get("name")
    }


def _resolve_enemy_name(enemy_key: str | None) -> str | None:
    if not enemy_key:
        return None
    return _load_enemy_names().get(enemy_key, enemy_key)


@lru_cache(maxsize=1)
def _load_buff_manifest_names() -> dict[str, str]:
    manifest_path = _repo_root() / "data" / "akedata" / "buff" / "manifest.json"
    if not manifest_path.exists():
        return {}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return {
        str(entry.get("id")): str(entry.get("name"))
        for entry in manifest
        if entry.get("id") and entry.get("name")
    }


def _humanize_buff_damage_name(skill_key: str) -> str | None:
    override = _BUFF_DAMAGE_NAME_OVERRIDES.get(skill_key)
    if override is not None:
        return override

    manifest_name = _load_buff_manifest_names().get(skill_key, skill_key.removeprefix("buff_"))
    normalized = manifest_name.removeprefix("buff_")

    anomaly_do_match = re.match(
        r"^common_(fire|pulse|cryst|natural)_(?:fire|pulse|cryst|natural)_(conduct_triggered_do|corrupt_do)$",
        normalized,
    )
    if anomaly_do_match:
        action = anomaly_do_match.group(2)
        if action == "conduct_triggered_do":
            return "导电"
        if action == "corrupt_do":
            return "腐蚀"

    same_element_burst_match = re.match(
        r"^common_(fire|pulse|cryst|natural|spell)_\1_triggered$",
        normalized,
    )
    if same_element_burst_match:
        element = _ELEMENT_TOKEN_TO_NAME.get(same_element_burst_match.group(1), same_element_burst_match.group(1))
        return f"{element}爆发"

    cross_element_trigger_match = re.match(
        r"^common_(fire|pulse|cryst|natural)_(fire|pulse|cryst|natural)_triggered$",
        normalized,
    )
    if cross_element_trigger_match:
        applied = cross_element_trigger_match.group(1)
        anomaly_name = {
            "fire": "燃烧",
            "pulse": "导电",
            "cryst": "冻结",
            "natural": "腐蚀",
        }.get(applied)
        if anomaly_name:
            return anomaly_name

    if normalized.startswith("common_") and normalized.endswith("_triggered"):
        parts = normalized.split("_")
        if len(parts) >= 4:
            left = _ELEMENT_TOKEN_TO_NAME.get(parts[1], parts[1])
            right = _ELEMENT_TOKEN_TO_NAME.get(parts[2], parts[2])
            return f"{left}·{right}触发"

    if normalized.startswith("enemy_spell_") and "_triggered_" in normalized:
        parts = normalized.split("_")
        if len(parts) >= 5:
            element = _ELEMENT_TOKEN_TO_NAME.get(parts[2], parts[2])
            return f"敌方法术{element}触发"

    if normalized.endswith("_airborne"):
        prefix = normalized.removesuffix("_airborne")
        prefix_name = _ELEMENT_TOKEN_TO_NAME.get(prefix, prefix)
        return f"{prefix_name}浮空伤害"

    if normalized.startswith("common_heal_moss_"):
        return "治疗苔藓"

    if normalized.startswith("chr_"):
        character_skill_name = _humanize_character_skill_name(normalized)
        if character_skill_name is not None:
            return character_skill_name

    if normalized.startswith("common_"):
        readable = normalized.removeprefix("common_").replace("_", " ")
        return readable

    return None


def _humanize_skill_suffix_text(suffix: str) -> str | None:
    text = suffix.strip("_").lower()
    if not text:
        return None
    explicit = {
        "abilityentity": "实体",
        "abilityentitymove": "实体移动",
        "abilityrange": "范围",
        "air_attack_abilityrange": "空中攻击范围",
        "air_attack_projhit": "空中攻击派生",
        "air_attack_sheep": "空中攻击 / 绵羊",
        "blocked": "格挡",
        "during_ult": "终结技期间",
        "gene_sheep": "召唤绵羊",
        "hit": "命中",
        "hit_self": "自身命中",
        "indicator": "指示器",
        "listen_combo": "连携监听",
        "projhit": "派生",
        "remain_loop_sheep": "绵羊持续伤害",
        "sheep": "绵羊派生",
        "shockwave": "冲击波",
        "start": "起手",
    }
    if text in explicit:
        return explicit[text]

    absorb_match = re.match(r"absorb(?:_(\d+))?_projhit$", text)
    if absorb_match:
        slot = absorb_match.group(1)
        return f"吸收{slot}派生" if slot else "吸收派生"

    attack_match = re.match(r"attack_?(\d+)(?:_(\d+))?_projhit(?:_blocked)?$", text)
    if attack_match:
        attack_index = attack_match.group(1)
        sub_index = attack_match.group(2)
        base = f"A{attack_index}"
        if sub_index:
            base += f"-{sub_index}"
        if text.endswith("_blocked"):
            return f"{base} 派生（格挡）"
        return f"{base} 派生"

    tokens = [token for token in text.split("_") if token]
    if not tokens:
        return None
    token_map = {
        "absorb": "吸收",
        "air": "空中",
        "airborne": "浮空",
        "attack": "攻击",
        "blocked": "格挡",
        "bleed": "流血",
        "break": "击破",
        "combo": "连携",
        "damage": "伤害",
        "drone": "无人机",
        "effect": "效果",
        "entity": "实体",
        "extra": "额外",
        "fx": "特效",
        "loop": "循环",
        "move": "移动",
        "normal": "普攻",
        "projhit": "派生",
        "range": "范围",
        "remain": "持续",
        "self": "自身",
        "sheep": "绵羊",
        "shockwave": "冲击波",
        "spawn": "召唤",
        "talent": "天赋",
    }
    pretty = [token_map.get(token, token.upper() if token.isdigit() else token) for token in tokens]
    return " / ".join(pretty)


def _humanize_character_skill_name(skill_key: str) -> str | None:
    exact_name = _load_skill_exact_names().get(skill_key)
    if exact_name:
        return exact_name

    lowered = skill_key.lower()

    if lowered.endswith("_dodge"):
        return "闪避"

    if _DASH_ATTACK_RE.match(lowered):
        return "闪避攻击 派生" if "projhit" in lowered else "闪避攻击"

    if lowered.endswith("_power_attack"):
        return "重击"

    plunging_match = _PLUNGING_ATTACK_RE.match(lowered)
    if plunging_match:
        phase = plunging_match.group(1)
        if phase == "projhit":
            return "下落攻击 派生"
        if phase == "start":
            return "下落攻击 起手"
        return "下落攻击"

    attack_match = _ATTACK_VARIANT_RE.match(lowered)
    if attack_match:
        attack_index = attack_match.group(1)
        sub_index = attack_match.group(2)
        base = f"A{attack_index}"
        if sub_index:
            base += f"-{sub_index}"
        if "projhit" in lowered and "blocked" in lowered:
            return f"{base} 派生（格挡）"
        if "projhit" in lowered:
            return f"{base} 派生"
        return base

    talent_match = _TALENT_RE.match(lowered)
    if talent_match:
        tier = talent_match.group(1)
        branch = talent_match.group(2)
        return f"天赋{tier}-{branch}" if branch else f"天赋{tier}"

    potential_match = _POTENTIAL_RE.match(lowered)
    if potential_match:
        tier = potential_match.group(1)
        branch = potential_match.group(2)
        return f"潜能{tier}-{branch}" if branch else f"潜能{tier}"

    passive_match = _PASSIVE_RE.match(lowered)
    if passive_match:
        suffix = _humanize_skill_suffix_text(passive_match.group(1) or "")
        return f"被动 / {suffix}" if suffix else "被动"
    if lowered.endswith("_passive"):
        suffix_name = _humanize_skill_suffix_text(lowered.split("_", 3)[-1].removesuffix("_passive"))
        return f"被动 / {suffix_name}" if suffix_name else "被动"

    talent_suffix_index = lowered.find("_talent_")
    if talent_suffix_index >= 0:
        suffix_name = _humanize_skill_suffix_text(lowered[talent_suffix_index + len("_talent_"):])
        return f"天赋 / {suffix_name}" if suffix_name else "天赋"

    if lowered.endswith("_tactic_skill"):
        return "战术技"

    if lowered.endswith("_extra_attack_projhit"):
        return "追加攻击 派生"
    if lowered.endswith("_extra_attack"):
        return "追加攻击"

    for base_suffix in ("_normal_skill", "_combo_skill", "_ultimate_skill"):
        if base_suffix not in lowered:
            continue
        base_index = lowered.index(base_suffix) + len(base_suffix)
        base_key = skill_key[:base_index]
        suffix = skill_key[base_index:]
        base_name = _load_skill_exact_names().get(base_key)
        suffix_name = _humanize_skill_suffix_text(suffix)
        if base_name and suffix_name:
            return f"{base_name} / {suffix_name}"
        if base_name:
            return base_name
        break

    for base_key, base_name in _load_skill_name_prefixes():
        prefix = f"{base_key}_"
        if not skill_key.startswith(prefix):
            continue
        suffix_name = _humanize_skill_suffix_text(skill_key[len(base_key):])
        if suffix_name:
            return f"{base_name} / {suffix_name}"
        break

    suffix_patterns = (
        "remain_loop",
        "air_attack",
        "absorb",
        "abilityentity",
        "airborne",
        "bleed",
        "break",
        "damage",
        "effect",
        "projhit",
        "blocked",
        "sheep",
    )
    if any(pattern in lowered for pattern in suffix_patterns):
        if "_remain_loop_" in lowered:
            suffix_name = _humanize_skill_suffix_text(lowered.split("_", 3)[-1])
            if suffix_name:
                return suffix_name
        tail = lowered.split("_", 3)[-1]
        suffix_name = _humanize_skill_suffix_text(tail)
        if suffix_name:
            return suffix_name

    return None


def _humanize_generic_skill_tokens(text: str) -> str | None:
    value = text.strip("_").lower()
    if not value:
        return None
    explicit = {
        "abilityrange": "范围",
        "activityspecial": "活动特化",
        "battleact": "战斗动作",
        "bornexit": "出场结束",
        "bornstart": "出场开始",
        "death": "死亡",
        "doodad": "装置",
        "dungeon": "副本",
        "endinggame": "终局",
        "explosion": "爆炸",
        "ex": "EX",
        "hard": "高难",
        "interact": "交互",
        "passive": "被动",
        "projhit": "派生",
        "settlement": "结算",
        "store": "存储",
    }
    if value in explicit:
        return explicit[value]

    skill_match = re.fullmatch(r"skill0?(\d+)", value)
    if skill_match:
        return f"技能{int(skill_match.group(1))}"

    dash_match = re.fullmatch(r"dash_([bflr])", value)
    if dash_match:
        direction = {"b": "后", "f": "前", "l": "左", "r": "右"}.get(dash_match.group(1), dash_match.group(1))
        return f"冲刺（{direction}）"

    tokens = [token for token in value.split("_") if token]
    token_map = {
        "abilityentity": "实体",
        "activityspecial": "活动特化",
        "anchor": "锚点",
        "attack": "攻击",
        "attackcore": "核心攻击",
        "attackplayer": "玩家攻击",
        "battleact": "战斗动作",
        "boom": "爆破",
        "bomb": "炸弹",
        "carpet": "地毯",
        "container": "容器",
        "core": "核心",
        "dash": "冲刺",
        "death": "死亡",
        "doodad": "装置",
        "endinggame": "终局",
        "entity": "实体",
        "explosion": "爆炸",
        "fire": "火焰",
        "flammable": "可燃",
        "interact": "交互",
        "matrix": "矩阵",
        "mud": "泥沼",
        "oil": "油桶",
        "passive": "被动",
        "plus": "强化",
        "projhit": "派生",
        "range": "范围",
        "settlement": "结算",
        "special": "特殊",
        "store": "存储",
        "wall": "墙",
        "wave": "波动",
        "weekraid": "周常",
    }
    pretty: list[str] = []
    for token in tokens:
        skill_match = re.fullmatch(r"skill0?(\d+)", token)
        if skill_match:
            pretty.append(f"技能{int(skill_match.group(1))}")
            continue
        dash_match = re.fullmatch(r"dash_([bflr])", token)
        if dash_match:
            direction = {"b": "后", "f": "前", "l": "左", "r": "右"}.get(dash_match.group(1), dash_match.group(1))
            pretty.append(f"冲刺（{direction}）")
            continue
        pretty.append(token_map.get(token, token.upper() if token.isdigit() else token))
    return " / ".join(pretty) if pretty else None


def _humanize_generic_skill_name(skill_key: str) -> str | None:
    lowered = skill_key.lower()
    if lowered.startswith("eny_"):
        parts = lowered.split("_", 3)
        suffix = parts[3] if len(parts) >= 4 else ""
        suffix_name = _humanize_generic_skill_tokens(suffix)
        return f"敌方 / {suffix_name}" if suffix_name else "敌方技能"
    if lowered.startswith("abilityentity_"):
        suffix_name = _humanize_generic_skill_tokens(lowered.removeprefix("abilityentity_"))
        return f"实体 / {suffix_name}" if suffix_name else "实体技能"
    if lowered.startswith("common_"):
        suffix_name = _humanize_generic_skill_tokens(lowered.removeprefix("common_"))
        return f"通用 / {suffix_name}" if suffix_name else "通用技能"
    return None
