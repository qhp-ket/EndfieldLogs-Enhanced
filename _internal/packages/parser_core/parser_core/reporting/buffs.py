"""Describe BUFF effects and visible timeline segments from finalized windows."""
from __future__ import annotations

from parser_core.effects.damage_types import _normalize_effect_element
from parser_core.effects.labels import _EFFECT_ZONE_LABELS
from parser_core.effects.labels import _collect_buff_labels
from parser_core.effects.lifecycle import _buff_record_end_ts_ms
from parser_core.effects.packet_mapping import _classify_packet_buff_record
from parser_core.effects.specifications import _collect_zone_effects
from parser_core.effects.specifications import _extract_dynamic_effect_specs
from parser_core.ingestion.fields import _coerce_optional_float
from parser_core.ingestion.fields import _ms_time_text
from parser_core.ingestion.fields import _safe_positive_rate
import copy
from typing import Any


def _packet_buff_semantic_candidates(record: dict[str, Any], *, limit: int = 5) -> list[dict[str, Any]]:
    return []


def _effect_summary_rows(effects: list[dict[str, Any]]) -> list[str]:
    rows: list[str] = []
    seen: set[str] = set()
    for effect in effects:
        zone = str(effect.get("zone") or "")
        element = _normalize_effect_element(effect.get("element"))
        rate = effect.get("rate")
        if rate is None:
            rate = effect.get("base_rate")
        try:
            base_rate = float(rate)
        except (TypeError, ValueError):
            base_rate = None
        label = _EFFECT_ZONE_LABELS.get(zone, zone)
        if 'keyword_rate_snapshots' in effect:
            rates = [base_rate]
            for snapshot in sorted(effect['keyword_rate_snapshots'],
                                   key=lambda row: (row['operation_seq'], row['line_no'])):
                if snapshot.get('session_id') != effect.get('keyword_session_id'):
                    continue
                snapshot_rate = (_coerce_optional_float(snapshot.get('rate_after'))
                                 if snapshot.get('status') == 'observed' else None)
                if snapshot_rate != rates[-1]:
                    rates.append(snapshot_rate)
            rate_text = ' -> '.join(f'{value * 100:.2f}%' if value is not None else '未确认'
                                    for value in rates)
            row_text = f"{label}/{element} {rate_text}"
        elif zone == 'res' and 'parameter_snapshots' in effect:
            row_text = f"{label}/{element} 按包内实际减抗点数更新"
        elif zone == 'res' and base_rate is not None:
            row_text = f"{label}/{element} {base_rate:g} 点"
        elif base_rate is None:
            row_text = f"{label}/{element} -"
        else:
            delayed_add_rate = _safe_positive_rate(effect.get("delayed_add_rate")) or 0.0
            delay_sec = float(effect.get("delay_sec") or 0.0)
            tick_rate = float(effect.get("tick_rate") or 0.0)
            max_rate = float(effect.get("max_rate") or 0.0)
            if delayed_add_rate > 0 and delay_sec > 0:
                row_text = (
                    f"{label}/{element} {base_rate * 100:.2f}%"
                    f" -> {(base_rate + delayed_add_rate) * 100:.2f}% @ {delay_sec:g}s"
                )
            elif tick_rate > 0 and max_rate > base_rate:
                row_text = (
                    f"{label}/{element} {base_rate * 100:.2f}%"
                    f" -> {max_rate * 100:.2f}% over time"
                )
            else:
                row_text = f"{label}/{element} {base_rate * 100:.2f}%"
        condition = effect.get("condition")
        if isinstance(condition, dict) and str(condition.get("type") or "") in {"target_hp_ratio_lte", "target_hp_compare"}:
            threshold = _coerce_optional_float(condition.get("threshold"))
            if threshold is not None:
                legacy = condition.get("type") == "target_hp_ratio_lte"
                compare = "LE" if legacy else condition.get("compare")
                operator = {"LT": "<", "LE": "<=", "GT": ">", "GE": ">=", "EQ": "=", "NE": "!="}.get(compare, "?")
                value = f"{threshold * 100:.2f}%" if legacy or condition.get("is_ratio") is True else str(threshold)
                row_text = f"{row_text} (target HP {operator} {value})"
        elif isinstance(condition, dict) and str(condition.get("type") or "") == "damage_type_in":
            elements = [str(item) for item in condition.get("elements") or [] if str(item or "")]
            if elements:
                row_text = f"{row_text} (damage type: {', '.join(elements)})"
        if row_text in seen:
            continue
        seen.add(row_text)
        rows.append(row_text)
    return rows


