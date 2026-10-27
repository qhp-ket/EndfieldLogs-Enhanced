"""Merge equivalent effect windows and retain explicit stack selection evidence."""
from __future__ import annotations

from parser_core.catalog.buff_templates import _load_current_buff_roots
from parser_core.effects.stacking_rules import _buff_stack_limit
from parser_core.ingestion.fields import _positive_int
import json
from typing import Any

from collections import defaultdict
from functools import lru_cache
from parser_core.catalog.buff_templates import _buff_classifier_hint
from parser_core.catalog.buff_templates import _load_local_buff_semantic_entries
from parser_core.effects.damage_types import _ELEMENTAL_ELEMENTS
from parser_core.effects.damage_types import _normalize_effect_element
from parser_core.effects.window_identity import _effect_condition_signature


def _merge_buff_windows(buff_windows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Temporal proximity does not prove refresh or shared instance identity.
    return sorted(buff_windows, key=lambda row: (
        int(row.get("start_ts_ms") or 0), int(row.get("line_no") or 0),
    ))


def _apply_buff_stack_limits(buff_windows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # A stack limit constrains the enabled set, not instance lifetime. A lower
    # priority instance can remain alive while disabled and later be enabled.
    # Never invent BUFF_END by dropping the oldest UID. Resolve competing
    # instances at each hit, after applying the observed enable timeline.
    limited: list[dict[str, Any]] = []
    for window in buff_windows:
        window = dict(window)
        root = _load_current_buff_roots().get(str(window.get('event_key') or ''))
        stacking = root.get('stackingSettings') if isinstance(root, dict) else None
        if isinstance(stacking, dict):
            window['stacking_type'] = stacking.get('stackingType')
            limit = _buff_stack_limit(str(window.get("event_key") or ""), window.get('bb_values'))
            if window['stacking_type'] == 'Unlimited':
                limit = None
            elif limit is None:
                window['rdps_unresolved_stack_evidence'] = True
        else:
            limit = _positive_int(window.get('stack_limit'))
        window['stack_limit'] = limit
        if int(window.get('end_ts_ms') or 0) < int(window.get('start_ts_ms') or 0):
            continue
        window["duration_ms"] = max(int(window["end_ts_ms"]) - int(window["start_ts_ms"]), 1)
        limited.append(window)
    return sorted(limited, key=lambda item: (int(item.get("start_ts_ms") or 0), str(item.get("event_key") or "")))


def _dedupe_mirrored_buff_windows(buff_windows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Remove only repeated observations of the same instance with identical
    # boundaries and effect data. Never select a richer-looking sibling.
    seen = set()
    result = []
    for window in buff_windows:
        uid = str(window.get("uid") or "")
        if not uid:
            result.append(window)
            continue
        identity = json.dumps({key: window.get(key) for key in (
            "uid", "uid_aliases", "source_character_key", "target_character_key", "event_key", "target_actor_id", "source_actor_id",
            "start_ts_ms", "end_ts_ms", "zone_effects", "dynamic_effects", "effect_segments",
            "start_line_no", "end_line_no", "snapshot_end_ts_ms", "snapshot_end_line_no",
            "enable_observations", "snapshot_update",
        )}, sort_keys=True, ensure_ascii=False)
        if identity not in seen:
            seen.add(identity)
            result.append(window)
    return result



_BUFF_MIRROR_DEDUPE_WINDOW_MS = 500


def _static_effect_signature(window: dict[str, Any]) -> tuple[tuple[Any, ...], ...] | None:
    if window.get("dynamic_effects"):
        return None
    effects = window.get("zone_effects") or []
    if not effects:
        return None
    signature: list[tuple[Any, ...]] = []
    for effect in effects:
        try:
            rate = round(float(effect.get("rate") or 0.0), 4)
        except (TypeError, ValueError):
            return None
        if rate <= 0:
            return None
        signature.append(
            (
                str(effect.get("zone") or ""),
                _normalize_effect_element(effect.get("element")),
                rate,
                _effect_condition_signature(effect),
            )
        )
    return tuple(sorted(signature))


def _dynamic_effect_signature(window: dict[str, Any]) -> tuple[tuple[str, str, float, float, float, float, float], ...] | None:
    effects = window.get("dynamic_effects") or []
    if not effects:
        return None
    signature: list[tuple[str, str, float, float, float, float, float]] = []
    for effect in effects:
        try:
            signature.append(
                (
                    str(effect.get("zone") or ""),
                    _normalize_effect_element(effect.get("element")),
                    round(float(effect.get("base_rate") or 0.0), 6),
                    round(float(effect.get("tick_rate") or 0.0), 6),
                    round(float(effect.get("max_rate") or 0.0), 6),
                    round(float(effect.get("delayed_add_rate") or 0.0), 6),
                    round(float(effect.get("delay_sec") or 0.0), 6),
                )
            )
        except (TypeError, ValueError):
            return None
    return tuple(sorted(signature))


def _window_detail_count(window: dict[str, Any]) -> int:
    return len(window.get("zone_effects") or []) + len(window.get("dynamic_effects") or [])


def _same_event_window_signature_matches(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_static = set(_static_effect_signature(left) or [])
    right_static = set(_static_effect_signature(right) or [])
    left_dynamic = _dynamic_effect_signature(left)
    right_dynamic = _dynamic_effect_signature(right)
    if left_dynamic != right_dynamic:
        return False
    if left_static == right_static:
        return True
    if not left_static or not right_static:
        return True
    return left_static.issuperset(right_static) or right_static.issuperset(left_static)


def _mirror_preference_score(window: dict[str, Any]) -> int:
    event_key = str(window.get("event_key") or "")
    hint = _buff_classifier_hint(event_key) or {}
    classification = hint.get("classification")
    score = 0
    if int(window.get("modifier_count") or 0) > 0:
        score += 4
    if classification == "effect_buff":
        score += 3
    elif classification == "wrapper":
        score -= 2
    elif classification == "marker_or_utility":
        score -= 3
    lowered = event_key.lower()
    if "icon" in lowered or "vfx" in lowered:
        score -= 1
    return score


def _event_key_parent_of_default_child(event_key: str | None) -> str | None:
    text = str(event_key or "")
    suffix = "_default_child"
    if not text.endswith(suffix):
        return None
    return text[: -len(suffix)]


def _effect_elements_compatible(parent_element: str, child_element: str) -> bool:
    if parent_element == child_element:
        return True
    if child_element == "all":
        return True
    if child_element == "spell":
        return parent_element in _ELEMENTAL_ELEMENTS or parent_element == "spell"
    return False


def _parent_window_covers_default_child(parent: dict[str, Any], child: dict[str, Any]) -> bool:
    parent_effects = parent.get("zone_effects") or []
    child_effects = child.get("zone_effects") or []
    if not parent_effects or not child_effects:
        return False

    parent_elements_by_lane: defaultdict[tuple[str, float], set[str]] = defaultdict(set)
    for effect in parent_effects:
        try:
            rate = round(float(effect.get("rate") or 0.0), 6)
        except (TypeError, ValueError):
            continue
        if rate <= 0:
            continue
        lane = (str(effect.get("zone") or ""), rate)
        parent_elements_by_lane[lane].add(_normalize_effect_element(effect.get("element")))

    for child_effect in child_effects:
        try:
            child_rate = round(float(child_effect.get("rate") or 0.0), 6)
        except (TypeError, ValueError):
            return False
        child_lane = (str(child_effect.get("zone") or ""), child_rate)
        parent_elements = parent_elements_by_lane.get(child_lane)
        if not parent_elements:
            return False
        child_element = _normalize_effect_element(child_effect.get("element"))
        if child_element in {"spell", "all"} and len(parent_elements & _ELEMENTAL_ELEMENTS) < 2:
            if child_element not in parent_elements and "all" not in parent_elements:
                return False
        elif not any(_effect_elements_compatible(parent_element, child_element) for parent_element in parent_elements):
            return False
    return True


@lru_cache(maxsize=4096)
def _created_child_buff_ids(buff_id: str) -> set[str]:
    ids: set[str] = set()
    entry = _load_local_buff_semantic_entries().get(str(buff_id or ""))
    if isinstance(entry, dict):
        ids.update(str(value) for value in entry.get("createdBuffIds") or [] if str(value or ""))
    hint = _buff_classifier_hint(str(buff_id or "")) or {}
    ids.update(str(value) for value in hint.get("createdBuffIds") or [] if str(value or ""))
    return ids


def _window_static_effect_pairs(window: dict[str, Any]) -> set[tuple[str, str, float]]:
    pairs: set[tuple[str, str, float]] = set()
    for effect in window.get("zone_effects") or []:
        try:
            rate = round(float(effect.get("rate") or 0.0), 6)
        except (TypeError, ValueError):
            continue
        if rate <= 0:
            continue
        pairs.add(
            (
                str(effect.get("zone") or ""),
                _normalize_effect_element(effect.get("element")),
                rate,
            )
        )
    return pairs


def _window_matches_same_lane(parent: dict[str, Any], child: dict[str, Any]) -> bool:
    return (
        parent.get("source_character_key") == child.get("source_character_key")
        and parent.get("target_character_key") == child.get("target_character_key")
        and abs(int(parent.get("start_ts_ms") or 0) - int(child.get("start_ts_ms") or 0)) <= _BUFF_MIRROR_DEDUPE_WINDOW_MS
    )


def _parent_window_covers_created_children(parent: dict[str, Any], siblings: list[dict[str, Any]]) -> bool:
    child_ids = _created_child_buff_ids(str(parent.get("event_key") or ""))
    if not child_ids:
        return False
    parent_pairs = _window_static_effect_pairs(parent)
    if not parent_pairs:
        return False
    child_pairs: set[tuple[str, str, float]] = set()
    for other in siblings:
        if other is parent:
            continue
        if str(other.get("event_key") or "") not in child_ids:
            continue
        if not _window_matches_same_lane(parent, other):
            continue
        child_pairs.update(_window_static_effect_pairs(other))
    if not child_pairs:
        return False
    for zone, element, rate in parent_pairs:
        if (zone, element, rate) in child_pairs:
            continue
        if element == "spell":
            spell_children = {
                child_element
                for child_zone, child_element, child_rate in child_pairs
                if child_zone == zone and child_rate == rate and child_element in _ELEMENTAL_ELEMENTS
            }
            if spell_children:
                continue
        if element == "all":
            matching_children = [
                child_element
                for child_zone, child_element, child_rate in child_pairs
                if child_zone == zone and child_rate == rate
            ]
            if matching_children:
                continue
        return False
    return True


def _parent_window_covers_specific_siblings(parent: dict[str, Any], siblings: list[dict[str, Any]]) -> bool:
    parent_pairs = _window_static_effect_pairs(parent)
    if not parent_pairs:
        return False
    child_pairs: set[tuple[str, str, float]] = set()
    child_event_keys: set[str] = set()
    for other in siblings:
        if other is parent:
            continue
        if str(other.get("event_key") or "") == str(parent.get("event_key") or ""):
            continue
        if not _window_matches_same_lane(parent, other):
            continue
        pairs = _window_static_effect_pairs(other)
        if not pairs:
            continue
        child_pairs.update(pairs)
        child_event_keys.add(str(other.get("event_key") or ""))
    if not child_pairs or not child_event_keys:
        return False
    for zone, element, rate in parent_pairs:
        if (zone, element, rate) in child_pairs:
            continue
        if element == "spell":
            spell_children = {
                child_element
                for child_zone, child_element, child_rate in child_pairs
                if child_zone == zone and child_rate == rate and child_element in _ELEMENTAL_ELEMENTS
            }
            if spell_children:
                continue
        if element == "all":
            matching_children = [
                child_element
                for child_zone, child_element, child_rate in child_pairs
                if child_zone == zone and child_rate == rate
            ]
            if matching_children:
                continue
        return False
    return True
