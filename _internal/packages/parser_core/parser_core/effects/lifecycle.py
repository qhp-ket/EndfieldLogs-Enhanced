"""Track recorded BUFF instance lifetimes and packet observations."""
from __future__ import annotations

from parser_core.catalog.buff_templates import _load_current_buff_roots
from parser_core.effects.approval import _normalize_buff_id
from parser_core.effects.damage_types import _normalize_effect_element
from parser_core.effects.specifications import _collect_zone_effects
from typing import Any




def _is_canonical_packet_buff_key(buff_id: str | None) -> bool:
    text = _normalize_buff_id(buff_id)
    return bool(text) and text != "unknown_buff" and not text.isdigit()


def _prefer_packet_buff_record(previous: dict[str, Any], current: dict[str, Any]) -> bool:
    previous_key = _normalize_buff_id(previous.get("event_key"))
    current_key = _normalize_buff_id(current.get("event_key"))
    if previous_key == current_key:
        return False
    previous_canonical = _is_canonical_packet_buff_key(previous_key)
    current_canonical = _is_canonical_packet_buff_key(current_key)
    if current_canonical and not previous_canonical:
        return True
    if previous_canonical and not current_canonical:
        return False
    if current_key == "unknown_buff" and previous_key != "unknown_buff":
        return False
    if previous_key == "unknown_buff" and current_key != "unknown_buff":
        return True
    return False


def _normalize_buff_duration_ms(
    start_ts_ms: int,
    *,
    event_key: str | None = None,
    end_ts_ms: int | None,
    raw_duration_ms: int | None,
    battle_end_ms: int,
) -> int:
    remaining = max(battle_end_ms - start_ts_ms, 0)
    if end_ts_ms is not None and end_ts_ms >= start_ts_ms:
        # Packet end timestamps include pauses. A nominal game-time duration
        # must not shorten the explicitly observed lifetime.
        return min(remaining, end_ts_ms - start_ts_ms)
    if raw_duration_ms is not None and raw_duration_ms >= 0:
        return min(remaining, raw_duration_ms)
    root = _load_current_buff_roots().get(_normalize_buff_id(event_key), {})
    return remaining if root.get('lifeType') == 'Infinity' else 0


def _extend_buff_records_from_packet_modifiers(
    buff_starts: list[dict[str, Any]],
    packet_modifier_last_seen_by_uid: dict[str, int],
) -> None:
    # UID occurrence proves participation in that hit, not an interval end.
    for record in buff_starts:
        uid = str(record.get("uid") or "")
        if uid in packet_modifier_last_seen_by_uid:
            record["packet_modifier_last_seen_ts_ms"] = packet_modifier_last_seen_by_uid[uid]


_RELATED_BUFF_LIFECYCLE_START_TOLERANCE_MS = 250


def _buff_record_lifecycle_target_key(record: dict[str, Any]) -> str:
    return str(
        record.get("target_character_key")
        or record.get("target_enemy_key")
        or record.get("owner_raw")
        or ""
    )


def _buff_record_lifecycle_lane_matches(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if str(left.get("source_character_key") or "") != str(right.get("source_character_key") or ""):
        return False
    if _buff_record_lifecycle_target_key(left) != _buff_record_lifecycle_target_key(right):
        return False
    return (
        abs(int(left.get("ts_ms") or 0) - int(right.get("ts_ms") or 0))
        <= _RELATED_BUFF_LIFECYCLE_START_TOLERANCE_MS
    )


def _buff_record_static_effect_pairs(record: dict[str, Any]) -> set[tuple[str, str, float]]:
    pairs: set[tuple[str, str, float]] = set()
    for effect in _collect_zone_effects(record):
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


def _buff_records_have_matching_lifecycle_effects(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_key = str(left.get("event_key") or "")
    right_key = str(right.get("event_key") or "")
    if not (left_key.endswith("_default_child") or right_key.endswith("_default_child")):
        return False
    left_pairs = _buff_record_static_effect_pairs(left)
    right_pairs = _buff_record_static_effect_pairs(right)
    if left_pairs & right_pairs:
        return True
    child_key = left_key if left_key.endswith("_default_child") else right_key
    parent_pairs = right_pairs if left_key.endswith("_default_child") else left_pairs
    if child_key.startswith("buff_common_affixes_vulnerable"):
        return any(zone in {"fragile", "vuln_taken", "res"} for zone, _element, _rate in parent_pairs)
    return False


def _buff_records_lifecycle_related(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_key = str(left.get("event_key") or "")
    right_key = str(right.get("event_key") or "")
    if not left_key or not right_key or left_key == right_key:
        return False
    return (
        _buff_semantically_reaches_buff(left_key, right_key)
        or _buff_semantically_reaches_buff(right_key, left_key)
        or _buff_records_have_matching_lifecycle_effects(left, right)
    )


def _record_has_authoritative_bb_duration(record: dict[str, Any]) -> bool:
    return str(record.get("raw_duration_source") or "") == "bb"


def _infer_related_buff_end_times(
    buff_starts: list[dict[str, Any]],
    skill_casts: list[dict[str, Any]],
) -> None:
    return


def _buff_record_end_ts_ms(record: dict[str, Any], battle_end_ms: int) -> int:
    start_ts_ms = int(record["ts_ms"])
    duration_ms = _normalize_buff_duration_ms(
        start_ts_ms,
        event_key=record.get("event_key"),
        end_ts_ms=record.get("end_ts_ms"),
        raw_duration_ms=record.get("raw_duration_ms"),
        battle_end_ms=battle_end_ms,
    )
    end = start_ts_ms + duration_ms
    return min(end, int(record['snapshot_end_ts_ms'])) if record.get('snapshot_end_ts_ms') is not None else end


def _buff_semantically_reaches_buff(*args: Any, **kwargs: Any) -> bool:
    return False



def _build_buff_record_index(buff_starts: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}
    for record in buff_starts:
        uid = str(record.get("uid") or "")
        if uid:
            index.setdefault(uid, []).append(record)
    return index


def _resolve_weapon_buff_sources(buff_records: list[dict[str, Any]]) -> None:
    return
