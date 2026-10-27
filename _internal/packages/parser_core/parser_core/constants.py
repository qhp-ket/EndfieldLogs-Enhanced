"""Stable report versions and sentinel identities shared by parser stages."""

PARSER_VERSION = "raw-log-parser-v60"
RULES_VERSION = "raw-log-parser-v45"
UNKNOWN_DUNGEON_KEY = "unknown_dungeon"
UNKNOWN_ENEMY_KEY = "eny_0000_unknown"

import re

_STATIC_TRIGGER_DAMAGE_BUFF_RE = re.compile(r"^buff_[a-z0-9_]+(?:triggered|damage)[a-z0-9_]*$", re.IGNORECASE)

_BUFF_MERGE_GAP_MS = 250

_CHAR_TYPE_TO_ELEMENT = {
    "物理": "physical",
    "灼热": "fire",
    "寒冷": "cryst",
    "电磁": "pulse",
    "自然": "natural",
    "Physical": "physical",
    "Fire": "fire",
    "Cryst": "cryst",
    "Pulse": "pulse",
    "Natural": "natural",
    "Ether": "ether",
}

_ATTR_TYPE_TO_LABEL = {
    39: "力量",
    40: "敏捷",
    41: "智识",
    42: "意志",
}

_ATTR_LABEL_TO_TYPE = {value: key for key, value in _ATTR_TYPE_TO_LABEL.items()}

_DEF_DECREASE_ATTR_TYPE_TO_EFFECT = {
    80: ("res", "physical"),
    81: ("res", "natural"),
    82: ("res", "cryst"),
    83: ("res", "pulse"),
    84: ("res", "fire"),
    85: ("res", "ether"),
}

_DPD_DAMAGE_TYPE_TO_ELEMENT = {
    0: "physical",
    1: "real",
    2: "fire",
    3: "pulse",
    4: "cryst",
    5: "lifedrain",
    6: "natural",
    7: "ether",
}

_ELEMENT_LABELS = {
    "physical": "物理",
    "fire": "灼热",
    "pulse": "电磁",
    "cryst": "寒冷",
    "natural": "自然",
    "ether": "源石技艺",
    "real": "真实",
    "lifedrain": "生命汲取",
    "spell": "法术",
}

_SINGLETON_REFRESH_EVENT_PATTERNS = (
    re.compile(r"^buff_equipsuit_", re.IGNORECASE),
    re.compile(r"^buff_chr_\d{4}_[a-z0-9]+_potential_\d+(?:_|$)", re.IGNORECASE),
)

_STACKABLE_EVENT_NAME_RE = re.compile(r"(?:^|_)(?:layer|stack)(?:_|$)", re.IGNORECASE)

_GENERIC_BUFF_PREFIXES = (
    "buff_common_affixes_enhance_",
    "buff_common_affixes_vulnerable_",
    "buff_common_pulse_",
    "buff_common_fire_",
    "buff_common_cryst_",
    "buff_common_natural_",
)

_PLAYER_TARGET_GENERIC_BUFF_PREFIXES = (
    "buff_common_affixes_enhance_",
)

_CHR_BORROW_WINDOW_MS = 1000

_DEF_DECREASE_TICKS_PER_SEC = 3.5

_ATTACK_INDEX_RE = re.compile(r"_attack(\d+)")

_COMBO_SKILL_RE = re.compile(r"_combo(?:_\d+)?_skill(?:$|_)")

_COMBO_DAMAGE_SKILL_KEY_RE = re.compile(
    r"^buff_(chr_\d{4}_[a-z0-9]+_combo(?:_\d+)?_)damage(?:wait)?$",
    re.IGNORECASE,
)

_FINAL_BB_KEY_OVERRIDES = {
    "spell_resistance_decrease": "final_spell_resistance_decrease",
}
