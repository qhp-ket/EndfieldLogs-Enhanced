"""Read enhanced child actions from decoded typed resources."""
from __future__ import annotations

from functools import lru_cache
from parser_core.catalog.buff_templates import _buff_decoded_detail_path
from parser_core.catalog.buff_templates import _load_local_buff_semantic_entries
import json
from typing import Any


_ENHANCED_ACTION_SUBTYPE_TO_ELEMENT = {
    "crystal": "cryst",
    "cryst": "cryst",
    "natural": "natural",
    "fire": "fire",
    "pulse": "pulse",
    "physical": "physical",
    "spell": "spell",
    "all": "all",
}


def _walk_enhanced_action_child_specs(payload: Any, *, target_child_buff_id: str) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            type_name = str(node.get("$type") or "")
            if "EnhancedAction+Data" in type_name:
                child_buff = node.get("childBuffId") if isinstance(node.get("childBuffId"), dict) else {}
                child_buff_id = str(child_buff.get("value") or "")
                subtype = str(node.get("subType") or "").lower()
                element = _ENHANCED_ACTION_SUBTYPE_TO_ELEMENT.get(subtype)
                if (
                    node.get("asChildBuff")
                    and child_buff_id == target_child_buff_id
                    and element
                ):
                    rate_cfg = node.get("rate") if isinstance(node.get("rate"), dict) else {}
                    specs.append(
                        {
                            "zone": "amp",
                            "element": element,
                            "bb_key": str(rate_cfg.get("blackboardKey") or ""),
                            # Child buff instances often carry the copied rate under a plain runtime `rate` key.
                            "prefer_runtime_rate_key": "rate",
                        }
                    )
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(payload)
    return specs


@lru_cache(maxsize=4096)
def _enhanced_action_child_effect_specs(buff_id: str) -> list[dict[str, Any]]:
    target_child_buff_id = str(buff_id or "")
    if not target_child_buff_id:
        return []
    reverse_parents: set[str] = set()
    for parent_buff_id, entry in _load_local_buff_semantic_entries().items():
        if not isinstance(entry, dict):
            continue
        referenced = {
            str(value)
            for value in entry.get("referencedBuffIds") or []
            if str(value or "")
        }
        if target_child_buff_id in referenced:
            reverse_parents.add(str(parent_buff_id))
    specs: list[dict[str, Any]] = []
    for parent_buff_id in sorted(reverse_parents):
        path = _buff_decoded_detail_path(parent_buff_id)
        if path is None:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        specs.extend(_walk_enhanced_action_child_specs(payload, target_child_buff_id=target_child_buff_id))
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for spec in specs:
        key = (
            str(spec.get("zone") or ""),
            str(spec.get("element") or ""),
            str(spec.get("bb_key") or ""),
            str(spec.get("prefer_runtime_rate_key") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(spec)
    return deduped
