from __future__ import annotations
import json
from pathlib import Path
from typing import Any


_CONTRACT_TAG_CLASS_NAMES = {
    "CS_CONTINGENCY_CONTRACT_SET_TAGS",
    "SC_CONTINGENCY_CONTRACT_SET_TAGS",
    "SC_CONTINGENCY_CONTRACT_TAGS_SYNC",
    "SC_CONTINGENCY_CONTRACT_BATTLE_RESULT",
}

def _load_multi_phase_dungeon_map(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return {}
    result: dict[str, str] = {}
    for dungeon_id, templateid in payload.items():
        dungeon = str(dungeon_id or "").strip()
        template = str(templateid or "").strip()
        if dungeon and template:
            result[dungeon] = template
    return result

def _attrs_payload(source: Any) -> list[dict[str, float | int]]:
    rows: list[dict[str, float | int]] = []
    attrs = getattr(source, "attrs", None)
    if attrs is None:
        attrs = getattr(source, "attr_list", [])
    for attr in attrs:
        attr_type = int(getattr(attr, "attr_type", 0) or 0)
        if not attr_type:
            continue
        rows.append(
            {
                "attr_type": attr_type,
                "basic_value": float(getattr(attr, "basic_value", 0.0) or 0.0),
                "value": float(getattr(attr, "value", 0.0) or 0.0),
            }
        )
    return rows

def _proto_has_field(message: Any, field_name: str) -> bool:
    try:
        return bool(message.HasField(field_name))
    except (AttributeError, ValueError):
        return getattr(message, field_name, None) is not None

def _optional_int(value: Any) -> int | None:
    try:
        number = int(value or 0)
    except (TypeError, ValueError):
        return None
    return number or None
