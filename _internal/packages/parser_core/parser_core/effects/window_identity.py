"""Buff instance identities, effect signatures and content-preserving merges."""
from __future__ import annotations

from parser_core.catalog.buff_templates import _load_current_buff_roots
from parser_core.effects.damage_types import _normalize_effect_element
import json
from typing import Any


def _window_uid_aliases(window: dict[str, Any]) -> set[str]:
    aliases: set[str] = set()
    uid = str(window.get("uid") or "")
    if uid:
        aliases.add(uid)
    for alias in window.get("uid_aliases") or []:
        text = str(alias or "")
        if text:
            aliases.add(text)
    return aliases


def _merge_window_uid_aliases(target: dict[str, Any], other: dict[str, Any]) -> None:
    aliases = _window_uid_aliases(target) | _window_uid_aliases(other)
    primary_uid = str(target.get("uid") or "")
    if primary_uid:
        aliases.discard(primary_uid)
    target["uid_aliases"] = sorted(aliases)


def _effect_condition_signature(effect: dict[str, Any]) -> str:
    condition = effect.get("condition")
    if not isinstance(condition, dict):
        return ""
    return json.dumps(condition, ensure_ascii=False, sort_keys=True)


def _effect_row_signature(effect: dict[str, Any]) -> tuple[Any, ...]:
    if "rate" in effect:
        return (
            "static",
            str(effect.get("zone") or ""),
            _normalize_effect_element(effect.get("element")),
            round(float(effect.get("rate") or 0.0), 6),
            str(effect.get("bb_key") or ""),
            int(effect.get("attr_type")) if effect.get("attr_type") is not None else None,
            _effect_condition_signature(effect),
            effect.get('recipient_side'),
            effect.get('external_rdps_allowed'),
            tuple(sorted(effect.get('rdps_whitelist_keys') or [])),
        )
    return (
        "dynamic",
        str(effect.get("zone") or ""),
        _normalize_effect_element(effect.get("element")),
        round(float(effect.get("base_rate") or 0.0), 6),
        round(float(effect.get("tick_rate") or 0.0), 6),
        round(float(effect.get("max_rate") or 0.0), 6),
        round(float(effect.get("delayed_add_rate") or 0.0), 6),
        round(float(effect.get("delay_sec") or 0.0), 6),
        str(effect.get("bb_key") or ""),
        str(effect.get("add_bb_key") or ""),
        str(effect.get("delay_bb_key") or ""),
        _effect_condition_signature(effect),
        effect.get('recipient_side'),
        effect.get('external_rdps_allowed'),
        tuple(sorted(effect.get('rdps_whitelist_keys') or [])),
    )


def _merge_effect_lists(primary: list[dict[str, Any]] | None, secondary: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for effect in [*(primary or []), *(secondary or [])]:
        if not isinstance(effect, dict):
            continue
        signature = _effect_row_signature(effect)
        if signature in seen:
            continue
        seen.add(signature)
        merged.append(dict(effect))
    return merged


def _prefer_window_event_name(primary: dict[str, Any], secondary: dict[str, Any]) -> str:
    primary_name = str(primary.get("event_name") or "")
    secondary_name = str(secondary.get("event_name") or "")
    event_key = str(primary.get("event_key") or secondary.get("event_key") or "")
    if primary_name and primary_name != event_key and secondary_name == event_key:
        return primary_name
    if secondary_name and secondary_name != event_key and primary_name == event_key:
        return secondary_name
    if len(secondary_name) > len(primary_name):
        return secondary_name
    return primary_name or secondary_name or event_key


def _merge_window_content(target: dict[str, Any], other: dict[str, Any]) -> None:
    target_start = int(target.get("start_ts_ms") or 0)
    other_start = int(other.get("start_ts_ms") or 0)
    target_line = int(target.get("start_line_no") or target.get("line_no") or 0)
    other_line = int(other.get("start_line_no") or other.get("line_no") or 0)
    if other_start < target_start or (other_start == target_start and other_line and (not target_line or other_line < target_line)):
        target["start_line_no"] = other_line
    _merge_window_uid_aliases(target, other)
    target["end_ts_ms"] = max(int(target.get("end_ts_ms") or 0), int(other.get("end_ts_ms") or 0))
    target["duration_ms"] = max(int(target["end_ts_ms"]) - int(target.get("start_ts_ms") or 0), 1)
    target["zone_effects"] = _merge_effect_lists(target.get("zone_effects"), other.get("zone_effects"))
    target["dynamic_effects"] = _merge_effect_lists(target.get("dynamic_effects"), other.get("dynamic_effects"))
    target["event_name"] = _prefer_window_event_name(target, other)
    if not target.get("stack_limit") and other.get("stack_limit"):
        target["stack_limit"] = other.get("stack_limit")


def _buff_window_stack_group_key(window: dict[str, Any]) -> tuple[str, str, str, str]:
    event_key = str(window.get('event_key') or '')
    root = _load_current_buff_roots().get(event_key)
    settings = root.get('stackingSettings') if isinstance(root, dict) else None
    key = event_key
    if isinstance(settings, dict) and settings.get('identifierType') == 'StackingKey':
        key = str(settings.get('stackingKey') or '')
    # BuffContainer owns the dictionary; BuffData.get_stackingKey supplies its
    # key. Source and skill family are not part of the native grouping rule.
    actor_id = str(window.get('target_actor_id') or '')
    return (
        'actor' if actor_id else 'unresolved_actor',
        actor_id or str(window.get('target_character_key') or ''),
        key,
        '',
    )