def _effect_segments_for_event(
    *,
    start_ts_ms: int,
    end_ts_ms: int,
    zone_effects: list[dict[str, Any]],
    dynamic_effects: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    for effect in zone_effects:
        segments.append(
            {
                "start_ts_ms": start_ts_ms,
                "start_time": _ms_time_text(start_ts_ms),
                "end_ts_ms": end_ts_ms,
                "end_time": _ms_time_text(end_ts_ms),
                "zone": str(effect.get("zone") or ""),
                "element": _normalize_effect_element(effect.get("element")),
                "rate": effect.get("rate"),
                "mode": "static",
            }
        )
    for effect in dynamic_effects:
        if 'keyword_rate_snapshots' in effect:
            states = [{'ts_ms': start_ts_ms, 'rate_after': effect.get('base_rate'),
                       'status': 'observed', 'operation_seq': None, 'line_no': None}]
            latest_seq = -1
            for snapshot in sorted(effect['keyword_rate_snapshots'],
                                   key=lambda row: (row['ts_ms'], row['line_no'], row['operation_seq'])):
                if (snapshot.get('session_id') != effect.get('keyword_session_id')
                        or snapshot['ts_ms'] > end_ts_ms
                        or snapshot['operation_seq'] < latest_seq):
                    continue
                latest_seq = snapshot['operation_seq']
                states.append(snapshot)
            for index, state in enumerate(states):
                following = states[index + 1] if index + 1 < len(states) else None
                segment_start = max(start_ts_ms, state['ts_ms'])
                segment_end = min(end_ts_ms, following['ts_ms'] if following else end_ts_ms)
                if segment_end < segment_start:
                    continue
                rate = (_coerce_optional_float(state.get('rate_after'))
                        if state.get('status') == 'observed' else None)
                # Equal timestamps still have an explicit packet/line boundary;
                # retain it instead of making the earlier operation disappear.
                segments.append({'start_ts_ms': segment_start, 'start_time': _ms_time_text(segment_start),
                                 'end_ts_ms': segment_end, 'end_time': _ms_time_text(segment_end),
                                 'zone': str(effect.get('zone') or ''),
                                 'element': _normalize_effect_element(effect.get('element')),
                                 'rate': rate, 'mode': 'packet_keyword_update',
                                 'operation_seq': state['operation_seq'], 'line_no': state['line_no'],
                                 'end_operation_seq': following['operation_seq'] if following else None,
                                 'end_line_no': following['line_no'] if following else None,
                                 'session_id': effect.get('keyword_session_id')})
            continue
        if 'parameter_snapshots' in effect:
            snapshots = effect['parameter_snapshots']
            for index, snapshot in enumerate(snapshots):
                values = [_coerce_optional_float((snapshot.get('bb_values') or {}).get(key))
                          for key in effect['parameter_keys']]
                resolved = (snapshot.get('status') == 'attribute_parameters_observed'
                            and values and all(value is not None and value <= 0 for value in values))
                start = max(start_ts_ms, snapshot['ts_ms'])
                end = min(end_ts_ms, snapshots[index + 1]['ts_ms'] if index + 1 < len(snapshots) else end_ts_ms)
                if end >= start:
                    segments.append({'start_ts_ms': start, 'start_time': _ms_time_text(start),
                                     'end_ts_ms': end, 'end_time': _ms_time_text(end),
                                     'zone': 'res', 'element': effect['element'],
                                     'rate': -sum(values) if resolved else None,
                                     'rate_unit': 'resistance_points', 'mode': 'packet_refresh',
                                     'operation_seq': snapshot['operation_seq']})
            continue
        base_rate = float(effect.get("base_rate") or 0.0)
        delayed_add_rate = float(effect.get("delayed_add_rate") or 0.0)
        delay_ms = int(max(0.0, float(effect.get("delay_sec") or 0.0)) * 1000)
        tick_rate = float(effect.get("tick_rate") or 0.0)
        max_rate = float(effect.get("max_rate") or 0.0)
        zone = str(effect.get("zone") or "")
        element = _normalize_effect_element(effect.get("element"))
        observed_points = [
            (int(point[0]), float(point[1]))
            for point in (effect.get("observed_points") or [])
            if isinstance(point, (list, tuple)) and len(point) == 2
        ]
        if observed_points:
            for index, (point_ts, point_rate) in enumerate(observed_points):
                segment_start = max(start_ts_ms, point_ts)
                segment_end = (observed_points[index + 1][0]
                               if index + 1 < len(observed_points)
                               else end_ts_ms)
                if segment_end <= segment_start:
                    continue
                segments.append({
                    "start_ts_ms": segment_start,
                    "start_time": _ms_time_text(segment_start),
                    "end_ts_ms": min(segment_end, end_ts_ms),
                    "end_time": _ms_time_text(min(segment_end, end_ts_ms)),
                    "zone": zone,
                    "element": element,
                    "rate": point_rate,
                    "mode": "dynamic_observed",
                })
            continue
        if delayed_add_rate > 0 and delay_ms > 0 and start_ts_ms + delay_ms < end_ts_ms:
            segments.append(
                {
                    "start_ts_ms": start_ts_ms,
                    "start_time": _ms_time_text(start_ts_ms),
                    "end_ts_ms": start_ts_ms + delay_ms,
                    "end_time": _ms_time_text(start_ts_ms + delay_ms),
                    "zone": zone,
                    "element": element,
                    "rate": base_rate,
                    "mode": "dynamic_before_delay",
                }
            )
            segments.append(
                {
                    "start_ts_ms": start_ts_ms + delay_ms,
                    "start_time": _ms_time_text(start_ts_ms + delay_ms),
                    "end_ts_ms": end_ts_ms,
                    "end_time": _ms_time_text(end_ts_ms),
                    "zone": zone,
                    "element": element,
                    "rate": base_rate + delayed_add_rate,
                    "mode": "dynamic_after_delay",
                }
            )
            continue
        segments.append(
            {
                "start_ts_ms": start_ts_ms,
                "start_time": _ms_time_text(start_ts_ms),
                "end_ts_ms": end_ts_ms,
                "end_time": _ms_time_text(end_ts_ms),
                "zone": zone,
                "element": element,
                "rate": base_rate,
                "tick_rate_per_sec": tick_rate,
                "max_rate": max_rate,
                "mode": "dynamic",
            }
        )
    return segments


def _buff_window_identity(window: dict[str, Any]) -> tuple[Any, ...]:
    uid = str(window.get("uid") or "")
    if uid:
        return ("uid", uid)
    return (
        "tuple",
        window.get("event_key"),
        window.get("source_character_key"),
        window.get("target_character_key"),
        int(window.get("start_ts_ms") or 0),
    )


def _build_buff_events(
    buff_starts: list[dict[str, Any]],
    buff_windows: list[dict[str, Any]],
    *,
    battle_start_ms: int,
    battle_end_ms: int,
    root_lookup_cache: dict | None = None,
) -> list[dict[str, Any]]:
    included_identities = {_buff_window_identity(window) for window in buff_windows}
    events: list[dict[str, Any]] = []
    for record in buff_starts:
        start_ts_ms = int(record.get("ts_ms") or 0)
        end_ts_ms = _buff_record_end_ts_ms(record, battle_end_ms)
        duration_ms = max(0, end_ts_ms - start_ts_ms)
        labels = _collect_buff_labels(record, root_lookup_cache=root_lookup_cache)
        zone_effects = _collect_zone_effects(record, root_lookup_cache=root_lookup_cache)
        dynamic_effects = _extract_dynamic_effect_specs(record, root_lookup_cache=root_lookup_cache)
        has_effects = bool(zone_effects or dynamic_effects)
        identity = _buff_window_identity(
            {
                "uid": record.get("uid"),
                "event_key": record.get("event_key"),
                "source_character_key": record.get("source_character_key"),
                "target_character_key": record.get("target_character_key") or record.get("target_enemy_key"),
                "start_ts_ms": start_ts_ms,
            }
        )
        included = has_effects and identity in included_identities
        status = "included" if included else "merged" if has_effects else "filtered"
        packet_classification = _classify_packet_buff_record(record)
        events.append(
            {
                "status": status,
                "status_label": "纳入" if included else "合并/未参与窗口" if has_effects else "过滤",
                "line_no": record.get("line_no"),
                "uid": record.get("uid"),
                "event_key": record.get("event_key"),
                "raw_event_key": record.get("raw_event_key"),
                "event_name": " / ".join(labels) if labels else record.get("event_key"),
                "packet_mapping": record.get("packet_mapping"),
                "origin_observations": copy.deepcopy(record.get('origin_observations') or []),
                "enable_observations": copy.deepcopy(record.get('enable_observations') or []),
                "creation_observations": copy.deepcopy(record.get('creation_observations') or []),
                "repeated_creation_observations": copy.deepcopy(record.get('repeated_creation_observations') or []),
                "attribute_refresh_snapshots": copy.deepcopy(record.get('attribute_refresh_snapshots') or []),
                "packet_classification": packet_classification,
                "semantic_candidates": _packet_buff_semantic_candidates(record),
                "source_character_key": record.get("source_character_key"),
                "source_character_name": record.get("source_character_name"),
                "source_skill_key": record.get("source_skill_key"),
                "source_skill_family_key": record.get("source_skill_family_key"),
                "raw_source": record.get("raw_source"),
                "target_character_key": record.get("target_character_key") or record.get("target_enemy_key"),
                "target_character_name": record.get("target_character_name") or record.get("target_enemy_name"),
                "target_player_key": record.get("target_character_key"),
                "target_enemy_key": record.get("target_enemy_key"),
                "owner_raw": record.get("owner_raw"),
                "target_actor_id": record.get("target_actor_id"),
                "source_actor_id": record.get("source_actor_id"),
                "source_weapon_template": record.get("source_weapon_template"),
                "start_ts_ms": start_ts_ms,
                "start_time": _ms_time_text(start_ts_ms),
                "end_ts_ms": end_ts_ms,
                "end_time": _ms_time_text(end_ts_ms),
                "start_ms_from_battle": start_ts_ms - battle_start_ms,
                "end_ms_from_battle": end_ts_ms - battle_start_ms,
                "duration_ms": duration_ms,
                "raw_end_ts_ms": record.get("end_ts_ms"),
                "snapshot_end_ts_ms": record.get('snapshot_end_ts_ms'),
                "snapshot_end_line_no": record.get('snapshot_end_line_no'),
                "snapshot_update": bool(record.get('snapshot_update')),
                "instance_start_line_no": record.get('instance_start_line_no'),
                "raw_end_time": _ms_time_text(record.get("end_ts_ms")) if record.get("end_ts_ms") is not None else None,
                "raw_duration_ms": record.get("raw_duration_ms"),
                "lifetime_mode": record.get('lifetime_mode'),
                "lifetime_source": record.get('lifetime_source'),
                "end_is_observation_boundary": record.get('end_ts_ms') is None and record.get('snapshot_end_ts_ms') is None and record.get('lifetime_mode') == 'Infinity',
                "end_source": ('snapshot_update' if record.get('snapshot_end_ts_ms') == end_ts_ms else
                               'buff_end' if record.get('end_ts_ms') == end_ts_ms else 'duration_or_capture_boundary'),
                "overlaps_battle": end_ts_ms >= battle_start_ms and start_ts_ms <= battle_end_ms,
                "dynamic_bb_events": list(record.get("dynamic_bb_events") or []),
                "bb_keys": sorted(set(str(key) for key in record.get("bb_keys") or [])),
                "bb_values": dict(record.get("bb_values") or {}),
                "attr_types": list(record.get("attr_types") or []),
                "attr_mods": list(record.get("attr_mods") or []),
                "zone_effects": zone_effects,
                "dynamic_effects": dynamic_effects,
                "effect_segments": _effect_segments_for_event(
                    start_ts_ms=start_ts_ms,
                    end_ts_ms=end_ts_ms,
                    zone_effects=zone_effects,
                    dynamic_effects=dynamic_effects,
                ),
                "effect_summary": _effect_summary_rows(zone_effects + dynamic_effects),
                "is_weapon_buff": bool(record.get("is_weapon_buff")),
            }
        )
    return sorted(events, key=lambda item: (int(item.get("start_ts_ms") or 0), int(item.get("line_no") or 0)))
