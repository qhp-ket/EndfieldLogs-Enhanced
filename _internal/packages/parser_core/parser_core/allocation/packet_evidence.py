"""Match hit-side packet modifiers and explicit active BUFF lifetimes."""
from __future__ import annotations

from parser_core.allocation.static_loadout import _ATTR_TYPE_TO_EFFECT
from parser_core.effects.approval import _normalize_buff_id
from parser_core.effects.damage_types import _BUFF_SKILL_FILTER
from parser_core.effects.damage_types import _normalize_effect_element
from parser_core.effects.evaluation import _window_effects_at_ts
from parser_core.effects.packet_mapping import _DPD_ZONE_BUCKETS
from parser_core.effects.window_identity import _effect_condition_signature
from parser_core.effects.window_identity import _effect_row_signature
from parser_core.effects.window_identity import _window_uid_aliases
from parser_core.ingestion.fields import _coerce_optional_int
from typing import Any


def _packet_attr_allowed_effects(tokens: list[str] | None) -> set[tuple[str, str]]:
    allowed: set[tuple[str, str]] = set()
    for token in tokens or []:
        head = str(token).split(":", 1)[0]
        try:
            attr_type = int(head)
        except (TypeError, ValueError):
            continue
        mapping = _ATTR_TYPE_TO_EFFECT.get(attr_type)
        if mapping is None:
            continue
        zone, element = mapping
        allowed.add((str(zone), str(element or "all")))
    return allowed


def _dpd_bucket_value_for_zone(zone: str, dpd_raw: dict[str, Any] | None) -> float | None:
    if not dpd_raw:
        return None
    bucket = _DPD_ZONE_BUCKETS.get(zone)
    if bucket is None:
        return None
    side, index = bucket
    values = dpd_raw.get("atk_zones") if side == "atk" else dpd_raw.get("def_zones")
    if not values or index >= len(values):
        return None
    try:
        return float(values[index])
    except (TypeError, ValueError):
        return None


def _window_matches_packet_uids(window: dict[str, Any], packet_uids: set[str]) -> bool:
    if not packet_uids:
        return True
    aliases = _window_uid_aliases(window)
    if not aliases:
        return True
    return bool(aliases & packet_uids)


def _packet_modifier_guard_signature(effect: dict[str, Any]) -> tuple[Any, ...]:
    zone = str(effect.get("zone") or "")
    element = _normalize_effect_element(effect.get("element"))
    bb_keys = tuple(
        str(effect.get(key_name) or "")
        for key_name in ("bb_key", "add_bb_key", "delay_bb_key", "tick_bb_key", "max_bb_key")
    )
    try:
        attr_type = int(effect.get("attr_type")) if effect.get("attr_type") is not None else None
    except (TypeError, ValueError):
        attr_type = None
    condition_signature = _effect_condition_signature(effect)
    if any(bb_keys) or attr_type is not None or condition_signature:
        return ("keyed", zone, element, bb_keys, attr_type, condition_signature)
    return _effect_row_signature(effect)


def _matched_packet_defender_effect_signatures(
    *,
    hit: dict[str, Any],
    buff_windows: list[dict[str, Any]],
    defender_modifier_uids: set[str],
) -> set[tuple[Any, ...]]:
    if not defender_modifier_uids:
        return set()

    target_enemy_key = str(hit.get("target_enemy_key") or "")
    hit_ts_ms = int(hit.get("ts_ms") or 0)
    hit_line_no = int(hit.get("line_no") or 0)
    skill_key = str(hit.get("skill_key") or "")
    signatures: set[tuple[Any, ...]] = set()
    for window in buff_windows:
        if not target_enemy_key or str(window.get("target_character_key") or "") != target_enemy_key:
            continue
        if not (_window_uid_aliases(window) & defender_modifier_uids):
            continue
        window_effects = _window_effects_at_ts(window, hit_ts_ms, line_no=int(hit.get('line_no') or 0),
                                               packet_seq_id=hit.get('packet_seq_id'))
        if not window_effects:
            continue
        window_start_ts_ms = int(window.get("start_ts_ms") or 0)
        if not (window_start_ts_ms <= hit_ts_ms <= int(window.get("end_ts_ms") or 0)):
            continue
        window_line_no = int(window.get("start_line_no") or window.get("line_no") or 0)
        if window_start_ts_ms == hit_ts_ms and hit_line_no and window_line_no and window_line_no > hit_line_no:
            continue
        if window_start_ts_ms == hit_ts_ms and str(window.get("event_key") or "") == skill_key:
            continue
        skill_family_key = window.get("skill_family_key")
        if skill_family_key and hit.get("skill_family_key") != skill_family_key:
            continue
        skill_filter = _BUFF_SKILL_FILTER.get(str(window.get("event_key") or ""))
        if skill_filter and not skill_filter.search(skill_key):
            continue

        for effect in window_effects:
            if str(effect.get("zone") or "") == "vuln_taken":
                signatures.add(_packet_modifier_guard_signature(effect))
    return signatures


def _active_target_buff_ids_for_hit(
    hit: dict[str, Any],
    condition_buff_records: list[dict[str, Any]] | None,
    *, side: str = 'defender',
) -> set[str]:
    target = str(hit.get('character_key' if side == 'attacker' else 'target_enemy_key') or '')
    target_id = str(hit.get('source_actor_id' if side == 'attacker' else 'target_actor_id') or '')
    stamp = int(hit.get("ts_ms") or 0)
    line_no = int(hit.get("line_no") or 0)
    packet_uids = {str(uid) for uid in (hit.get("packet_modifier_uids") or {}).get(side, [])}
    active = set()
    for record in condition_buff_records or []:
        if str(record.get("target_enemy_key") or record.get("target_character_key") or "") != target:
            continue
        owner_id = str(record.get("target_actor_id") or "")
        uid_seen = str(record.get("uid") or "") in packet_uids
        if target_id and owner_id and target_id != owner_id:
            continue
        if not (target_id and owner_id) and not uid_seen:
            continue
        start = _coerce_optional_int(record.get("ts_ms"))
        if start is None or start > stamp:
            continue
        start_line = int(record.get("line_no") or 0)
        if start == stamp and line_no and start_line and start_line > line_no:
            continue
        end = _coerce_optional_int(record.get("end_ts_ms"))
        end_line = int(record.get("end_line_no") or 0)
        if end is not None and (stamp > end or (stamp == end and (not end_line or not line_no or line_no >= end_line))):
            continue
        snapshot_end = record.get('snapshot_end_ts_ms')
        if snapshot_end is not None and (stamp > int(snapshot_end) or stamp == int(snapshot_end)
                and (not line_no or line_no >= int(record.get('snapshot_end_line_no') or 0))):
            continue
        duration = _coerce_optional_int(record.get("raw_duration_ms"))
        if duration is not None and (duration <= 0 or stamp >= start + duration):
            continue
        if end is None and duration is None and not uid_seen and record.get('lifetime_mode') != 'Infinity':
            continue
        for key in (record.get("event_key"), record.get("raw_event_key")):
            if key:
                active.add(_normalize_buff_id(key))
    return active
