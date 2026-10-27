"""Evaluate recorded static and dynamic effects at the exact hit coordinates."""
from __future__ import annotations

from math import isfinite
from parser_core.effects.damage_types import _normalize_effect_element
from parser_core.ingestion.fields import _coerce_optional_float
import copy
from typing import Any


def _window_effects_at_ts(window: dict[str, Any], hit_ts_ms: int, *,
                          line_no: int | None = None, packet_seq_id: int | None = None,
                          packet_session_id: str | None = None) -> list[dict[str, Any]]:
    window['_enable_state_unobserved_at_hit'] = False
    window['_effect_state_unresolved_at_hit'] = False
    window['_buff_enabled_at_hit'] = None
    start = window.get('start_ts_ms')
    end = window.get('end_ts_ms')
    if type(start) is int and hit_ts_ms < start or type(end) is int and hit_ts_ms > end:
        return []
    if line_no:
        if start == hit_ts_ms and int(window.get('start_line_no') or 0) > line_no:
            return []
        if end == hit_ts_ms and window.get('end_line_no') and line_no >= int(window['end_line_no']):
            return []
    elif (window.get('snapshot_update') and start == hit_ts_ms
          or window.get('snapshot_end_ts_ms') == hit_ts_ms):
        window['rdps_snapshot_order_unresolved'] = True
        window['_effect_state_unresolved_at_hit'] = True
        return []
    observations = window.get('enable_observations') or []
    if window.get('rdps_conflicting_enable_state') and not observations:
        window['_effect_state_unresolved_at_hit'] = True
        return []
    prior = []
    if observations:
        if type(packet_seq_id) is int:
            prior = [row for row in observations if row['operationSeq'] <= packet_seq_id]
            prior.sort(key=lambda row: (row['operationSeq'], row['line_no']))
        else:
            prior = [row for row in observations if row['ts_ms'] < hit_ts_ms or
                     row['ts_ms'] == hit_ts_ms and (not line_no or row['line_no'] <= line_no)]
            prior.sort(key=lambda row: (row['ts_ms'], row['line_no']))
        if prior:
            latest = prior[-1]
            values = {row['enabled'] for row in observations if row['operationSeq'] == latest['operationSeq']}
            if len(values) != 1:
                window['_effect_state_unresolved_at_hit'] = True
                return []
            if latest['enabled'] is False:
                window['_buff_enabled_at_hit'] = False
                return []
    if window.get('requires_enable_observation') and not prior:
        window['_enable_state_unobserved_at_hit'] = True
        window['_effect_state_unresolved_at_hit'] = True
        window['rdps_unresolved_enable_evidence'] = True
        return []
    window['_buff_enabled_at_hit'] = True
    dynamic_specs = list(window.get("dynamic_effects") or [])
    if not dynamic_specs:
        return list(window.get("zone_effects") or [])

    effects: list[dict[str, Any]] = []
    for spec in dynamic_specs:
        if 'keyword_rate_snapshots' in spec:
            if ((packet_session_id is not None and packet_session_id != spec.get('keyword_session_id'))
                    or type(packet_seq_id) is int and packet_session_id is None):
                window['_effect_state_unresolved_at_hit'] = True
                return []
            prior = [row for row in spec['keyword_rate_snapshots']
                     if row.get('session_id') == spec.get('keyword_session_id')
                     and ((type(packet_seq_id) is int and row['operation_seq'] <= packet_seq_id)
                          or packet_seq_id is None and (row['ts_ms'] < hit_ts_ms or
                              row['ts_ms'] == hit_ts_ms and line_no and row['line_no'] <= line_no))]
            rate = _coerce_optional_float(spec.get('base_rate'))
            if prior:
                latest = max(prior, key=lambda row: (row['operation_seq'], row['line_no']))
                rate = (_coerce_optional_float(latest.get('rate_after'))
                        if latest.get('status') == 'observed' else None)
            if rate is None or rate < 0:
                window['_effect_state_unresolved_at_hit'] = True
                return []
            if rate > 0:
                effect = {key: copy.deepcopy(spec[key]) for key in
                          ('zone', 'element', 'condition', 'external_rdps_allowed', 'rdps_whitelist_keys', 'keyword_origin')
                          if key in spec}
                effect['rate'] = rate
                effects.append(effect)
            continue
        if 'parameter_snapshots' in spec:
            prior = [row for row in spec['parameter_snapshots']
                     if (type(packet_seq_id) is int and type(row.get('operation_seq')) is int
                         and row['operation_seq'] <= packet_seq_id)
                     or (packet_seq_id is None and (row['ts_ms'] < hit_ts_ms or
                         row['ts_ms'] == hit_ts_ms and line_no and row['line_no'] <= line_no))]
            if not prior:
                window['_effect_state_unresolved_at_hit'] = True
                return []
            snapshot = max(prior, key=lambda row: (row['operation_seq'], row['line_no']))
            snapshot_session = snapshot.get('session_id') or (snapshot.get('identity') or {}).get('sessionId')
            if packet_session_id is not None and snapshot_session is not None and packet_session_id != snapshot_session:
                window['_effect_state_unresolved_at_hit'] = True
                return []
            values = [_coerce_optional_float((snapshot.get('bb_values') or {}).get(key))
                      for key in spec['parameter_keys']]
            if (snapshot.get('status') != 'attribute_parameters_observed'
                    or not values or any(value is None or value > 0 for value in values)):
                window['_effect_state_unresolved_at_hit'] = True
                return []
            rate = -sum(values)
            if not isfinite(rate):
                window['_effect_state_unresolved_at_hit'] = True
                return []
            if rate > 0:
                effects.append({'zone': 'res', 'element': spec['element'], 'rate': rate,
                                'external_rdps_allowed': spec['external_rdps_allowed'],
                                'rdps_whitelist_keys': list(spec['rdps_whitelist_keys']),
                                'resistance_point_source': 'packet_bb_update_and_refresh',
                                'resistance_snapshot_seq': snapshot['operation_seq']})
            continue
        if (spec.get("observed_points")
                and spec.get("observed_points_source") != "typed_runtime_dynamic_action"):
            window["rdps_invalid_dynamic_evaluation"] = True
            return []
        if float(spec.get("tick_rate") or 0.0) != 0.0:
            window["rdps_invalid_dynamic_evaluation"] = True
            return []
        if float(spec.get("delayed_add_rate") or 0.0) != 0.0:
            window["rdps_invalid_dynamic_evaluation"] = True
            return []
        rate = float(spec.get("base_rate") or 0.0)
        if spec.get("observed_points"):
            earlier = [point for point in spec["observed_points"]
                       if isinstance(point, (list, tuple)) and len(point) == 2
                       and int(point[0]) <= hit_ts_ms]
            if not earlier:
                continue
            rate = max(0.0, float(earlier[-1][1]))
        if not isfinite(rate):
            window["rdps_invalid_dynamic_evaluation"] = True
            return []
        if rate <= 0:
            continue
        effect = {
                "zone": str(spec["zone"]),
                "element": _normalize_effect_element(spec.get("element")),
                "rate": rate,
            }
        if "condition" in spec:
            effect["condition"] = copy.deepcopy(spec["condition"])
        for key in ('external_rdps_allowed', 'rdps_whitelist_keys'):
            if key in spec:
                effect[key] = copy.deepcopy(spec[key])
        effects.append(effect)
    return effects
