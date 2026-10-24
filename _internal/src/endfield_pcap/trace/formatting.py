from __future__ import annotations
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any
from endfield_pcap.runtime.paths import bundle_root


_UNKNOWN_ENEMY_KEY = "eny_0000_unknown"

_ENEMY_KEY_RE = re.compile(r"(eny_\d{4}_[a-z0-9]+)")

_DUNGEON_ENEMY_HINT_ALIASES: dict[str, str] = {
    "indie_hard011_s": "eny_0090_wgabyss",
    "indie_hard016": "eny_0046_lbshamman",
    "indie_hard016_s": "eny_0046_lbshamman",
    "indie_hard017": "eny_0095_ethillu",
    "indie_hard017_s": "eny_0095_ethillu",
    "indie_hard018": "eny_0082_hsbear",
    "indie_hard018_s": "eny_0082_hsbear",
    "indie_hard019": "eny_0088_wgthorns",
    "indie_hard019_s": "eny_0088_wgthorns",
    "indie_hard020": "eny_0107_wgshoal2",
    "indie_hard020_s": "eny_0107_wgshoal2",
    "indie_hard021": "eny_0102_hstiger2",
    "indie_hard021_s": "eny_0102_hstiger2",
    "dung01_bossrush01_01": "eny_0051_rodin",
    "dung01_bossrush01_02": "eny_0051_rodin",
    "dung01_bossrush01_03": "eny_0051_rodin",
    "dung01_bossrush01_04": "eny_0051_rodin",
    "dung01_bossrush03_01": "eny_0052_palesent",
    "dung01_bossrush03_02": "eny_0052_palesent",
    "dung01_bossrush03_03": "eny_0052_palesent",
    "dung02_bossrush02_01": "eny_0079_nefarp2",
    "dung02_bossrush02_02": "eny_0079_nefarp2",
    "dung02_bossrush02_03": "eny_0079_nefarp2",
}

def _intish(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

def _floatish(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

def _trace_string(value: Any) -> str:
    text = str(value or "")
    return json.dumps(text, ensure_ascii=False)

def _template_id(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    if not isinstance(value, dict):
        return None
    str_id = value.get("str_id")
    if isinstance(str_id, str) and str_id:
        return str_id
    int_id = _intish(value.get("int_id"))
    if int_id:
        typ = str(value.get("type") or "template").lower()
        return f"{typ}_{int_id}"
    return None

def _character_family_from_any(text: str | None) -> str:
    match = re.search(r"(chr_\d{4}_[a-z0-9]+)", str(text or ""))
    return match.group(1) if match else ""

def _enemy_family_from_any(text: str | None) -> str:
    match = _ENEMY_KEY_RE.search(str(text or ""))
    if not match:
        return ""
    enemy_key = match.group(1)
    return "" if enemy_key == _UNKNOWN_ENEMY_KEY else enemy_key

def _resource_dungeon_enemy_hints(root: Path) -> dict[str, str]:
    """Extract unambiguous dungeon -> enemy families from shipped game data."""
    mapping: dict[str, str] = {}
    item_root = root / "data" / "local_tables" / "dungeon" / "items"
    if not item_root.exists():
        return mapping
    for item_path in item_root.glob("*.json"):
        try:
            payload = json.loads(item_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        pending = [payload]
        while pending:
            node = pending.pop()
            if isinstance(node, dict):
                dungeon_id = str(node.get("dungeonId") or "").strip()
                enemy_ids = node.get("enemyIds")
                if dungeon_id and isinstance(enemy_ids, list):
                    enemy_keys = {
                        enemy_key
                        for raw_enemy_id in enemy_ids
                        if (enemy_key := _enemy_family_from_any(str(raw_enemy_id)))
                    }
                    if len(enemy_keys) == 1:
                        mapping.setdefault(dungeon_id, next(iter(enemy_keys)))
                pending.extend(node.values())
            elif isinstance(node, list):
                pending.extend(node)
    return mapping

@lru_cache(maxsize=1)
def _load_dungeon_enemy_hints() -> dict[str, str]:
    mapping = dict(_DUNGEON_ENEMY_HINT_ALIASES)
    root = bundle_root()
    for dungeon_id, enemy_key in _resource_dungeon_enemy_hints(root).items():
        mapping.setdefault(dungeon_id, enemy_key)
    path = root / "jsondata" / "Dungeon.json"
    if not path.exists():
        return mapping
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return mapping
    if not isinstance(payload, dict):
        return mapping
    for dungeon_id, raw_enemy_key in payload.items():
        enemy_key = _enemy_family_from_any(str(raw_enemy_key))
        if dungeon_id and enemy_key:
            mapping[str(dungeon_id)] = enemy_key
    return mapping

def _parse_equip_suit_counts(raw: Any) -> set[str]:
    if not isinstance(raw, str):
        return set()
    return {
        suit_id
        for suit_id, count in re.findall(r"\[([^\]]+)\]=(\d+)", raw)
        if int(count) >= 3
    }

def _blackboard_pairs(payload: Any) -> list[tuple[str, float]]:
    if not isinstance(payload, dict):
        return []
    blackboard = payload.get("blackboard")
    if not isinstance(blackboard, dict):
        return []
    pairs: list[tuple[str, float]] = []
    for key, item in blackboard.items():
        if not isinstance(item, dict):
            continue
        value = _floatish(item.get("float_value"))
        if value is None:
            value = _floatish(item.get("numeric_value"))
        if value is None:
            value = _floatish(item.get("value"))
        if value is not None:
            pairs.append((str(key), value))
    return pairs

def _modifier_uid_tokens(modifier_args: Any, field_name: str) -> list[str]:
    if not isinstance(modifier_args, dict):
        return []
    values: list[str] = []
    for item in modifier_args.get(field_name) or []:
        if not isinstance(item, dict):
            continue
        uid = str(item.get("buff_inst_id") or "")
        if uid:
            values.append(uid)
    return values

def _attr_info_tokens(battle_report_info: Any, field_name: str) -> list[str]:
    if not isinstance(battle_report_info, dict):
        return []
    values: list[str] = []
    for item in battle_report_info.get(field_name) or []:
        if not isinstance(item, dict):
            continue
        attr_type = _intish(item.get("attr_type"))
        attrs = item.get("attrs") if isinstance(item.get("attrs"), list) else []
        if attr_type is None:
            continue
        payload = ",".join(str(_floatish(value) if _floatish(value) is not None else value) for value in attrs)
        values.append(f"{attr_type}:{payload}")
    return values

def _entity_attr_tokens(attrs: Any) -> list[str]:
    if not isinstance(attrs, list):
        return []
    values: list[str] = []
    for item in attrs:
        if not isinstance(item, dict):
            continue
        attr_type = _intish(item.get("attr_type"))
        value = _floatish(item.get("value"))
        basic_value = _floatish(item.get("basic_value"))
        if attr_type is None:
            continue
        if value is None:
            value = 0.0
        if basic_value is None:
            basic_value = value
        values.append(f"{attr_type}:{value:.6g}/{basic_value:.6g}")
    return values
